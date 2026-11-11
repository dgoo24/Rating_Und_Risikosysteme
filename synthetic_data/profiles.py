"""Reproducible synthetic institution profiles.

All institutions, portfolios and cashflows are fictional. Values are designed to
create visibly different risk profiles for the demonstration.
"""
from __future__ import annotations

from dataclasses import dataclass

from config.institutions import INSTITUTIONS

PRODUCT_TYPES = ("MORTGAGE", "COMMERCIAL", "SME", "CONSUMER", "MUNICIPAL")
SECTORS = (
    "MANUFACTURING",
    "REAL_ESTATE",
    "TRADE",
    "SERVICES",
    "CONSTRUCTION",
    "ENERGY",
    "PUBLIC_SECTOR",
    "AGRICULTURE",
    "HEALTHCARE",
)


@dataclass(frozen=True)
class BankProfile:
    bank_id: str
    active_target: int
    rating_probabilities: tuple[float, ...]  # A..F
    risk_multiplier: float
    recovery_base: float
    collateral_probability: float
    collateral_weights: tuple[float, ...]  # REAL_ESTATE, FINANCIAL, OTHER
    product_weights: tuple[float, ...]
    sector_weights: tuple[float, ...]
    annual_growth: float
    transition_upgrade_bias: float
    stale_valuation_probability: float

    @property
    def master_count(self) -> int:
        return int(self.active_target * 1.38)


PROFILES: dict[str, BankProfile] = {
    "SSK001": BankProfile(
        bank_id="SSK001",
        active_target=360,
        rating_probabilities=(0.28, 0.30, 0.22, 0.12, 0.06, 0.02),
        risk_multiplier=0.78,
        recovery_base=0.58,
        collateral_probability=0.68,
        collateral_weights=(0.72, 0.16, 0.12),
        product_weights=(0.42, 0.22, 0.22, 0.06, 0.08),
        sector_weights=(0.12, 0.26, 0.11, 0.18, 0.07, 0.04, 0.08, 0.04, 0.10),
        annual_growth=0.030,
        transition_upgrade_bias=0.008,
        stale_valuation_probability=0.10,
    ),
    "SSK002": BankProfile(
        bank_id="SSK002",
        active_target=280,
        rating_probabilities=(0.18, 0.26, 0.27, 0.17, 0.09, 0.03),
        risk_multiplier=1.05,
        recovery_base=0.46,
        collateral_probability=0.55,
        collateral_weights=(0.58, 0.14, 0.28),
        product_weights=(0.36, 0.25, 0.25, 0.09, 0.05),
        sector_weights=(0.16, 0.18, 0.16, 0.21, 0.08, 0.05, 0.03, 0.05, 0.08),
        annual_growth=0.012,
        transition_upgrade_bias=0.000,
        stale_valuation_probability=0.18,
    ),
    "SSK003": BankProfile(
        bank_id="SSK003",
        active_target=470,
        rating_probabilities=(0.10, 0.20, 0.27, 0.23, 0.14, 0.06),
        risk_multiplier=1.50,
        recovery_base=0.34,
        collateral_probability=0.44,
        collateral_weights=(0.36, 0.22, 0.42),
        product_weights=(0.28, 0.32, 0.29, 0.07, 0.04),
        sector_weights=(0.23, 0.14, 0.18, 0.20, 0.10, 0.04, 0.01, 0.04, 0.06),
        annual_growth=0.018,
        transition_upgrade_bias=-0.012,
        stale_valuation_probability=0.28,
    ),
    "SSK004": BankProfile(
        bank_id="SSK004",
        active_target=240,
        rating_probabilities=(0.32, 0.31, 0.20, 0.11, 0.05, 0.01),
        risk_multiplier=0.66,
        recovery_base=0.63,
        collateral_probability=0.72,
        collateral_weights=(0.56, 0.30, 0.14),
        product_weights=(0.47, 0.17, 0.20, 0.04, 0.12),
        sector_weights=(0.08, 0.24, 0.09, 0.14, 0.05, 0.03, 0.14, 0.06, 0.17),
        annual_growth=0.022,
        transition_upgrade_bias=0.014,
        stale_valuation_probability=0.06,
    ),
    "SSK005": BankProfile(
        bank_id="SSK005",
        active_target=380,
        rating_probabilities=(0.14, 0.24, 0.28, 0.20, 0.10, 0.04),
        risk_multiplier=1.22,
        recovery_base=0.42,
        collateral_probability=0.50,
        collateral_weights=(0.50, 0.12, 0.38),
        product_weights=(0.33, 0.28, 0.27, 0.08, 0.04),
        sector_weights=(0.18, 0.16, 0.15, 0.19, 0.09, 0.06, 0.03, 0.06, 0.08),
        annual_growth=0.008,
        transition_upgrade_bias=-0.004,
        stale_valuation_probability=0.22,
    ),
}

PROFILE_BY_BANK = {profile.bank_id: profile for profile in PROFILES.values()}
INSTITUTION_BY_BANK = {inst.bank_id: inst for inst in INSTITUTIONS}
