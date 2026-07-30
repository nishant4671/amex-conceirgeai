"""Human-in-the-Loop Escalation and Context Hydration Service.

Prepares rich context states for human operator concierge handoffs, ensuring they
have instant access to AI filter decisions, scoring breakdowns, and audit trails.
Also implements a 15-second unattended fallback SLA check.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql_models import AuditLog, DisruptionEvent, User
from app.models.schemas import DisruptionStatus
from app.services.database import AsyncSessionLocal

logger = logging.getLogger("escalation_service")


async def hydrate_escalation_context(
    event_id: int,
    db: AsyncSession
) -> Dict[str, Any]:
    """Hydrates the full agent state history and details for human concierges.

    Args:
        event_id: Database disruption identifier.
        db: Active AsyncSession.

    Returns:
        JSON-compatible dictionary containing user, disruption history, and XAI details.
    """
    # 1. Fetch Disruption Event and User
    stmt = (
        select(DisruptionEvent)
        .where(DisruptionEvent.id == event_id)
    )
    res = await db.execute(stmt)
    disruption = res.scalar_one_or_none()

    if not disruption:
        return {"error": "Disruption event not found"}

    user_stmt = select(User).where(User.id == disruption.user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()

    # 2. Fetch associated XAI audit logs
    audit_stmt = (
        select(AuditLog)
        .where(AuditLog.disruption_event_id == event_id)
        .order_by(AuditLog.timestamp.asc())
    )
    audit_res = await db.execute(audit_stmt)
    audit_logs = audit_res.scalars().all()

    # 3. Assemble unified payload
    history = []
    dropped_options = []
    scoring_matrix_applied = {}
    last_known_options = []

    for log in audit_logs:
        history.append({
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "decision_type": log.decision_type,
            "reasoning": log.reasoning_json
        })

        # Parse filter and scoring details for dashboard summary widgets
        reasoning = log.reasoning_json
        if log.decision_type == "HARD_FILTER_APPLIED":
            dropped_options.extend(reasoning.get("dropped_flights", []))
            dropped_options.extend(reasoning.get("dropped_hotels", []))
        elif log.decision_type == "RECOMMENDATIONS_SCORED":
            scoring_matrix_applied = reasoning.get("xai_scores", {})
        elif log.decision_type == "DETERMINISTIC_FALLBACK_TRIGGERED":
            dropped_options.extend(reasoning.get("dropped_flights", []))
            scoring_matrix_applied = reasoning.get("execution_info", {})

    return {
        "disruption_event_id": disruption.id,
        "flight_number": disruption.flight_number,
        "status": disruption.status,
        "created_at": disruption.created_at.isoformat(),
        "user": {
            "user_id": user.id if user else None,
            "email": user.email if user else None,
            "tier": user.tier if user else None,
        } if user else None,
        "dropped_options": dropped_options,
        "scoring_matrix_applied": scoring_matrix_applied,
        "agent_decision_trail": history
    }


# ==========================================
# Unattended Fallback SLA Monitoring
# ==========================================

async def check_unattended_sla(event_id: int) -> None:
    """Waits 15 seconds to check if a live agent has claimed the session.

    If not claimed, auto-routes to the VIP backup emergency hotline.
    """
    logger.info(f"Initiating 15-second SLA monitoring task for disruption_event_id={event_id}...")
    await asyncio.sleep(15.0)

    async with AsyncSessionLocal() as db:
        stmt = select(DisruptionEvent).where(DisruptionEvent.id == event_id)
        res = await db.execute(stmt)
        disruption = res.scalar_one_or_none()

        if not disruption:
            logger.error(f"SLA monitor failed: Disruption event {event_id} does not exist.")
            return

        # If session is still escalated and unclaimed, trigger auto-routing
        if disruption.status == DisruptionStatus.ESCALATED.value:
            logger.warning(
                f"[SLA EXPIRED] Disruption event {event_id} remains unclaimed after 15s. "
                "Triggering VIP Backup Auto-Routing..."
            )

            # 1. Update status to reflect emergency auto-route
            disruption.status = "VIP_AUTO_ROUTED"
            db.add(disruption)

            # 2. Persist emergency routing audit entry
            sla_audit = AuditLog(
                disruption_event_id=event_id,
                decision_type="SLA_UNATTENDED_FALLBACK_TRIGGERED",
                reasoning_json={
                    "assigned_queue": "VIP_EMERGENCY_HOTLINE",
                    "escalation_sla_duration_seconds": 15,
                    "action_taken": "AUTO_ROUTE_TO_VIP_SUPERVISOR"
                },
                timestamp=datetime.now(timezone.utc)
            )
            db.add(sla_audit)
            await db.commit()

            # 3. Stream to Dashboard WebSocket channel
            from app.api.disruptions import ws_manager
            await ws_manager.broadcast_to_user(
                user_id=disruption.user_id,
                message={
                    "type": "STATE_UPDATE",
                    "disruption_event_id": event_id,
                    "status": "VIP_AUTO_ROUTED",
                    "message": "Auto-routing to VIP Senior Specialist due to wait times."
                }
            )


def trigger_sla_timer(event_id: int) -> None:
    """Spawns an asynchronous background task to monitor the 15-second SLA timer."""
    asyncio.create_task(check_unattended_sla(event_id))
