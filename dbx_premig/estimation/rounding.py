"""The one rounding helper. Round only at the presentation boundary; half-up, never banker's."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

__all__ = ["round_hours"]


def round_hours(value: float, places: int = 1) -> float:
    """Half-up rounding through Decimal (2.25 -> 2.3, unlike round())."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
