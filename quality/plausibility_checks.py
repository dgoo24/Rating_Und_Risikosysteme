"""Plausibility and value-range checks, including recovery/EAD consistency."""
from __future__ import annotations

import pandas as pd

from config.settings import COLLATERAL_VALUATION_WARNING_YEARS
from quality.context import ValidationContext
from quality.findings import finding_rows, future_mask, missing_mask, stale_mask


def _non_negative(
    df: pd.DataFrame,
    field_name: str,
    rule_id: str,
    ctx: ValidationContext,
    reason: str,
) -> list[dict[str, object]]:
    values = pd.to_numeric(df[field_name], errors="coerce")
    return finding_rows(df, values.notna() & (values < 0), rule_id, reason, field_name, ctx)


def check_exposures(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings = _non_negative(df, "exposure_at_default", "PLAUS-EXP-001", ctx, "Exposure at default is negative.")
    findings.extend(
        _non_negative(df, "outstanding_balance", "PLAUS-EXP-002", ctx, "Outstanding balance is negative.")
    )
    origination = pd.to_datetime(df["origination_date"], errors="coerce")
    maturity = pd.to_datetime(df["maturity_date"], errors="coerce")
    findings.extend(
        finding_rows(
            df,
            origination.notna() & maturity.notna() & (maturity < origination),
            "PLAUS-EXP-003",
            "Maturity date is before origination date.",
            "maturity_date",
            ctx,
        )
    )
    snapshot = pd.to_datetime(df["snapshot_date"], errors="coerce")
    findings.extend(
        finding_rows(
            df,
            origination.notna() & snapshot.notna() & (origination > snapshot),
            "PLAUS-EXP-004",
            "Origination date is after the reporting snapshot date.",
            "origination_date",
            ctx,
        )
    )
    default_date = pd.to_datetime(df["default_date"], errors="coerce")
    findings.extend(
        finding_rows(
            df,
            origination.notna() & default_date.notna() & (default_date < origination),
            "PLAUS-EXP-005",
            "Default date is before origination date.",
            "default_date",
            ctx,
        )
    )
    findings.extend(
        finding_rows(
            df,
            future_mask(df["snapshot_date"], pd.Timestamp(ctx.execution_timestamp).normalize()),
            "PLAUS-EXP-006",
            "Snapshot date lies in the future relative to the import.",
            "snapshot_date",
            ctx,
        )
    )
    # .where instead of .fillna avoids pandas' object-dtype downcasting warning.
    flag = df["default_flag"].where(df["default_flag"].notna(), False).astype(bool)
    findings.extend(
        finding_rows(
            df,
            flag & default_date.isna(),
            "PLAUS-EXP-007",
            "Default flag is true but no default date is available.",
            "default_date",
            ctx,
        )
    )
    findings.extend(
        finding_rows(
            df,
            ~flag & default_date.notna(),
            "PLAUS-EXP-008",
            "Default date is populated although the record is flagged as performing.",
            "default_flag",
            ctx,
        )
    )
    return findings


def check_rating_history(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    return finding_rows(
        df,
        future_mask(df["observation_date"], pd.Timestamp(ctx.execution_timestamp).normalize()),
        "PLAUS-RAT-001",
        "Rating observation date lies in the future relative to the import.",
        "observation_date",
        ctx,
    )


def check_collateral(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings = _non_negative(df, "collateral_value", "PLAUS-COL-001", ctx, "Collateral value is negative.")
    reference = pd.Timestamp(ctx.execution_timestamp).normalize()
    findings.extend(
        finding_rows(
            df,
            future_mask(df["valuation_date"], reference),
            "PLAUS-COL-002",
            "Collateral valuation date lies in the future.",
            "valuation_date",
            ctx,
        )
    )
    findings.extend(
        finding_rows(
            df,
            stale_mask(df["valuation_date"], reference, COLLATERAL_VALUATION_WARNING_YEARS),
            "PLAUS-COL-003",
            f"Collateral valuation is older than {COLLATERAL_VALUATION_WARNING_YEARS} years.",
            "valuation_date",
            ctx,
        )
    )
    return findings


def _recovery_over_ead(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    required = ["exposure_id", "payment_date", "recovery_amount"]
    if any(column not in df.columns for column in required) or df.empty:
        return []
    working = df.copy()
    working["_amount"] = pd.to_numeric(working["recovery_amount"], errors="coerce")
    working = working.sort_values(["exposure_id", "payment_date"], kind="stable")
    flagged: set[int] = set()
    for exposure_id, group in working.groupby("exposure_id", dropna=True):
        ead = ctx.exposure_ead_map.get(str(exposure_id))
        if ead is None or ead <= 0:
            continue
        cumulative = float(ctx.existing_recovery_by_exposure.get(str(exposure_id), 0.0))
        for index, row in group.iterrows():
            amount = row["_amount"]
            if pd.isna(amount):
                continue
            if amount > 0:
                cumulative += float(amount)
            explained = row.get("adjustment_reason")
            has_reason = explained is not None and not pd.isna(explained) and str(explained).strip() != ""
            if cumulative > ead + 0.01 and not has_reason:
                flagged.add(int(index))
    if not flagged:
        return []
    mask = pd.Series(False, index=df.index)
    mask.loc[list(flagged)] = True
    return finding_rows(
        df,
        mask,
        "PLAUS-REC-003",
        "Cumulative recoveries exceed exposure at default and no adjustment reason is documented.",
        "recovery_amount",
        ctx,
    )


def check_recovery_cashflows(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings = _non_negative(df, "recovery_amount", "PLAUS-REC-001", ctx, "Recovery amount is negative.")
    findings.extend(
        finding_rows(
            df,
            future_mask(df["payment_date"], pd.Timestamp(ctx.execution_timestamp).normalize()),
            "PLAUS-REC-002",
            "Recovery payment date lies in the future.",
            "payment_date",
            ctx,
        )
    )
    findings.extend(_recovery_over_ead(df, ctx))
    return findings
