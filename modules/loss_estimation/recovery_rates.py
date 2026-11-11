"""Observed recovery-rate analysis for the 12-month default cohort.

Portfolio recovery rates are calculated as total observed recoveries divided by
total exposure at default. They are never an unweighted average of exposure-level
percentages. Median and distribution statistics are shown separately.
"""
from __future__ import annotations

import pandas as pd

from modules.loss_estimation.calculations import add_default_quarter, aggregate_cohort

RECOVERY_BUCKETS = (0.0, 0.000001, 0.25, 0.50, 0.75, 1.000001)
RECOVERY_BUCKET_LABELS = ("No recovery", "0-25%", "25-50%", "50-75%", "75-100%")


def recovery_summary(cohort: pd.DataFrame) -> dict[str, float | int | None]:
    if cohort.empty:
        return {
            "default_count": 0,
            "ead_at_default": 0.0,
            "total_recoveries": 0.0,
            "recovery_rate": None,
            "median_recovery_rate": None,
            "average_recovery_rate": None,
            "zero_recovery_count": 0,
            "zero_recovery_share": None,
            "recoveries_observed": 0,
        }
    ead = float(cohort["ead_at_default"].sum())
    recoveries = float(cohort["total_recoveries"].sum())
    zero_count = int((cohort["total_recoveries"] <= 0).sum())
    return {
        "default_count": int(len(cohort)),
        "ead_at_default": ead,
        "total_recoveries": recoveries,
        "recovery_rate": recoveries / ead if ead > 0 else None,
        "median_recovery_rate": float(cohort["recovery_rate"].median()) if not cohort.empty else None,
        "average_recovery_rate": float(cohort["recovery_rate"].mean()) if not cohort.empty else None,
        "zero_recovery_count": zero_count,
        "zero_recovery_share": zero_count / len(cohort) if len(cohort) else None,
        "recoveries_observed": int(cohort["total_recoveries"].gt(0).sum()),
    }


def recovery_rate_summary(cohort: pd.DataFrame) -> pd.DataFrame:
    summary = recovery_summary(cohort)
    return pd.DataFrame([summary])


def recovery_rate_by_dimension(cohort: pd.DataFrame, dimension: str) -> pd.DataFrame:
    if cohort.empty or dimension not in cohort.columns:
        return pd.DataFrame(
            columns=[
                dimension, "default_count", "ead_at_default", "total_recoveries",
                "recovery_count", "loss_amount", "recovery_rate", "loss_rate",
            ]
        )
    return aggregate_cohort(cohort, [dimension]).sort_values(dimension).reset_index(drop=True)


def recovery_rate_by_bank(cohort: pd.DataFrame) -> pd.DataFrame:
    return recovery_rate_by_dimension(cohort, "bank_id")


def recovery_rate_by_rating(cohort: pd.DataFrame) -> pd.DataFrame:
    return recovery_rate_by_dimension(cohort, "rating_at_default")


def recovery_rate_by_product(cohort: pd.DataFrame) -> pd.DataFrame:
    return recovery_rate_by_dimension(cohort, "product_type")


def recovery_rate_by_sector(cohort: pd.DataFrame) -> pd.DataFrame:
    return recovery_rate_by_dimension(cohort, "industry_sector")


def recovery_rate_by_collateral_type(cohort: pd.DataFrame) -> pd.DataFrame:
    return recovery_rate_by_dimension(cohort, "primary_collateral_type")


def recovery_rate_by_default_quarter(cohort: pd.DataFrame) -> pd.DataFrame:
    frame = add_default_quarter(cohort)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "default_quarter", "default_count", "ead_at_default", "total_recoveries",
                "recovery_count", "loss_amount", "recovery_rate", "loss_rate",
            ]
        )
    return aggregate_cohort(frame, ["default_quarter"]).sort_values("default_quarter").reset_index(drop=True)


def recovery_distribution(cohort: pd.DataFrame) -> pd.DataFrame:
    """Distribution of exposure-level recovery rates with exposure and EAD weights."""
    columns = ["recovery_bucket", "default_count", "ead_at_default", "share_count", "share_ead", "average_recovery_rate"]
    if cohort.empty:
        return pd.DataFrame(columns=columns)
    bucket = pd.cut(
        cohort["recovery_rate"].astype(float),
        bins=RECOVERY_BUCKETS,
        labels=RECOVERY_BUCKET_LABELS,
        right=False,
        include_lowest=True,
    )
    frame = cohort.assign(recovery_bucket=bucket)
    grouped = (
        frame.groupby("recovery_bucket", observed=False)
        .agg(
            default_count=("exposure_id", "nunique"),
            ead_at_default=("ead_at_default", "sum"),
            average_recovery_rate=("recovery_rate", "mean"),
        )
        .reset_index()
    )
    grouped["share_count"] = grouped["default_count"] / grouped["default_count"].sum() if grouped["default_count"].sum() else 0.0
    grouped["share_ead"] = grouped["ead_at_default"] / grouped["ead_at_default"].sum() if grouped["ead_at_default"].sum() else 0.0
    return grouped[columns].reset_index(drop=True)


def recovery_by_rating_vs_collateral(cohort: pd.DataFrame) -> pd.DataFrame:
    """Recovery rates by rating and collateral status for portfolio discussion."""
    if cohort.empty:
        return pd.DataFrame(
            columns=["rating_at_default", "primary_collateral_type", "default_count", "ead_at_default", "total_recoveries", "recovery_rate"]
        )
    return aggregate_cohort(cohort, ["rating_at_default", "primary_collateral_type"]).sort_values(
        ["rating_at_default", "primary_collateral_type"]
    ).reset_index(drop=True)
