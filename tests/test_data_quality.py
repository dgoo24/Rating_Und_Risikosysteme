"""Tests for the data-quality validation engine.

Every expected outcome is hand-computed from the documented rule catalog in
``quality/rules.py``. The lifecycle case validates a deliberately flawed
five-row exposure batch (invalid rating G, an exact duplicate, a
non-quarter-end snapshot with a missing recommended balance) and expects:

- 5 rows received, 2 rejected (ERROR), 3 valid, 1 row retained with warnings
- quality score 60.0 (3 of 5 rows valid)
- 4 persisted findings: CONS-EXP-002 (ERROR), UNIQ-EXP-001 (ERROR),
  CONS-EXP-004 (WARNING), COMP-EXP-006 (WARNING)

Single-rule tests use one minimal canonical row each and assert the exact
rule_id, severity and row index of the finding.
"""
from __future__ import annotations

import pandas as pd
import pytest

from quality.validation_engine import (
    CURATED_COLUMNS,
    DATE_COLUMNS,
    evaluate_findings,
    load_outcome,
)
from tests.conftest import (
    CASHFLOW_COLUMNS,
    COLLATERAL_COLUMNS,
    EXPOSURE_COLUMNS,
    RATING_COLUMNS,
    make_validation_context,
)


# ---------------------------------------------------------------------------
# Canonical single-row builders (real booleans and string dates)
# ---------------------------------------------------------------------------


def exposure_frame(**overrides) -> pd.DataFrame:
    """One canonical exposure row; keyword overrides replace single fields."""
    row = {
        "exposure_id": "EXP001",
        "bank_id": "SSK001",
        "customer_id": "C001",
        "snapshot_date": "2026-06-30",
        "product_type": "MORTGAGE",
        "industry_sector": "MANUFACTURING",
        "region": "NORTH",
        "rating_grade": "A",
        "exposure_at_default": 100.0,
        "outstanding_balance": 95.0,
        "currency": "EUR",
        "origination_date": "2020-01-15",
        "maturity_date": "2030-06-30",
        "default_flag": False,
        "default_date": None,
    }
    row.update(overrides)
    return pd.DataFrame([row], columns=EXPOSURE_COLUMNS)


def rating_frame(**overrides) -> pd.DataFrame:
    row = {
        "exposure_id": "EXP001",
        "bank_id": "SSK001",
        "observation_date": pd.Timestamp("2026-06-30"),
        "rating_grade": "A",
    }
    row.update(overrides)
    return pd.DataFrame([row], columns=RATING_COLUMNS)


def collateral_frame(**overrides) -> pd.DataFrame:
    row = {
        "collateral_id": "COL001",
        "exposure_id": "EXP001",
        "bank_id": "SSK001",
        "collateral_type": "REAL_ESTATE",
        "collateral_value": 100.0,
        "valuation_date": "2026-01-15",
        "currency": "EUR",
    }
    row.update(overrides)
    return pd.DataFrame([row], columns=COLLATERAL_COLUMNS)


def cashflow_frame(**overrides) -> pd.DataFrame:
    row = {
        "cashflow_id": "CF001",
        "exposure_id": "EXP001",
        "bank_id": "SSK001",
        "payment_date": "2026-04-15",
        "recovery_amount": 40.0,
        "recovery_type": "CASH",
        "adjustment_reason": None,
    }
    row.update(overrides)
    return pd.DataFrame([row], columns=CASHFLOW_COLUMNS)


def findings_for(frame: pd.DataFrame, dataset_type: str, **ctx_overrides) -> pd.DataFrame:
    return evaluate_findings(frame, make_validation_context(dataset_type, **ctx_overrides))


def assert_single_finding(
    findings: pd.DataFrame,
    rule_id: str,
    severity: str,
    row_index: int = 0,
    record_id: str = "EXP001",
) -> None:
    assert len(findings) == 1, findings.to_dict("records")
    finding = findings.iloc[0]
    assert finding["rule_id"] == rule_id
    assert finding["severity"] == severity
    assert finding["row_index"] == row_index
    assert finding["record_id"] == record_id


