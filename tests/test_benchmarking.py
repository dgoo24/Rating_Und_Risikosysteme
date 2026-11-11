"""Benchmarking engine tests against hand-computed peer comparisons.

Synthetic benchmark frame (metric M_TEST, higher is worse):
  SSK001 30/100 = 0.30 | SSK003 40/400 = 0.10 | SSK005 90/100 = 0.90

Hand-computed peer results (peers exclude the bank itself, peer value is the
weighted aggregate sum(numerator)/sum(denominator) of the peers):
  SSK001 peers = SSK003 + SSK005 -> 130/500 = 0.26 -> gap +0.04,
    relative gap 2/13 -> WORSE; peer median 0.50; rank 2; percentile 0.5
  SSK003 peers = SSK001 + SSK005 -> 120/200 = 0.60 -> BETTER; rank 3; pct 1.0
  SSK005 peers = SSK001 + SSK003 -> 70/500 = 0.14 -> WORSE; rank 1; pct 0.0
  portfolio value = 160/600.
"""
from __future__ import annotations

import pandas as pd
import pytest

from benchmarking.aggregation import (
    METRICS,
    benchmark_kpis,
    build_benchmark_detail,
    metric_catalog_frame,
    normalize_metrics,
    peer_group_summary,
)
from benchmarking.benchmark_engine import (
    build_benchmark_result,
    build_historical_benchmark,
    benchmark_for_bank,
    benchmark_for_metric,
)

from .conftest import REPORT_DATE

METRIC_COLUMNS = [
    "bank_id", "reporting_date", "unit", "metric_id", "metric_name",
    "higher_is_better", "numerator", "denominator",
]


def metric_frame(rows: list[tuple[str, float, float]], metric_id: str = "M_TEST") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "bank_id": bank_id,
                "reporting_date": REPORT_DATE,
                "unit": "ratio",
                "metric_id": metric_id,
                "metric_name": "Test metric",
                "higher_is_better": False,
                "numerator": numerator,
                "denominator": denominator,
            }
            for bank_id, numerator, denominator in rows
        ],
        columns=METRIC_COLUMNS,
    )


def institutions_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"bank_id": "SSK001", "bank_name": "Nord (fiktiv)", "region": "NORTH", "peer_group": "PG_URBAN"},
            {"bank_id": "SSK003", "bank_name": "West (fiktiv)", "region": "WEST", "peer_group": "PG_URBAN"},
            {"bank_id": "SSK005", "bank_name": "Ost (fiktiv)", "region": "EAST", "peer_group": "PG_URBAN"},
        ]
    )


def detail_row(detail: pd.DataFrame, bank_id: str, metric_id: str = "M_TEST") -> pd.Series:
    row = detail[(detail["bank_id"] == bank_id) & (detail["metric_id"] == metric_id)]
    assert len(row) == 1, row
    return row.iloc[0]


# ---------------------------------------------------------------------------
# Catalogue and normalisation
# ---------------------------------------------------------------------------


def test_metric_catalogue_has_fifteen_unique_metrics():
    catalog = metric_catalog_frame()
    assert catalog["metric_id"].nunique() == 15
    assert len(METRICS) == 15
    assert set(catalog["module"]) == {"rating", "loss"}


def test_normalize_metrics_drops_non_positive_denominators():
    frame = metric_frame([("SSK001", 30.0, 100.0), ("SSK003", 40.0, 0.0), ("SSK005", 10.0, -5.0)])
    normalized = normalize_metrics(frame)
    assert normalized["bank_id"].tolist() == ["SSK001"]


def test_normalize_metrics_fills_missing_metadata():
    frame = metric_frame([("SSK001", 30.0, 100.0)], metric_id="PD_12M_WEIGHTED").drop(
        columns=["metric_name", "higher_is_better", "unit"]
    )
    normalized = normalize_metrics(frame)
    assert normalized.iloc[0]["metric_name"] == "PD 12M (EAD-gewichtet)"
    # pandas infers a bool dtype (numpy.bool_) when no None values are present.
    assert bool(normalized.iloc[0]["higher_is_better"]) is False
    assert normalized.iloc[0]["unit"] == "ratio"


# ---------------------------------------------------------------------------
# Peer aggregation
# ---------------------------------------------------------------------------


