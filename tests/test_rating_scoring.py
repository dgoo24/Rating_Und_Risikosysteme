"""Module A (Rating & Scoring) tests against hand-computed portfolio results.

All expected values below were derived manually from the fixture data in
``tests/conftest.py`` and the configured PD mapping (A 0.1%, B 0.3%, C 0.8%,
D 2.0%, E 5.0%, F 12%). They intentionally do not re-derive the module's
formulas.

Current snapshot 2026-06-30 (8 exposures, EAD 1,900):
  EXP001 A 100 | EXP002 B 200 | EXP003 C 400 | EXP004 D 100
  EXP005 A 500 | EXP006 E 100 | EXP007 B 300 | EXP008 C 200
  expected default EAD = 0.1 + 0.6 + 3.2 + 2.0 + 0.5 + 5.0 + 0.9 + 1.6 = 13.9

12M default observation (start snapshot 2025-06-30, 6 performing, EAD 1,400):
  defaults EXP004 (2026-03-31) and EXP006 (2025-11-15); model PD EAD 17.4.

Migration 2025-06-30 -> 2026-06-30: 6 matched, upgrades EXP002 (C->B) and
EXP006 (F->E), downgrade EXP003 (B->C), 3 unchanged, 2 entries, 0 exits.
"""
from __future__ import annotations

import pandas as pd
import pytest

from modules.rating_scoring.calculations import (
    filter_exposures,
    latest_reporting_date,
    portfolio_ead,
    quarter_end_dates,
    weighted_pd,
)
from modules.rating_scoring.default_rates import (
    default_observation,
    default_rate_by_bank,
    default_rate_summary,
    default_rate_trend,
    observation_start_date,
)
from modules.rating_scoring.pd_calculations import (
    pd_by_bank,
    pd_by_rating,
    pd_summary_kpis,
    pd_trend,
)
from modules.rating_scoring.rating_distribution import (
    investment_grade_share,
    rating_distribution,
)
from modules.rating_scoring.rating_migration import (
    calculate_migration,
    empty_migration_result,
    migration_matrix_long,
)
from modules.rating_scoring.reporting import (
    build_rating_benchmark_metrics,
    build_rating_result,
)

from .conftest import REPORT_DATE, RATING_COLUMNS


# ---------------------------------------------------------------------------
# Shared preparation helpers
# ---------------------------------------------------------------------------


def test_prepare_exposures_normalises_ratings_dates_and_flags(exposures_frame):
    from modules.rating_scoring.calculations import prepare_exposures

    frame = exposures_frame.copy()
    frame["rating_grade"] = frame["rating_grade"].str.lower()
    prepared = prepare_exposures(frame)
    assert set(prepared["rating_grade"]).issubset({"A", "B", "C", "D", "E", "F"})
    assert pd.api.types.is_datetime64_any_dtype(prepared["snapshot_date"])
    # EXP009 keeps its snapshot; only reporting-period helpers drop non-quarter-ends.
    assert (prepared["exposure_id"] == "EXP009").sum() == 1


def test_filter_exposures_selects_snapshot_and_bank(exposures_frame):
    current = filter_exposures(exposures_frame, REPORT_DATE)
    assert len(current) == 8
    assert portfolio_ead(current) == pytest.approx(1900.0)

    bank = filter_exposures(exposures_frame, REPORT_DATE, bank_ids=["SSK001"])
    assert bank["exposure_id"].tolist() == ["EXP001", "EXP002", "EXP007"]
    assert portfolio_ead(bank) == pytest.approx(600.0)

    sector = filter_exposures(exposures_frame, REPORT_DATE, sectors=["REAL_ESTATE"])
    assert sector["exposure_id"].tolist() == ["EXP005"]


def test_quarter_end_dates_ignores_intradate_snapshots(exposures_frame):
    dates = quarter_end_dates(exposures_frame)
    assert dates == [pd.Timestamp("2025-06-30"), pd.Timestamp("2026-06-30")]


def test_latest_reporting_date(exposures_frame):
    assert latest_reporting_date(exposures_frame) == pd.Timestamp("2026-06-30")


# ---------------------------------------------------------------------------
# PD calculations
# ---------------------------------------------------------------------------


def test_weighted_pd_matches_hand_computation(exposures_frame):
    current = filter_exposures(exposures_frame, REPORT_DATE)
    assert weighted_pd(current) == pytest.approx(13.9 / 1900.0)


