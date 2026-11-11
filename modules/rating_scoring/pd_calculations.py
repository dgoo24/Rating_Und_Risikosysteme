"""PD 12M calculations with a configurable rating-to-PD mapping."""
from __future__ import annotations

import pandas as pd

from config.rating_pd_mapping import RATING_PD_MAPPING
from modules.rating_scoring.calculations import (
    RATING_ORDER,
    prepare_exposures,
    quarter_end_dates,
    weighted_pd,
)


def _pd_by_group(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    frame = prepare_exposures(frame)
    frame = frame[frame["rating_grade"].isin(RATING_ORDER)].copy()
    frame["exposure_at_default"] = pd.to_numeric(frame["exposure_at_default"], errors="coerce").fillna(0).clip(lower=0)
    frame = frame[frame["exposure_at_default"] > 0]
    if frame.empty:
        return pd.DataFrame(columns=[*group_columns, "ead", "expected_default_ead", "weighted_pd", "exposure_count"])
    frame["pd_rate"] = frame["rating_grade"].map(RATING_PD_MAPPING)
    frame["expected_default_ead"] = frame["exposure_at_default"] * frame["pd_rate"]
    grouped = (
        frame.groupby(group_columns, as_index=False)
        .agg(
            ead=("exposure_at_default", "sum"),
            expected_default_ead=("expected_default_ead", "sum"),
            exposure_count=("exposure_id", "count"),
        )
    )
    grouped["weighted_pd"] = grouped["expected_default_ead"] / grouped["ead"].where(grouped["ead"] > 0)
    return grouped


def pd_by_rating(exposures: pd.DataFrame) -> pd.DataFrame:
    grouped = _pd_by_group(exposures, ["rating_grade"])
    if grouped.empty:
        return pd.DataFrame(columns=["rating_grade", "ead", "expected_default_ead", "weighted_pd", "exposure_count"])
    return grouped.set_index("rating_grade").reindex(RATING_ORDER).dropna(subset=["ead"]).reset_index()


def pd_by_bank(exposures: pd.DataFrame) -> pd.DataFrame:
    return _pd_by_group(exposures, ["bank_id"])


def pd_by_sector(exposures: pd.DataFrame) -> pd.DataFrame:
    return _pd_by_group(exposures, ["industry_sector"])


def portfolio_pd(exposures: pd.DataFrame) -> float:
    return weighted_pd(prepare_exposures(exposures))


def pd_trend(exposures: pd.DataFrame) -> pd.DataFrame:
    frame = prepare_exposures(exposures)
    reporting_dates = quarter_end_dates(frame)
    if frame.empty or not reporting_dates:
        return pd.DataFrame(columns=["snapshot_date", "ead", "expected_default_ead", "weighted_pd", "exposure_count"])
    grouped = _pd_by_group(frame[frame["snapshot_date"].isin(reporting_dates)], ["snapshot_date"])
    return grouped.sort_values("snapshot_date").reset_index(drop=True)


def pd_trend_by_bank(exposures: pd.DataFrame) -> pd.DataFrame:
    frame = prepare_exposures(exposures)
    reporting_dates = quarter_end_dates(frame)
    if frame.empty or not reporting_dates:
        return pd.DataFrame(
            columns=["snapshot_date", "bank_id", "ead", "expected_default_ead", "weighted_pd", "exposure_count"]
        )
    grouped = _pd_by_group(
        frame[frame["snapshot_date"].isin(reporting_dates)],
        ["snapshot_date", "bank_id"],
    )
    return grouped.sort_values(["snapshot_date", "bank_id"]).reset_index(drop=True)


def pd_by_sector_and_bank(exposures: pd.DataFrame) -> pd.DataFrame:
    return _pd_by_group(exposures, ["bank_id", "industry_sector"])


def pd_summary_kpis(exposures: pd.DataFrame) -> dict[str, float | int]:
    frame = prepare_exposures(exposures)
    ead = pd.to_numeric(frame["exposure_at_default"], errors="coerce").fillna(0)
    return {
        "portfolio_pd": weighted_pd(frame),
        "total_ead": float(ead[ead > 0].sum()),
        "expected_default_ead": float(
            (
                frame.loc[frame["exposure_at_default"] > 0, "exposure_at_default"]
                * frame.loc[frame["exposure_at_default"] > 0, "rating_grade"].map(RATING_PD_MAPPING).fillna(0)
            ).sum()
        ),
        "exposure_count": int(len(frame)),
    }
