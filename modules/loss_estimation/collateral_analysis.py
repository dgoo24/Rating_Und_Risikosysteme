"""Collateral valuation, haircut and coverage analysis.

Collateral is used to explain secured exposure and recovery capacity. It is not
subtracted a second time from the observed loss amount: loss estimation is based
on realised recovery cashflows only. This module therefore provides coverage
and concentration views, not an alternative LGD calculation.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from config.collateral_haircuts import COLLATERAL_HAIRCUTS
from config.settings import COLLATERAL_VALUATION_WARNING_YEARS
from modules.loss_estimation.calculations import filter_current_exposures, prepare_collateral


def _empty_exposure_detail() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "exposure_id", "bank_id", "rating_grade", "product_type", "industry_sector",
            "exposure_at_default", "collateral_items", "total_collateral_value",
            "total_adjusted_collateral", "haircut_reduction", "coverage_ratio",
            "coverage_ratio_capped", "secured_ead", "unsecured_ead",
            "primary_collateral_type", "latest_valuation_date", "max_valuation_age_years",
            "stale_items",
        ]
    )


def collateral_items(
    collateral: pd.DataFrame,
    exposures: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    haircuts: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Latest collateral valuation per collateral item for current exposures."""
    items = prepare_collateral(collateral, reporting_date, haircuts=haircuts)
    current = filter_current_exposures(exposures, reporting_date, bank_ids, sectors)
    if items.empty or current.empty:
        return items.iloc[0:0].copy()
    exposure_fields = current[
        ["exposure_id", "bank_id", "rating_grade", "product_type", "industry_sector", "exposure_at_default"]
    ].copy()
    merged = items.merge(
        exposure_fields,
        on="exposure_id",
        how="inner",
        suffixes=("", "_exposure"),
    )
    # Use the curated exposure bank as the authoritative reporting attribution.
    if "bank_id_exposure" in merged.columns:
        merged["bank_id"] = merged["bank_id_exposure"]
        merged = merged.drop(columns=["bank_id_exposure"])
    merged["exposure_at_default"] = pd.to_numeric(merged["exposure_at_default"], errors="coerce").fillna(0).clip(lower=0)
    merged["haircut_reduction"] = merged["collateral_value"] - merged["adjusted_collateral_value"]
    return merged.reset_index(drop=True)


def primary_collateral(
    collateral: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    haircuts: dict[str, float] | None = None,
) -> pd.DataFrame:
    """One row per exposure with the largest adjusted collateral type."""
    items = prepare_collateral(collateral, reporting_date, haircuts=haircuts)
    if items.empty:
        return pd.DataFrame(columns=["exposure_id", "primary_collateral_type", "adjusted_collateral_value"])
    if bank_ids:
        items = items[items["bank_id"].isin(list(bank_ids))]
    primary = (
        items.sort_values(["exposure_id", "adjusted_collateral_value", "collateral_type"])
        .drop_duplicates("exposure_id", keep="last")
        [["exposure_id", "collateral_type", "adjusted_collateral_value"]]
        .rename(columns={"collateral_type": "primary_collateral_type"})
    )
    return primary.reset_index(drop=True)


