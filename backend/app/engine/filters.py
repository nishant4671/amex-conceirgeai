"""Hard Filters Module for the Amex ConciergeAI Engine.

This module implements deterministic filtering rules based on user card tiers
and entitlements, eliminating options exceeding spend limits or downgrading cabin class.
"""

from typing import Any, Dict, List, Tuple
from pydantic import BaseModel, Field
from app.models.schemas import CardTier


class FlightCandidate(BaseModel):
    """Pydantic model representing a flight rebooking option candidate."""
    option_id: str = Field(..., description="Unique identifier for the flight option.")
    flight_number: str = Field(..., description="Flight code (e.g., 'AA123').")
    price: float = Field(..., description="Total cost of the flight in USD.")
    cabin: str = Field(..., description="Cabin class (ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST).")
    alliance: str = Field(..., description="Airline alliance (Star Alliance, OneWorld, SkyTeam, None).")
    layovers: int = Field(default=0, description="Number of layovers/stops.")
    layover_duration_minutes: int = Field(default=0, description="Total cumulative layover duration in minutes.")
    travel_time_minutes: int = Field(..., description="Total travel duration in minutes.")


class HotelCandidate(BaseModel):
    """Pydantic model representing a hotel accommodation option candidate."""
    option_id: str = Field(..., description="Unique identifier for the hotel option.")
    name: str = Field(..., description="Name of the hotel.")
    price_per_night: float = Field(..., description="Cost per night in USD.")
    star_rating: float = Field(..., description="Hotel star rating (1.0 to 5.0).")
    distance_from_airport_miles: float = Field(..., description="Distance from the airport in miles.")


class TierPolicy(BaseModel):
    """Policy guidelines configured per Cardmember Tier."""
    tier: CardTier
    max_flight_cost_increase_pct: float = Field(..., description="Max percentage price increase allowed over original price.")
    max_absolute_flight_budget: float = Field(..., description="Absolute maximum budget for flight rebooking.")
    max_hotel_cost_per_night: float = Field(..., description="Maximum budget per night for hotel bookings.")
    allow_upgrades: bool = Field(default=False, description="Whether cabin/room upgrades are allowed.")


# Standard Tier Policies
TIER_POLICIES = {
    CardTier.PLATINUM: TierPolicy(
        tier=CardTier.PLATINUM,
        max_flight_cost_increase_pct=0.50,  # Max 50% over original price
        max_absolute_flight_budget=2000.0,
        max_hotel_cost_per_night=500.0,
        allow_upgrades=True,
    ),
    CardTier.CENTURION: TierPolicy(
        tier=CardTier.CENTURION,
        max_flight_cost_increase_pct=1.50,  # Max 150% over original price
        max_absolute_flight_budget=5000.0,
        max_hotel_cost_per_night=1000.0,
        allow_upgrades=True,
    ),
}

CABIN_HIERARCHY = ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"]


def get_cabin_rank(cabin: str) -> int:
    """Helper function to get integer rank of a cabin class to prevent downgrades."""
    try:
        return CABIN_HIERARCHY.index(cabin.upper())
    except ValueError:
        return -1


def filter_flights(
    candidates: List[FlightCandidate],
    original_price: float,
    original_cabin: str,
    card_tier: CardTier,
) -> Tuple[List[FlightCandidate], List[Dict[str, Any]]]:
    """Filters candidate flights based on cardmember tier limits and cabin entitlements.

    Rules:
        1. Eliminate options exceeding tier price limits (max increase % or absolute max).
        2. Eliminate options downgrading cabin class below original cabin.

    Args:
        candidates: List of flight candidates to filter.
        original_price: The price of the original flight booking.
        original_cabin: Cabin class of the original flight.
        card_tier: Card tier of the member (PLATINUM, CENTURION).

    Returns:
        A tuple containing:
            - List of compliant FlightCandidates.
            - Audit trail list of dictionaries showing dropped candidates and reason.
    """
    policy = TIER_POLICIES.get(card_tier)
    if not policy:
        # Default fallback to Platinum if tier unrecognized
        policy = TIER_POLICIES[CardTier.PLATINUM]

    compliant_flights: List[FlightCandidate] = []
    dropped_audit: List[Dict[str, Any]] = []

    original_cabin_rank = get_cabin_rank(original_cabin)

    for flight in candidates:
        # Check 1: Price Delta cap
        max_allowed_price = min(
            original_price * (1.0 + policy.max_flight_cost_increase_pct),
            policy.max_absolute_flight_budget
        )
        if flight.price > max_allowed_price:
            dropped_audit.append({
                "option_id": flight.option_id,
                "flight_number": flight.flight_number,
                "reason": "EXCEEDS_SPEND_CAP",
                "details": f"Price ${flight.price:.2f} exceeds max allowed ${max_allowed_price:.2f} for tier {card_tier}."
            })
            continue

        # Check 2: Cabin Downgrade
        flight_cabin_rank = get_cabin_rank(flight.cabin)
        if flight_cabin_rank < original_cabin_rank:
            dropped_audit.append({
                "option_id": flight.option_id,
                "flight_number": flight.flight_number,
                "reason": "CABIN_DOWNGRADE",
                "details": f"Cabin '{flight.cabin}' is a downgrade from original '{original_cabin}'."
            })
            continue

        compliant_flights.append(flight)

    return compliant_flights, dropped_audit


def filter_hotels(
    candidates: List[HotelCandidate],
    card_tier: CardTier,
) -> Tuple[List[HotelCandidate], List[Dict[str, Any]]]:
    """Filters candidate hotels based on cardmember tier budget limits.

    Args:
        candidates: List of hotel candidates to filter.
        card_tier: Card tier of the member.

    Returns:
        A tuple containing:
            - List of compliant HotelCandidates.
            - Audit trail list of dictionaries showing dropped candidates and reason.
    """
    policy = TIER_POLICIES.get(card_tier)
    if not policy:
        policy = TIER_POLICIES[CardTier.PLATINUM]

    compliant_hotels: List[HotelCandidate] = []
    dropped_audit: List[Dict[str, Any]] = []

    for hotel in candidates:
        if hotel.price_per_night > policy.max_hotel_cost_per_night:
            dropped_audit.append({
                "option_id": hotel.option_id,
                "name": hotel.name,
                "reason": "EXCEEDS_SPEND_CAP",
                "details": f"Price ${hotel.price_per_night:.2f}/night exceeds max ${policy.max_hotel_cost_per_night:.2f}/night for tier {card_tier}."
            })
            continue

        compliant_hotels.append(hotel)

    return compliant_hotels, dropped_audit
