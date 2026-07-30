"""LangGraph State Module for the Amex ConciergeAI Agent.

Defines the TypedDict schema representing the workflow state machine.
"""

from typing import Any, Dict, List, Optional, TypedDict
from app.engine.filters import FlightCandidate, HotelCandidate
from app.engine.scoring import ScoredFlightOption
from app.models.schemas import CardTier, DisruptionStatus


class AgentState(TypedDict):
    """Execution state tracked across the LangGraph rebooking process.

    Attributes:
        user_id: The identifier of the cardmember.
        card_tier: The card tier of the member (PLATINUM, CENTURION).
        disruption_event_id: The database ID of the disruption.
        flight_number: The disrupted flight code (e.g. 'AA123').
        original_price: Original flight cost in USD.
        original_cabin: Original cabin class (e.g. 'BUSINESS').
        original_alliance: Original alliance carrier network.
        
        flight_candidates: Unfiltered flight candidate alternatives.
        hotel_candidates: Unfiltered hotel candidate alternatives.
        
        filtered_flights: Flight candidates surviving hard filters.
        filtered_hotels: Hotel candidates surviving hard filters.
        
        scored_flights: Sorted flight options with multi-factor scores.
        selected_flight: The flight candidate chosen/approved for rebooking.
        selected_hotel: The hotel candidate chosen/approved for booking if applicable.
        
        status: Current workflow status (DETECTED, PROCESSING, RESOLVED, ESCALATED).
        current_node: Name of the active node executing in the graph.
        execution_spans: Dictionary tracking timers/durations for execution steps.
        error_logs: Chronological list of warning or error messages encountered.
        audit_trail: Audit log items emitted during node transitions for persistence.
        
        approval_granted: Boolean set during the human approval interrupt.
    """
    user_id: int
    card_tier: CardTier
    disruption_event_id: int
    flight_number: str
    original_price: float
    original_cabin: str
    original_alliance: str

    flight_candidates: List[Dict[str, Any]]
    hotel_candidates: List[Dict[str, Any]]

    filtered_flights: List[Dict[str, Any]]
    filtered_hotels: List[Dict[str, Any]]

    scored_flights: List[Dict[str, Any]]
    selected_flight: Optional[Dict[str, Any]]
    selected_hotel: Optional[Dict[str, Any]]

    status: DisruptionStatus
    current_node: str
    execution_spans: Dict[str, float]
    error_logs: List[str]
    audit_trail: List[Dict[str, Any]]

    approval_granted: bool
