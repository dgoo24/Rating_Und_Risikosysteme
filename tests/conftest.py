"""Shared fixtures for the risk-reporting prototype test suite.

The fixtures describe one small, fully deterministic portfolio whose expected
analytical results were computed by hand (see docstrings of the individual
test modules). All data is fictional demonstration data.

Portfolio summary (reporting date 2026-06-30, observation start 2025-06-30):
- 8 current exposures, EAD 1,900, expected default EAD 13.9 -> PD 13.9/1900
- 6 performing exposures in the start snapshot, 2 defaults in the window
- default cohort EAD 200, recoveries 85 -> recovery rate 0.425, loss 115
- adjusted collateral 1,320.5 (haircuts 20%/5%/40%)
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from database.connection import connect

REPORT_DATE = pd.Timestamp("2026-06-30")
OBSERVATION_START = pd.Timestamp("2025-06-30")

EXPOSURE_COLUMNS = [
    "exposure_id", "bank_id", "customer_id", "snapshot_date", "product_type",
    "industry_sector", "region", "rating_grade", "exposure_at_default",
    "outstanding_balance", "currency", "origination_date", "maturity_date",
    "default_flag", "default_date",
]
RATING_COLUMNS = ["exposure_id", "bank_id", "observation_date", "rating_grade"]
COLLATERAL_COLUMNS = [
    "collateral_id", "exposure_id", "bank_id", "collateral_type",
    "collateral_value", "valuation_date", "currency",
]
CASHFLOW_COLUMNS = [
    "cashflow_id", "exposure_id", "bank_id", "payment_date",
    "recovery_amount", "recovery_type", "adjustment_reason",
]
INSTITUTION_COLUMNS = ["bank_id", "bank_name", "region", "peer_group"]


def _exposure_row(
    exposure_id: str,
    bank_id: str,
    snapshot: str,
    rating: str,
    ead: float,
    *,
    customer_id: str | None = None,
    product: str = "MORTGAGE",
    sector: str = "MANUFACTURING",
    region: str = "NORTH",
    balance: float | None = None,
    origination: str = "2020-01-15",
    maturity: str = "2030-06-30",
    default_flag: bool = False,
    default_date: str | None = None,
) -> dict[str, object]:
    return {
        "exposure_id": exposure_id,
        "bank_id": bank_id,
        "customer_id": customer_id or f"C{exposure_id[-3:]}",
        "snapshot_date": snapshot,
        "product_type": product,
        "industry_sector": sector,
        "region": region,
        "rating_grade": rating,
        "exposure_at_default": ead,
        "outstanding_balance": balance if balance is not None else ead * 0.95,
        "currency": "EUR",
        "origination_date": origination,
        "maturity_date": maturity,
        "default_flag": default_flag,
        "default_date": default_date,
    }


def _rating_row(exposure_id: str, bank_id: str, observation: str, rating: str) -> dict[str, object]:
    return {
        "exposure_id": exposure_id,
        "bank_id": bank_id,
        "observation_date": observation,
        "rating_grade": rating,
    }


def _collateral_row(
    collateral_id: str,
    exposure_id: str,
    bank_id: str,
    collateral_type: str,
    value: float,
    valuation: str,
) -> dict[str, object]:
    return {
        "collateral_id": collateral_id,
        "exposure_id": exposure_id,
        "bank_id": bank_id,
        "collateral_type": collateral_type,
        "collateral_value": value,
        "valuation_date": valuation,
        "currency": "EUR",
    }


def _cashflow_row(
    cashflow_id: str,
    exposure_id: str,
    bank_id: str,
    payment_date: str,
    amount: float,
    recovery_type: str = "CASH",
) -> dict[str, object]:
    return {
        "cashflow_id": cashflow_id,
        "exposure_id": exposure_id,
        "bank_id": bank_id,
        "payment_date": payment_date,
        "recovery_amount": amount,
        "recovery_type": recovery_type,
        "adjustment_reason": None,
    }


@pytest.fixture
def exposures_frame() -> pd.DataFrame:
    """Canonical exposures: two quarter snapshots plus one non-quarter-end date.

    Snapshot 2025-06-30 (observation start, all performing):
      EXP001 SSK001 A 100 | EXP002 SSK001 C 200 | EXP003 SSK003 B 400
      EXP004 SSK003 D 100 | EXP005 SSK005 A 500 | EXP006 SSK005 F 100
    Snapshot 2026-06-30 (reporting date):
      EXP001 A 100 | EXP002 B 200 | EXP003 C 400 | EXP004 D 100 defaulted 2026-03-31
      EXP005 A 500 | EXP006 E 100 defaulted 2025-11-15 | EXP007 B 300 | EXP008 C 200
    Extra: EXP009 on non-quarter-end 2026-05-15 (must never become a reporting period).
    """
    rows = [
        _exposure_row("EXP001", "SSK001", "2025-06-30", "A", 100),
        _exposure_row("EXP002", "SSK001", "2025-06-30", "C", 200, product="COMMERCIAL", sector="TRADE"),
        _exposure_row("EXP003", "SSK003", "2025-06-30", "B", 400, sector="SERVICES", region="WEST", product="SME"),
        _exposure_row("EXP004", "SSK003", "2025-06-30", "D", 100, sector="HEALTHCARE", region="WEST", product="CONSUMER"),
        _exposure_row("EXP005", "SSK005", "2025-06-30", "A", 500, sector="REAL_ESTATE", region="EAST"),
        _exposure_row("EXP006", "SSK005", "2025-06-30", "F", 100, sector="AGRICULTURE", region="EAST", product="SME"),
        _exposure_row("EXP001", "SSK001", "2026-06-30", "A", 100),
        _exposure_row("EXP002", "SSK001", "2026-06-30", "B", 200, product="COMMERCIAL", sector="TRADE"),
        _exposure_row("EXP003", "SSK003", "2026-06-30", "C", 400, sector="SERVICES", region="WEST", product="SME"),
        _exposure_row(
            "EXP004", "SSK003", "2026-06-30", "D", 100,
            sector="HEALTHCARE", region="WEST", product="CONSUMER",
            default_flag=True, default_date="2026-03-31",
        ),
        _exposure_row("EXP005", "SSK005", "2026-06-30", "A", 500, sector="REAL_ESTATE", region="EAST"),
        _exposure_row(
            "EXP006", "SSK005", "2026-06-30", "E", 100,
            sector="AGRICULTURE", region="EAST", product="SME",
            default_flag=True, default_date="2025-11-15",
        ),
        _exposure_row(
            "EXP007", "SSK001", "2026-06-30", "B", 300,
            product="MUNICIPAL", sector="PUBLIC_SECTOR", origination="2025-10-01", maturity="2035-10-01",
        ),
        _exposure_row(
            "EXP008", "SSK005", "2026-06-30", "C", 200,
            product="COMMERCIAL", sector="TRADE", region="EAST", origination="2025-12-01", maturity="2030-12-01",
        ),
        _exposure_row(
            "EXP009", "SSK001", "2026-05-15", "B", 100,
            product="CONSUMER", sector="SERVICES", origination="2025-01-01", maturity="2028-01-01",
        ),
    ]
    return pd.DataFrame(rows, columns=EXPOSURE_COLUMNS)


@pytest.fixture
def rating_history_frame() -> pd.DataFrame:
    """Portfolio rating history aligned with the exposure snapshots.

    Migration 2025-06-30 -> 2026-06-30: 6 matched, 2 upgrades (EXP002 C->B,
    EXP006 F->E), 1 downgrade (EXP003 B->C), 3 unchanged, 2 entries, 0 exits.
    """
    rows = [
        _rating_row("EXP001", "SSK001", "2025-06-30", "A"),
        _rating_row("EXP002", "SSK001", "2025-06-30", "C"),
        _rating_row("EXP003", "SSK003", "2025-06-30", "B"),
        _rating_row("EXP004", "SSK003", "2025-06-30", "D"),
        _rating_row("EXP005", "SSK005", "2025-06-30", "A"),
        _rating_row("EXP006", "SSK005", "2025-06-30", "F"),
        _rating_row("EXP001", "SSK001", "2026-06-30", "A"),
        _rating_row("EXP002", "SSK001", "2026-06-30", "B"),
        _rating_row("EXP003", "SSK003", "2026-06-30", "C"),
        _rating_row("EXP004", "SSK003", "2026-06-30", "D"),
        _rating_row("EXP005", "SSK005", "2026-06-30", "A"),
        _rating_row("EXP006", "SSK005", "2026-06-30", "E"),
        _rating_row("EXP007", "SSK001", "2026-06-30", "B"),
        _rating_row("EXP008", "SSK005", "2026-06-30", "C"),
    ]
    return pd.DataFrame(rows, columns=RATING_COLUMNS)


@pytest.fixture
def collateral_frame() -> pd.DataFrame:
    """Collateral stock with haircuts 20% (RE), 5% (FIN), 40% (OTHER).

    Hand-computed adjusted values (reporting date 2026-06-30):
      COL001 100 -> 80 | COL002 150 -> 120 (stale, valued 2023-01-10)
      COL003 90 -> 85.5 | COL004 50 -> 30 | COL005 900 -> 720 (latest of two)
      COL006 300 -> 285 | COL007 future -> excluded | COL008 orphan -> excluded
    """
    rows = [
        _collateral_row("COL001", "EXP001", "SSK001", "REAL_ESTATE", 100, "2026-01-15"),
        _collateral_row("COL002", "EXP001", "SSK001", "REAL_ESTATE", 150, "2023-01-10"),
        _collateral_row("COL003", "EXP002", "SSK001", "FINANCIAL_COLLATERAL", 90, "2025-12-31"),
        _collateral_row("COL004", "EXP005", "SSK005", "OTHER", 50, "2026-02-20"),
        _collateral_row("COL005", "EXP005", "SSK005", "REAL_ESTATE", 700, "2024-06-30"),
        _collateral_row("COL005", "EXP005", "SSK005", "REAL_ESTATE", 900, "2025-06-30"),
        _collateral_row("COL006", "EXP007", "SSK001", "FINANCIAL_COLLATERAL", 300, "2026-03-01"),
        _collateral_row("COL007", "EXP003", "SSK003", "REAL_ESTATE", 500, "2026-12-31"),
        _collateral_row("COL008", "EXP999", "SSK001", "OTHER", 75, "2025-06-30"),
    ]
    return pd.DataFrame(rows, columns=COLLATERAL_COLUMNS)


@pytest.fixture
def cashflows_frame() -> pd.DataFrame:
    """Recovery cashflows.

    Cohort (defaults 2025-06-30 < date <= 2026-06-30): EXP004, EXP006.
    Post-default, on/before report payments: CF001 40 + CF002 20 = 60 for EXP004,
    CF003 25 for EXP006. CF004 predates the default and CF005 lies in the
    future; both must be ignored.
    """
    rows = [
        _cashflow_row("CF001", "EXP004", "SSK003", "2026-04-15", 40, "CASH"),
        _cashflow_row("CF002", "EXP004", "SSK003", "2026-05-20", 20, "COLLATERAL_LIQUIDATION"),
        _cashflow_row("CF003", "EXP006", "SSK005", "2026-01-10", 25, "CASH"),
        _cashflow_row("CF004", "EXP004", "SSK003", "2025-01-05", 10, "CASH"),
        _cashflow_row("CF005", "EXP004", "SSK003", "2026-12-01", 50, "CASH"),
    ]
    return pd.DataFrame(rows, columns=CASHFLOW_COLUMNS)


@pytest.fixture
def institutions_frame() -> pd.DataFrame:
    """Three PG_URBAN peer-group members matching the portfolio banks."""
    rows = [
        {"bank_id": "SSK001", "bank_name": "Muster-Sparkasse Nord (fiktiv)", "region": "NORTH", "peer_group": "PG_URBAN"},
        {"bank_id": "SSK003", "bank_name": "Muster-Sparkasse West (fiktiv)", "region": "WEST", "peer_group": "PG_URBAN"},
        {"bank_id": "SSK005", "bank_name": "Muster-Sparkasse Ost (fiktiv)", "region": "EAST", "peer_group": "PG_URBAN"},
    ]
    return pd.DataFrame(rows, columns=INSTITUTION_COLUMNS)


@pytest.fixture
def portfolio(
    exposures_frame: pd.DataFrame,
    rating_history_frame: pd.DataFrame,
    collateral_frame: pd.DataFrame,
    cashflows_frame: pd.DataFrame,
    institutions_frame: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """All analytical inputs as one dictionary (reporting-shaped)."""
    return {
        "institutions": institutions_frame,
        "exposures": exposures_frame,
        "rating_history": rating_history_frame,
        "collateral": collateral_frame,
        "recovery_cashflows": cashflows_frame,
        "batches": pd.DataFrame(),
        "quality_findings": pd.DataFrame(),
        "quarantine": pd.DataFrame(),
        "pipeline_runs": pd.DataFrame(),
        "rule_catalog": pd.DataFrame(),
        "report_log": pd.DataFrame(),
        "distribution_log": pd.DataFrame(),
    }


@pytest.fixture
def tmp_db(tmp_path):
    """A fresh DuckDB with the application schema; yields the connection."""
    con = connect(tmp_path / "test.duckdb")
    try:
        yield con
    finally:
        con.close()


def make_validation_context(dataset_type: str, **overrides) -> object:
    """Build a ValidationContext without touching the database."""
    from quality.context import ValidationContext

    defaults = dict(
        batch_id="BATCH-TEST-0001",
        dataset_type=dataset_type,
        bank_id="SSK001",
        reporting_date=date(2026, 6, 30),
        execution_timestamp=datetime(2026, 7, 1, 8, 0, 0),
        reference_bank_ids={"SSK001", "SSK003", "SSK005"},
    )
    defaults.update(overrides)
    return ValidationContext(**defaults)
