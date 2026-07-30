"""Unit tests for the Multi-Factor Scoring Matrix engine."""

from app.engine.filters import FlightCandidate
from app.engine.scoring import calculate_flight_scores


def test_scoring_weights_and_ranking():
    """Verify that composite scores and XAI explainable models are calculated correctly."""
    candidates = [
        # Closer to original price ($800), same alliance (OneWorld)
        FlightCandidate(
            option_id="FL-01",
            flight_number="AA100",
            price=850.0,
            cabin="BUSINESS",
            alliance="OneWorld",
            layovers=0,
            layover_duration_minutes=0,
            travel_time_minutes=300
        ),
        # Higher price, different alliance
        FlightCandidate(
            option_id="FL-02",
            flight_number="UA200",
            price=1100.0,
            cabin="BUSINESS",
            alliance="Star Alliance",
            layovers=1,
            layover_duration_minutes=60,
            travel_time_minutes=420
        ),
    ]

    original_price = 800.0
    original_cabin = "BUSINESS"
    original_alliance = "OneWorld"

    scored_list, xai_map = calculate_flight_scores(
        candidates=candidates,
        original_price=original_price,
        original_cabin=original_cabin,
        original_alliance=original_alliance
    )

    assert len(scored_list) == 2
    # Option 1 should be ranked higher due to price delta and alliance match
    assert scored_list[0].flight.option_id == "FL-01"
    assert scored_list[0].total_score > scored_list[1].total_score

    # Check XAI explanation exists
    assert "FL-01" in xai_map
    assert "FL-02" in xai_map
    assert "formula_applied" in xai_map["FL-01"]
    assert "price_score_raw" in xai_map["FL-01"]["breakdown"]
