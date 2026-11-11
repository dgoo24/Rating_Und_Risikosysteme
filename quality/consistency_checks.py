"""Consistency checks against reference data and relationships."""
from __future__ import annotations

import pandas as pd

from config.settings import CURRENCY, RATING_SCALE
from quality.context import ValidationContext
from quality.findings import finding_rows, missing_mask


def _unknown_bank(df: pd.DataFrame, ctx: ValidationContext, rule_id: str) -> list[dict[str, object]]:
    mask = ~missing_mask(df["bank_id"]) & ~df["bank_id"].isin(list(ctx.reference_bank_ids))
    return finding_rows(
        df,
        mask,
        rule_id,
        "Bank identifier is not present in the institution master.",
        "bank_id",
        ctx,
    )


def _invalid_rating(df: pd.DataFrame, ctx: ValidationContext, rule_id: str) -> list[dict[str, object]]:
    mask = ~missing_mask(df["rating_grade"]) & ~df["rating_grade"].isin(list(RATING_SCALE))
    return finding_rows(
        df,
        mask,
        rule_id,
        "Rating grade is outside the configured A-F rating scale.",
        "rating_grade",
        ctx,
    )


def _relationship(
    df: pd.DataFrame,
    ctx: ValidationContext,
    orphan_rule: str,
    mismatch_rule: str,
) -> list[dict[str, object]]:
    exposure_present = ~missing_mask(df["exposure_id"])
    orphan = exposure_present & ~df["exposure_id"].isin(list(ctx.exposure_bank_map.keys()))
    findings = finding_rows(
        df,
        orphan,
        orphan_rule,
        "Referenced exposure does not exist in curated data.",
        "exposure_id",
        ctx,
    )
    mapped_bank = df["exposure_id"].map(ctx.exposure_bank_map)
    mismatch = exposure_present & mapped_bank.notna() & ~missing_mask(df["bank_id"]) & (df["bank_id"] != mapped_bank)
    findings.extend(
        finding_rows(
            df,
            mismatch,
            mismatch_rule,
            "Record bank does not match the bank of the referenced exposure.",
            "bank_id",
            ctx,
        )
    )
    return findings


def check_exposures(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings = _unknown_bank(df, ctx, "CONS-EXP-001")
    findings.extend(_invalid_rating(df, ctx, "CONS-EXP-002"))
    currency_mask = ~missing_mask(df["currency"]) & (df["currency"] != CURRENCY)
    findings.extend(
        finding_rows(
            df,
            currency_mask,
            "CONS-EXP-003",
            f"Currency is not the configured reporting currency {CURRENCY}.",
            "currency",
            ctx,
        )
    )
    dates = pd.to_datetime(df["snapshot_date"], errors="coerce")
    non_quarter = dates.notna() & ~dates.dt.is_quarter_end
    findings.extend(
        finding_rows(
            df,
            non_quarter,
            "CONS-EXP-004",
            "Snapshot date is not a calendar quarter end.",
            "snapshot_date",
            ctx,
        )
    )
    if "default_flag" in df.columns:
        findings.extend(
            finding_rows(
                df,
                df["default_flag"].isna(),
                "CONS-EXP-005",
                "Default flag could not be interpreted.",
                "default_flag",
                ctx,
            )
        )
    return findings


def check_rating_history(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings = _unknown_bank(df, ctx, "CONS-RAT-001")
    findings.extend(_invalid_rating(df, ctx, "CONS-RAT-002"))
    findings.extend(_relationship(df, ctx, "CONS-RAT-003", "CONS-RAT-004"))
    return findings


def check_collateral(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings = _unknown_bank(df, ctx, "CONS-COL-001")
    currency_mask = ~missing_mask(df["currency"]) & (df["currency"] != CURRENCY)
    findings.extend(
        finding_rows(
            df,
            currency_mask,
            "CONS-COL-002",
            f"Collateral currency is not the configured reporting currency {CURRENCY}.",
            "currency",
            ctx,
        )
    )
    findings.extend(_relationship(df, ctx, "CONS-COL-003", "CONS-COL-004"))
    return findings


def check_recovery_cashflows(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings = _unknown_bank(df, ctx, "CONS-REC-001")
    findings.extend(_relationship(df, ctx, "CONS-REC-002", "CONS-REC-003"))
    return findings