def test_weighted_pd_excludes_invalid_ratings(exposures_frame):
    current = filter_exposures(exposures_frame, REPORT_DATE).copy()
    current.loc[current["exposure_id"] == "EXP008", "rating_grade"] = "X"
    # EXP008 contributes 1.6 of the 13.9 expected default EAD and 200 EAD.
    assert weighted_pd(current) == pytest.approx((13.9 - 1.6) / 1700.0)


def test_pd_by_rating_matches_hand_computation(exposures_frame):
    current = filter_exposures(exposures_frame, REPORT_DATE)
    grouped = pd_by_rating(current).set_index("rating_grade")
    assert grouped.loc["A", "ead"] == pytest.approx(600.0)
    assert grouped.loc["A", "expected_default_ead"] == pytest.approx(0.6)
    assert grouped.loc["A", "exposure_count"] == 2
    assert grouped.loc["B", "expected_default_ead"] == pytest.approx(1.5)
    assert grouped.loc["C", "expected_default_ead"] == pytest.approx(4.8)
    assert grouped.loc["D", "expected_default_ead"] == pytest.approx(2.0)
    assert grouped.loc["E", "expected_default_ead"] == pytest.approx(5.0)
    # Grade F has no exposures and is dropped from the table.
    assert "F" not in grouped.index
    assert grouped["expected_default_ead"].sum() == pytest.approx(13.9)


def test_pd_by_bank_matches_hand_computation(exposures_frame):
    current = filter_exposures(exposures_frame, REPORT_DATE)
    grouped = pd_by_bank(current).set_index("bank_id")
    assert grouped.loc["SSK001", "ead"] == pytest.approx(600.0)
    assert grouped.loc["SSK001", "expected_default_ead"] == pytest.approx(1.6)
    assert grouped.loc["SSK003", "expected_default_ead"] == pytest.approx(5.2)
    assert grouped.loc["SSK003", "weighted_pd"] == pytest.approx(5.2 / 500.0)
    assert grouped.loc["SSK005", "expected_default_ead"] == pytest.approx(7.1)


def test_pd_summary_kpis(exposures_frame):
    current = filter_exposures(exposures_frame, REPORT_DATE)
    kpis = pd_summary_kpis(current)
    assert kpis["portfolio_pd"] == pytest.approx(13.9 / 1900.0)
    assert kpis["total_ead"] == pytest.approx(1900.0)
    assert kpis["expected_default_ead"] == pytest.approx(13.9)
    assert kpis["exposure_count"] == 8


def test_pd_trend_covers_both_quarter_ends(exposures_frame):
    trend = pd_trend(exposures_frame).set_index("snapshot_date")
    assert len(trend) == 2
    assert trend.loc[pd.Timestamp("2025-06-30"), "ead"] == pytest.approx(1400.0)
    assert trend.loc[pd.Timestamp("2025-06-30"), "expected_default_ead"] == pytest.approx(17.4)
    assert trend.loc[pd.Timestamp("2026-06-30"), "expected_default_ead"] == pytest.approx(13.9)
    # EXP009 (2026-05-15) must not create a third reporting period.
    assert pd.Timestamp("2026-05-15") not in trend.index


# ---------------------------------------------------------------------------
# Rating distribution
# ---------------------------------------------------------------------------


def test_rating_distribution_matches_hand_computation(exposures_frame):
    current = filter_exposures(exposures_frame, REPORT_DATE)
    distribution = rating_distribution(current).set_index("rating_grade")
    assert distribution.index.tolist() == ["A", "B", "C", "D", "E", "F"]
    assert distribution.loc["A", "exposure_count"] == 2
    assert distribution.loc["A", "ead"] == pytest.approx(600.0)
    assert distribution.loc["B", "ead"] == pytest.approx(500.0)
    assert distribution.loc["C", "ead"] == pytest.approx(600.0)
    assert distribution.loc["D", "exposure_count"] == 1
    assert distribution.loc["E", "exposure_count"] == 1
    assert distribution.loc["F", "exposure_count"] == 0
    assert distribution.loc["F", "ead"] == pytest.approx(0.0)
    assert distribution["exposure_count"].sum() == 8
    assert distribution["ead"].sum() == pytest.approx(1900.0)
    assert distribution["expected_default_ead"].sum() == pytest.approx(13.9)
    # Shares use the aggregate portfolio, not averages of bank percentages.
    assert distribution.loc["A", "share_count"] == pytest.approx(0.25)
    assert distribution.loc["D", "share_count"] == pytest.approx(0.125)
    assert distribution.loc["A", "share_ead"] == pytest.approx(600.0 / 1900.0)


