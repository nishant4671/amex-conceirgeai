"""FastAPI Router for the Concierge Operator Portal.

Provides endpoints for human support agents to inspect escalated travel
disruption queues and claim sessions with hydrated AI context records.
"""

import logging
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql_models import DisruptionEvent
from app.models.schemas import DisruptionStatus
from app.services.database import get_db
from app.services.escalation import hydrate_escalation_context, trigger_sla_timer

logger = logging.getLogger("api_concierge")

router = APIRouter(prefix="/concierge", tags=["concierge"])


@router.get("/queue", response_model=List[Dict[str, Any]])
async def get_escalation_queue(
    db: AsyncSession = Depends(get_db)
) -> List[Dict[str, Any]]:
    """Retrieves all active unassigned escalated disruption events."""
    stmt = (
        select(DisruptionEvent)
        .where(DisruptionEvent.status == DisruptionStatus.ESCALATED.value)
        .order_by(DisruptionEvent.created_at.asc())
    )
    res = await db.execute(stmt)
    escalations = res.scalars().all()

    queue_list = []
    for item in escalations:
        queue_list.append({
            "disruption_event_id": item.id,
            "user_id": item.user_id,
            "flight_number": item.flight_number,
            "original_departure": item.original_departure.isoformat(),
            "status": item.status,
            "created_at": item.created_at.isoformat()
        })
    return queue_list


@router.post("/claim/{event_id}", response_model=Dict[str, Any])
async def claim_escalation(
    event_id: int,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Allows a live human concierge agent to claim and take over an escalated session.

    Upon claim:
        1. Updates disruption status to 'PROCESSING' (representing live agent handling).
        2. Hydrates the operator dashboard with complete historical data (XAI score breakdown).
    """
    stmt = select(DisruptionEvent).where(DisruptionEvent.id == event_id)
    res = await db.execute(stmt)
    disruption = res.scalar_one_or_none()

    if not disruption:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disruption event with ID {event_id} not found."
        )

    # 1. Update status to live agent processing
    disruption.status = DisruptionStatus.PROCESSING.value
    db.add(disruption)
    await db.commit()
    await db.refresh(disruption)

    # 2. Hydrate full contextual payload
    context = await hydrate_escalation_context(event_id, db)

    # 3. Broadcast state update to cardmember UI via WebSockets
    from app.api.disruptions import ws_manager
    await ws_manager.broadcast_to_user(
        user_id=disruption.user_id,
        message={
            "type": "STATE_UPDATE",
            "disruption_event_id": event_id,
            "status": DisruptionStatus.PROCESSING.value,
            "message": "A live Amex Concierge agent has claimed your session and is resolving your disruption."
        }
    )

    return {
        "status": "CLAIMED",
        "message": f"Successfully claimed disruption event {event_id}.",
        "hydrated_context": context
    }


# ==========================================
# Trigger SLA Endpoint (Helper / Testing)
# ==========================================

@router.post("/monitor-sla/{event_id}", status_code=status.HTTP_202_ACCEPTED)
async def monitor_sla_endpoint(
    event_id: int
) -> Dict[str, str]:
    """Helper endpoint to manually trigger/test the 15-second SLA timer."""
    trigger_sla_timer(event_id)
    return {"message": f"SLA timer started for event {event_id}"}
