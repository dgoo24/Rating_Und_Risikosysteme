"""Configurable, explicitly fictional rating-to-PD mapping.

The PD values are demonstration assumptions. They are not official Sparkassen,
BaFin, EBA or other regulatory parameters.
"""
from __future__ import annotations

RATING_SCALE: tuple[str, ...] = ("A", "B", "C", "D", "E", "F")

RATING_PD_MAPPING: dict[str, float] = {
    "A": 0.001,
    "B": 0.003,
    "C": 0.008,
    "D": 0.020,
    "E": 0.050,
    "F": 0.120,
}

RATING_PD_DESCRIPTION = (
    "Demonstrations-PD 12M (durch den Zyklus, TTC-artig) je Ratingstufe. "
    "Die Werte sind konfigurierbare Annahmen, keine validierten Modellparameter."
)


def pd_for_rating(rating: str | None) -> float | None:
    """Return the configured PD for a rating grade or None if unknown."""
    if rating is None:
        return None
    return RATING_PD_MAPPING.get(str(rating).strip().upper())


def rating_rank(rating: str | None) -> int | None:
    """Rank 1 (best, A) to 6 (worst, F)."""
    if rating is None:
        return None
    try:
        return RATING_SCALE.index(str(rating).strip().upper()) + 1
    except ValueError:
        return None