def test_investment_grade_share(exposures_frame):
    current = filter_exposures(exposures_frame, REPORT_DATE)
    # A/B EAD: 100 + 200 + 500 + 300 = 1,100 of 1,900.
    assert investment_grade_share(current) == pytest.approx(1100.0 / 1900.0)


def test_investment_grade_share_is_none_without_ead(exposures_frame):
    assert investment_grade_share(exposures_frame.iloc[0:0]) is None


# ---------------------------------------------------------------------------
# Observed default rates
# ---------------------------------------------------------------------------


def test_observation_start_date(exposures_frame):
    assert observation_start_date(exposures_frame, REPORT_DATE) == pd.Timestamp("2025-06-30")


def test_default_observation_builds_the_documented_cohort(exposures_frame):
    detail, start = default_observation(exposures_frame, REPORT_DATE)
    assert start == pd.Timestamp("2025-06-30")
    # 6 performing exposures with valid ratings in the start snapshot.
    assert detail["exposure_id"].tolist() == ["EXP001", "EXP002", "EXP003", "EXP004", "EXP005", "EXP006"]
    assert detail["ead"].sum() == pytest.approx(1400.0)
    assert bool(detail.loc[detail["exposure_id"] == "EXP004", "is_default"].iloc[0])
    assert bool(detail.loc[detail["exposure_id"] == "EXP006", "is_default"].iloc[0])
    assert int(detail["is_default"].sum()) == 2


def test_default_rate_summary_matches_hand_computation(exposures_frame):
    summary = default_rate_summary(exposures_frame, REPORT_DATE)
    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["base_exposures"] == 6
    assert row["base_ead"] == pytest.approx(1400.0)
    assert row["default_count"] == 2
    assert row["default_ead"] == pytest.approx(200.0)
    assert row["observed_default_rate"] == pytest.approx(1.0 / 3.0)
    assert row["observed_default_rate_ead"] == pytest.approx(200.0 / 1400.0)
    assert row["model_pd_weighted"] == pytest.approx(17.4 / 1400.0)
    assert row["observation_start"] == pd.Timestamp("2025-06-30")


def test_default_rate_by_bank_matches_hand_computation(exposures_frame):
    by_bank = default_rate_by_bank(exposures_frame, REPORT_DATE).set_index("bank_id")
    assert by_bank.loc["SSK001", "base_exposures"] == 2
    assert by_bank.loc["SSK001", "default_count"] == 0
    assert by_bank.loc["SSK003", "base_ead"] == pytest.approx(500.0)
    assert by_bank.loc["SSK003", "default_ead"] == pytest.approx(100.0)
    assert by_bank.loc["SSK003", "observed_default_rate"] == pytest.approx(0.5)
    assert by_bank.loc["SSK005", "default_ead"] == pytest.approx(100.0)
    assert by_bank.loc["SSK005", "base_ead"] == pytest.approx(600.0)
    assert by_bank.loc["SSK005", "observed_default_rate_ead"] == pytest.approx(100.0 / 600.0)


def test_default_rate_trend_starts_once_an_earlier_snapshot_exists(exposures_frame):
    trend = default_rate_trend(exposures_frame)
    # 2025-06-30 has no earlier quarter snapshot -> only the 2026-06-30 row remains.
    assert trend["reporting_date"].tolist() == [pd.Timestamp("2026-06-30")]
    assert trend.iloc[0]["base_exposures"] == 6
    assert trend.iloc[0]["default_count"] == 2


def test_default_rate_summary_empty_without_history(exposures_frame):
    first_only = exposures_frame[exposures_frame["snapshot_date"] == "2025-06-30"]
    assert default_rate_summary(first_only, pd.Timestamp("2025-06-30")).empty


# ---------------------------------------------------------------------------
# Rating migration
# ---------------------------------------------------------------------------


