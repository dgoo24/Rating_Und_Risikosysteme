"""Module B (Loss Estimation) tests against hand-computed portfolio results.

All expected values below were derived manually from the fixture data in
``tests/conftest.py`` and the configured haircuts (REAL_ESTATE 20%,
FINANCIAL_COLLATERAL 5%, OTHER 40%). They intentionally do not re-derive the
module's formulas.

Current collateral (reporting date 2026-06-30), latest valuation per item:
  COL001 100 -> 80 | COL002 150 -> 120 (stale, 2023-01-10) | COL003 90 -> 85.5
  COL004 50 -> 30 | COL005 900 -> 720 (latest of two) | COL006 300 -> 285
  COL007 future -> excluded | COL008 orphan exposure -> excluded from items
  attached value 1,590, adjusted 1,320.5, secured 970.5, unsecured 929.5

Default cohort (defaults 2025-06-30 < date <= 2026-06-30): EXP004 (EAD 100,
recoveries 60 -> 0.6, loss 40 -> 0.4) and EXP006 (EAD 100, recoveries 25 ->
0.25, loss 75 -> 0.75); aggregate recovery 85/200 = 0.425, loss 115/200 = 0.575.
"""
from __future__ import annotations

import pandas as pd
import pytest

from modules.loss_estimation.calculations import (
    filter_current_exposures,
    prepare_collateral,
    prepare_default_cohort,
)
from modules.loss_estimation.collateral_analysis import (
    collateral_exposure_detail,
    collateral_items,
    collateral_summary_detail,
    collateral_type_mix,
    primary_collateral,
    stale_collateral_items,
)
from modules.loss_estimation.loss_rates import (
    loss_severity_bands,
    loss_summary,
)
from modules.loss_estimation.recovery_cashflows import (
    cashflow_by_period,
    prepare_recovery_detail,
    recovery_cashflow_summary,
    recovery_type_mix,
)
from modules.loss_estimation.recovery_rates import (
    recovery_by_rating_vs_collateral,
    recovery_distribution,
    recovery_summary,
)
from modules.loss_estimation.reporting import (
    benchmark_metrics_from_components,
    build_loss_benchmark_metrics,
    build_loss_result,
)

from .conftest import REPORT_DATE


# ---------------------------------------------------------------------------
# Preparation helpers
# ---------------------------------------------------------------------------


def test_prepare_collateral_keeps_latest_valuation_and_orphans(collateral_frame):
    items = prepare_collateral(collateral_frame, REPORT_DATE)
    # COL007 (future valuation) is excluded, COL005 keeps only the 900 value,
    # and the orphan COL008 stays in the raw stock (it is only dropped when
    # joined to current exposures).
    assert items["collateral_id"].tolist() == [
        "COL001", "COL002", "COL003", "COL004", "COL005", "COL006", "COL008",
    ]
    by_id = items.set_index("collateral_id")
    assert by_id.loc["COL005", "collateral_value"] == pytest.approx(900.0)
    assert by_id.loc["COL005", "adjusted_collateral_value"] == pytest.approx(720.0)
    assert by_id.loc["COL003", "adjusted_collateral_value"] == pytest.approx(85.5)
    assert by_id.loc["COL008", "adjusted_collateral_value"] == pytest.approx(45.0)
    assert items["adjusted_collateral_value"].sum() == pytest.approx(1365.5)
    # COL002 was valued 2023-01-10: 1,267 days before the reporting date.
    assert by_id.loc["COL002", "valuation_age_days"] == 1267
    assert by_id.loc["COL002", "valuation_age_years"] == pytest.approx(1267 / 365.25)


def test_collateral_items_drops_orphan_records(collateral_frame, exposures_frame):
    items = collateral_items(collateral_frame, exposures_frame, REPORT_DATE)
    assert "COL008" not in set(items["collateral_id"])
    assert "COL007" not in set(items["collateral_id"])
    assert len(items) == 6
    assert items["adjusted_collateral_value"].sum() == pytest.approx(1320.5)
    assert items["collateral_value"].sum() == pytest.approx(1590.0)


