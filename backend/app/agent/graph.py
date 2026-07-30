"""LangGraph Workflow StateGraph Definition for the Amex ConciergeAI Agent.

Defines the node transitions, state updates, and interrupt markers for the
autonomous disruption resolution pipeline, featuring Redis session checkpointers.
"""

import time
import logging
from typing import Any, Dict, List
from langgraph.graph import StateGraph, START, END

from app.agent.state import AgentState
from app.engine.filters import FlightCandidate, HotelCandidate, filter_flights, filter_hotels
from app.engine.scoring import calculate_flight_scores
from app.models.schemas import DisruptionStatus

logger = logging.getLogger("agent_graph")


async def detect_disruption(state: AgentState) -> Dict[str, Any]:
    """Ingests the travel disruption payload, logging initial details."""
    start_time = time.perf_counter()
    logger.info(f"Node [detect_disruption]: processing event for user_id={state.get('user_id')}")

    # Initialize state fields
    audit_log = {
        "decision_type": "DISRUPTION_DETECTED",
        "reasoning_json": {
            "flight_number": state.get("flight_number"),
            "original_price": state.get("original_price"),
            "original_cabin": state.get("original_cabin"),
            "original_alliance": state.get("original_alliance"),
            "candidates_count": len(state.get("flight_candidates", []))
        }
    }

    elapsed = (time.perf_counter() - start_time) * 1000.0
    return {
        "current_node": "detect_disruption",
        "status": DisruptionStatus.PROCESSING,
        "execution_spans": {"detect_disruption": round(elapsed, 2)},
        "audit_trail": [audit_log],
        "error_logs": []
    }


async def apply_hard_filters(state: AgentState) -> Dict[str, Any]:
    """Applies card tier and entitlement hard filters on candidate choices."""
    start_time = time.perf_counter()
    logger.info("Node [apply_hard_filters]: running filters on candidates")

    # Reconstruct candidate objects
    flight_candidates = [FlightCandidate(**f) for f in state.get("flight_candidates", [])]
    hotel_candidates = [HotelCandidate(**h) for h in state.get("hotel_candidates", [])]

    # Execute engine filters
    compliant_flights, dropped_flights = filter_flights(
        candidates=flight_candidates,
        original_price=state.get("original_price"),
        original_cabin=state.get("original_cabin"),
        card_tier=state.get("card_tier")
    )

    compliant_hotels, dropped_hotels = filter_hotels(
        candidates=hotel_candidates,
        card_tier=state.get("card_tier")
    )

    audit_log = {
        "decision_type": "HARD_FILTER_APPLIED",
        "reasoning_json": {
            "surviving_flights": [f.option_id for f in compliant_flights],
            "dropped_flights": dropped_flights,
            "surviving_hotels": [h.option_id for h in compliant_hotels],
            "dropped_hotels": dropped_hotels
        }
    }

    elapsed = (time.perf_counter() - start_time) * 1000.0
    
    # Store existing spans
    spans = dict(state.get("execution_spans", {}))
    spans["apply_hard_filters"] = round(elapsed, 2)

    return {
        "current_node": "apply_hard_filters",
        "filtered_flights": [f.model_dump() for f in compliant_flights],
        "filtered_hotels": [h.model_dump() for h in compliant_hotels],
        "execution_spans": spans,
        "audit_trail": state.get("audit_trail", []) + [audit_log]
    }


async def run_scoring_matrix(state: AgentState) -> Dict[str, Any]:
    """Applies the multi-factor scoring matrix to rank surviving flights."""
    start_time = time.perf_counter()
    logger.info("Node [run_scoring_matrix]: ranking flights")

    filtered_flights = [FlightCandidate(**f) for f in state.get("filtered_flights", [])]

    scored_flights, xai_explanation = calculate_flight_scores(
        candidates=filtered_flights,
        original_price=state.get("original_price"),
        original_cabin=state.get("original_cabin"),
        original_alliance=state.get("original_alliance")
    )

    # Pre-select top candidate
    selected_flight = scored_flights[0].flight.model_dump() if scored_flights else None
    
    # Auto-select top hotel if available
    filtered_hotels = [HotelCandidate(**h) for h in state.get("filtered_hotels", [])]
    sorted_hotels = sorted(filtered_hotels, key=lambda h: (-h.star_rating, h.price_per_night))
    selected_hotel = sorted_hotels[0].model_dump() if sorted_hotels else None

    # Handle escalation if no flights survive
    status = DisruptionStatus.PROCESSING
    if not scored_flights and state.get("flight_candidates"):
        status = DisruptionStatus.ESCALATED
        logger.warning("No flight options survived filters. Directing state machine to ESCALATED status.")

    audit_log = {
        "decision_type": "RECOMMENDATIONS_SCORED",
        "reasoning_json": {
            "xai_scores": xai_explanation,
            "top_recommended_flight": selected_flight.get("option_id") if selected_flight else None,
            "top_recommended_hotel": selected_hotel.get("option_id") if selected_hotel else None,
            "escalated_due_to_no_options": not scored_flights
        }
    }

    elapsed = (time.perf_counter() - start_time) * 1000.0
    spans = dict(state.get("execution_spans", {}))
    spans["run_scoring_matrix"] = round(elapsed, 2)

    return {
        "current_node": "run_scoring_matrix",
        "scored_flights": [sf.model_dump() for sf in scored_flights],
        "selected_flight": selected_flight,
        "selected_hotel": selected_hotel,
        "status": status,
        "execution_spans": spans,
        "audit_trail": state.get("audit_trail", []) + [audit_log]
    }


