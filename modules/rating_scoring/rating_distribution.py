"""Rating distribution calculations."""
from __future__ import annotations

import pandas as pd

from config.rating_pd_mapping import RATING_PD_MAPPING
from modules.rating_scoring.calculations import (
    RATING_ORDER,
    prepare_exposures,
    quarter_end_dates,
    valid_rating_portfolio,
)


def _empty_distribution(extra_columns: list[str] | None = None) -> pd.DataFrame:
    columns = ["rating_grade", "exposure_count", "ead", "share_count", "share_ead", "pd_rate", "expected_default_ead"]
    columns.extend(extra_columns or [])
    return pd.DataFrame(columns=columns)


def rating_distribution(exposures: pd.DataFrame) -> pd.DataFrame:
    """Count and exposure-volume distribution across configured rating grades.

    Shares use the aggregate valid portfolio as denominator; they are not averages
    of bank-level percentages.
    """
    frame = valid_rating_portfolio(prepare_exposures(exposures))
    if frame.empty:
        return _empty_distribution()
    ead = pd.to_numeric(frame["exposure_at_default"], errors="coerce").fillna(0).clip(lower=0)
    grouped = (
        frame.assign(_ead=ead, _pd=frame["rating_grade"].map(RATING_PD_MAPPING))
        .groupby("rating_grade", as_index=False)
        .agg(exposure_count=("exposure_id", "count"), ead=("_ead", "sum"), expected_default_ead=("_ead", lambda values: 0.0))
    )
    # Expected default is calculated after adding the flat PD so that the formula is explicit.
    grouped["pd_rate"] = grouped["rating_grade"].map(RATING_PD_MAPPING)
    grouped["expected_default_ead"] = grouped["ead"] * grouped["pd_rate"]
    total_count = grouped["exposure_count"].sum()
    total_ead = grouped["ead"].sum()
    grouped["share_count"] = grouped["exposure_count"] / total_count if total_count else 0.0
    grouped["share_ead"] = grouped["ead"] / total_ead if total_ead else 0.0
    grouped = grouped.set_index("rating_grade").reindex(RATING_ORDER).fillna(0).reset_index()
    grouped["exposure_count"] = grouped["exposure_count"].astype(int)
    return grouped[
        ["rating_grade", "exposure_count", "ead", "share_count", "share_ead", "pd_rate", "expected_default_ead"]
    ]


def rating_distribution_by_bank(exposures: pd.DataFrame) -> pd.DataFrame:
    frame = valid_rating_portfolio(prepare_exposures(exposures))
    if frame.empty:
        return _empty_distribution(["bank_id", "snapshot_date"])
    rows = []
    for (bank_id, snapshot_date), group in frame.groupby(["bank_id", "snapshot_date"]):
        distribution = rating_distribution(group)
        distribution["bank_id"] = bank_id
        distribution["snapshot_date"] = snapshot_date
        rows.append(distribution)
    return pd.concat(rows, ignore_index=True) if rows else _empty_distribution(["bank_id", "snapshot_date"])


def rating_distribution_trend(exposures: pd.DataFrame) -> pd.DataFrame:
    frame = valid_rating_portfolio(prepare_exposures(exposures))
    reporting_dates = quarter_end_dates(frame)
    if frame.empty or not reporting_dates:
        return _empty_distribution(["snapshot_date"])
    frame = frame[frame["snapshot_date"].isin(reporting_dates)]
    rows = []
    for snapshot_date, group in frame.groupby("snapshot_date"):
        distribution = rating_distribution(group)
        distribution["snapshot_date"] = snapshot_date
        rows.append(distribution)
    return pd.concat(rows, ignore_index=True) if rows else _empty_distribution(["snapshot_date"])


def rating_distribution_by_dimension(exposures: pd.DataFrame, dimension: str) -> pd.DataFrame:
    frame = valid_rating_portfolio(prepare_exposures(exposures))
    if frame.empty or dimension not in frame.columns:
        return _empty_distribution([dimension])
    rows = []
    for value, group in frame.groupby(dimension):
        distribution = rating_distribution(group)
        distribution[dimension] = value
        rows.append(distribution)
    return pd.concat(rows, ignore_index=True) if rows else _empty_distribution([dimension])


def investment_grade_share(exposures: pd.DataFrame, grades: tuple[str, ...] = ("A", "B")) -> float | None:
    frame = valid_rating_portfolio(prepare_exposures(exposures))
    if frame.empty:
        return None
    ead = pd.to_numeric(frame["exposure_at_default"], errors="coerce").fillna(0).clip(lower=0)
    total = ead.sum()
    if total <= 0:
        return None
    return float(ead[frame["rating_grade"].isin(grades)].sum() / total)