def test_filter_current_exposures(exposures_frame):
    current = filter_current_exposures(exposures_frame, REPORT_DATE)
    assert len(current) == 8
    bank = filter_current_exposures(exposures_frame, REPORT_DATE, bank_ids=["SSK001"])
    assert bank["exposure_id"].tolist() == ["EXP001", "EXP002", "EXP007"]


def test_primary_collateral_picks_largest_adjusted_type(collateral_frame):
    primary = primary_collateral(collateral_frame, REPORT_DATE)
    by_exposure = primary.set_index("exposure_id")
    # EXP001: COL002 adjusted 120 beats COL001 adjusted 80.
    assert by_exposure.loc["EXP001", "primary_collateral_type"] == "REAL_ESTATE"
    assert by_exposure.loc["EXP001", "adjusted_collateral_value"] == pytest.approx(120.0)
    assert by_exposure.loc["EXP005", "primary_collateral_type"] == "REAL_ESTATE"
    assert by_exposure.loc["EXP007", "primary_collateral_type"] == "FINANCIAL_COLLATERAL"


# ---------------------------------------------------------------------------
# Collateral coverage
# ---------------------------------------------------------------------------


def test_collateral_exposure_detail_matches_hand_computation(collateral_frame, exposures_frame):
    detail = collateral_exposure_detail(collateral_frame, exposures_frame, REPORT_DATE).set_index("exposure_id")

    exp001 = detail.loc["EXP001"]
    assert exp001["collateral_items"] == 2
    assert exp001["total_collateral_value"] == pytest.approx(250.0)
    assert exp001["total_adjusted_collateral"] == pytest.approx(200.0)
    assert exp001["haircut_reduction"] == pytest.approx(50.0)
    assert exp001["coverage_ratio"] == pytest.approx(2.0)
    assert exp001["coverage_ratio_capped"] == pytest.approx(1.0)
    assert exp001["secured_ead"] == pytest.approx(100.0)
    assert exp001["unsecured_ead"] == pytest.approx(0.0)
    assert exp001["primary_collateral_type"] == "REAL_ESTATE"
    assert exp001["stale_items"] == 1

    exp002 = detail.loc["EXP002"]
    assert exp002["total_adjusted_collateral"] == pytest.approx(85.5)
    assert exp002["secured_ead"] == pytest.approx(85.5)
    assert exp002["unsecured_ead"] == pytest.approx(114.5)

    exp005 = detail.loc["EXP005"]
    assert exp005["total_collateral_value"] == pytest.approx(950.0)
    assert exp005["total_adjusted_collateral"] == pytest.approx(750.0)
    assert exp005["coverage_ratio_capped"] == pytest.approx(1.0)
    assert exp005["secured_ead"] == pytest.approx(500.0)

    exp007 = detail.loc["EXP007"]
    assert exp007["total_adjusted_collateral"] == pytest.approx(285.0)
    assert exp007["unsecured_ead"] == pytest.approx(15.0)

    for exposure_id in ("EXP003", "EXP004", "EXP006", "EXP008"):
        assert detail.loc[exposure_id, "collateral_items"] == 0
        assert detail.loc[exposure_id, "primary_collateral_type"] == "UNCOLLATERALIZED"
        assert detail.loc[exposure_id, "unsecured_ead"] == pytest.approx(
            detail.loc[exposure_id, "exposure_at_default"]
        )


def test_collateral_summary_detail_matches_hand_computation(collateral_frame, exposures_frame):
    detail = collateral_exposure_detail(collateral_frame, exposures_frame, REPORT_DATE)
    summary = collateral_summary_detail(detail)
    assert summary["current_exposures"] == 8
    assert summary["total_ead"] == pytest.approx(1900.0)
    assert summary["exposures_with_collateral"] == 4
    assert summary["share_exposures_with_collateral"] == pytest.approx(0.5)
    assert summary["share_ead_with_collateral"] == pytest.approx(1100.0 / 1900.0)
    assert summary["total_collateral_value"] == pytest.approx(1590.0)
    assert summary["total_adjusted_collateral"] == pytest.approx(1320.5)
    assert summary["haircut_reduction"] == pytest.approx(269.5)
    assert summary["collateral_coverage"] == pytest.approx(1320.5 / 1900.0)
    assert summary["secured_ead_share"] == pytest.approx(970.5 / 1900.0)
    assert summary["unsecured_ead"] == pytest.approx(929.5)
    assert summary["stale_items"] == 1