# ---------------------------------------------------------------------------
# Lifecycle: RAW -> STAGING -> QUALITY -> CURATED via load_outcome
# ---------------------------------------------------------------------------


def flawed_batch() -> pd.DataFrame:
    """The five-row batch documented in the module docstring."""
    rows = [
        {
            "exposure_id": "EXP001", "bank_id": "SSK001", "customer_id": "C001",
            "snapshot_date": "2026-06-30", "product_type": "MORTGAGE",
            "industry_sector": "MANUFACTURING", "region": "NORTH", "rating_grade": "A",
            "exposure_at_default": 1000.0, "outstanding_balance": 950.0, "currency": "EUR",
            "origination_date": "2020-01-15", "maturity_date": "2030-06-30",
            "default_flag": False, "default_date": None,
        },
        {
            "exposure_id": "EXP002", "bank_id": "SSK001", "customer_id": "C002",
            "snapshot_date": "2026-06-30", "product_type": "COMMERCIAL",
            "industry_sector": "TRADE", "region": "NORTH", "rating_grade": "B",
            "exposure_at_default": 2000.0, "outstanding_balance": 1900.0, "currency": "EUR",
            "origination_date": "2021-06-01", "maturity_date": "2028-06-01",
            "default_flag": False, "default_date": None,
        },
        {
            # rating G is not on the configured A-F scale -> CONS-EXP-002 (ERROR)
            "exposure_id": "EXP003", "bank_id": "SSK001", "customer_id": "C003",
            "snapshot_date": "2026-06-30", "product_type": "SME",
            "industry_sector": "SERVICES", "region": "NORTH", "rating_grade": "G",
            "exposure_at_default": 500.0, "outstanding_balance": 450.0, "currency": "EUR",
            "origination_date": "2022-01-01", "maturity_date": "2029-01-01",
            "default_flag": False, "default_date": None,
        },
        {
            # exact duplicate of EXP002 -> UNIQ-EXP-001 (ERROR, first occurrence kept)
            "exposure_id": "EXP002", "bank_id": "SSK001", "customer_id": "C002",
            "snapshot_date": "2026-06-30", "product_type": "COMMERCIAL",
            "industry_sector": "TRADE", "region": "NORTH", "rating_grade": "B",
            "exposure_at_default": 2000.0, "outstanding_balance": 1900.0, "currency": "EUR",
            "origination_date": "2021-06-01", "maturity_date": "2028-06-01",
            "default_flag": False, "default_date": None,
        },
        {
            # non-quarter-end snapshot + missing recommended balance
            # -> CONS-EXP-004 (WARNING) + COMP-EXP-006 (WARNING), row retained
            "exposure_id": "EXP004", "bank_id": "SSK001", "customer_id": "C004",
            "snapshot_date": "2026-06-15", "product_type": "CONSUMER",
            "industry_sector": "HEALTHCARE", "region": "NORTH", "rating_grade": "C",
            "exposure_at_default": 300.0, "outstanding_balance": None, "currency": "EUR",
            "origination_date": "2023-03-01", "maturity_date": "2028-03-01",
            "default_flag": False, "default_date": None,
        },
    ]
    return pd.DataFrame(rows, columns=EXPOSURE_COLUMNS)


