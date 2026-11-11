"""Recovery cashflow timing, mix and cumulative curve analysis."""
from __future__ import annotations

import pandas as pd

from modules.loss_estimation.calculations import prepare_cashflows


def prepare_recovery_detail(cashflows: pd.DataFrame, cohort: pd.DataFrame, reporting_date: object) -> pd.DataFrame:
    """Attach cashflows to observed defaults, keeping only post-default payments."""
    if cohort.empty or cashflows.empty:
        return pd.DataFrame(
            columns=[
                "cashflow_id", "exposure_id", "bank_id", "payment_date", "recovery_amount",
                "recovery_type", "days_to_recovery", "months_since_default", "default_date",
                "ead_at_default", "rating_at_default", "product_type", "industry_sector",
                "primary_collateral_type",
            ]
        )
    payments = prepare_cashflows(cashflows, reporting_date)
    if payments.empty:
        return pd.DataFrame()
    context = cohort[
        [
            "exposure_id", "bank_id", "default_date", "ead_at_default", "rating_at_default",
            "product_type", "industry_sector", "primary_collateral_type",
        ]
    ].copy()
    detail = payments.merge(context, on="exposure_id", how="inner", suffixes=("", "_cohort"))
    if detail.empty:
        return detail
    detail["payment_date"] = pd.to_datetime(detail["payment_date"], errors="coerce").dt.normalize()
    detail["default_date"] = pd.to_datetime(detail["default_date"], errors="coerce").dt.normalize()
    detail = detail[
        detail["payment_date"].notna()
        & detail["default_date"].notna()
        & (detail["payment_date"] >= detail["default_date"])
    ].copy()
    if "bank_id_cohort" in detail.columns:
        detail["bank_id"] = detail["bank_id_cohort"]
        detail = detail.drop(columns=["bank_id_cohort"])
    detail["recovery_type"] = detail["recovery_type"].fillna("UNSPECIFIED").astype("string").str.upper()
    detail["days_to_recovery"] = (detail["payment_date"] - detail["default_date"]).dt.days
    detail["months_since_default"] = (detail["days_to_recovery"] / 30.4375).round().astype(int)
    return detail.sort_values(["payment_date", "cashflow_id"]).reset_index(drop=True)


def recovery_cashflow_summary(detail: pd.DataFrame) -> dict[str, float | int | None]:
    if detail.empty:
        return {
            "cashflow_count": 0,
            "total_recovered": 0.0,
            "average_recovery": None,
            "median_recovery": None,
            "weighted_average_days": None,
            "max_days": None,
            "exposures_with_recovery": 0,
        }
    total = float(detail["recovery_amount"].sum())
    weighted_days = (
        float((detail["days_to_recovery"] * detail["recovery_amount"]).sum() / total) if total > 0 else None
    )
    return {
        "cashflow_count": int(len(detail)),
        "total_recovered": total,
        "average_recovery": float(detail["recovery_amount"].mean()),
        "median_recovery": float(detail["recovery_amount"].median()),
        "weighted_average_days": weighted_days,
        "max_days": int(detail["days_to_recovery"].max()) if len(detail) else None,
        "exposures_with_recovery": int(detail["exposure_id"].nunique()),
    }


def recovery_type_mix(detail: pd.DataFrame) -> pd.DataFrame:
    columns = ["recovery_type", "cashflow_count", "recovered_amount", "share_amount", "average_amount"]
    if detail.empty:
        return pd.DataFrame(columns=columns)
    grouped = (
        detail.groupby("recovery_type", as_index=False)
        .agg(cashflow_count=("cashflow_id", "nunique"), recovered_amount=("recovery_amount", "sum"))
    )
    total = grouped["recovered_amount"].sum()
    grouped["share_amount"] = grouped["recovered_amount"] / total if total > 0 else 0.0
    grouped["average_amount"] = grouped["recovered_amount"] / grouped["cashflow_count"].where(grouped["cashflow_count"] > 0)
    return grouped.sort_values("recovered_amount", ascending=False).reset_index(drop=True)


def cashflow_by_period(detail: pd.DataFrame, frequency: str = "Q") -> pd.DataFrame:
    """Observed recovery cashflows by payment period with cumulative share."""
    columns = ["payment_period", "cashflow_count", "recovered_amount", "share_amount", "cumulative_amount", "cumulative_share"]
    if detail.empty:
        return pd.DataFrame(columns=columns)
    frame = detail.copy()
    frame["payment_period"] = pd.PeriodIndex(pd.to_datetime(frame["payment_date"]), freq=frequency).astype(str)
    grouped = (
        frame.groupby("payment_period", as_index=False)
        .agg(cashflow_count=("cashflow_id", "nunique"), recovered_amount=("recovery_amount", "sum"))
        .sort_values("payment_period")
        .reset_index(drop=True)
    )
    total = grouped["recovered_amount"].sum()
    grouped["share_amount"] = grouped["recovered_amount"] / total if total > 0 else 0.0
    grouped["cumulative_amount"] = grouped["recovered_amount"].cumsum()
    grouped["cumulative_share"] = grouped["cumulative_amount"] / total if total > 0 else 0.0
    return grouped[columns]