def test_collateral_type_mix_matches_hand_computation(collateral_frame, exposures_frame):
    items = collateral_items(collateral_frame, exposures_frame, REPORT_DATE)
    mix = collateral_type_mix(items).set_index("collateral_type")
    assert mix.loc["REAL_ESTATE", "collateral_items"] == 3
    assert mix.loc["REAL_ESTATE", "collateral_value"] == pytest.approx(1150.0)
    assert mix.loc["REAL_ESTATE", "adjusted_collateral_value"] == pytest.approx(920.0)
    assert mix.loc["FINANCIAL_COLLATERAL", "collateral_value"] == pytest.approx(390.0)
    assert mix.loc["FINANCIAL_COLLATERAL", "adjusted_collateral_value"] == pytest.approx(370.5)
    assert mix.loc["OTHER", "collateral_value"] == pytest.approx(50.0)
    assert mix.loc["OTHER", "adjusted_collateral_value"] == pytest.approx(30.0)


def test_stale_collateral_items_flags_only_col002(collateral_frame):
    stale = stale_collateral_items(collateral_frame, REPORT_DATE)
    assert stale["collateral_id"].tolist() == ["COL002"]
    assert stale["valuation_age_years"].iloc[0] == pytest.approx(1267 / 365.25)


def test_collateral_is_not_double_counted_in_loss(collateral_frame, exposures_frame, cashflows_frame):
    """Adding large collateral to a defaulted exposure must not change loss rates."""
    with_big = pd.concat(
        [
            collateral_frame,
            pd.DataFrame(
                [
                    {
                        "collateral_id": "COL_BIG",
                        "exposure_id": "EXP004",
                        "bank_id": "SSK003",
                        "collateral_type": "REAL_ESTATE",
                        "collateral_value": 5000.0,
                        "valuation_date": "2026-01-01",
                        "currency": "EUR",
                    }
                ],
                columns=collateral_frame.columns,
            ),
        ],
        ignore_index=True,
    )
    primary = primary_collateral(with_big, REPORT_DATE)
    cohort = prepare_default_cohort(
        exposures_frame, cashflows_frame, REPORT_DATE, primary_collateral=primary
    )
    by_exposure = cohort.set_index("exposure_id")
    assert by_exposure.loc["EXP004", "recovery_rate"] == pytest.approx(0.6)
    assert by_exposure.loc["EXP004", "loss_rate"] == pytest.approx(0.4)
    assert by_exposure.loc["EXP004", "primary_collateral_type"] == "REAL_ESTATE"

    recovery = recovery_summary(cohort)
    loss = loss_summary(cohort)
    assert recovery["recovery_rate"] == pytest.approx(0.425)
    assert loss["loss_rate"] == pytest.approx(0.575)

    detail = collateral_exposure_detail(with_big, exposures_frame, REPORT_DATE)
    summary = collateral_summary_detail(detail)
    assert summary["total_adjusted_collateral"] == pytest.approx(1320.5 + 4000.0)
    # Secured EAD is capped at the exposure EAD of 100.
    assert summary["secured_ead_share"] == pytest.approx((970.5 + 100.0) / 1900.0)


# ---------------------------------------------------------------------------
# Default cohort and recovery rates
# ---------------------------------------------------------------------------


