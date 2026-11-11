"""Report-ready Loss Estimation result bundle and benchmark inputs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from config.settings import DEFAULT_OBSERVATION_MONTHS
from modules.loss_estimation.calculations import (
    filter_current_exposures,
    prepare_default_cohort,
)
from modules.loss_estimation.collateral_analysis import (
    collateral_coverage_by_bank,
    collateral_coverage_by_product,
    collateral_coverage_by_primary_type,
    collateral_coverage_by_rating,
    collateral_exposure_detail,
    collateral_items as build_collateral_items,
    collateral_summary_detail,
    collateral_type_mix,
    haircut_comparison,
    primary_collateral,
    stale_collateral_items,
)
from modules.loss_estimation.loss_rates import (
    loss_distribution,
    loss_rate_by_bank,
    loss_rate_by_collateral_type,
    loss_rate_by_default_quarter,
    loss_rate_by_product,
    loss_rate_by_rating,
    loss_rate_by_sector,
    loss_severity_bands,
    loss_summary,
)
from modules.loss_estimation.recovery_cashflows import (
    cashflow_by_period,
    cumulative_recovery_curve,
    prepare_recovery_detail,
    recovery_cashflow_summary,
    recovery_lag_by_dimension,
    recovery_type_mix,
    time_to_recovery_bands,
)
from modules.loss_estimation.recovery_rates import (
    recovery_by_rating_vs_collateral,
    recovery_distribution,
    recovery_rate_by_bank,
    recovery_rate_by_collateral_type,
    recovery_rate_by_default_quarter,
    recovery_rate_by_product,
    recovery_rate_by_rating,
    recovery_rate_by_sector,
    recovery_summary,
)


@dataclass
class LossModuleResult:
    reporting_date: pd.Timestamp
    bank_ids: list[str]
    sectors: list[str]
    window_months: int
    window_start: pd.Timestamp
    current_exposures: pd.DataFrame
    cohort: pd.DataFrame
    collateral_detail: pd.DataFrame
    collateral_items: pd.DataFrame
    summary: dict[str, object]
    recovery_summary: dict[str, object]
    loss_summary: dict[str, object]
    collateral_summary: dict[str, object]
    by_bank: pd.DataFrame
    by_rating: pd.DataFrame
    by_product: pd.DataFrame
    by_sector: pd.DataFrame
    by_collateral_type: pd.DataFrame
    recovery_by_rating_collateral: pd.DataFrame
    recovery_by_default_quarter: pd.DataFrame
    loss_by_default_quarter: pd.DataFrame
    recovery_distribution: pd.DataFrame
    loss_distribution: pd.DataFrame
    loss_severity: pd.DataFrame
    collateral_by_bank: pd.DataFrame
    collateral_by_rating: pd.DataFrame
    collateral_by_product: pd.DataFrame
    collateral_by_primary_type: pd.DataFrame
    collateral_type_mix: pd.DataFrame
    stale_collateral: pd.DataFrame
    haircut_comparison: pd.DataFrame
    cashflow_detail: pd.DataFrame
    cashflow_summary: dict[str, object]
    cashflow_by_quarter: pd.DataFrame
    recovery_type_mix: pd.DataFrame
    recovery_curve: pd.DataFrame
    time_to_recovery: pd.DataFrame
    recovery_lag_by_bank: pd.DataFrame
    benchmark_metrics: pd.DataFrame = field(default_factory=pd.DataFrame)
    kpis: dict[str, object] = field(default_factory=dict)


def _empty_benchmark_metrics() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "bank_id", "reporting_date", "unit", "metric_id", "metric_name",
            "higher_is_better", "numerator", "denominator",
        ]
    )


def benchmark_metrics_from_components(
    current_exposures: pd.DataFrame,
    cohort: pd.DataFrame,
    collateral_detail: pd.DataFrame,
    reporting_date: object,
) -> pd.DataFrame:
    """Build long-form numerator/denominator loss metrics per institution."""
    report = pd.Timestamp(reporting_date).normalize()
    rows: list[dict[str, object]] = []

    if not cohort.empty:
        for bank_id, group in cohort.groupby("bank_id"):
            rows.append(
                {
                    "bank_id": bank_id,
                    "reporting_date": report,
                    "unit": "ratio",
                    "metric_id": "RECOVERY_RATE_12M",
                    "metric_name": "Observed 12M recovery rate (EAD-weighted)",
                    "higher_is_better": True,
                    "numerator": float(group["total_recoveries"].sum()),
                    "denominator": float(group["ead_at_default"].sum()),
                }
            )
            rows.append(
                {
                    "bank_id": bank_id,
                    "reporting_date": report,
                    "unit": "ratio",
                    "metric_id": "LOSS_RATE_12M",
                    "metric_name": "Observed 12M loss rate (EAD-weighted)",
                    "higher_is_better": False,
                    "numerator": float(group["loss_amount"].sum()),
                    "denominator": float(group["ead_at_default"].sum()),
                }
            )

    if not collateral_detail.empty:
        for bank_id, group in collateral_detail.groupby("bank_id"):
            total_ead = float(group["exposure_at_default"].sum())
            rows.append(
                {
                    "bank_id": bank_id,
                    "reporting_date": report,
                    "unit": "ratio",
                    "metric_id": "COLLATERAL_COVERAGE",
                    "metric_name": "Adjusted collateral coverage of current EAD",
                    "higher_is_better": True,
                    "numerator": float(group["total_adjusted_collateral"].sum()),
                    "denominator": total_ead,
                }
            )
            rows.append(
                {
                    "bank_id": bank_id,
                    "reporting_date": report,
                    "unit": "ratio",
                    "metric_id": "SECURED_EAD_SHARE",
                    "metric_name": "Secured share of current EAD (capped)",
                    "higher_is_better": True,
                    "numerator": float(group["secured_ead"].sum()),
                    "denominator": total_ead,
                }
            )

    if not rows:
        return _empty_benchmark_metrics()
    return pd.DataFrame(rows)


def build_loss_benchmark_metrics(
    exposures: pd.DataFrame,
    collateral: pd.DataFrame,
    cashflows: pd.DataFrame,
    reporting_date: object,
    sectors: Iterable[str] | None = None,
    window_months: int = DEFAULT_OBSERVATION_MONTHS,
) -> pd.DataFrame:
    report = pd.Timestamp(reporting_date).normalize()
    sector_list = list(sectors) if sectors else []
    current = filter_current_exposures(exposures, report, sectors=sector_list or None)
    primary = primary_collateral(collateral, report)
    cohort = prepare_default_cohort(
        exposures,
        cashflows,
        report,
        sectors=sector_list or None,
        window_months=window_months,
        primary_collateral=primary,
    )
    detail = collateral_exposure_detail(
        collateral, exposures, report, sectors=sector_list or None
    )
    return benchmark_metrics_from_components(current, cohort, detail, report)


def build_loss_result(
    exposures: pd.DataFrame,
    collateral: pd.DataFrame,
    cashflows: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    window_months: int = DEFAULT_OBSERVATION_MONTHS,
) -> LossModuleResult:
    report = pd.Timestamp(reporting_date).normalize()
    bank_list = list(bank_ids) if bank_ids else []
    sector_list = list(sectors) if sectors else []
    window_start = report - pd.DateOffset(months=window_months)

    current = filter_current_exposures(
        exposures, report, bank_list or None, sector_list or None
    )
    if current.empty:
        raise ValueError(
            f"No exposures available for loss reporting date {report.date()} and selected filters"
        )

    primary = primary_collateral(collateral, report, bank_list or None)
    cohort = prepare_default_cohort(
        exposures,
        cashflows,
        report,
        bank_ids=bank_list or None,
        sectors=sector_list or None,
        window_months=window_months,
        primary_collateral=primary,
    )
    detail = collateral_exposure_detail(
        collateral,
        exposures,
        report,
        bank_ids=bank_list or None,
        sectors=sector_list or None,
    )
    items = build_collateral_items(
        collateral,
        exposures,
        report,
        bank_ids=bank_list or None,
        sectors=sector_list or None,
    )
    recovery = recovery_summary(cohort)
    loss = loss_summary(cohort)
    coverage = collateral_summary_detail(detail)
    cashflow_detail = prepare_recovery_detail(cashflows, cohort, report)
    cashflow_stats = recovery_cashflow_summary(cashflow_detail)

    summary: dict[str, object] = {
        "reporting_date": report,
        "window_months": window_months,
        "window_start": window_start,
        "current_exposures": int(len(current)),
        "current_ead": float(pd.to_numeric(current["exposure_at_default"], errors="coerce").fillna(0).clip(lower=0).sum()),
        **recovery,
        **{f"collateral_{key}": value for key, value in coverage.items()},
        "cashflow_count": cashflow_stats["cashflow_count"],
        "weighted_average_days": cashflow_stats["weighted_average_days"],
    }
    kpis = {
        "reporting_date": report,
        "current_ead": summary["current_ead"],
        "default_count": recovery["default_count"],
        "ead_at_default": recovery["ead_at_default"],
        "recovery_rate": recovery["recovery_rate"],
        "loss_rate": loss["loss_rate"],
        "loss_amount": loss["loss_amount"],
        "zero_recovery_share": recovery["zero_recovery_share"],
        "full_loss_share": loss["full_loss_share"],
        "collateral_coverage": coverage["collateral_coverage"],
        "secured_ead_share": coverage["secured_ead_share"],
        "stale_collateral_items": coverage["stale_items"],
        "cashflow_count": cashflow_stats["cashflow_count"],
        "weighted_average_days": cashflow_stats["weighted_average_days"],
        "cohort_start": window_start,
        "cohort_end": report,
    }

    metrics = benchmark_metrics_from_components(current, cohort, detail, report)
    return LossModuleResult(
        reporting_date=report,
        bank_ids=bank_list,
        sectors=sector_list,
        window_months=window_months,
        window_start=window_start,
        current_exposures=current,
        cohort=cohort,
        collateral_detail=detail,
        collateral_items=items,
        summary=summary,
        recovery_summary=recovery,
        loss_summary=loss,
        collateral_summary=coverage,
        by_bank=recovery_rate_by_bank(cohort),
        by_rating=recovery_rate_by_rating(cohort),
        by_product=recovery_rate_by_product(cohort),
        by_sector=recovery_rate_by_sector(cohort),
        by_collateral_type=recovery_rate_by_collateral_type(cohort),
        recovery_by_rating_collateral=recovery_by_rating_vs_collateral(cohort),
        recovery_by_default_quarter=recovery_rate_by_default_quarter(cohort),
        loss_by_default_quarter=loss_rate_by_default_quarter(cohort),
        recovery_distribution=recovery_distribution(cohort),
        loss_distribution=loss_distribution(cohort),
        loss_severity=loss_severity_bands(cohort),
        collateral_by_bank=collateral_coverage_by_bank(detail),
        collateral_by_rating=collateral_coverage_by_rating(detail),
        collateral_by_product=collateral_coverage_by_product(detail),
        collateral_by_primary_type=collateral_coverage_by_primary_type(detail),
        collateral_type_mix=collateral_type_mix(items),
        stale_collateral=stale_collateral_items(
            collateral, report, bank_list or None
        ),
        haircut_comparison=haircut_comparison(collateral, report),
        cashflow_detail=cashflow_detail,
        cashflow_summary=cashflow_stats,
        cashflow_by_quarter=cashflow_by_period(cashflow_detail),
        recovery_type_mix=recovery_type_mix(cashflow_detail),
        recovery_curve=cumulative_recovery_curve(cashflow_detail, cohort),
        time_to_recovery=time_to_recovery_bands(cashflow_detail, cohort),
        recovery_lag_by_bank=recovery_lag_by_dimension(cashflow_detail, "bank_id"),
        benchmark_metrics=metrics,
        kpis=kpis,
    )
