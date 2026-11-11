"""Shared benchmarking engine for Rating & Scoring and Loss Estimation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

import pandas as pd

from benchmarking.aggregation import (
    benchmark_kpis,
    benchmark_metric_summary,
    build_benchmark_detail,
    combine_metrics,
    metric_catalog_frame,
    peer_group_summary,
    top_gaps,
)
from modules.loss_estimation.reporting import build_loss_benchmark_metrics
from modules.rating_scoring.reporting import build_rating_benchmark_metrics


@dataclass
class BenchmarkResult:
    reporting_date: pd.Timestamp
    sectors: list[str]
    metrics: pd.DataFrame
    detail: pd.DataFrame
    peer_group_summary: pd.DataFrame
    metric_summary: pd.DataFrame
    top_gaps: pd.DataFrame
    catalog: pd.DataFrame
    kpis: dict[str, object] = field(default_factory=dict)


@dataclass
class HistoricalBenchmarkResult:
    dates: list[pd.Timestamp]
    detail: pd.DataFrame
    kpis: pd.DataFrame


def build_benchmark_result(
    exposures: pd.DataFrame,
    rating_history: pd.DataFrame,
    collateral: pd.DataFrame,
    cashflows: pd.DataFrame,
    institutions: pd.DataFrame,
    reporting_date: object,
    sectors: Iterable[str] | None = None,
    peer_group_override: str | Mapping[str, str] | None = None,
    peer_ids_override: Mapping[str, Iterable[str]] | None = None,
) -> BenchmarkResult:
    """Combine both modules' metrics and calculate peer and portfolio comparisons."""
    report = pd.Timestamp(reporting_date).normalize()
    sector_list = list(sectors) if sectors else []
    rating_metrics = build_rating_benchmark_metrics(
        exposures, rating_history, report, sectors=sector_list or None
    )
    loss_metrics = build_loss_benchmark_metrics(
        exposures, collateral, cashflows, report, sectors=sector_list or None
    )
    metrics = combine_metrics(rating_metrics, loss_metrics)
    detail = build_benchmark_detail(
        metrics,
        institutions,
        peer_group_override=peer_group_override,
        peer_ids_override=peer_ids_override,
    )
    return BenchmarkResult(
        reporting_date=report,
        sectors=sector_list,
        metrics=metrics,
        detail=detail,
        peer_group_summary=peer_group_summary(metrics, institutions),
        metric_summary=benchmark_metric_summary(detail),
        top_gaps=top_gaps(detail),
        catalog=metric_catalog_frame(),
        kpis=benchmark_kpis(detail),
    )


def build_historical_benchmark(
    exposures: pd.DataFrame,
    rating_history: pd.DataFrame,
    collateral: pd.DataFrame,
    cashflows: pd.DataFrame,
    institutions: pd.DataFrame,
    reporting_dates: Iterable[object] | None = None,
    sectors: Iterable[str] | None = None,
    peer_group_override: str | Mapping[str, str] | None = None,
) -> HistoricalBenchmarkResult:
    """Run the benchmark for several quarter-ends and stack the detail rows.

    This is intentionally a thin loop over :func:`build_benchmark_result` so
    every period uses exactly the same metric definitions and weighted
    aggregation as the single-period report.
    """
    if reporting_dates is not None:
        dates = sorted({pd.Timestamp(value).normalize() for value in reporting_dates})
    elif exposures.empty or "snapshot_date" not in exposures.columns:
        dates = []
    else:
        values = pd.to_datetime(exposures["snapshot_date"], errors="coerce").dropna().dt.normalize()
        dates = sorted({pd.Timestamp(value) for value in values.unique() if pd.Timestamp(value).is_quarter_end})

    detail_frames: list[pd.DataFrame] = []
    kpi_rows: list[dict[str, object]] = []
    for report in dates:
        try:
            result = build_benchmark_result(
                exposures,
                rating_history,
                collateral,
                cashflows,
                institutions,
                report,
                sectors=sectors,
                peer_group_override=peer_group_override,
            )
        except ValueError:
            # A reporting date without current exposures is skipped rather than
            # aborting the whole trend series.
            continue
        if result.detail.empty:
            continue
        detail_frames.append(result.detail.copy())
        kpi_rows.append(
            {
                "reporting_date": report,
                "banks": result.kpis.get("banks", 0),
                "metrics": result.kpis.get("metrics", 0),
                "better": result.kpis.get("better", 0),
                "worse": result.kpis.get("worse", 0),
                "in_line": result.kpis.get("in_line", 0),
                "benchmarked": result.kpis.get("benchmarked", 0),
            }
        )

    detail = (
        pd.concat(detail_frames, ignore_index=True)
        if detail_frames
        else pd.DataFrame(columns=["bank_id", "bank_name", "peer_group", "reporting_date", "metric_id"])
    )
    kpis = pd.DataFrame(
        kpi_rows,
        columns=["reporting_date", "banks", "metrics", "better", "worse", "in_line", "benchmarked"],
    )
    return HistoricalBenchmarkResult(dates=dates, detail=detail, kpis=kpis)


def benchmark_for_bank(result: BenchmarkResult, bank_id: str) -> pd.DataFrame:
    if result.detail.empty:
        return result.detail.copy()
    return result.detail[result.detail["bank_id"] == bank_id].reset_index(drop=True)


def benchmark_for_metric(result: BenchmarkResult, metric_id: str) -> pd.DataFrame:
    if result.detail.empty:
        return result.detail.copy()
    return result.detail[result.detail["metric_id"] == metric_id].reset_index(drop=True)


def benchmark_health_flags(detail: pd.DataFrame, module: str | None = None) -> pd.DataFrame:
    """Count better/worse/in-line outcomes by bank for a compact heat map."""
    if detail.empty:
        return pd.DataFrame(columns=["bank_id", "bank_name", "better", "worse", "in_line", "benchmarked"])
    frame = detail.copy()
    if module:
        frame = frame[frame["module"] == module]
    if frame.empty:
        return pd.DataFrame(columns=["bank_id", "bank_name", "better", "worse", "in_line", "benchmarked"])
    grouped = (
        frame.groupby(["bank_id", "bank_name"], as_index=False)
        .agg(
            better=("performance_flag", lambda values: int((values == "BETTER").sum())),
            worse=("performance_flag", lambda values: int((values == "WORSE").sum())),
            in_line=("performance_flag", lambda values: int((values == "IN_LINE").sum())),
            benchmarked=("peer_value", lambda values: int(values.notna().sum())),
        )
    )
    return grouped.sort_values("bank_id").reset_index(drop=True)
