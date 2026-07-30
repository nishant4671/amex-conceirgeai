"""Unit tests for the Tier 1 Deterministic Fallback script."""

from app.engine.filters import FlightCandidate, HotelCandidate
from app.engine.fallback import execute_fallback_pipeline
from app.models.schemas import CardTier, DisruptionStatus


def test_execute_fallback_pipeline_success():
    """Verify that deterministic fallback resolves alternative offers successfully."""
    flights = [
        FlightCandidate(
            option_id="FL-01",
            flight_number="AA100",
            price=600.0,
            cabin="BUSINESS",
            alliance="OneWorld",
            travel_time_minutes=180
        ),
        FlightCandidate(
            option_id="FL-02",
            flight_number="UA200",
            price=900.0,
            cabin="BUSINESS",
            alliance="Star Alliance",
            travel_time_minutes=240
        ),
    ]

    hotels = [
        HotelCandidate(
            option_id="HT-01",
            name="Lodge",
            price_per_night=300.0,
            star_rating=4.0,
            distance_from_airport_miles=1.5
        )
    ]

    res = execute_fallback_pipeline(
        flight_candidates=flights,
        original_price=800.0,
        original_cabin="BUSINESS",
        original_alliance="OneWorld",
        card_tier=CardTier.PLATINUM,
        hotel_candidates=hotels
    )

    assert res.success is True
    assert res.status == DisruptionStatus.PROCESSING
    assert len(res.recommended_flights) == 2
    assert len(res.recommended_hotels) == 1
    assert "duration_ms" in res.execution_info


def test_execute_fallback_pipeline_escalation():
    """Verify that fallback pipeline correctly flags escalation when no options survive filters."""
    flights = [
        # Downgrade
        FlightCandidate(
            option_id="FL-01",
            flight_number="AA100",
            price=600.0,
            cabin="ECONOMY",
            alliance="OneWorld",
            travel_time_minutes=180
        ),
    ]

    res = execute_fallback_pipeline(
        flight_candidates=flights,
        original_price=800.0,
        original_cabin="BUSINESS",
        original_alliance="OneWorld",
        card_tier=CardTier.PLATINUM
    )

    assert res.success is False
    assert res.status == DisruptionStatus.ESCALATED
    assert len(res.recommended_flights) == 0
