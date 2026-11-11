"""Report-ready Rating & Scoring result bundle and benchmark inputs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from config.rating_pd_mapping import RATING_PD_MAPPING, RATING_SCALE
from modules.rating_scoring.calculations import (
    filter_exposures,
    prepare_exposures,
    weighted_pd,
)
from modules.rating_scoring.default_rates import (
    default_rate_by_bank,
    default_rate_by_dimension,
    default_rate_by_rating,
    default_rate_summary,
    default_rate_trend,
    default_rate_trend_by_bank,
)
from modules.rating_scoring.pd_calculations import (
    pd_by_bank,
    pd_by_rating,
    pd_by_sector,
    pd_trend,
    pd_trend_by_bank,
)
from modules.rating_scoring.rating_distribution import (
    investment_grade_share,
    rating_distribution,
)
from modules.rating_scoring.rating_migration import MigrationResult, calculate_migration, empty_migration_result


@dataclass
class RatingModuleResult:
    reporting_date: pd.Timestamp
    bank_ids: list[str]
    sectors: list[str]
    exposures: pd.DataFrame
    distribution: pd.DataFrame
    pd_by_rating: pd.DataFrame
    pd_by_bank: pd.DataFrame
    pd_by_sector: pd.DataFrame
    pd_trend: pd.DataFrame
    pd_trend_by_bank: pd.DataFrame
    default_by_rating: pd.DataFrame
    default_by_bank: pd.DataFrame
    default_by_sector: pd.DataFrame
    default_summary: pd.DataFrame
    default_trend: pd.DataFrame
    default_trend_by_bank: pd.DataFrame
    migration: MigrationResult
    kpis: dict[str, object] = field(default_factory=dict)


def migration_start_default(rating_history: pd.DataFrame, reporting_date: object) -> pd.Timestamp | None:
    if rating_history.empty:
        return None
    end = pd.Timestamp(reporting_date).normalize()
    dates = pd.to_datetime(rating_history["observation_date"], errors="coerce").dropna().dt.normalize()
    earlier = sorted({pd.Timestamp(date) for date in dates.unique() if pd.Timestamp(date) < end})
    if not earlier:
        return None
    target = end - pd.DateOffset(years=1)
    if target in earlier:
        return target
    return pd.Timestamp(max(earlier))


def build_rating_result(
    exposures: pd.DataFrame,
    rating_history: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    migration_start: object | None = None,
) -> RatingModuleResult:
    report = pd.Timestamp(reporting_date).normalize()
    bank_list = list(bank_ids) if bank_ids else []
    sector_list = list(sectors) if sectors else []
    current = filter_exposures(exposures, report, bank_list or None, sector_list or None)
    if current.empty:
        raise ValueError(f"No exposures available for reporting date {report.date()} and selected filters")

    all_prepared = prepare_exposures(exposures)
    filtered_all = all_prepared.copy()
    if bank_list:
        filtered_all = filtered_all[filtered_all["bank_id"].isin(bank_list)]
    if sector_list:
        filtered_all = filtered_all[filtered_all["industry_sector"].isin(sector_list)]

    start = (
        pd.Timestamp(migration_start).normalize()
        if migration_start is not None
        else migration_start_default(rating_history, report)
    )
    if start is not None and start < report:
        migration = calculate_migration(
            rating_history,
            start,
            report,
            bank_ids=bank_list or None,
            sectors=sector_list or None,
            exposures=all_prepared,
        )
    else:
        migration = empty_migration_result(report, report)

    summary = default_rate_summary(filtered_all, report, sectors=sector_list or None)
    default_row = summary.iloc[0] if not summary.empty else {}
    kpis = {
        "reporting_date": report,
        "exposure_count": int(len(current)),
        "total_ead": float(pd.to_numeric(current["exposure_at_default"], errors="coerce").fillna(0).clip(lower=0).sum()),
        "bank_count": int(current["bank_id"].nunique()),
        "portfolio_pd": weighted_pd(current),
        "investment_grade_share": investment_grade_share(current),
        "default_rate_12m": default_row.get("observed_default_rate"),
        "default_count_12m": int(default_row.get("default_count", 0) or 0),
        "base_exposures_12m": int(default_row.get("base_exposures", 0) or 0),
        "model_pd_12m": default_row.get("model_pd_weighted"),
        "migration_matched": int(migration.summary.get("matched_count", 0) or 0),
        "upgrade_rate": migration.summary.get("upgrade_rate"),
        "downgrade_rate": migration.summary.get("downgrade_rate"),
        "migration_start": migration.start_date,
        "migration_end": migration.end_date,
    }

    return RatingModuleResult(
        reporting_date=report,
        bank_ids=bank_list,
        sectors=sector_list,
        exposures=current,
        distribution=rating_distribution(current),
        pd_by_rating=pd_by_rating(current),
        pd_by_bank=pd_by_bank(current),
        pd_by_sector=pd_by_sector(current),
        pd_trend=pd_trend(filtered_all),
        pd_trend_by_bank=pd_trend_by_bank(filtered_all),
        default_by_rating=default_rate_by_rating(filtered_all, report, sectors=sector_list or None),
        default_by_bank=default_rate_by_bank(filtered_all, report, sectors=sector_list or None),
        default_by_sector=default_rate_by_dimension(
            filtered_all, report, "industry_sector", sectors=sector_list or None
        ),
        default_summary=summary,
        default_trend=default_rate_trend(filtered_all, sectors=sector_list or None),
        default_trend_by_bank=default_rate_trend_by_bank(filtered_all, sectors=sector_list or None),
        migration=migration,
        kpis=kpis,
    )


def build_rating_benchmark_metrics(
    exposures: pd.DataFrame,
    rating_history: pd.DataFrame,
    reporting_date: object,
    sectors: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Create long-form numerator/denominator metrics for all banks."""
    report = pd.Timestamp(reporting_date).normalize()
    sector_list = list(sectors) if sectors else []
    current = filter_exposures(exposures, report, None, sector_list or None)
    if current.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for bank_id, group in current.groupby("bank_id"):
        ead = pd.to_numeric(group["exposure_at_default"], errors="coerce").fillna(0).clip(lower=0)
        total_ead = float(ead.sum())
        expected_default = float(
            (group["exposure_at_default"].clip(lower=0) * group["rating_grade"].map(RATING_PD_MAPPING)).sum()
        )
        base = {
            "bank_id": bank_id,
            "reporting_date": report,
            "unit": "ratio",
        }
        rows.append(
            {
                **base,
                "metric_id": "PD_12M_WEIGHTED",
                "metric_name": "Exposure-weighted PD 12M",
                "higher_is_better": False,
                "numerator": expected_default,
                "denominator": total_ead,
            }
        )
        rows.append(
            {
                **base,
                "metric_id": "SHARE_IG_A_B",
                "metric_name": "Investment-grade share (A-B, EAD)",
                "higher_is_better": True,
                "numerator": float(ead[group["rating_grade"].isin(["A", "B"])].sum()),
                "denominator": total_ead,
            }
        )
        for rating in RATING_SCALE:
            rows.append(
                {
                    **base,
                    "metric_id": f"SHARE_RATING_{rating}",
                    "metric_name": f"Rating {rating} share (EAD)",
                    "higher_is_better": None,
                    "numerator": float(ead[group["rating_grade"] == rating].sum()),
                    "denominator": total_ead,
                }
            )

    defaults = default_rate_by_bank(exposures, report, sectors=sector_list or None)
    if not defaults.empty:
        for _, row in defaults.iterrows():
            rows.append(
                {
                    "bank_id": row["bank_id"],
                    "reporting_date": report,
                    "unit": "ratio",
                    "metric_id": "DEFAULT_RATE_12M",
                    "metric_name": "Observed 12M default rate (count)",
                    "higher_is_better": False,
                    "numerator": float(row["default_count"]),
                    "denominator": float(row["base_exposures"]),
                }
            )

    start = migration_start_default(rating_history, report)
    if start is not None and start < report:
        migration = calculate_migration(
            rating_history,
            start,
            report,
            sectors=sector_list or None,
            exposures=exposures,
        )
        if not migration.by_bank.empty:
            for _, row in migration.by_bank.iterrows():
                common = {
                    "bank_id": row["bank_id"],
                    "reporting_date": report,
                    "unit": "ratio",
                }
                rows.append(
                    {
                        **common,
                        "metric_id": "RATING_UPGRADE_RATE",
                        "metric_name": "Rating upgrade rate (matched exposures)",
                        "higher_is_better": True,
                        "numerator": float(row["upgrades"]),
                        "denominator": float(row["matched_count"]),
                    }
                )
                rows.append(
                    {
                        **common,
                        "metric_id": "RATING_DOWNGRADE_RATE",
                        "metric_name": "Rating downgrade rate (matched exposures)",
                        "higher_is_better": False,
                        "numerator": float(row["downgrades"]),
                        "denominator": float(row["matched_count"]),
                    }
                )
    return pd.DataFrame(rows)