def count(tmp_db, table: str) -> int:
    return int(tmp_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_load_outcome_quarantines_errors_and_keeps_warnings(tmp_db):
    outcome = load_outcome(tmp_db, flawed_batch(), make_validation_context("exposures"))

    assert outcome.rows_received == 5
    assert outcome.rows_valid == 3
    assert outcome.rows_rejected == 2
    assert outcome.rows_warned == 1
    assert outcome.quality_score == 60.0  # 3 valid of 5 received

    assert count(tmp_db, "exposures") == 3
    assert count(tmp_db, "quarantine_records") == 2
    assert count(tmp_db, "quality_results") == 4

    curated = tmp_db.execute(
        "SELECT exposure_id FROM exposures ORDER BY exposure_id"
    ).fetchall()
    assert [row[0] for row in curated] == ["EXP001", "EXP002", "EXP004"]

    quarantined = tmp_db.execute(
        "SELECT record_id FROM quarantine_records ORDER BY record_id"
    ).fetchall()
    assert [row[0] for row in quarantined] == ["EXP002", "EXP003"]

    rules = sorted(outcome.findings["rule_id"].tolist())
    assert rules == ["COMP-EXP-006", "CONS-EXP-002", "CONS-EXP-004", "UNIQ-EXP-001"]

    severities = tmp_db.execute(
        "SELECT severity, COUNT(*) FROM quality_results GROUP BY severity ORDER BY 1"
    ).fetchall()
    assert severities == [("ERROR", 2), ("WARNING", 2)]

    batch_ids = {
        row[0]
        for row in tmp_db.execute("SELECT DISTINCT batch_id FROM exposures").fetchall()
    }
    assert batch_ids == {"BATCH-TEST-0001"}


def test_load_outcome_accepts_a_clean_batch(tmp_db):
    outcome = load_outcome(tmp_db, exposure_frame(), make_validation_context("exposures"))
    assert outcome.rows_received == 1
    assert outcome.rows_valid == 1
    assert outcome.rows_rejected == 0
    assert outcome.rows_warned == 0
    assert outcome.quality_score == 100.0
    assert outcome.findings.empty
    assert count(tmp_db, "exposures") == 1
    assert count(tmp_db, "quarantine_records") == 0


def test_load_outcome_writes_canonical_columns(tmp_db):
    load_outcome(tmp_db, exposure_frame(), make_validation_context("exposures"))
    columns = [
        row[0]
        for row in tmp_db.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'exposures' ORDER BY ordinal_position"
        ).fetchall()
    ]
    assert set(CURATED_COLUMNS["exposures"]).issubset(columns)


# ---------------------------------------------------------------------------
# Exposure rules
# ---------------------------------------------------------------------------


def test_missing_exposure_id_is_an_error():
    findings = findings_for(exposure_frame(exposure_id=None), "exposures")
    assert_single_finding(findings, "COMP-EXP-001", "ERROR", record_id="MISSING_ID")


def test_unknown_bank_is_an_error():
    findings = findings_for(exposure_frame(bank_id="SSK999"), "exposures")
    assert_single_finding(findings, "CONS-EXP-001", "ERROR")


def test_rating_outside_scale_is_an_error():
    findings = findings_for(exposure_frame(rating_grade="G"), "exposures")
    assert_single_finding(findings, "CONS-EXP-002", "ERROR")


def test_wrong_currency_is_an_error():
    findings = findings_for(exposure_frame(currency="USD"), "exposures")
    assert_single_finding(findings, "CONS-EXP-003", "ERROR")


def test_non_quarter_end_snapshot_is_a_warning():
    findings = findings_for(exposure_frame(snapshot_date="2026-06-15"), "exposures")
    assert_single_finding(findings, "CONS-EXP-004", "WARNING")


def test_unreadable_default_flag_is_a_warning():
    findings = findings_for(exposure_frame(default_flag=None), "exposures")
    assert_single_finding(findings, "CONS-EXP-005", "WARNING")


def test_negative_ead_is_an_error():
    findings = findings_for(exposure_frame(exposure_at_default=-50.0), "exposures")
    assert_single_finding(findings, "PLAUS-EXP-001", "ERROR")


def test_negative_outstanding_balance_is_a_warning():
    findings = findings_for(exposure_frame(outstanding_balance=-10.0), "exposures")
    assert_single_finding(findings, "PLAUS-EXP-002", "WARNING")


def test_maturity_before_origination_is_an_error():
    findings = findings_for(exposure_frame(maturity_date="2019-01-01"), "exposures")
    assert_single_finding(findings, "PLAUS-EXP-003", "ERROR")


def test_origination_after_snapshot_is_an_error():
    findings = findings_for(exposure_frame(origination_date="2026-09-01"), "exposures")
    assert_single_finding(findings, "PLAUS-EXP-004", "ERROR")


