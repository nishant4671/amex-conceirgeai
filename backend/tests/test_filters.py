"""Unit tests for the Hard Filters engine."""

from app.engine.filters import FlightCandidate, HotelCandidate, filter_flights, filter_hotels
from app.models.schemas import CardTier


def test_flight_filters_dropped_and_survived():
    """Verify that flights exceeding spend caps or cabin downgrades are filtered."""
    candidates = [
        # Compliant Business
        FlightCandidate(
            option_id="FL-01",
            flight_number="AA100",
            price=1100.0,
            cabin="BUSINESS",
            alliance="OneWorld",
            travel_time_minutes=300
        ),
        # Downgrade to Economy
        FlightCandidate(
            option_id="FL-02",
            flight_number="UA200",
            price=450.0,
            cabin="ECONOMY",
            alliance="Star Alliance",
            travel_time_minutes=320
        ),
        # Over Spend Cap (exceeds $1200 max for $800 original on Platinum: +50%)
        FlightCandidate(
            option_id="FL-03",
            flight_number="DL300",
            price=1500.0,
            cabin="BUSINESS",
            alliance="SkyTeam",
            travel_time_minutes=290
        ),
    ]

    original_price = 800.0
    original_cabin = "BUSINESS"

    survived, dropped = filter_flights(
        candidates=candidates,
        original_price=original_price,
        original_cabin=original_cabin,
        card_tier=CardTier.PLATINUM
    )

    # Assert survived flights
    assert len(survived) == 1
    assert survived[0].option_id == "FL-01"

    # Assert dropped reasons
    assert len(dropped) == 2
    dropped_reasons = {d["option_id"]: d["reason"] for d in dropped}
    assert dropped_reasons["FL-02"] == "CABIN_DOWNGRADE"
    assert dropped_reasons["FL-03"] == "EXCEEDS_SPEND_CAP"


def test_hotel_spend_filters():
    """Verify that hotels exceeding per-night caps are correctly eliminated."""
    candidates = [
        HotelCandidate(
            option_id="HT-01",
            name="Amex Platinum Resort",
            price_per_night=450.0,
            star_rating=4.5,
            distance_from_airport_miles=2.0
        ),
        HotelCandidate(
            option_id="HT-02",
            name="Ultra Ritz Centurion",
            price_per_night=750.0,  # Exceeds Platinum $500 cap
            star_rating=5.0,
            distance_from_airport_miles=3.0
        ),
    ]

    # Test Platinum Tier
    survived_plat, dropped_plat = filter_hotels(candidates, CardTier.PLATINUM)
    assert len(survived_plat) == 1
    assert survived_plat[0].option_id == "HT-01"
    assert dropped_plat[0]["reason"] == "EXCEEDS_SPEND_CAP"

    # Test Centurion Tier (allows up to $1000)
    survived_cent, dropped_cent = filter_hotels(candidates, CardTier.CENTURION)
    assert len(survived_cent) == 2
    assert len(dropped_cent) == 0
