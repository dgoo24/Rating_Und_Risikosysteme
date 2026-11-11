"""Shared calculations for the Loss Estimation module."""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from config.collateral_haircuts import COLLATERAL_HAIRCUTS
from config.settings import DEFAULT_OBSERVATION_MONTHS
from modules.rating_scoring.calculations import prepare_exposures


def filter_current_exposures(
    exposures: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    performing_only: bool = False,
) -> pd.DataFrame:
    frame = prepare_exposures(exposures)
    if frame.empty:
        return frame
    report = pd.Timestamp(reporting_date).normalize()
    frame = frame[frame["snapshot_date"] == report].copy()
    if bank_ids:
        frame = frame[frame["bank_id"].isin(list(bank_ids))]
    if sectors:
        frame = frame[frame["industry_sector"].isin(list(sectors))]
    if performing_only:
        frame = frame[~frame["default_flag"].fillna(False)]
    return frame.reset_index(drop=True)


def prepare_collateral(
    collateral: pd.DataFrame,
    reporting_date: object,
    haircuts: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Select latest collateral valuation as of the reporting date and apply haircuts."""
    if collateral.empty:
        return collateral.copy()
    haircuts = haircuts or COLLATERAL_HAIRCUTS
    frame = collateral.copy()
    frame["valuation_date"] = pd.to_datetime(frame["valuation_date"], errors="coerce").dt.normalize()
    frame["collateral_value"] = pd.to_numeric(frame["collateral_value"], errors="coerce")
    frame["collateral_type"] = frame["collateral_type"].astype("string").str.upper()
    report = pd.Timestamp(reporting_date).normalize()
    frame = frame[
        frame["valuation_date"].notna()
        & (frame["valuation_date"] <= report)
        & frame["collateral_value"].notna()
    ].copy()
    frame = frame.sort_values(["collateral_id", "valuation_date"]).drop_duplicates("collateral_id", keep="last")
    frame["haircut"] = frame["collateral_type"].map(haircuts).fillna(haircuts.get("OTHER", 0.40))
    frame["adjusted_collateral_value"] = frame["collateral_value"].clip(lower=0) * (1.0 - frame["haircut"])
    frame["valuation_age_days"] = (report - frame["valuation_date"]).dt.days
    frame["valuation_age_years"] = frame["valuation_age_days"] / 365.25
    return frame.reset_index(drop=True)


def prepare_cashflows(cashflows: pd.DataFrame, reporting_date: object) -> pd.DataFrame:
    if cashflows.empty:
        return cashflows.copy()
    frame = cashflows.copy()
    frame["payment_date"] = pd.to_datetime(frame["payment_date"], errors="coerce").dt.normalize()
    frame["recovery_amount"] = pd.to_numeric(frame["recovery_amount"], errors="coerce")
    report = pd.Timestamp(reporting_date).normalize()
    frame = frame[
        frame["payment_date"].notna()
        & (frame["payment_date"] <= report)
        & frame["recovery_amount"].notna()
    ].copy()
    return frame.reset_index(drop=True)


def _fallback_metadata(exposures: pd.DataFrame) -> pd.DataFrame:
    if exposures.empty:
        return pd.DataFrame(
            columns=[
                "exposure_id", "fallback_ead", "fallback_rating", "fallback_sector",
                "fallback_product", "fallback_region",
            ]
        )
    first = (
        exposures.sort_values("snapshot_date")
        .drop_duplicates("exposure_id", keep="first")
        [["exposure_id", "exposure_at_default", "rating_grade", "industry_sector", "product_type", "region"]]
        .rename(
            columns={
                "exposure_at_default": "fallback_ead",
                "rating_grade": "fallback_rating",
                "industry_sector": "fallback_sector",
                "product_type": "fallback_product",
                "region": "fallback_region",
            }
        )
    )
    return first


def prepare_default_cohort(
    exposures: pd.DataFrame,
    cashflows: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    window_months: int = DEFAULT_OBSERVATION_MONTHS,
    primary_collateral: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the observed default cohort and cumulative recovery/loss at reporting date.

    EAD at default is the latest available snapshot on or before the observed
    default date; if none exists, the first available snapshot is used as a
    documented proxy. Recoveries are only cashflows observed on or before the
    reporting date. Collateral values are not subtracted from loss: they are used
    for coverage analysis only, preventing double counting.
    """
    frame = prepare_exposures(exposures)
    report = pd.Timestamp(reporting_date).normalize()
    start = report - pd.DateOffset(months=window_months)
    empty_columns = [
        "exposure_id", "bank_id", "default_date", "ead_at_default", "rating_at_default",
        "industry_sector", "product_type", "region", "total_recoveries", "recovery_count",
        "recovery_rate", "loss_amount", "loss_rate", "primary_collateral_type",
    ]
    if frame.empty:
        return pd.DataFrame(columns=empty_columns)

    defaults = frame[
        frame["default_flag"].fillna(False) & frame["default_date"].notna()
    ][["exposure_id", "bank_id", "default_date"]].copy()
    if defaults.empty:
        return pd.DataFrame(columns=empty_columns)
    defaults = defaults.rename(columns={"bank_id": "default_bank_id"})
    defaults = defaults.sort_values("default_date").drop_duplicates("exposure_id", keep="first")
    events = defaults[(defaults["default_date"] > start) & (defaults["default_date"] <= report)].copy()
    if events.empty:
        return pd.DataFrame(columns=empty_columns)

    snapshot_data = frame[
        ["exposure_id", "snapshot_date", "exposure_at_default", "rating_grade", "industry_sector", "product_type", "region"]
    ].sort_values("snapshot_date")
    events = events.sort_values("default_date")
    cohort = pd.merge_asof(
        events,
        snapshot_data,
        left_on="default_date",
        right_on="snapshot_date",
        by="exposure_id",
        direction="backward",
    )
    fallback = _fallback_metadata(frame)
    cohort = cohort.merge(fallback, on="exposure_id", how="left")
    cohort["exposure_at_default"] = cohort["exposure_at_default"].fillna(cohort["fallback_ead"])
    cohort["rating_grade"] = cohort["rating_grade"].fillna(cohort["fallback_rating"])
    cohort["industry_sector"] = cohort["industry_sector"].fillna(cohort["fallback_sector"])
    cohort["product_type"] = cohort["product_type"].fillna(cohort["fallback_product"])
    cohort["region"] = cohort["region"].fillna(cohort["fallback_region"])
    cohort["bank_id"] = cohort["default_bank_id"]
    cohort = cohort.rename(
        columns={
            "exposure_at_default": "ead_at_default",
            "rating_grade": "rating_at_default",
        }
    )
    cohort["ead_at_default"] = pd.to_numeric(cohort["ead_at_default"], errors="coerce")
    cohort = cohort[cohort["ead_at_default"] > 0].copy()
    if bank_ids:
        cohort = cohort[cohort["bank_id"].isin(list(bank_ids))]
    if sectors:
        cohort = cohort[cohort["industry_sector"].isin(list(sectors))]
    if cohort.empty:
        return pd.DataFrame(columns=empty_columns)

    payments = prepare_cashflows(cashflows, report)
    if not payments.empty:
        payments = payments.merge(events[["exposure_id", "default_date"]], on="exposure_id", how="inner")
        payments = payments[
            payments["payment_date"].notna() & (payments["payment_date"] >= payments["default_date"])
        ]
        recovery_summary = (
            payments.groupby("exposure_id", as_index=False)
            .agg(total_recoveries=("recovery_amount", "sum"), recovery_count=("cashflow_id", "count"))
        )
    else:
        recovery_summary = pd.DataFrame(columns=["exposure_id", "total_recoveries", "recovery_count"])

    cohort = cohort.merge(recovery_summary, on="exposure_id", how="left")
    cohort["total_recoveries"] = cohort["total_recoveries"].fillna(0.0).clip(lower=0)
    cohort["recovery_count"] = cohort["recovery_count"].fillna(0).astype(int)
    cohort["recovery_rate"] = cohort["total_recoveries"] / cohort["ead_at_default"].where(cohort["ead_at_default"] > 0)
    cohort["loss_amount"] = cohort["ead_at_default"] - cohort["total_recoveries"]
    cohort["loss_rate"] = cohort["loss_amount"] / cohort["ead_at_default"].where(cohort["ead_at_default"] > 0)

    if primary_collateral is not None and not primary_collateral.empty:
        cohort = cohort.merge(
            primary_collateral[["exposure_id", "primary_collateral_type"]],
            on="exposure_id",
            how="left",
        )
    else:
        cohort["primary_collateral_type"] = None
    cohort["primary_collateral_type"] = cohort["primary_collateral_type"].fillna("UNCOLLATERALIZED")

    columns = [
        "exposure_id", "bank_id", "default_date", "ead_at_default", "rating_at_default",
        "industry_sector", "product_type", "region", "total_recoveries", "recovery_count",
        "recovery_rate", "loss_amount", "loss_rate", "primary_collateral_type",
    ]
    return cohort[columns].sort_values("default_date").reset_index(drop=True)


def safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator is None or pd.isna(denominator) or denominator == 0:
        return None
    return float(numerator) / float(denominator)


def add_default_quarter(cohort: pd.DataFrame) -> pd.DataFrame:
    if cohort.empty:
        return cohort.copy()
    result = cohort.copy()
    dates = pd.to_datetime(result["default_date"], errors="coerce")
    result["default_quarter"] = dates.dt.to_period("Q").astype("string")
    return result


def aggregate_cohort(cohort: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    """Aggregate via total numerator / total denominator, never an average of ratios."""
    if cohort.empty:
        return pd.DataFrame(
            columns=[
                *group_columns,
                "default_count",
                "ead_at_default",
                "total_recoveries",
                "loss_amount",
                "recovery_rate",
                "loss_rate",
            ]
        )
    grouped = (
        cohort.groupby(group_columns, dropna=False)
        .agg(
            default_count=("exposure_id", "nunique"),
            ead_at_default=("ead_at_default", "sum"),
            total_recoveries=("total_recoveries", "sum"),
            recovery_count=("recovery_count", "sum"),
        )
        .reset_index()
    )
    grouped["loss_amount"] = grouped["ead_at_default"] - grouped["total_recoveries"]
    grouped["recovery_rate"] = grouped["total_recoveries"] / grouped["ead_at_default"].where(grouped["ead_at_default"] > 0)
    grouped["loss_rate"] = grouped["loss_amount"] / grouped["ead_at_default"].where(grouped["ead_at_default"] > 0)
    return grouped
