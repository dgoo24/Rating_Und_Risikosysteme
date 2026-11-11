"""Observed loss-rate analysis derived from the default cohort.

Loss amount = EAD at default - observed recovery cashflows through the reporting
date. No indirect costs, discounting or collateral double-counting are applied in
this prototype; the resulting rate is therefore an observed, undiscounted loss
rate for the selected cohort.
"""
from __future__ import annotations

import pandas as pd

from modules.loss_estimation.calculations import add_default_quarter, aggregate_cohort

LOSS_BUCKETS = (0.0, 0.000001, 0.25, 0.50, 0.75, 1.000001)
LOSS_BUCKET_LABELS = ("No loss", "0-25%", "25-50%", "50-75%", "75-100%")


def loss_summary(cohort: pd.DataFrame) -> dict[str, float | int | None]:
    if cohort.empty:
        return {
            "default_count": 0,
            "ead_at_default": 0.0,
            "total_recoveries": 0.0,
            "loss_amount": 0.0,
            "loss_rate": None,
            "median_loss_rate": None,
            "average_loss_rate": None,
            "full_loss_count": 0,
            "full_loss_share": None,
        }
    ead = float(cohort["ead_at_default"].sum())
    recoveries = float(cohort["total_recoveries"].sum())
    loss = ead - recoveries
    full_loss_count = int((cohort["loss_rate"] >= 0.999).sum())
    return {
        "default_count": int(len(cohort)),
        "ead_at_default": ead,
        "total_recoveries": recoveries,
        "loss_amount": loss,
        "loss_rate": loss / ead if ead > 0 else None,
        "median_loss_rate": float(cohort["loss_rate"].median()),
        "average_loss_rate": float(cohort["loss_rate"].mean()),
        "full_loss_count": full_loss_count,
        "full_loss_share": full_loss_count / len(cohort) if len(cohort) else None,
    }


def loss_summary_frame(cohort: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([loss_summary(cohort)])


def loss_rate_by_dimension(cohort: pd.DataFrame, dimension: str) -> pd.DataFrame:
    if cohort.empty or dimension not in cohort.columns:
        return pd.DataFrame(
            columns=[
                dimension, "default_count", "ead_at_default", "total_recoveries",
                "recovery_count", "loss_amount", "recovery_rate", "loss_rate",
            ]
        )
    return aggregate_cohort(cohort, [dimension]).sort_values(dimension).reset_index(drop=True)


def loss_rate_by_bank(cohort: pd.DataFrame) -> pd.DataFrame:
    return loss_rate_by_dimension(cohort, "bank_id")


def loss_rate_by_rating(cohort: pd.DataFrame) -> pd.DataFrame:
    return loss_rate_by_dimension(cohort, "rating_at_default")


def loss_rate_by_product(cohort: pd.DataFrame) -> pd.DataFrame:
    return loss_rate_by_dimension(cohort, "product_type")


def loss_rate_by_sector(cohort: pd.DataFrame) -> pd.DataFrame:
    return loss_rate_by_dimension(cohort, "industry_sector")


def loss_rate_by_collateral_type(cohort: pd.DataFrame) -> pd.DataFrame:
    return loss_rate_by_dimension(cohort, "primary_collateral_type")


def loss_rate_by_default_quarter(cohort: pd.DataFrame) -> pd.DataFrame:
    frame = add_default_quarter(cohort)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "default_quarter", "default_count", "ead_at_default", "total_recoveries",
                "recovery_count", "loss_amount", "recovery_rate", "loss_rate",
            ]
        )
    return aggregate_cohort(frame, ["default_quarter"]).sort_values("default_quarter").reset_index(drop=True)


def loss_distribution(cohort: pd.DataFrame) -> pd.DataFrame:
    columns = ["loss_bucket", "default_count", "ead_at_default", "loss_amount", "share_count", "share_ead", "average_loss_rate"]
    if cohort.empty:
        return pd.DataFrame(columns=columns)
    bucket = pd.cut(
        cohort["loss_rate"].astype(float),
        bins=LOSS_BUCKETS,
        labels=LOSS_BUCKET_LABELS,
        right=False,
    )
    frame = cohort.assign(loss_bucket=bucket, _loss_amount=(cohort["ead_at_default"] - cohort["total_recoveries"]))
    grouped = (
        frame.groupby("loss_bucket", observed=False)
        .agg(
            default_count=("exposure_id", "nunique"),
            ead_at_default=("ead_at_default", "sum"),
            loss_amount=("_loss_amount", "sum"),
            average_loss_rate=("loss_rate", "mean"),
        )
        .reset_index()
    )
    grouped["share_count"] = grouped["default_count"] / grouped["default_count"].sum() if grouped["default_count"].sum() else 0.0
    grouped["share_ead"] = grouped["ead_at_default"] / grouped["ead_at_default"].sum() if grouped["ead_at_default"].sum() else 0.0
    return grouped[columns].reset_index(drop=True)


def loss_severity_bands(cohort: pd.DataFrame) -> pd.DataFrame:
    """Simple severity bands for risk committee discussion (counts and EAD)."""
    columns = ["severity", "default_count", "ead_at_default", "loss_amount", "share_ead"]
    if cohort.empty:
        return pd.DataFrame(columns=columns)
    frame = cohort.copy()
    frame["severity"] = pd.cut(
        frame["loss_rate"].astype(float),
        bins=(0.0, 0.25, 0.50, 0.75, 0.95, 1.000001),
        labels=("LOW", "MODERATE", "HIGH", "SEVERE", "FULL_LOSS"),
        right=False,
    )
    grouped = (
        frame.groupby("severity", observed=False)
        .agg(
            default_count=("exposure_id", "nunique"),
            ead_at_default=("ead_at_default", "sum"),
            loss_amount=("loss_amount", "sum"),
        )
        .reset_index()
    )
    grouped["share_ead"] = grouped["ead_at_default"] / grouped["ead_at_default"].sum() if grouped["ead_at_default"].sum() else 0.0
    return grouped[columns].reset_index(drop=True)