def test_default_before_origination_is_an_error():
    findings = findings_for(
        exposure_frame(default_flag=True, default_date="2019-06-30"), "exposures"
    )
    assert_single_finding(findings, "PLAUS-EXP-005", "ERROR")


def test_future_snapshot_date_is_an_error():
    # execution_timestamp defaults to 2026-07-01: a 2026-12-31 snapshot is future.
    findings = findings_for(exposure_frame(snapshot_date="2026-12-31"), "exposures")
    assert_single_finding(findings, "PLAUS-EXP-006", "ERROR")


def test_default_flag_without_default_date_is_an_error():
    findings = findings_for(exposure_frame(default_flag=True), "exposures")
    assert_single_finding(findings, "PLAUS-EXP-007", "ERROR")


def test_default_date_without_flag_is_a_warning():
    findings = findings_for(
        exposure_frame(default_flag=False, default_date="2026-01-31"), "exposures"
    )
    assert_single_finding(findings, "PLAUS-EXP-008", "WARNING")


def test_duplicate_within_batch_flags_second_row_only():
    frame = pd.concat(
        [exposure_frame(), exposure_frame()], ignore_index=True
    )
    findings = findings_for(frame, "exposures")
    assert_single_finding(findings, "UNIQ-EXP-001", "ERROR", row_index=1)


def test_existing_curated_snapshot_is_an_error():
    findings = findings_for(
        exposure_frame(),
        "exposures",
        existing_exposure_keys={("EXP001", "2026-06-30")},
    )
    assert_single_finding(findings, "UNIQ-EXP-002", "ERROR")


# ---------------------------------------------------------------------------
# Rating-history rules
# ---------------------------------------------------------------------------


def test_future_rating_observation_is_an_error():
    findings = findings_for(
        rating_frame(observation_date=pd.Timestamp("2026-12-31")),
        "rating_history",
        exposure_bank_map={"EXP001": "SSK001"},
    )
    assert_single_finding(findings, "PLAUS-RAT-001", "ERROR", record_id="EXP001@2026-12-31")


def test_rating_history_with_invalid_grade_is_an_error():
    findings = findings_for(
        rating_frame(rating_grade="X"),
        "rating_history",
        exposure_bank_map={"EXP001": "SSK001"},
    )
    assert_single_finding(findings, "CONS-RAT-002", "ERROR", record_id="EXP001@2026-06-30")


def test_rating_history_for_unknown_exposure_is_an_error():
    findings = findings_for(rating_frame(exposure_id="EXP999"), "rating_history")
    assert_single_finding(findings, "CONS-RAT-003", "ERROR", record_id="EXP999@2026-06-30")


# ---------------------------------------------------------------------------
# Collateral rules
# ---------------------------------------------------------------------------


def test_future_collateral_valuation_is_an_error():
    findings = findings_for(
        collateral_frame(valuation_date="2026-12-31"),
        "collateral",
        exposure_bank_map={"EXP001": "SSK001"},
    )
    assert_single_finding(findings, "PLAUS-COL-002", "ERROR", record_id="COL001")


def test_stale_collateral_valuation_is_a_warning():
    # execution_timestamp 2026-07-01 minus 3 years -> cutoff 2023-07-01;
    # a valuation from 2023-01-10 is older than the threshold.
    findings = findings_for(
        collateral_frame(valuation_date="2023-01-10"),
        "collateral",
        exposure_bank_map={"EXP001": "SSK001"},
    )
    assert_single_finding(findings, "PLAUS-COL-003", "WARNING", record_id="COL001")


def test_collateral_for_unknown_bank_is_an_error():
    # exposure_bank_map points to the same (unknown) bank so that only the
    # unknown-bank rule fires, not the orphan/mismatch relationship rules.
    findings = findings_for(
        collateral_frame(bank_id="SSK999"),
        "collateral",
        exposure_bank_map={"EXP001": "SSK999"},
    )
    assert_single_finding(findings, "CONS-COL-001", "ERROR", record_id="COL001")


