"""FastAPI Router for Travel Disruption Detection and Rebooking Orchestration.

Provides REST and WebSocket endpoints allowing webhook ingestion, real-time
dashboard synchronization, and JWT-authenticated rebooking approvals/rejections.
"""

import json
import logging
from typing import Any, Dict, List, Optional
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import execute_agent_workflow
from app.core.config import settings
from app.models.schemas import CardTier, DisruptionStatus
from app.models.sql_models import User, DisruptionEvent
from app.services.amadeus_client import amadeus_service
from app.services.database import get_db
from app.services.twilio_client import twilio_service

logger = logging.getLogger("api_disruptions")

router = APIRouter(prefix="/disruptions", tags=["disruptions"])


# ==========================================
# WebSocket Connection Manager
# ==========================================
class WebSocketManager:
    """Manages active WebSocket connections per cardmember for real-time dashboard sync."""

    def __init__(self) -> None:
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        """Register a new active WebSocket connection for a cardmember."""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"WebSocket client connected for user_id={user_id}")

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        """Unregister a disconnected WebSocket channel."""
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"WebSocket client disconnected for user_id={user_id}")

    async def broadcast_to_user(self, user_id: int, message: Dict[str, Any]) -> None:
        """Dispatches data updates to all open web panels of a cardmember."""
        if user_id in self.active_connections:
            # Create a copy of the list to avoid modification issues during iterations
            sockets = list(self.active_connections[user_id])
            for socket in sockets:
                try:
                    await socket.send_json(message)
                except Exception as e:
                    logger.warning(f"Failed broadcasting socket to user {user_id}: {e}")
                    self.disconnect(user_id, socket)


# Global WebSocket tracker
ws_manager = WebSocketManager()


# ==========================================
# API Endpoints
# ==========================================

@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int) -> None:
    """WebSocket endpoint streaming disruption updates to the dashboard."""
    await ws_manager.connect(user_id, websocket)
    try:
        while True:
            # Keep connection alive, listen for client messages if any
            data = await websocket.receive_text()
            logger.info(f"Received WS message from user {user_id}: {data}")
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id, websocket)


