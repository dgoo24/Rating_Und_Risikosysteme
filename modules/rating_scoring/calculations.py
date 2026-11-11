"""Shared helpers for the Rating & Scoring module."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from config.rating_pd_mapping import RATING_SCALE, RATING_PD_MAPPING, pd_for_rating


def as_timestamp(value: object) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def prepare_exposures(exposures: pd.DataFrame) -> pd.DataFrame:
    """Normalise canonical fields used by both risk modules."""
    if exposures.empty:
        return exposures.copy()
    frame = exposures.copy()
    for column in ("snapshot_date", "origination_date", "maturity_date", "default_date"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    frame["rating_grade"] = frame["rating_grade"].astype("string").str.upper()
    for column in ("exposure_at_default", "outstanding_balance"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "default_flag" in frame.columns:
        frame["default_flag"] = frame["default_flag"].fillna(False).astype(bool)
    return frame


def filter_exposures(
    exposures: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
) -> pd.DataFrame:
    frame = prepare_exposures(exposures)
    if frame.empty:
        return frame
    report = as_timestamp(reporting_date)
    frame = frame[frame["snapshot_date"] == report].copy()
    if bank_ids:
        bank_list = list(bank_ids)
        if bank_list:
            frame = frame[frame["bank_id"].isin(bank_list)]
    if sectors:
        sector_list = list(sectors)
        if sector_list:
            frame = frame[frame["industry_sector"].isin(sector_list)]
    return frame.reset_index(drop=True)


def latest_reporting_date(exposures: pd.DataFrame) -> pd.Timestamp | None:
    if exposures.empty:
        return None
    dates = pd.to_datetime(exposures["snapshot_date"], errors="coerce")
    return dates.max().normalize() if dates.notna().any() else None


def quarter_end_dates(
    frame: pd.DataFrame,
    column: str = "snapshot_date",
) -> list[pd.Timestamp]:
    """Return sorted quarter-end dates present in a frame.

    Records with non-quarter-end dates can be retained as warnings by the data
    quality engine. They must not create additional analytical reporting periods.
    """
    if frame.empty or column not in frame.columns:
        return []
    dates = pd.to_datetime(frame[column], errors="coerce").dropna().dt.normalize().unique()
    return sorted(pd.Timestamp(value) for value in dates if pd.Timestamp(value).is_quarter_end)


def valid_rating_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["rating_grade"].isin(RATING_SCALE)].copy()


def add_pd(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["pd_rate"] = result["rating_grade"].map(RATING_PD_MAPPING)
    return result


def weighted_pd(frame: pd.DataFrame) -> float:
    """Exposure-weighted portfolio PD: sum(EAD*PD) / sum(EAD)."""
    eligible = valid_rating_portfolio(frame)
    eligible = eligible[eligible["exposure_at_default"] > 0].copy()
    if eligible.empty:
        return 0.0
    eligible["pd_rate"] = eligible["rating_grade"].map(RATING_PD_MAPPING)
    denominator = eligible["exposure_at_default"].sum()
    if denominator <= 0:
        return 0.0
    return float((eligible["exposure_at_default"] * eligible["pd_rate"]).sum() / denominator)


def safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator is None or denominator == 0 or pd.isna(denominator):
        return None
    return float(numerator) / float(denominator)


def all_ratings() -> list[str]:
    return list(RATING_SCALE)


def pd_for(rating: str | None) -> float | None:
    return pd_for_rating(rating)


def portfolio_ead(frame: pd.DataFrame) -> float:
    values = pd.to_numeric(frame["exposure_at_default"], errors="coerce")
    return float(values[values > 0].sum())


def rating_rank_or_none(rating: str | None) -> int | None:
    if rating is None or pd.isna(rating):
        return None
    try:
        return RATING_SCALE.index(str(rating)) + 1
    except ValueError:
        return None


RATING_ORDER = list(RATING_SCALE)