async def human_approval_interrupt(state: AgentState) -> Dict[str, Any]:
    """Node where the execution halts. Will only execute once resume is triggered."""
    start_time = time.perf_counter()
    logger.info("Node [human_approval_interrupt]: user response input received")

    # This is entered post-interrupt
    approval = state.get("approval_granted", False)
    status = DisruptionStatus.RESOLVED if approval else DisruptionStatus.ESCALATED

    audit_log = {
        "decision_type": "APPROVAL_DECISION_RECEIVED",
        "reasoning_json": {
            "approval_granted": approval,
            "target_flight": state.get("selected_flight", {}).get("option_id") if state.get("selected_flight") else None
        }
    }

    elapsed = (time.perf_counter() - start_time) * 1000.0
    spans = dict(state.get("execution_spans", {}))
    spans["human_approval_interrupt"] = round(elapsed, 2)

    return {
        "current_node": "human_approval_interrupt",
        "status": status,
        "execution_spans": spans,
        "audit_trail": state.get("audit_trail", []) + [audit_log]
    }


async def execute_booking(state: AgentState) -> Dict[str, Any]:
    """Books the approved selection, resolving the disruption."""
    start_time = time.perf_counter()
    logger.info("Node [execute_booking]: booking final selection")

    booking_flight = state.get("selected_flight", {})
    booking_hotel = state.get("selected_hotel", {})

    audit_log = {
        "decision_type": "BOOKING_EXECUTED",
        "reasoning_json": {
            "booked_flight_id": booking_flight.get("option_id"),
            "booked_flight_number": booking_flight.get("flight_number"),
            "booked_hotel_id": booking_hotel.get("option_id") if booking_hotel else None,
            "status": "SUCCESS"
        }
    }

    elapsed = (time.perf_counter() - start_time) * 1000.0
    spans = dict(state.get("execution_spans", {}))
    spans["execute_booking"] = round(elapsed, 2)

    return {
        "current_node": "execute_booking",
        "status": DisruptionStatus.RESOLVED,
        "execution_spans": spans,
        "audit_trail": state.get("audit_trail", []) + [audit_log]
    }


# Transition routers
def route_after_scoring(state: AgentState) -> str:
    """Routes state machine to human interruption node, or escalates immediately if no options exist."""
    if state.get("status") == DisruptionStatus.ESCALATED or not state.get("scored_flights"):
        return "escalated"
    return "approval"


def route_after_approval(state: AgentState) -> str:
    """Routes state machine depending on whether approval was granted or denied."""
    if state.get("status") == DisruptionStatus.RESOLVED or state.get("approval_granted", False):
        return "book"
    return "escalated"


# Build Graph
builder = StateGraph(AgentState)

# Add Nodes
builder.add_node("detect_disruption", detect_disruption)
builder.add_node("apply_hard_filters", apply_hard_filters)
builder.add_node("run_scoring_matrix", run_scoring_matrix)
builder.add_node("human_approval_interrupt", human_approval_interrupt)
builder.add_node("execute_booking", execute_booking)

# Add Edges
builder.add_edge(START, "detect_disruption")
builder.add_edge("detect_disruption", "apply_hard_filters")
builder.add_edge("apply_hard_filters", "run_scoring_matrix")

# Conditional Edges from Scoring
builder.add_conditional_edges(
    "run_scoring_matrix",
    route_after_scoring,
    {
        "approval": "human_approval_interrupt",
        "escalated": END
    }
)

# Conditional Edges from Interrupt
builder.add_conditional_edges(
    "human_approval_interrupt",
    route_after_approval,
    {
        "book": "execute_booking",
        "escalated": END
    }
)

builder.add_edge("execute_booking", END)


def compile_workflow(checkpointer: Any = None) -> Any:
    """Compiles the StateGraph workflow with checkpointers and interrupts."""
    # We compile the graph to pause (interrupt) before entering human_approval_interrupt node.
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_approval_interrupt"]
    )
