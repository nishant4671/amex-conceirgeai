"""Orchestration Runner Module for the Amex ConciergeAI Agent.

Wraps LangGraph workflow execution with a strict 3-second timeout protection
layer. If any network or LLM node hangs, it rolls back and triggers the
deterministic rule engine fallback (fallback.py) to guarantee sub-5-second SLA.
Also manages writing XAI audit logs to PostgreSQL.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from app.agent.graph import compile_workflow
from app.agent.state import AgentState
from app.engine.fallback import execute_fallback_pipeline
from app.engine.filters import FlightCandidate, HotelCandidate
from app.models.sql_models import AuditLog, DisruptionEvent
from app.models.schemas import CardTier, DisruptionStatus
from app.services.database import AsyncSessionLocal
from app.services.redis_client import redis_checkpointer

logger = logging.getLogger("agent_runner")


async def persist_audit_log(
    db: AsyncSession,
    disruption_event_id: int,
    decision_type: str,
    reasoning_json: Dict[str, Any]
) -> None:
    """Helper to save structured XAI audit logs into PostgreSQL."""
    try:
        audit_entry = AuditLog(
            disruption_event_id=disruption_event_id,
            decision_type=decision_type,
            reasoning_json=reasoning_json,
            timestamp=datetime.utcnow()
        )
        db.add(audit_entry)
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to persist audit log to DB: {e}")
        await db.rollback()


async def update_disruption_status(
    db: AsyncSession,
    disruption_event_id: int,
    status: DisruptionStatus
) -> None:
    """Helper to update the overall status of the disruption event in PostgreSQL."""
    try:
        from sqlalchemy import update
        stmt = (
            update(DisruptionEvent)
            .where(DisruptionEvent.id == disruption_event_id)
            .values(status=status.value)
        )
        await db.execute(stmt)
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to update disruption event status in DB: {e}")
        await db.rollback()


async def execute_agent_workflow(
    user_id: int,
    card_tier: CardTier,
    disruption_event_id: int,
    flight_number: str,
    original_price: float,
    original_cabin: str,
    original_alliance: str,
    flight_candidates: List[Dict[str, Any]],
    hotel_candidates: List[Dict[str, Any]],
    resume_approval: Optional[bool] = None,
) -> Dict[str, Any]:
    """Orchestrates the LangGraph state machine with strict SLA timeout protection.

    Args:
        user_id: Target cardmember.
        card_tier: Member tier (e.g., PLATINUM).
        disruption_event_id: DB tracking primary key.
        flight_number: Code of original disrupted flight.
        original_price: Original cost.
        original_cabin: Original cabin class.
        original_alliance: Original carrier alliance network.
        flight_candidates: Options available for flight rebooking.
        hotel_candidates: Options available for overnight hotel rebooking.
        resume_approval: Boolean response passed when resuming an approval-paused session.

    Returns:
        Workflow state result or deterministic fallback outcome.
    """
    config = {"configurable": {"thread_id": f"disruption-{disruption_event_id}"}}
    workflow = compile_workflow(checkpointer=redis_checkpointer)

    initial_state = AgentState(
        user_id=user_id,
        card_tier=card_tier,
        disruption_event_id=disruption_event_id,
        flight_number=flight_number,
        original_price=original_price,
        original_cabin=original_cabin,
        original_alliance=original_alliance,
        flight_candidates=flight_candidates,
        hotel_candidates=hotel_candidates,
        filtered_flights=[],
        filtered_hotels=[],
        scored_flights=[],
        selected_flight=None,
        selected_hotel=None,
        status=DisruptionStatus.DETECTED,
        current_node="start",
        execution_spans={},
        error_logs=[],
        audit_trail=[],
        approval_granted=False
    )

    try:
        # Protect workflow execution with a strict 3-second timeout limit
        # This acts as our safety guardrail for API calls or agent logic
        async with asyncio.timeout(3.0):
            if resume_approval is not None:
                logger.info(f"Resuming approval flow with approval_granted={resume_approval}")
                # We resume execution after human interrupt
                state_update = {"approval_granted": resume_approval}
                # Update current state on the checkpointer
                await workflow.aupdate_state(config, state_update, as_node="human_approval_interrupt")
                # Resume execution
                final_state = await workflow.ainvoke(None, config)
            else:
                logger.info("Triggering initial state execution of disruption workflow...")
                # Start new run
                final_state = await workflow.ainvoke(initial_state, config)

        # Sync audit trail and status to DB
        async with AsyncSessionLocal() as db:
            # 1. Update overall disruption event status in DB
            new_status = final_state.get("status", DisruptionStatus.PROCESSING)
            await update_disruption_status(db, disruption_event_id, new_status)
            
            # 2. Write new audit logs to PostgreSQL
            # We filter out audits that are already in the DB by comparing length or tracking index
            # Simple approach: write all new entries from the trail
            audit_trail = final_state.get("audit_trail", [])
            for log in audit_trail:
                await persist_audit_log(
                    db,
                    disruption_event_id=disruption_event_id,
                    decision_type=log.get("decision_type"),
                    reasoning_json=log.get("reasoning_json")
                )

        return dict(final_state)

    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(
            f"LangGraph execution encountered timeout/failure: {str(e)}. "
            f"Activating Tier 1 Deterministic Fallback Stack for immediate resolution."
        )

        # Convert raw dicts to engine candidates
        f_cand = [FlightCandidate(**f) for f in flight_candidates]
        h_cand = [HotelCandidate(**h) for h in hotel_candidates]

        # Execute deterministic pipeline
        fallback_res = execute_fallback_pipeline(
            flight_candidates=f_cand,
            original_price=original_price,
            original_cabin=original_cabin,
            original_alliance=original_alliance,
            card_tier=card_tier,
            hotel_candidates=h_cand
        )

        # Build fallback explanation details
        fallback_explanation = {
            "fallback_reason": str(e),
            "execution_info": fallback_res.execution_info,
            "recommended_flights": [sf.model_dump() for sf in fallback_res.recommended_flights],
            "dropped_flights": fallback_res.dropped_flights
        }

        # Write fallback audit log directly to database
        async with AsyncSessionLocal() as db:
            await update_disruption_status(db, disruption_event_id, fallback_res.status)
            await persist_audit_log(
                db,
                disruption_event_id=disruption_event_id,
                decision_type="DETERMINISTIC_FALLBACK_TRIGGERED",
                reasoning_json=fallback_explanation
            )

        # Return mock matching state format so caller doesn't break
        return {
            "user_id": user_id,
            "card_tier": card_tier,
            "disruption_event_id": disruption_event_id,
            "flight_number": flight_number,
            "original_price": original_price,
            "original_cabin": original_cabin,
            "original_alliance": original_alliance,
            "flight_candidates": flight_candidates,
            "hotel_candidates": hotel_candidates,
            "filtered_flights": [f.model_dump() for f in f_cand],
            "filtered_hotels": [h.model_dump() for h in h_cand],
            "scored_flights": [sf.model_dump() for sf in fallback_res.recommended_flights],
            "selected_flight": fallback_res.recommended_flights[0].flight.model_dump() if fallback_res.recommended_flights else None,
            "selected_hotel": fallback_res.recommended_hotels[0].model_dump() if fallback_res.recommended_hotels else None,
            "status": fallback_res.status,
            "current_node": "fallback_engine",
            "execution_spans": {"fallback_run_ms": fallback_res.execution_info.get("duration_ms", 0.0)},
            "error_logs": [f"Fallback triggered: {str(e)}"],
            "audit_trail": [{"decision_type": "DETERMINISTIC_FALLBACK_TRIGGERED", "reasoning_json": fallback_explanation}],
            "approval_granted": False
        }