def test_prepare_default_cohort_matches_hand_computation(exposures_frame, cashflows_frame, collateral_frame):
    primary = primary_collateral(collateral_frame, REPORT_DATE)
    cohort = prepare_default_cohort(
        exposures_frame, cashflows_frame, REPORT_DATE, primary_collateral=primary
    )
    assert set(cohort["exposure_id"]) == {"EXP004", "EXP006"}

    by_exposure = cohort.set_index("exposure_id")
    exp004 = by_exposure.loc["EXP004"]
    assert exp004["bank_id"] == "SSK003"
    assert exp004["ead_at_default"] == pytest.approx(100.0)
    assert exp004["rating_at_default"] == "D"
    assert exp004["total_recoveries"] == pytest.approx(60.0)
    assert exp004["recovery_count"] == 2
    assert exp004["recovery_rate"] == pytest.approx(0.6)
    assert exp004["loss_amount"] == pytest.approx(40.0)
    assert exp004["loss_rate"] == pytest.approx(0.4)
    assert exp004["primary_collateral_type"] == "UNCOLLATERALIZED"

    exp006 = by_exposure.loc["EXP006"]
    assert exp006["bank_id"] == "SSK005"
    assert exp006["rating_at_default"] == "F"
    assert exp006["total_recoveries"] == pytest.approx(25.0)
    assert exp006["recovery_rate"] == pytest.approx(0.25)
    assert exp006["loss_rate"] == pytest.approx(0.75)


def test_prepare_default_cohort_ignores_pre_default_and_future_payments(exposures_frame, cashflows_frame):
    cohort = prepare_default_cohort(exposures_frame, cashflows_frame, REPORT_DATE)
    exp004 = cohort[cohort["exposure_id"] == "EXP004"].iloc[0]
    # CF004 (2025-01-05, before the default) and CF005 (2026-12-01, after the
    # reporting date) must not count: 40 + 20 = 60 only.
    assert exp004["total_recoveries"] == pytest.approx(60.0)
    assert exp004["recovery_count"] == 2


def test_recovery_summary_matches_hand_computation(exposures_frame, cashflows_frame):
    cohort = prepare_default_cohort(exposures_frame, cashflows_frame, REPORT_DATE)
    summary = recovery_summary(cohort)
    assert summary["default_count"] == 2
    assert summary["ead_at_default"] == pytest.approx(200.0)
    assert summary["total_recoveries"] == pytest.approx(85.0)
    assert summary["recovery_rate"] == pytest.approx(0.425)
    assert summary["median_recovery_rate"] == pytest.approx(0.425)
    assert summary["average_recovery_rate"] == pytest.approx(0.425)
    assert summary["zero_recovery_count"] == 0
    assert summary["recoveries_observed"] == 2


def test_loss_summary_matches_hand_computation(exposures_frame, cashflows_frame):
    cohort = prepare_default_cohort(exposures_frame, cashflows_frame, REPORT_DATE)
    summary = loss_summary(cohort)
    assert summary["loss_amount"] == pytest.approx(115.0)
    assert summary["loss_rate"] == pytest.approx(0.575)
    assert summary["median_loss_rate"] == pytest.approx(0.575)
    assert summary["full_loss_count"] == 0


def test_recovery_distribution_buckets(exposures_frame, cashflows_frame):
    cohort = prepare_default_cohort(exposures_frame, cashflows_frame, REPORT_DATE)
    distribution = recovery_distribution(cohort).set_index("recovery_bucket")
    assert distribution.loc["50-75%", "default_count"] == 1  # EXP004: 0.6
    assert distribution.loc["25-50%", "default_count"] == 1  # EXP006: 0.25
    assert distribution["default_count"].sum() == 2


def test_loss_severity_bands(exposures_frame, cashflows_frame):
    cohort = prepare_default_cohort(exposures_frame, cashflows_frame, REPORT_DATE)
    severity = loss_severity_bands(cohort).set_index("severity")
    assert severity.loc["MODERATE", "default_count"] == 1  # 0.4 loss rate
    assert severity.loc["SEVERE", "default_count"] == 1  # 0.75 loss rate
    assert severity["default_count"].sum() == 2


