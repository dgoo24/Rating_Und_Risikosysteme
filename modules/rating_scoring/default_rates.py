"""Observed 12-month default rates with an explicit cohort definition.

Observed default rates are deliberately separated from model-based PD values.

Definition:
- observation start = latest available quarter snapshot on or before
  reporting_date minus 12 months;
- denominator = exposures that were performing at the observation start and are
  present in that start snapshot (after optional bank/sector filters);
- a default is counted once per exposure when its first observed default date lies
  after the start snapshot and on or before the reporting date;
- exposure-weighted rates use exposure at default at the start snapshot.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from config.rating_pd_mapping import RATING_PD_MAPPING
from modules.rating_scoring.calculations import (
    RATING_ORDER,
    as_timestamp,
    prepare_exposures,
    quarter_end_dates,
)


def _default_events(exposures: pd.DataFrame) -> pd.DataFrame:
    events = exposures[
        exposures["default_flag"].fillna(False) & exposures["default_date"].notna()
    ][["exposure_id", "default_date"]].copy()
    if events.empty:
        return pd.DataFrame(columns=["exposure_id", "default_date"])
    events = events.sort_values("default_date").drop_duplicates("exposure_id", keep="first")
    return events.reset_index(drop=True)


def observation_start_date(
    exposures: pd.DataFrame,
    reporting_date: object,
    window_months: int = 12,
) -> pd.Timestamp | None:
    report = as_timestamp(reporting_date)
    target = report - pd.DateOffset(months=window_months)
    frame = prepare_exposures(exposures)
    candidates = [date for date in quarter_end_dates(frame) if date <= target]
    return pd.Timestamp(max(candidates)).normalize() if candidates else None


def default_observation(
    exposures: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    window_months: int = 12,
) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    frame = prepare_exposures(exposures)
    report = as_timestamp(reporting_date)
    start = observation_start_date(frame, report, window_months=window_months)
    if start is None:
        return pd.DataFrame(), None

    base = frame[frame["snapshot_date"] == start].copy()
    if bank_ids:
        base = base[base["bank_id"].isin(list(bank_ids))]
    if sectors:
        base = base[base["industry_sector"].isin(list(sectors))]
    if base.empty:
        return pd.DataFrame(), start

    base = base[~base["default_flag"].fillna(False)].copy()
    base = base[base["rating_grade"].isin(RATING_ORDER)].copy()
    base = base.drop(columns=["default_date"], errors="ignore")
    events = _default_events(frame)
    base = base.merge(events, on="exposure_id", how="left")
    base["is_default"] = (
        base["default_date"].notna()
        & (base["default_date"] > start)
        & (base["default_date"] <= report)
    )
    base["ead"] = pd.to_numeric(base["exposure_at_default"], errors="coerce").fillna(0).clip(lower=0)
    base["model_pd"] = base["rating_grade"].map(RATING_PD_MAPPING)
    return base, start


def _aggregate(detail: pd.DataFrame, group_columns: list[str], observation_start: pd.Timestamp, reporting_date: pd.Timestamp) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(
            columns=[
                *group_columns,
                "base_exposures",
                "base_ead",
                "default_count",
                "default_ead",
                "observed_default_rate",
                "observed_default_rate_ead",
                "model_pd_weighted",
                "observation_start",
                "reporting_date",
            ]
        )
    detail = detail.copy()
    detail["_default_count"] = detail["is_default"].astype(int)
    detail["_default_ead"] = detail["ead"] * detail["_default_count"]
    detail["_expected_default_ead"] = detail["ead"] * detail["model_pd"].fillna(0)

    def summarize(group: pd.DataFrame) -> pd.Series:
        base_ead = float(group["ead"].sum())
        default_count = int(group["_default_count"].sum())
        default_ead = float(group["_default_ead"].sum())
        return pd.Series(
            {
                "base_exposures": int(len(group)),
                "base_ead": base_ead,
                "default_count": default_count,
                "default_ead": default_ead,
                "observed_default_rate": default_count / len(group) if len(group) else None,
                "observed_default_rate_ead": default_ead / base_ead if base_ead > 0 else None,
                "model_pd_weighted": float(group["_expected_default_ead"].sum()) / base_ead if base_ead > 0 else None,
            }
        )

    if group_columns:
        result = detail.groupby(group_columns, dropna=False).apply(summarize, include_groups=False).reset_index()
    else:
        summary = summarize(detail).to_frame().T
        result = summary
    result["observation_start"] = observation_start
    result["reporting_date"] = reporting_date
    for column in ("base_exposures", "default_count"):
        if column in result.columns:
            result[column] = result[column].astype(int)
    return result.reset_index(drop=True)


def default_rate_by_rating(
    exposures: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    window_months: int = 12,
) -> pd.DataFrame:
    report = as_timestamp(reporting_date)
    detail, start = default_observation(exposures, report, bank_ids, sectors, window_months)
    if detail.empty or start is None:
        return pd.DataFrame()
    result = _aggregate(detail, ["rating_grade"], start, report)
    return result.sort_values("rating_grade").reset_index(drop=True)


def default_rate_by_bank(
    exposures: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    window_months: int = 12,
) -> pd.DataFrame:
    report = as_timestamp(reporting_date)
    detail, start = default_observation(exposures, report, bank_ids, sectors, window_months)
    if detail.empty or start is None:
        return pd.DataFrame()
    return _aggregate(detail, ["bank_id"], start, report).sort_values("bank_id").reset_index(drop=True)


def default_rate_by_dimension(
    exposures: pd.DataFrame,
    reporting_date: object,
    dimension: str,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    window_months: int = 12,
) -> pd.DataFrame:
    report = as_timestamp(reporting_date)
    detail, start = default_observation(exposures, report, bank_ids, sectors, window_months)
    if detail.empty or start is None or dimension not in detail.columns:
        return pd.DataFrame()
    return _aggregate(detail, [dimension], start, report).sort_values(dimension).reset_index(drop=True)


def default_rate_summary(
    exposures: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    window_months: int = 12,
) -> pd.DataFrame:
    report = as_timestamp(reporting_date)
    detail, start = default_observation(exposures, report, bank_ids, sectors, window_months)
    if detail.empty or start is None:
        return pd.DataFrame()
    return _aggregate(detail, [], start, report)


def default_rate_trend(
    exposures: pd.DataFrame,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    window_months: int = 12,
) -> pd.DataFrame:
    frame = prepare_exposures(exposures)
    reports = quarter_end_dates(frame)
    rows: list[pd.DataFrame] = []
    for report in reports:
        detail, start = default_observation(frame, report, bank_ids, sectors, window_months)
        if detail.empty or start is None:
            continue
        summary = _aggregate(detail, [], start, pd.Timestamp(report).normalize())
        rows.append(summary)
    if not rows:
        return pd.DataFrame(
            columns=[
                "base_exposures", "base_ead", "default_count", "default_ead",
                "observed_default_rate", "observed_default_rate_ead", "model_pd_weighted",
                "observation_start", "reporting_date",
            ]
        )
    return pd.concat(rows, ignore_index=True).sort_values("reporting_date").reset_index(drop=True)


def default_rate_trend_by_bank(
    exposures: pd.DataFrame,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    window_months: int = 12,
) -> pd.DataFrame:
    frame = prepare_exposures(exposures)
    if bank_ids:
        frame = frame[frame["bank_id"].isin(list(bank_ids))]
    if sectors:
        frame = frame[frame["industry_sector"].isin(list(sectors))]
    rows: list[pd.DataFrame] = []
    for bank_id, bank_frame in frame.groupby("bank_id"):
        trend = default_rate_trend(bank_frame, sectors=sectors, window_months=window_months)
        if not trend.empty:
            trend["bank_id"] = bank_id
            rows.append(trend)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