# ---------------------------------------------------------------------------
# Recovery-cashflow rules
# ---------------------------------------------------------------------------


def test_future_recovery_payment_is_an_error():
    findings = findings_for(
        cashflow_frame(payment_date="2026-12-01"),
        "recovery_cashflows",
        exposure_bank_map={"EXP001": "SSK001"},
    )
    assert_single_finding(findings, "PLAUS-REC-002", "ERROR", record_id="CF001")


def test_recoveries_above_ead_without_reason_are_an_error():
    # EAD 100; cumulative payments 60 + 50 = 110 > 100 -> second row flagged.
    frame = pd.concat(
        [
            cashflow_frame(cashflow_id="CF001", recovery_amount=60.0, payment_date="2026-04-01"),
            cashflow_frame(cashflow_id="CF002", recovery_amount=50.0, payment_date="2026-05-01"),
        ],
        ignore_index=True,
    )
    findings = findings_for(
        frame,
        "recovery_cashflows",
        exposure_bank_map={"EXP001": "SSK001"},
        exposure_ead_map={"EXP001": 100.0},
    )
    assert_single_finding(findings, "PLAUS-REC-003", "ERROR", row_index=1, record_id="CF002")


def test_recoveries_above_ead_with_reason_pass():
    frame = pd.concat(
        [
            cashflow_frame(cashflow_id="CF001", recovery_amount=60.0, payment_date="2026-04-01"),
            cashflow_frame(
                cashflow_id="CF002",
                recovery_amount=50.0,
                payment_date="2026-05-01",
                adjustment_reason="Documented settlement including litigation proceeds",
            ),
        ],
        ignore_index=True,
    )
    findings = findings_for(
        frame,
        "recovery_cashflows",
        exposure_bank_map={"EXP001": "SSK001"},
        exposure_ead_map={"EXP001": 100.0},
    )
    assert findings.empty


def test_recovery_for_unknown_exposure_is_an_error():
    findings = findings_for(cashflow_frame(exposure_id="EXP999"), "recovery_cashflows")
    assert_single_finding(findings, "CONS-REC-002", "ERROR", record_id="CF001")


def test_negative_recovery_amount_is_an_error():
    findings = findings_for(
        cashflow_frame(recovery_amount=-5.0),
        "recovery_cashflows",
        exposure_bank_map={"EXP001": "SSK001"},
    )
    assert_single_finding(findings, "PLAUS-REC-001", "ERROR", record_id="CF001")


# ---------------------------------------------------------------------------
# Engine plumbing
# ---------------------------------------------------------------------------


def test_evaluate_findings_enriches_findings_with_metadata():
    findings = findings_for(exposure_frame(rating_grade="G"), "exposures")
    finding = findings.iloc[0]
    assert finding["rule_name"] == "Rating grade is on the configured scale"
    assert finding["category"] == "Consistency"
    assert finding["bank_id"] == "SSK001"
    assert finding["reporting_date"] == pd.Timestamp("2026-06-30").date()
    assert finding["batch_id"] == "BATCH-TEST-0001"
    assert finding["failed_value"] == "G"
    assert finding["field_name"] == "rating_grade"
    assert str(finding["quality_result_id"]).startswith("QR-")


def test_evaluate_findings_returns_empty_frame_without_rows():
    findings = findings_for(exposure_frame().iloc[0:0], "exposures")
    assert findings.empty
    assert "rule_id" in findings.columns


def test_curated_column_contracts_are_complete():
    # The curated layer always persists the batch lineage column.
    for dataset_type in ("exposures", "rating_history", "collateral", "recovery_cashflows"):
        assert "batch_id" in CURATED_COLUMNS[dataset_type]
        assert DATE_COLUMNS[dataset_type]


@pytest.mark.parametrize(
    "dataset_type",
    ["exposures", "rating_history", "collateral", "recovery_cashflows"],
)
def test_checks_registry_covers_all_dataset_types(dataset_type):
    from quality.validation_engine import CHECKS

    assert len(CHECKS[dataset_type]) == 4  # completeness, uniqueness, consistency, plausibility