def test_calculate_migration_portfolio_result(rating_history_frame):
    result = calculate_migration(
        rating_history_frame, pd.Timestamp("2025-06-30"), pd.Timestamp("2026-06-30")
    )
    summary = result.summary
    assert summary["base_count"] == 6
    assert summary["target_count"] == 8
    assert summary["matched_count"] == 6
    assert summary["upgrades"] == 2
    assert summary["downgrades"] == 1
    assert summary["unchanged"] == 3
    assert summary["entries"] == 2
    assert summary["exits"] == 0
    assert summary["upgrade_rate"] == pytest.approx(1.0 / 3.0)
    assert summary["downgrade_rate"] == pytest.approx(1.0 / 6.0)

    counts = result.matrix_counts
    assert int(counts.loc["A", "A"]) == 2
    assert int(counts.loc["B", "C"]) == 1
    assert int(counts.loc["C", "B"]) == 1
    assert int(counts.loc["D", "D"]) == 1
    assert int(counts.loc["F", "E"]) == 1
    assert int(counts.values.sum()) == 6
    assert result.matrix_pct.loc["A", "A"] == pytest.approx(1.0)

    upgrades = result.transitions[result.transitions["transition"] == "UPGRADE"]["exposure_id"]
    assert set(upgrades) == {"EXP002", "EXP006"}
    downgrades = result.transitions[result.transitions["transition"] == "DOWNGRADE"]["exposure_id"]
    assert set(downgrades) == {"EXP003"}
    entries = set(result.transitions[result.transitions["period_status"] == "ENTRY"]["exposure_id"])
    assert entries == {"EXP007", "EXP008"}


def test_calculate_migration_by_bank(rating_history_frame):
    result = calculate_migration(
        rating_history_frame, pd.Timestamp("2025-06-30"), pd.Timestamp("2026-06-30")
    )
    by_bank = result.by_bank.set_index("bank_id")
    assert by_bank.loc["SSK001", "matched_count"] == 2
    assert by_bank.loc["SSK001", "upgrades"] == 1
    assert by_bank.loc["SSK001", "entries"] == 1
    assert by_bank.loc["SSK003", "downgrades"] == 1
    assert by_bank.loc["SSK005", "upgrades"] == 1


def migration_history() -> pd.DataFrame:
    """Dedicated migration frame: 6 start / 7 end observations.

    start: E1 A, E2 A, E3 B, E4 B, E5 C (SSK001), E6 B (SSK003)
    end:   E1 A, E2 B, E3 A, E4 B, E5 A, E7 A (SSK003), E8 C (SSK005)
    Hand-computed: matched 5 (2 upgrades E3/E5, 1 downgrade E2, 2 unchanged),
    entries E7/E8, exits E6.
    """
    rows = [
        ("E1", "SSK001", "2025-06-30", "A"),
        ("E2", "SSK001", "2025-06-30", "A"),
        ("E3", "SSK001", "2025-06-30", "B"),
        ("E4", "SSK001", "2025-06-30", "B"),
        ("E5", "SSK001", "2025-06-30", "C"),
        ("E6", "SSK003", "2025-06-30", "B"),
        ("E1", "SSK001", "2026-06-30", "A"),
        ("E2", "SSK001", "2026-06-30", "B"),
        ("E3", "SSK001", "2026-06-30", "A"),
        ("E4", "SSK001", "2026-06-30", "B"),
        ("E5", "SSK001", "2026-06-30", "A"),
        ("E7", "SSK003", "2026-06-30", "A"),
        ("E8", "SSK005", "2026-06-30", "C"),
    ]
    return pd.DataFrame(rows, columns=RATING_COLUMNS)


def test_calculate_migration_entries_and_exits():
    result = calculate_migration(
        migration_history(), pd.Timestamp("2025-06-30"), pd.Timestamp("2026-06-30")
    )
    summary = result.summary
    assert summary["base_count"] == 6
    assert summary["target_count"] == 7
    assert summary["matched_count"] == 5
    assert summary["upgrades"] == 2
    assert summary["downgrades"] == 1
    assert summary["unchanged"] == 2
    assert summary["entries"] == 2
    assert summary["exits"] == 1

    counts = result.matrix_counts
    assert int(counts.loc["A", "A"]) == 1
    assert int(counts.loc["A", "B"]) == 1
    assert int(counts.loc["B", "A"]) == 1
    assert int(counts.loc["B", "B"]) == 1
    assert int(counts.loc["C", "A"]) == 1

    by_bank = result.by_bank.set_index("bank_id")
    assert by_bank.loc["SSK003", "matched_count"] == 0
    assert by_bank.loc["SSK003", "entries"] == 1
    assert by_bank.loc["SSK003", "exits"] == 1
    assert by_bank.loc["SSK005", "matched_count"] == 0


def test_calculate_migration_rejects_reversed_dates(rating_history_frame):
    with pytest.raises(ValueError):
        calculate_migration(
            rating_history_frame,
            pd.Timestamp("2026-06-30"),
            pd.Timestamp("2025-06-30"),
        )
    with pytest.raises(ValueError):
        calculate_migration(
            rating_history_frame,
            pd.Timestamp("2026-06-30"),
            pd.Timestamp("2026-06-30"),
        )


