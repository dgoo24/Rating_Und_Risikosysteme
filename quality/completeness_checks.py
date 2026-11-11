"""Completeness checks for canonical datasets."""
from __future__ import annotations

import pandas as pd

from quality.context import ValidationContext
from quality.findings import finding_rows, missing_mask


def _required(
    df: pd.DataFrame,
    field_name: str,
    rule_id: str,
    ctx: ValidationContext,
    label: str | None = None,
) -> list[dict[str, object]]:
    mask = missing_mask(df[field_name])
    return finding_rows(
        df,
        mask,
        rule_id,
        f"Missing value in required field '{label or field_name}'.",
        field_name,
        ctx,
    )


def check_exposures(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    required = (
        ("exposure_id", "COMP-EXP-001", "exposure_id"),
        ("bank_id", "COMP-EXP-002", "bank_id"),
        ("snapshot_date", "COMP-EXP-003", "snapshot_date"),
        ("exposure_at_default", "COMP-EXP-004", "exposure_at_default"),
        ("rating_grade", "COMP-EXP-005", "rating_grade"),
        ("outstanding_balance", "COMP-EXP-006", "outstanding_balance"),
        ("customer_id", "COMP-EXP-007", "customer_id"),
    )
    for field_name, rule_id, label in required:
        findings.extend(_required(df, field_name, rule_id, ctx, label))
    return findings


def check_rating_history(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for field_name, rule_id in (
        ("exposure_id", "COMP-RAT-001"),
        ("bank_id", "COMP-RAT-002"),
        ("observation_date", "COMP-RAT-003"),
        ("rating_grade", "COMP-RAT-004"),
    ):
        findings.extend(_required(df, field_name, rule_id, ctx))
    return findings


def check_collateral(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for field_name, rule_id in (
        ("collateral_id", "COMP-COL-001"),
        ("exposure_id", "COMP-COL-002"),
        ("bank_id", "COMP-COL-003"),
        ("collateral_value", "COMP-COL-004"),
        ("valuation_date", "COMP-COL-005"),
        ("collateral_type", "COMP-COL-006"),
    ):
        findings.extend(_required(df, field_name, rule_id, ctx))
    return findings


def check_recovery_cashflows(df: pd.DataFrame, ctx: ValidationContext) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for field_name, rule_id in (
        ("cashflow_id", "COMP-REC-001"),
        ("exposure_id", "COMP-REC-002"),
        ("bank_id", "COMP-REC-003"),
        ("recovery_amount", "COMP-REC-004"),
        ("payment_date", "COMP-REC-005"),
        ("recovery_type", "COMP-REC-006"),
    ):
        findings.extend(_required(df, field_name, rule_id, ctx))
    return findings