def cumulative_recovery_curve(
    detail: pd.DataFrame,
    cohort: pd.DataFrame,
    max_months: int = 24,
) -> pd.DataFrame:
    """Cumulative recoveries by months since default, versus total cohort EAD."""
    columns = [
        "months_since_default", "cumulative_recoveries", "incremental_recoveries",
        "cumulative_recovery_rate", "exposures_with_recovery",
    ]
    if cohort.empty:
        return pd.DataFrame(columns=columns)
    total_ead = float(cohort["ead_at_default"].sum())
    rows: list[dict[str, object]] = []
    previous = 0.0
    if detail.empty:
        for month in range(max_months + 1):
            rows.append(
                {
                    "months_since_default": month,
                    "cumulative_recoveries": 0.0,
                    "incremental_recoveries": 0.0,
                    "cumulative_recovery_rate": 0.0 if total_ead > 0 else None,
                    "exposures_with_recovery": 0,
                }
            )
        return pd.DataFrame(rows, columns=columns)
    for month in range(max_months + 1):
        observed = detail[detail["months_since_default"] <= month]
        cumulative = float(observed["recovery_amount"].sum())
        rows.append(
            {
                "months_since_default": month,
                "cumulative_recoveries": cumulative,
                "incremental_recoveries": cumulative - previous,
                "cumulative_recovery_rate": cumulative / total_ead if total_ead > 0 else None,
                "exposures_with_recovery": int(observed["exposure_id"].nunique()),
            }
        )
        previous = cumulative
    return pd.DataFrame(rows, columns=columns)


def time_to_recovery_bands(detail: pd.DataFrame, cohort: pd.DataFrame) -> pd.DataFrame:
    """First observed recovery timing per exposure, weighted by EAD."""
    columns = ["time_to_recovery", "default_count", "ead_at_default", "recovered_amount", "share_count", "share_ead"]
    if cohort.empty:
        return pd.DataFrame(columns=columns)
    first = (
        detail.groupby("exposure_id", as_index=False)
        .agg(first_recovery_days=("days_to_recovery", "min"), recovered_amount=("recovery_amount", "sum"))
        if not detail.empty
        else pd.DataFrame(columns=["exposure_id", "first_recovery_days", "recovered_amount"])
    )
    frame = cohort[["exposure_id", "ead_at_default"]].merge(first, on="exposure_id", how="left")
    frame["first_recovery_days"] = frame["first_recovery_days"].fillna(99999)
    frame["time_to_recovery"] = pd.cut(
        frame["first_recovery_days"],
        bins=(-1, 90, 180, 365, 730, 100000),
        labels=("0-90 days", "91-180 days", "181-365 days", "1-2 years", "No recovery yet"),
    )
    grouped = (
        frame.groupby("time_to_recovery", observed=False)
        .agg(
            default_count=("exposure_id", "nunique"),
            ead_at_default=("ead_at_default", "sum"),
            recovered_amount=("recovered_amount", "sum"),
        )
        .reset_index()
    )
    grouped["recovered_amount"] = grouped["recovered_amount"].fillna(0.0)
    grouped["share_count"] = grouped["default_count"] / grouped["default_count"].sum() if grouped["default_count"].sum() else 0.0
    grouped["share_ead"] = grouped["ead_at_default"] / grouped["ead_at_default"].sum() if grouped["ead_at_default"].sum() else 0.0
    return grouped[columns].reset_index(drop=True)


def recovery_lag_by_dimension(detail: pd.DataFrame, dimension: str) -> pd.DataFrame:
    columns = [dimension, "cashflow_count", "exposures", "recovered_amount", "weighted_average_days", "average_days"]
    if detail.empty or dimension not in detail.columns:
        return pd.DataFrame(columns=columns)
    grouped = (
        detail.groupby(dimension, dropna=False)
        .agg(
            cashflow_count=("cashflow_id", "nunique"),
            exposures=("exposure_id", "nunique"),
            recovered_amount=("recovery_amount", "sum"),
            average_days=("days_to_recovery", "mean"),
        )
        .reset_index()
    )
    weighted = (
        detail.assign(_weighted=detail["days_to_recovery"] * detail["recovery_amount"])
        .groupby(dimension, dropna=False, as_index=False)["_weighted"].sum()
    )
    grouped = grouped.merge(weighted, on=dimension, how="left")
    grouped["weighted_average_days"] = grouped["_weighted"] / grouped["recovered_amount"].where(
        grouped["recovered_amount"] > 0
    )
    return grouped.drop(columns=["_weighted"]).sort_values(dimension).reset_index(drop=True)
