"""Configurable demonstration collateral haircuts.

Haircuts are simplified assumptions for the prototype. They are not regulatory
loss-given-default parameters.
"""
from __future__ import annotations

COLLATERAL_TYPES: tuple[str, ...] = (
    "REAL_ESTATE",
    "FINANCIAL_COLLATERAL",
    "OTHER",
)

COLLATERAL_HAIRCUTS: dict[str, float] = {
    "REAL_ESTATE": 0.20,
    "FINANCIAL_COLLATERAL": 0.05,
    "OTHER": 0.40,
}

COLLATERAL_HAIRCUT_DESCRIPTION = (
    "Vereinfachte Demonstrations-Haircuts, angewendet als adjustierter Wert = Wert x (1 - Haircut). "
    "Sie sind konfigurierbar und keine offiziellen Bankparameter."
)


def haircut_for(collateral_type: str | None) -> float:
    if collateral_type is None:
        return COLLATERAL_HAIRCUTS["OTHER"]
    return COLLATERAL_HAIRCUTS.get(str(collateral_type).strip().upper(), COLLATERAL_HAIRCUTS["OTHER"])


def adjusted_collateral_value(value: float, collateral_type: str | None) -> float:
    if value is None:
        return 0.0
    return max(float(value), 0.0) * (1.0 - haircut_for(collateral_type))