@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_disruption(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Ingests flight disruption event webhooks or manual simulation triggers.

    Payload schema:
        {
            "user_id": int,
            "flight_number": str,
            "original_price": float,
            "original_cabin": str,
            "original_alliance": str,
            "user_phone": str
        }
    """
    user_id = payload.get("user_id")
    flight_number = payload.get("flight_number")
    original_price = payload.get("original_price")
    original_cabin = payload.get("original_cabin", "BUSINESS")
    original_alliance = payload.get("original_alliance", "OneWorld")
    user_phone = payload.get("user_phone", "+1234567890")

    if not user_id or not flight_number or not original_price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: user_id, flight_number, original_price"
        )

    # 1. Fetch user to verify card tier entitlement
    from sqlalchemy import select
    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    db_user = res.scalar_one_or_none()
    
    if not db_user:
        # Create a mock user on the fly if not found to allow testing/simulations
        db_user = User(
            email=f"member_{user_id}@amex.com",
            hashed_card_token="mock_hashed_token_987654",
            tier=CardTier.PLATINUM.value
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)

    card_tier = CardTier(db_user.tier)

    # 2. Store the disruption event in PostgreSQL
    disruption = DisruptionEvent(
        user_id=user_id,
        flight_number=flight_number,
        original_departure=datetime.utcnow(),
        status=DisruptionStatus.DETECTED.value
    )
    db.add(disruption)
    await db.commit()
    await db.refresh(disruption)

    # 3. Retrieve live alternative flight offers from Amadeus client
    # Assuming NYC to LON for mock queries
    alternatives = await amadeus_service.fetch_alternative_flights(
        origin="JFK",
        destination="LHR",
        departure_date="2026-07-31",
        original_flight_number=flight_number
    )

    # 4. Trigger workflow execution
    # Run the initial LangGraph segments asynchronously
    async def run_pipeline():
        final_state = await execute_agent_workflow(
            user_id=user_id,
            card_tier=card_tier,
            disruption_event_id=disruption.id,
            flight_number=flight_number,
            original_price=original_price,
            original_cabin=original_cabin,
            original_alliance=original_alliance,
            flight_candidates=alternatives,
            hotel_candidates=[],  # Mock empty hotels
        )

        # Broadcast state updates to active WebSocket sessions
        await ws_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "DISRUPTION_UPDATE",
                "disruption_event_id": disruption.id,
                "status": final_state.get("status"),
                "selected_flight": final_state.get("selected_flight"),
                "scored_options": final_state.get("scored_flights", [])[:3]
            }
        )

        # If rebooking alternative exists and needs approval, send Twilio notification with signed link
        top_flight = final_state.get("selected_flight")
        if top_flight and final_state.get("status") == DisruptionStatus.PROCESSING:
            jwt_token = twilio_service.generate_signed_jwt_link(
                disruption_event_id=disruption.id,
                user_id=user_id,
                flight_option_id=top_flight["option_id"]
            )
            await twilio_service.send_rebook_request(
                to_phone=user_phone,
                user_id=user_id,
                disruption_event_id=disruption.id,
                flight_number=flight_number,
                new_flight_number=top_flight["flight_number"],
                new_price=top_flight["price"],
                token=jwt_token
            )

    # Launch task in background
    import asyncio
    asyncio.create_task(run_pipeline())

    return {
        "status": "PROCESSING",
        "message": "Disruption workflow triggered successfully.",
        "disruption_event_id": disruption.id
    }


@router.get("/rebook/approve", response_class=HTMLResponse)
async def rebook_approve(
    token: str = Query(..., description="JWT rebooking token"),
    db: AsyncSession = Depends(get_db)
) -> str:
    """Ingests signed JWT token, resumes paused state machine, and executes booking."""
    try:
        # Decode and validate token
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        disruption_event_id = payload["disruption_event_id"]
        user_id = payload["user_id"]

        # Fetch original disruption record
        from sqlalchemy import select
        stmt = select(DisruptionEvent).where(DisruptionEvent.id == disruption_event_id)
        res = await db.execute(stmt)
        disruption = res.scalar_one_or_none()

        if not disruption:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Disruption event not found")

        # Ingest state resumption
        final_state = await execute_agent_workflow(
            user_id=user_id,
            card_tier=CardTier.PLATINUM,  # Will hydrate rest from state checkpointer anyway
            disruption_event_id=disruption_event_id,
            flight_number=disruption.flight_number,
            original_price=1.0,
            original_cabin="",
            original_alliance="",
            flight_candidates=[],
            hotel_candidates=[],
            resume_approval=True  # Instructs runner to inject approval & resume
        )

        # Notify UI about resolution success
        await ws_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "STATE_UPDATE",
                "disruption_event_id": disruption_event_id,
                "status": final_state.get("status")
            }
        )

        return (
            "<html>"
            "<head><title>Rebooking Confirmed</title></head>"
            "<body style='font-family: sans-serif; text-align: center; margin-top: 10%;'>"
            "<div style='border: 1px solid #d4af37; padding: 40px; display: inline-block; border-radius: 8px; background-color: #fcfbf7;'>"
            "<h1 style='color: #002b49;'>Amex ConciergeAI</h1>"
            "<p style='color: green; font-size: 1.2em;'>Your alternative travel arrangements have been booked successfully!</p>"
            "<p>Your live React dashboard has been updated. Safe travels.</p>"
            "</div>"
            "</body>"
            "</html>"
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rebooking request link expired (TTL 15 min exceeded).")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token verification.")


@router.get("/rebook/reject", response_class=HTMLResponse)
async def rebook_reject(
    token: str = Query(..., description="JWT rebooking token"),
    db: AsyncSession = Depends(get_db)
) -> str:
    """Ingests signed JWT token, rejects rebooking, and escalates to human portal."""
    try:
        # Decode and validate token
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        disruption_event_id = payload["disruption_event_id"]
        user_id = payload["user_id"]

        from sqlalchemy import select
        stmt = select(DisruptionEvent).where(DisruptionEvent.id == disruption_event_id)
        res = await db.execute(stmt)
        disruption = res.scalar_one_or_none()

        if not disruption:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Disruption event not found")

        # Resume state graph, denying approval to force escalation
        final_state = await execute_agent_workflow(
            user_id=user_id,
            card_tier=CardTier.PLATINUM,
            disruption_event_id=disruption_event_id,
            flight_number=disruption.flight_number,
            original_price=1.0,
            original_cabin="",
            original_alliance="",
            flight_candidates=[],
            hotel_candidates=[],
            resume_approval=False  # Denied approval
        )

        # Notify UI about escalation
        await ws_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "STATE_UPDATE",
                "disruption_event_id": disruption_event_id,
                "status": final_state.get("status")
            }
        )

        return (
            "<html>"
            "<head><title>Escalated to Agent</title></head>"
            "<body style='font-family: sans-serif; text-align: center; margin-top: 10%;'>"
            "<div style='border: 1px solid #d4af37; padding: 40px; display: inline-block; border-radius: 8px; background-color: #fcfbf7;'>"
            "<h1 style='color: #002b49;'>Amex ConciergeAI</h1>"
            "<p style='color: #e06666; font-size: 1.2em;'>Proposal rejected. Session escalated to a live Amex agent.</p>"
            "<p>Please stand by. An operator will contact you shortly.</p>"
            "</div>"
            "</body>"
            "</html>"
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rebooking request link expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token verification.")
