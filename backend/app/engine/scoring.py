"""Multi-Factor Scoring Matrix Module for the Amex ConciergeAI Engine.

This module scores and ranks compliant flight candidates based on four weighted vectors:
1. Price Delta (40%) - Prefers options closer to (or lower than) original price.
2. Total Travel Time (25%) - Prefers shorter elapsed flight times.
3. Alliance / Cabin Match (20%) - Prefers loyalty program alliance alignment and equal/better cabin class.
4. Layover Count & Duration (15%) - Prefers direct flights and shorter wait times.
"""

from typing import Any, Dict, List, Tuple
from pydantic import BaseModel, Field
from app.engine.filters import FlightCandidate, get_cabin_rank


class ScoredFlightOption(BaseModel):
    """Pydantic model for a candidate flight containing its multi-factor score breakdown."""
    flight: FlightCandidate
    total_score: float = Field(..., description="Overall calculated score (0.0 to 1.0).")
    price_score: float = Field(..., description="Score component for price delta.")
    travel_time_score: float = Field(..., description="Score component for total travel time.")
    alliance_cabin_score: float = Field(..., description="Score component for alliance/cabin match.")
    layover_score: float = Field(..., description="Score component for layover counts/durations.")


def calculate_flight_scores(
    candidates: List[FlightCandidate],
    original_price: float,
    original_cabin: str,
    original_alliance: str,
) -> Tuple[List[ScoredFlightOption], Dict[str, Any]]:
    """Calculates multi-factor scores and ranks candidate flights.

    Formula Weights:
        - Price Delta: 40%
        - Total Travel Time: 25%
        - Alliance / Cabin Match: 20%
        - Layover Count & Duration: 15%

    Args:
        candidates: Compliant flight candidates surviving hard filters.
        original_price: Cost of the disrupted flight.
        original_cabin: Cabin class of the disrupted flight.
        original_alliance: Alliance carrier network of the disrupted flight.

    Returns:
        A tuple of:
            - Sorted list of ScoredFlightOption from highest score to lowest.
            - XAI explanation dictionary mapping each option to its score calculation breakdown.
    """
    if not candidates:
        return [], {}

    scored_options: List[ScoredFlightOption] = []
    explanation_map: Dict[str, Any] = {}

    # Gather limits/extremes for normalization
    prices = [c.price for c in candidates]
    travel_times = [c.travel_time_minutes for c in candidates]
    layovers = [c.layovers for c in candidates]
    layover_durations = [c.layover_duration_minutes for c in candidates]

    min_price = min(prices) if prices else original_price
    max_price = max(prices) if prices else original_price
    min_travel = min(travel_times) if travel_times else 60
    max_travel = max(travel_times) if travel_times else 600
    max_layover = max(layovers) if layovers else 1
    max_layover_dur = max(layover_durations) if layover_durations else 60

    original_cabin_rank = get_cabin_rank(original_cabin)

    for c in candidates:
        # 1. Price Score (40% Weight)
        # Lower price is better. If price matches or is lower than original, score is 1.0.
        # Otherwise, normalize based on max price delta.
        if c.price <= original_price:
            price_score = 1.0
        elif max_price > original_price:
            price_score = max(0.0, 1.0 - (c.price - original_price) / (max_price - original_price))
        else:
            price_score = 1.0

        # 2. Travel Time Score (25% Weight)
        # Shorter travel time is better. Normalized against the candidate pool.
        if max_travel > min_travel:
            travel_time_score = 1.0 - ((c.travel_time_minutes - min_travel) / (max_travel - min_travel))
        else:
            travel_time_score = 1.0

        # 3. Alliance / Cabin Match Score (20% Weight)
        # Loyalty alignment (alliance match) = 50% of this subscore.
        alliance_score = 1.0 if c.alliance.lower() == original_alliance.lower() and c.alliance.lower() != "none" else 0.2
        # Same cabin class = 1.0, upgraded cabin class = 1.2.
        c_rank = get_cabin_rank(c.cabin)
        cabin_score = 1.2 if c_rank > original_cabin_rank else 1.0
        alliance_cabin_score = (0.5 * alliance_score) + (0.5 * cabin_score)

        # 4. Layover Score (15% Weight)
        # Fewer layovers and shorter duration is better.
        layover_count_score = 1.0 - (c.layovers / max_layover) if max_layover > 0 else 1.0
        layover_dur_score = 1.0 - (c.layover_duration_minutes / max_layover_dur) if max_layover_dur > 0 else 1.0
        layover_score = (0.5 * layover_count_score) + (0.5 * layover_dur_score)

        # Compute combined score
        total_score = (
            (0.40 * price_score) +
            (0.25 * travel_time_score) +
            (0.20 * alliance_cabin_score) +
            (0.15 * layover_score)
        )

        scored_opt = ScoredFlightOption(
            flight=c,
            total_score=round(total_score, 4),
            price_score=round(price_score, 4),
            travel_time_score=round(travel_time_score, 4),
            alliance_cabin_score=round(alliance_cabin_score, 4),
            layover_score=round(layover_score, 4)
        )

        scored_options.append(scored_opt)

        explanation_map[c.option_id] = {
            "flight_number": c.flight_number,
            "total_score": scored_opt.total_score,
            "breakdown": {
                "price_score_raw": scored_opt.price_score,
                "price_score_weighted": round(0.40 * scored_opt.price_score, 4),
                "travel_time_score_raw": scored_opt.travel_time_score,
                "travel_time_score_weighted": round(0.25 * scored_opt.travel_time_score, 4),
                "alliance_cabin_score_raw": scored_opt.alliance_cabin_score,
                "alliance_cabin_score_weighted": round(0.20 * scored_opt.alliance_cabin_score, 4),
                "layover_score_raw": scored_opt.layover_score,
                "layover_score_weighted": round(0.15 * scored_opt.layover_score, 4)
            },
            "formula_applied": "0.40*Price + 0.25*TravelTime + 0.20*AllianceCabin + 0.15*Layovers"
        }

    # Sort scored options by total score in descending order
    scored_options.sort(key=lambda x: x.total_score, reverse=True)

    return scored_options, explanation_map
