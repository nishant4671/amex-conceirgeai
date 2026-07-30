"""Deterministic Fallback Module for the Amex ConciergeAI Engine.

Provides the rule-based execution fallback tier of the Dual Fallback Stack.
This script ensures travel disruptions can be resolved in under <50ms without
external LLM or non-deterministic agent dependencies.
"""

import logging
from typing import Any, Dict, List
from pydantic import BaseModel, Field

from app.engine.filters import (
    FlightCandidate,
    HotelCandidate,
    filter_flights,
    filter_hotels,
)
from app.engine.scoring import ScoredFlightOption, calculate_flight_scores
from app.models.schemas import CardTier, DisruptionStatus

logger = logging.getLogger("fallback_engine")


class FallbackResult(BaseModel):
    """The structured result returned by the deterministic fallback resolution engine."""
    success: bool = Field(..., description="True if recommendations were found; False if escalation is required.")
    status: DisruptionStatus = Field(..., description="Resulting disruption lifecycle status.")
    recommended_flights: List[ScoredFlightOption] = Field(default_factory=list, description="Top ranked flight recommendations.")
    recommended_hotels: List[HotelCandidate] = Field(default_factory=list, description="Top ranked hotel recommendations if applicable.")
    dropped_flights: List[Dict[str, Any]] = Field(default_factory=list, description="Audit trail of flights dropped by hard filters.")
    dropped_hotels: List[Dict[str, Any]] = Field(default_factory=list, description="Audit trail of hotels dropped by hard filters.")
    xai_explanation: Dict[str, Any] = Field(default_factory=dict, description="Explainable AI score details for recommendations.")
    execution_info: Dict[str, Any] = Field(default_factory=dict, description="Execution performance and engine metadata.")


def execute_fallback_pipeline(
    flight_candidates: List[FlightCandidate],
    original_price: float,
    original_cabin: str,
    original_alliance: str,
    card_tier: CardTier,
    hotel_candidates: List[HotelCandidate] = None,
) -> FallbackResult:
    """Executes the complete rule-based rebooking filtering and scoring pipeline.

    Steps:
        1. Parse and apply Hard Filters on candidates to eliminate non-compliant options.
        2. Apply Multi-Factor Scoring Matrix on remaining candidates.
        3. Rank results and output structured decision audit logs.

    Args:
        flight_candidates: Raw flight alternatives.
        original_price: Base price of the original flight booking.
        original_cabin: Cabin of the original flight.
        original_alliance: Alliance carrier network of the original flight.
        card_tier: Member tier (e.g. PLATINUM, CENTURION).
        hotel_candidates: Optional list of hotel alternatives.

    Returns:
        FallbackResult payload indicating selected options, audit trail, and status.
    """
    import time
    start_time = time.perf_counter()

    if hotel_candidates is None:
        hotel_candidates = []

    logger.info("Executing deterministic fallback pipeline...")

    # 1. Apply Hard Filters
    compliant_flights, dropped_flights = filter_flights(
        candidates=flight_candidates,
        original_price=original_price,
        original_cabin=original_cabin,
        card_tier=card_tier,
    )

    compliant_hotels, dropped_hotels = filter_hotels(
        candidates=hotel_candidates,
        card_tier=card_tier,
    )

    # 2. Score and Rank remaining flights
    recommended_flights, xai_explanation = calculate_flight_scores(
        candidates=compliant_flights,
        original_price=original_price,
        original_cabin=original_cabin,
        original_alliance=original_alliance,
    )

    # 3. Sort hotels by price and star rating
    # We rank hotels by star rating descending, then price ascending as secondary sort
    recommended_hotels = sorted(
        compliant_hotels,
        key=lambda h: (-h.star_rating, h.price_per_night)
    )

    execution_duration_ms = (time.perf_counter() - start_time) * 1000.0

    # 4. Resolve Status
    # If no flights or hotels survived filters but candidates were provided, escalate to human agent.
    # Otherwise mark as PROCESSING or RESOLVED depending on recommendations.
    if not recommended_flights and flight_candidates:
        success = False
        status = DisruptionStatus.ESCALATED
        logger.warning("No compliant flight options survived hard filters. Escalating to human concierge portal.")
    else:
        success = True
        status = DisruptionStatus.PROCESSING

    return FallbackResult(
        success=success,
        status=status,
        recommended_flights=recommended_flights,
        recommended_hotels=recommended_hotels,
        dropped_flights=dropped_flights,
        dropped_hotels=dropped_hotels,
        xai_explanation=xai_explanation,
        execution_info={
            "engine": "Deterministic Fallback Rule-Engine",
            "version": "1.0.0",
            "duration_ms": round(execution_duration_ms, 3),
            "total_flights_evaluated": len(flight_candidates),
            "compliant_flights_count": len(compliant_flights)
        }
    )