def test_recovery_by_rating_vs_collateral(exposures_frame, cashflows_frame):
    cohort = prepare_default_cohort(exposures_frame, cashflows_frame, REPORT_DATE)
    table = recovery_by_rating_vs_collateral(cohort)
    assert set(zip(table["rating_at_default"], table["primary_collateral_type"])) == {
        ("D", "UNCOLLATERALIZED"), ("F", "UNCOLLATERALIZED"),
    }


# ---------------------------------------------------------------------------
# Recovery cashflows
# ---------------------------------------------------------------------------


def test_prepare_recovery_detail_matches_hand_computation(exposures_frame, cashflows_frame):
    cohort = prepare_default_cohort(exposures_frame, cashflows_frame, REPORT_DATE)
    detail = prepare_recovery_detail(cashflows_frame, cohort, REPORT_DATE)
    assert detail["cashflow_id"].tolist() == ["CF003", "CF001", "CF002"]
    by_id = detail.set_index("cashflow_id")
    # CF003: 2026-01-10 - 2025-11-15 = 56 days; CF001: 2026-04-15 - 2026-03-31 = 15;
    # CF002: 2026-05-20 - 2026-03-31 = 50.
    assert by_id.loc["CF003", "days_to_recovery"] == 56
    assert by_id.loc["CF003", "exposure_id"] == "EXP006"
    assert by_id.loc["CF001", "days_to_recovery"] == 15
    assert by_id.loc["CF002", "days_to_recovery"] == 50


def test_recovery_cashflow_summary_matches_hand_computation(exposures_frame, cashflows_frame):
    cohort = prepare_default_cohort(exposures_frame, cashflows_frame, REPORT_DATE)
    detail = prepare_recovery_detail(cashflows_frame, cohort, REPORT_DATE)
    summary = recovery_cashflow_summary(detail)
    assert summary["cashflow_count"] == 3
    assert summary["total_recovered"] == pytest.approx(85.0)
    assert summary["weighted_average_days"] == pytest.approx(3000.0 / 85.0)
    assert summary["max_days"] == 56
    assert summary["exposures_with_recovery"] == 2


def test_recovery_type_mix(exposures_frame, cashflows_frame):
    cohort = prepare_default_cohort(exposures_frame, cashflows_frame, REPORT_DATE)
    detail = prepare_recovery_detail(cashflows_frame, cohort, REPORT_DATE)
    mix = recovery_type_mix(detail).set_index("recovery_type")
    assert mix.loc["CASH", "cashflow_count"] == 2
    assert mix.loc["CASH", "recovered_amount"] == pytest.approx(65.0)
    assert mix.loc["COLLATERAL_LIQUIDATION", "recovered_amount"] == pytest.approx(20.0)