def collateral_exposure_detail(
    collateral: pd.DataFrame,
    exposures: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    haircuts: dict[str, float] | None = None,
    stale_years: float = COLLATERAL_VALUATION_WARNING_YEARS,
) -> pd.DataFrame:
    """Build per-exposure collateral coverage including unsecured exposures."""
    current = filter_current_exposures(exposures, reporting_date, bank_ids, sectors)
    if current.empty:
        return _empty_exposure_detail()
    items = collateral_items(collateral, exposures, reporting_date, bank_ids, sectors, haircuts=haircuts)
    if not items.empty:
        summary = (
            items.groupby("exposure_id", as_index=False)
            .agg(
                collateral_items=("collateral_id", "nunique"),
                total_collateral_value=("collateral_value", "sum"),
                total_adjusted_collateral=("adjusted_collateral_value", "sum"),
                haircut_reduction=("haircut_reduction", "sum"),
                latest_valuation_date=("valuation_date", "max"),
                oldest_valuation_date=("valuation_date", "min"),
                max_valuation_age_years=("valuation_age_years", "max"),
                stale_items=("valuation_age_years", lambda values: int((values > stale_years).sum())),
            )
        )
        primary = (
            items.sort_values(["exposure_id", "adjusted_collateral_value", "collateral_type"])
            .drop_duplicates("exposure_id", keep="last")[["exposure_id", "collateral_type"]]
            .rename(columns={"collateral_type": "primary_collateral_type"})
        )
        summary = summary.merge(primary, on="exposure_id", how="left")
    else:
        summary = pd.DataFrame(
            columns=[
                "exposure_id", "collateral_items", "total_collateral_value", "total_adjusted_collateral",
                "haircut_reduction", "latest_valuation_date", "oldest_valuation_date",
                "max_valuation_age_years", "stale_items", "primary_collateral_type",
            ]
        )

    detail = current[
        ["exposure_id", "bank_id", "rating_grade", "product_type", "industry_sector", "exposure_at_default"]
    ].copy()
    detail["exposure_at_default"] = pd.to_numeric(detail["exposure_at_default"], errors="coerce").fillna(0).clip(lower=0)
    detail = detail.merge(summary, on="exposure_id", how="left")
    for column in ("collateral_items", "stale_items"):
        # to_numeric avoids the deprecated object-dtype fillna downcasting.
        detail[column] = pd.to_numeric(detail[column], errors="coerce").fillna(0).astype(int)
    for column in ("total_collateral_value", "total_adjusted_collateral", "haircut_reduction", "max_valuation_age_years"):
        detail[column] = pd.to_numeric(detail[column], errors="coerce").fillna(0.0)
    detail["primary_collateral_type"] = detail["primary_collateral_type"].fillna("UNCOLLATERALIZED")
    detail["coverage_ratio"] = detail["total_adjusted_collateral"] / detail["exposure_at_default"].where(
        detail["exposure_at_default"] > 0
    )
    detail["coverage_ratio_capped"] = detail["coverage_ratio"].clip(upper=1.0).fillna(0.0)
    detail["secured_ead"] = detail["total_adjusted_collateral"].clip(upper=detail["exposure_at_default"])
    detail["unsecured_ead"] = (detail["exposure_at_default"] - detail["secured_ead"]).clip(lower=0)
    return detail.reset_index(drop=True)


def collateral_summary_detail(detail: pd.DataFrame) -> dict[str, float | int | None]:
    if detail.empty:
        return {
            "current_exposures": 0,
            "total_ead": 0.0,
            "exposures_with_collateral": 0,
            "share_exposures_with_collateral": None,
            "share_ead_with_collateral": None,
            "total_collateral_value": 0.0,
            "total_adjusted_collateral": 0.0,
            "haircut_reduction": 0.0,
            "collateral_coverage": None,
            "secured_ead_share": None,
            "unsecured_ead": 0.0,
            "stale_items": 0,
        }
    total_ead = float(detail["exposure_at_default"].sum())
    with_collateral = detail[detail["collateral_items"] > 0]
    covered_ead = float(with_collateral["exposure_at_default"].sum())
    adjusted = float(detail["total_adjusted_collateral"].sum())
    secured = float(detail["secured_ead"].sum())
    unsecured = float(detail["unsecured_ead"].sum())
    return {
        "current_exposures": int(len(detail)),
        "total_ead": total_ead,
        "exposures_with_collateral": int(len(with_collateral)),
        "share_exposures_with_collateral": len(with_collateral) / len(detail) if len(detail) else None,
        "share_ead_with_collateral": covered_ead / total_ead if total_ead > 0 else None,
        "total_collateral_value": float(detail["total_collateral_value"].sum()),
        "total_adjusted_collateral": adjusted,
        "haircut_reduction": float(detail["haircut_reduction"].sum()),
        "collateral_coverage": adjusted / total_ead if total_ead > 0 else None,
        "secured_ead_share": secured / total_ead if total_ead > 0 else None,
        "unsecured_ead": unsecured,
        "stale_items": int(detail["stale_items"].sum()),
    }


def collateral_summary_kpis(
    collateral: pd.DataFrame,
    exposures: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    haircuts: dict[str, float] | None = None,
) -> dict[str, float | int | None]:
    detail = collateral_exposure_detail(
        collateral, exposures, reporting_date, bank_ids=bank_ids, sectors=sectors, haircuts=haircuts
    )
    return collateral_summary_detail(detail)