def test_weighted_peer_aggregation_matches_hand_computation():
    detail = build_benchmark_detail(metric_frame([
        ("SSK001", 30.0, 100.0), ("SSK003", 40.0, 400.0), ("SSK005", 90.0, 100.0),
    ]), institutions_frame())

    ssk001 = detail_row(detail, "SSK001")
    assert ssk001["bank_value"] == pytest.approx(0.30)
    assert ssk001["peer_numerator"] == pytest.approx(130.0)
    assert ssk001["peer_denominator"] == pytest.approx(500.0)
    assert ssk001["peer_value"] == pytest.approx(0.26)  # weighted, not mean 0.5
    assert ssk001["gap"] == pytest.approx(0.04)
    assert ssk001["relative_gap"] == pytest.approx(2.0 / 13.0)
    assert ssk001["performance_flag"] == "WORSE"
    assert ssk001["peer_median"] == pytest.approx(0.50)
    assert ssk001["peer_min"] == pytest.approx(0.10)
    assert ssk001["peer_max"] == pytest.approx(0.90)
    assert ssk001["peer_count"] == 2
    assert ssk001["rank_in_peer_group"] == 2
    assert ssk001["percentile"] == pytest.approx(0.5)
    assert ssk001["portfolio_value"] == pytest.approx(160.0 / 600.0)

    ssk003 = detail_row(detail, "SSK003")
    assert ssk003["peer_value"] == pytest.approx(0.60)
    assert ssk003["performance_flag"] == "BETTER"
    assert ssk003["rank_in_peer_group"] == 3
    assert ssk003["percentile"] == pytest.approx(1.0)

    ssk005 = detail_row(detail, "SSK005")
    assert ssk005["peer_value"] == pytest.approx(0.14)
    assert ssk005["performance_flag"] == "WORSE"
    assert ssk005["rank_in_peer_group"] == 1
    assert ssk005["percentile"] == pytest.approx(0.0)


def test_equal_banks_are_flagged_in_line():
    detail = build_benchmark_detail(metric_frame([
        ("SSK001", 25.0, 100.0), ("SSK003", 50.0, 200.0), ("SSK005", 75.0, 300.0),
    ]), institutions_frame())
    for bank_id in ("SSK001", "SSK003", "SSK005"):
        row = detail_row(detail, bank_id)
        assert row["bank_value"] == pytest.approx(0.25)
        assert row["peer_value"] == pytest.approx(0.25)
        assert row["gap"] == pytest.approx(0.0)
        assert row["performance_flag"] == "IN_LINE"


def test_peer_ids_override_replaces_peer_group():
    detail = build_benchmark_detail(
        metric_frame([("SSK001", 30.0, 100.0), ("SSK003", 40.0, 400.0), ("SSK005", 90.0, 100.0)]),
        institutions_frame(),
        peer_ids_override={"SSK001": ["SSK003"]},
    )
    row = detail_row(detail, "SSK001")
    assert row["peer_value"] == pytest.approx(0.10)
    assert row["peer_count"] == 1
    assert row["peer_median"] == pytest.approx(0.10)


def test_peer_group_override_without_available_peers_is_no_benchmark():
    detail = build_benchmark_detail(
        metric_frame([("SSK001", 30.0, 100.0), ("SSK003", 40.0, 400.0), ("SSK005", 90.0, 100.0)]),
        institutions_frame(),
        peer_group_override={"SSK001": "PG_REGIONAL"},
    )
    row = detail_row(detail, "SSK001")
    # PG_REGIONAL members (SSK002, SSK004) are absent from the metrics frame.
    assert row["peer_group"] == "PG_REGIONAL"
    assert pd.isna(row["peer_value"])  # None in a float column is stored as NaN
    assert row["peer_count"] == 0
    assert row["performance_flag"] == "NO_BENCHMARK"


def test_benchmark_kpis_counts_flags():
    detail = build_benchmark_detail(metric_frame([
        ("SSK001", 30.0, 100.0), ("SSK003", 40.0, 400.0), ("SSK005", 90.0, 100.0),
    ]), institutions_frame())
    kpis = benchmark_kpis(detail)
    assert kpis == {"banks": 3, "metrics": 1, "better": 1, "worse": 2, "in_line": 0, "benchmarked": 3}


def test_benchmark_kpis_on_empty_detail():
    assert benchmark_kpis(pd.DataFrame()) == {
        "banks": 0, "metrics": 0, "better": 0, "worse": 0, "in_line": 0, "benchmarked": 0,
    }


# ---------------------------------------------------------------------------
# Full portfolio benchmark result
# ---------------------------------------------------------------------------