def test_empty_migration_result_is_all_zero():
    result = empty_migration_result("2026-06-30", "2026-09-30")
    assert int(result.matrix_counts.values.sum()) == 0
    assert result.summary["matched_count"] == 0
    assert result.summary["upgrade_rate"] is None


def test_migration_matrix_long_roundtrip(rating_history_frame):
    result = calculate_migration(
        rating_history_frame, pd.Timestamp("2025-06-30"), pd.Timestamp("2026-06-30")
    )
    long_form = migration_matrix_long(result.matrix_counts)
    non_zero = long_form[long_form["transition_count"] > 0]
    assert set(zip(non_zero["base_rating"], non_zero["target_rating"])) == {
        ("A", "A"), ("B", "C"), ("C", "B"), ("D", "D"), ("F", "E"),
    }


# ---------------------------------------------------------------------------
# Report bundle
# ---------------------------------------------------------------------------


def test_build_rating_result_community_kpis(exposures_frame, rating_history_frame):
    result = build_rating_result(exposures_frame, rating_history_frame, REPORT_DATE)
    kpis = result.kpis
    assert kpis["reporting_date"] == REPORT_DATE
    assert kpis["exposure_count"] == 8
    assert kpis["total_ead"] == pytest.approx(1900.0)
    assert kpis["bank_count"] == 3
    assert kpis["portfolio_pd"] == pytest.approx(13.9 / 1900.0)
    assert kpis["investment_grade_share"] == pytest.approx(1100.0 / 1900.0)
    assert kpis["default_rate_12m"] == pytest.approx(1.0 / 3.0)
    assert kpis["default_count_12m"] == 2
    assert kpis["base_exposures_12m"] == 6
    assert kpis["model_pd_12m"] == pytest.approx(17.4 / 1400.0)
    assert kpis["migration_matched"] == 6
    assert kpis["upgrade_rate"] == pytest.approx(1.0 / 3.0)
    assert kpis["downgrade_rate"] == pytest.approx(1.0 / 6.0)
    assert kpis["migration_start"] == pd.Timestamp("2025-06-30")
    assert kpis["migration_end"] == REPORT_DATE
    assert len(result.exposures) == 8
    assert len(result.distribution) == 6


def test_build_rating_result_bank_scope(exposures_frame, rating_history_frame):
    result = build_rating_result(
        exposures_frame, rating_history_frame, REPORT_DATE, bank_ids=["SSK001"]
    )
    kpis = result.kpis
    assert kpis["exposure_count"] == 3
    assert kpis["total_ead"] == pytest.approx(600.0)
    assert kpis["bank_count"] == 1
    assert kpis["portfolio_pd"] == pytest.approx(1.6 / 600.0)
    assert kpis["default_rate_12m"] == pytest.approx(0.0)
    assert kpis["default_count_12m"] == 0
    assert kpis["base_exposures_12m"] == 2
    assert kpis["migration_matched"] == 2
    assert kpis["upgrade_rate"] == pytest.approx(0.5)
    assert result.exposures["exposure_id"].tolist() == ["EXP001", "EXP002", "EXP007"]


def test_build_rating_result_raises_without_current_exposures(exposures_frame, rating_history_frame):
    with pytest.raises(ValueError, match="No exposures available"):
        build_rating_result(exposures_frame, rating_history_frame, pd.Timestamp("2026-03-31"))


def test_build_rating_benchmark_metrics_row_contract(exposures_frame, rating_history_frame):
    metrics = build_rating_benchmark_metrics(exposures_frame, rating_history_frame, REPORT_DATE)
    # 3 banks x (PD, IG share, 6 rating shares, default rate, upgrade, downgrade) = 33.
    assert len(metrics) == 33
    ssk001 = metrics[metrics["bank_id"] == "SSK001"].set_index("metric_id")
    assert ssk001.loc["PD_12M_WEIGHTED", "numerator"] == pytest.approx(1.6)
    assert ssk001.loc["PD_12M_WEIGHTED", "denominator"] == pytest.approx(600.0)
    assert ssk001.loc["SHARE_IG_A_B", "numerator"] == pytest.approx(600.0)
    default = metrics[(metrics["bank_id"] == "SSK003") & (metrics["metric_id"] == "DEFAULT_RATE_12M")]
    assert default["numerator"].iloc[0] == 1.0
    assert default["denominator"].iloc[0] == 2.0