def _coverage_aggregation(detail: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(
            columns=[
                *group_columns, "exposure_count", "ead", "exposures_with_collateral",
                "collateral_value", "adjusted_collateral_value", "secured_ead",
                "unsecured_ead", "coverage_ratio", "secured_ead_share",
            ]
        )
    grouped = (
        detail.groupby(group_columns, dropna=False)
        .agg(
            exposure_count=("exposure_id", "nunique"),
            ead=("exposure_at_default", "sum"),
            exposures_with_collateral=("collateral_items", lambda values: int((values > 0).sum())),
            collateral_value=("total_collateral_value", "sum"),
            adjusted_collateral_value=("total_adjusted_collateral", "sum"),
            secured_ead=("secured_ead", "sum"),
            unsecured_ead=("unsecured_ead", "sum"),
        )
        .reset_index()
    )
    grouped["coverage_ratio"] = (
        grouped["adjusted_collateral_value"] / grouped["ead"].where(grouped["ead"] > 0)
    )
    grouped["secured_ead_share"] = grouped["secured_ead"] / grouped["ead"].where(grouped["ead"] > 0)
    return grouped


def collateral_coverage_by_bank(detail: pd.DataFrame) -> pd.DataFrame:
    return _coverage_aggregation(detail, ["bank_id"]).sort_values("bank_id").reset_index(drop=True)


def collateral_coverage_by_rating(detail: pd.DataFrame) -> pd.DataFrame:
    return _coverage_aggregation(detail, ["rating_grade"]).sort_values("rating_grade").reset_index(drop=True)


def collateral_coverage_by_product(detail: pd.DataFrame) -> pd.DataFrame:
    return _coverage_aggregation(detail, ["product_type"]).sort_values("product_type").reset_index(drop=True)


def collateral_coverage_by_primary_type(detail: pd.DataFrame) -> pd.DataFrame:
    return _coverage_aggregation(detail, ["primary_collateral_type"]).sort_values("ead", ascending=False).reset_index(drop=True)


def collateral_type_mix(items: pd.DataFrame) -> pd.DataFrame:
    """Item-level collateral mix and haircut impact by collateral type."""
    if items.empty:
        return pd.DataFrame(
            columns=[
                "collateral_type", "collateral_items", "collateral_value",
                "adjusted_collateral_value", "haircut_reduction", "share_value",
                "share_adjusted_value", "average_haircut", "stale_items",
            ]
        )
    grouped = (
        items.groupby("collateral_type", dropna=False)
        .agg(
            collateral_items=("collateral_id", "nunique"),
            collateral_value=("collateral_value", "sum"),
            adjusted_collateral_value=("adjusted_collateral_value", "sum"),
            haircut_reduction=("haircut_reduction", "sum"),
            average_haircut=("haircut", "mean"),
            stale_items=("valuation_age_years", lambda values: int((values > COLLATERAL_VALUATION_WARNING_YEARS).sum())),
        )
        .reset_index()
    )
    total_value = grouped["collateral_value"].sum()
    total_adjusted = grouped["adjusted_collateral_value"].sum()
    grouped["share_value"] = grouped["collateral_value"] / total_value if total_value > 0 else 0.0
    grouped["share_adjusted_value"] = grouped["adjusted_collateral_value"] / total_adjusted if total_adjusted > 0 else 0.0
    return grouped.sort_values("collateral_value", ascending=False).reset_index(drop=True)


def stale_collateral_items(
    collateral: pd.DataFrame,
    reporting_date: object,
    bank_ids: Iterable[str] | None = None,
    stale_years: float = COLLATERAL_VALUATION_WARNING_YEARS,
) -> pd.DataFrame:
    items = prepare_collateral(collateral, reporting_date)
    if items.empty:
        return items
    if bank_ids:
        items = items[items["bank_id"].isin(list(bank_ids))]
    stale = items[items["valuation_age_years"] > stale_years].copy()
    columns = [
        "collateral_id", "exposure_id", "bank_id", "collateral_type", "collateral_value",
        "valuation_date", "valuation_age_years", "haircut", "adjusted_collateral_value",
    ]
    return stale[columns].sort_values("valuation_age_years", ascending=False).reset_index(drop=True)


def haircut_comparison(
    collateral: pd.DataFrame,
    reporting_date: object,
    haircuts: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Compare configured haircuts for the latest collateral stock."""
    active_haircuts = haircuts or COLLATERAL_HAIRCUTS
    items = prepare_collateral(collateral, reporting_date, haircuts=active_haircuts)
    if items.empty:
        return pd.DataFrame(columns=["collateral_type", "collateral_value", "configured_haircut", "adjusted_value", "reduction"])
    grouped = (
        items.groupby("collateral_type", as_index=False)
        .agg(collateral_value=("collateral_value", "sum"), adjusted_value=("adjusted_collateral_value", "sum"))
    )
    grouped["configured_haircut"] = grouped["collateral_type"].map(active_haircuts).fillna(
        active_haircuts.get("OTHER", 0.40)
    )
    grouped["reduction"] = grouped["collateral_value"] - grouped["adjusted_value"]
    return grouped.sort_values("collateral_value", ascending=False).reset_index(drop=True)