def test_build_benchmark_result_on_portfolio(portfolio):
    result = build_benchmark_result(
        portfolio["exposures"],
        portfolio["rating_history"],
        portfolio["collateral"],
        portfolio["recovery_cashflows"],
        portfolio["institutions"],
        REPORT_DATE,
    )
    # Row counts: SSK001 has no default cohort -> 11 rating + 2 collateral metrics;
    # SSK003 and SSK005 have 11 rating + 4 loss metrics each.
    counts = result.detail.groupby("bank_id").size()
    assert counts.to_dict() == {"SSK001": 13, "SSK003": 15, "SSK005": 15}
    assert len(result.detail) == 43

    kpis = result.kpis
    assert kpis["banks"] == 3
    assert kpis["metrics"] == 15

    ssk001 = detail_row(result.detail, "SSK001", "COLLATERAL_COVERAGE")
    assert ssk001["bank_value"] == pytest.approx(570.5 / 600.0)
    ssk001_pd = detail_row(result.detail, "SSK001", "PD_12M_WEIGHTED")
    assert ssk001_pd["bank_value"] == pytest.approx(1.6 / 600.0)
    ssk001_default = detail_row(result.detail, "SSK001", "DEFAULT_RATE_12M")
    assert ssk001_default["numerator"] == pytest.approx(0.0)
    assert ssk001_default["denominator"] == pytest.approx(2.0)
    ssk001_upgrade = detail_row(result.detail, "SSK001", "RATING_UPGRADE_RATE")
    assert ssk001_upgrade["bank_value"] == pytest.approx(0.5)

    ssk003_recovery = detail_row(result.detail, "SSK003", "RECOVERY_RATE_12M")
    assert ssk003_recovery["bank_value"] == pytest.approx(0.6)
    ssk003_loss = detail_row(result.detail, "SSK003", "LOSS_RATE_12M")
    assert ssk003_loss["bank_value"] == pytest.approx(0.4)
    ssk003_downgrade = detail_row(result.detail, "SSK003", "RATING_DOWNGRADE_RATE")
    assert ssk003_downgrade["bank_value"] == pytest.approx(0.5)

    ssk005_recovery = detail_row(result.detail, "SSK005", "RECOVERY_RATE_12M")
    assert ssk005_recovery["bank_value"] == pytest.approx(0.25)
    ssk005_loss = detail_row(result.detail, "SSK005", "LOSS_RATE_12M")
    assert ssk005_loss["bank_value"] == pytest.approx(0.75)
    ssk005_upgrade = detail_row(result.detail, "SSK005", "RATING_UPGRADE_RATE")
    assert ssk005_upgrade["bank_value"] == pytest.approx(0.5)


def test_peer_group_summary_on_portfolio(portfolio):
    result = build_benchmark_result(
        portfolio["exposures"],
        portfolio["rating_history"],
        portfolio["collateral"],
        portfolio["recovery_cashflows"],
        portfolio["institutions"],
        REPORT_DATE,
    )
    summary = result.peer_group_summary.set_index(["peer_group", "metric_id"])
    recovery = summary.loc[("PG_URBAN", "RECOVERY_RATE_12M")]
    # Only SSK003 (60/100) and SSK005 (25/100) have defaults in the cohort.
    assert recovery["bank_count"] == 2
    assert recovery["numerator"] == pytest.approx(85.0)
    assert recovery["denominator"] == pytest.approx(200.0)
    assert recovery["peer_value"] == pytest.approx(0.425)


def test_benchmark_for_bank_and_metric_selectors(portfolio):
    result = build_benchmark_result(
        portfolio["exposures"],
        portfolio["rating_history"],
        portfolio["collateral"],
        portfolio["recovery_cashflows"],
        portfolio["institutions"],
        REPORT_DATE,
    )
    bank_view = benchmark_for_bank(result, "SSK005")
    assert set(bank_view["bank_id"]) == {"SSK005"}
    metric_view = benchmark_for_metric(result, "PD_12M_WEIGHTED")
    assert set(metric_view["metric_id"]) == {"PD_12M_WEIGHTED"}
    assert set(metric_view["bank_id"]) == {"SSK001", "SSK003", "SSK005"}


def test_build_historical_benchmark_stacks_both_dates(portfolio):
    historical = build_historical_benchmark(
        portfolio["exposures"],
        portfolio["rating_history"],
        portfolio["collateral"],
        portfolio["recovery_cashflows"],
        portfolio["institutions"],
        reporting_dates=[pd.Timestamp("2025-06-30"), pd.Timestamp("2026-06-30")],
    )
    assert historical.dates == [pd.Timestamp("2025-06-30"), pd.Timestamp("2026-06-30")]
    assert len(historical.kpis) == 2
    assert set(historical.detail["reporting_date"]) == {
        pd.Timestamp("2025-06-30"), pd.Timestamp("2026-06-30"),
    }
    # 2026-06-30 contributes the 43 rows documented above; the earlier snapshot
    # has no default cohort and no migration history: 8 rating metrics for each
    # of the 3 banks plus 2 collateral metrics per bank = 30 rows.
    counts = historical.detail.groupby("reporting_date").size()
    assert counts[pd.Timestamp("2025-06-30")] == 30
    assert counts[pd.Timestamp("2026-06-30")] == 43
