"""Uniqueness checks within a batch and against curated history."""
from __future__ import annotations

import pandas as pd

from quality.context import ValidationContext
from quality.findings import duplicate_within_batch, finding_rows, key_tuples, missing_mask


def _existing_mask(df: pd.DataFrame, fields: tuple[str, ...], existing: set[tuple[str, ...]]) -> pd.Series:
    keys = key_tuples(df, fields)
    return pd.Series([bool(key) and key in existing for key in keys], index=df.index)


def _unique_simple_key(df: pd.DataFrame, field: str) -> pd.Series:
    complete = ~missing_mask(df[field])
    mask = pd.Series(False, index=df.index)
    if complete.any():
        mask.loc[complete] = df.loc[complete].duplicated(subset=[field], keep="first")
    return mask


def check_exposures(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    fields = ("exposure_id", "snapshot_date")
    findings = finding_rows(
        df,
        duplicate_within_batch(df, fields),
        "UNIQ-EXP-001",
        "Duplicate exposure_id/snapshot_date within the import batch; first occurrence retained.",
        "exposure_id",
        ctx,
    )
    findings.extend(
        finding_rows(
            df,
            _existing_mask(df, fields, ctx.existing_exposure_keys),
            "UNIQ-EXP-002",
            "Exposure snapshot already exists in curated data; historical data is not overwritten.",
            "exposure_id",
            ctx,
        )
    )
    return findings


def check_rating_history(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    fields = ("exposure_id", "observation_date")
    findings = finding_rows(
        df,
        duplicate_within_batch(df, fields),
        "UNIQ-RAT-001",
        "Duplicate exposure/observation_date within the rating-history batch.",
        "exposure_id",
        ctx,
    )
    findings.extend(
        finding_rows(
            df,
            _existing_mask(df, fields, ctx.existing_rating_keys),
            "UNIQ-RAT-002",
            "Rating observation already exists in curated data; historical data is not overwritten.",
            "exposure_id",
            ctx,
        )
    )
    return findings


def check_collateral(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    fields = ("collateral_id", "valuation_date")
    findings = finding_rows(
        df,
        duplicate_within_batch(df, fields),
        "UNIQ-COL-001",
        "Duplicate collateral_id/valuation_date within the collateral batch.",
        "collateral_id",
        ctx,
    )
    findings.extend(
        finding_rows(
            df,
            _existing_mask(df, fields, ctx.existing_collateral_keys),
            "UNIQ-COL-002",
            "Collateral valuation already exists in curated data; historical data is not overwritten.",
            "collateral_id",
            ctx,
        )
    )
    return findings


def check_recovery_cashflows(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings = finding_rows(
        df,
        _unique_simple_key(df, "cashflow_id"),
        "UNIQ-REC-001",
        "Duplicate cashflow_id within the recovery batch; first occurrence retained.",
        "cashflow_id",
        ctx,
    )
    existing_mask = df["cashflow_id"].astype("string").isin(list(ctx.existing_cashflow_ids)).fillna(False)
    findings.extend(
        finding_rows(
            df,
            existing_mask,
            "UNIQ-REC-002",
            "Cashflow ID already exists in curated data; historical data is not overwritten.",
            "cashflow_id",
            ctx,
        )
    )
    fields = ("exposure_id", "payment_date", "recovery_amount", "recovery_type")
    findings.extend(
        finding_rows(
            df,
            duplicate_within_batch(df, fields),
            "UNIQ-REC-003",
            "Identical recovery business record occurs more than once within the batch.",
            "cashflow_id",
            ctx,
        )
    )
    return findings