def test_cashflow_by_period_quarters(exposures_frame, cashflows_frame):
    cohort = prepare_default_cohort(exposures_frame, cashflows_frame, REPORT_DATE)
    detail = prepare_recovery_detail(cashflows_frame, cohort, REPORT_DATE)
    by_period = cashflow_by_period(detail).set_index("payment_period")
    assert by_period.loc["2026Q1", "recovered_amount"] == pytest.approx(25.0)
    assert by_period.loc["2026Q2", "recovered_amount"] == pytest.approx(60.0)
    assert by_period.loc["2026Q2", "cumulative_amount"] == pytest.approx(85.0)
    assert by_period.loc["2026Q2", "cumulative_share"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Report bundle and benchmark inputs
# ---------------------------------------------------------------------------


def test_build_loss_result_community_kpis(exposures_frame, collateral_frame, cashflows_frame):
    result = build_loss_result(exposures_frame, collateral_frame, cashflows_frame, REPORT_DATE)
    kpis = result.kpis
    assert kpis["current_ead"] == pytest.approx(1900.0)
    assert kpis["default_count"] == 2
    assert kpis["ead_at_default"] == pytest.approx(200.0)
    assert kpis["recovery_rate"] == pytest.approx(0.425)
    assert kpis["loss_rate"] == pytest.approx(0.575)
    assert kpis["loss_amount"] == pytest.approx(115.0)
    assert kpis["collateral_coverage"] == pytest.approx(1320.5 / 1900.0)
    assert kpis["secured_ead_share"] == pytest.approx(970.5 / 1900.0)
    assert kpis["stale_collateral_items"] == 1
    assert kpis["cashflow_count"] == 3
    assert kpis["weighted_average_days"] == pytest.approx(3000.0 / 85.0)
    assert kpis["cohort_start"] == pd.Timestamp("2025-06-30")
    assert kpis["cohort_end"] == REPORT_DATE
    assert len(result.current_exposures) == 8
    assert len(result.collateral_detail) == 8
    assert len(result.collateral_items) == 6


def test_build_loss_result_bank_scope(exposures_frame, collateral_frame, cashflows_frame):
    result = build_loss_result(
        exposures_frame, collateral_frame, cashflows_frame, REPORT_DATE, bank_ids=["SSK001"]
    )
    kpis = result.kpis
    assert kpis["current_ead"] == pytest.approx(600.0)
    assert kpis["default_count"] == 0
    assert kpis["recovery_rate"] is None  # no defaults in the SSK001 cohort
    assert kpis["loss_rate"] is None
    assert kpis["collateral_coverage"] == pytest.approx(570.5 / 600.0)
    assert kpis["secured_ead_share"] == pytest.approx(470.5 / 600.0)
    assert kpis["cashflow_count"] == 0
    assert result.cohort.empty
    assert len(result.collateral_detail) == 3


def test_build_loss_result_raises_without_current_exposures(exposures_frame, collateral_frame, cashflows_frame):
    with pytest.raises(ValueError, match="No exposures available"):
        build_loss_result(
            exposures_frame, collateral_frame, cashflows_frame, pd.Timestamp("2026-03-31")
        )


def test_benchmark_metrics_from_components_matches_hand_computation(
    exposures_frame, collateral_frame, cashflows_frame
):
    primary = primary_collateral(collateral_frame, REPORT_DATE)
    cohort = prepare_default_cohort(
        exposures_frame, cashflows_frame, REPORT_DATE, primary_collateral=primary
    )
    detail = collateral_exposure_detail(collateral_frame, exposures_frame, REPORT_DATE)
    current = filter_current_exposures(exposures_frame, REPORT_DATE)
    metrics = benchmark_metrics_from_components(current, cohort, detail, REPORT_DATE)

    # Cohort banks get RECOVERY_RATE_12M and LOSS_RATE_12M (SSK003, SSK005);
    # every bank with current exposures gets COLLATERAL_COVERAGE and SECURED_EAD_SHARE.
    assert len(metrics) == 10
    ssk003 = metrics[metrics["bank_id"] == "SSK003"].set_index("metric_id")
    assert ssk003.loc["RECOVERY_RATE_12M", "numerator"] == pytest.approx(60.0)
    assert ssk003.loc["RECOVERY_RATE_12M", "denominator"] == pytest.approx(100.0)
    assert ssk003.loc["LOSS_RATE_12M", "numerator"] == pytest.approx(40.0)
    ssk005 = metrics[metrics["bank_id"] == "SSK005"].set_index("metric_id")
    assert ssk005.loc["RECOVERY_RATE_12M", "numerator"] == pytest.approx(25.0)
    ssk001 = metrics[metrics["bank_id"] == "SSK001"].set_index("metric_id")
    assert ssk001.loc["COLLATERAL_COVERAGE", "numerator"] == pytest.approx(570.5)
    assert ssk001.loc["COLLATERAL_COVERAGE", "denominator"] == pytest.approx(600.0)
    assert ssk001.loc["SECURED_EAD_SHARE", "numerator"] == pytest.approx(470.5)


def test_build_loss_benchmark_metrics_matches_components(
    exposures_frame, collateral_frame, cashflows_frame
):
    metrics = build_loss_benchmark_metrics(
        exposures_frame, collateral_frame, cashflows_frame, REPORT_DATE
    )
    assert len(metrics) == 10
    assert set(metrics["metric_id"]) == {
        "RECOVERY_RATE_12M", "LOSS_RATE_12M", "COLLATERAL_COVERAGE", "SECURED_EAD_SHARE",
    }
