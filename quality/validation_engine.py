"""Data-quality validation engine and quarantine/curated loading."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

import duckdb
import pandas as pd

from database.connection import insert_dataframe
from quality.completeness_checks import (
    check_collateral,
    check_exposures,
    check_rating_history,
    check_recovery_cashflows,
)
from quality.consistency_checks import (
    check_collateral as check_collateral_consistency,
)
from quality.consistency_checks import (
    check_exposures as check_exposures_consistency,
)
from quality.consistency_checks import (
    check_rating_history as check_rating_history_consistency,
)
from quality.consistency_checks import (
    check_recovery_cashflows as check_recovery_consistency,
)
from quality.context import ValidationContext
from quality.plausibility_checks import (
    check_collateral as check_collateral_plausibility,
)
from quality.plausibility_checks import (
    check_exposures as check_exposures_plausibility,
)
from quality.plausibility_checks import (
    check_rating_history as check_rating_history_plausibility,
)
from quality.plausibility_checks import (
    check_recovery_cashflows as check_recovery_plausibility,
)
from quality.rules import RULE_BY_ID
from quality.uniqueness_checks import (
    check_collateral as check_collateral_uniqueness,
)
from quality.uniqueness_checks import (
    check_exposures as check_exposures_uniqueness,
)
from quality.uniqueness_checks import (
    check_rating_history as check_rating_history_uniqueness,
)
from quality.uniqueness_checks import (
    check_recovery_cashflows as check_recovery_uniqueness,
)

CheckFunction = Callable[[pd.DataFrame, ValidationContext], list[dict[str, object]]]

CHECKS: dict[str, tuple[CheckFunction, ...]] = {
    "exposures": (
        check_exposures,
        check_exposures_uniqueness,
        check_exposures_consistency,
        check_exposures_plausibility,
    ),
    "rating_history": (
        check_rating_history,
        check_rating_history_uniqueness,
        check_rating_history_consistency,
        check_rating_history_plausibility,
    ),
    "collateral": (
        check_collateral,
        check_collateral_uniqueness,
        check_collateral_consistency,
        check_collateral_plausibility,
    ),
    "recovery_cashflows": (
        check_recovery_cashflows,
        check_recovery_uniqueness,
        check_recovery_consistency,
        check_recovery_plausibility,
    ),
}

DATE_FIELD = {
    "exposures": "snapshot_date",
    "rating_history": "observation_date",
    "collateral": "valuation_date",
    "recovery_cashflows": "payment_date",
}
CURATED_TABLE = {
    "exposures": "exposures",
    "rating_history": "rating_history",
    "collateral": "collateral",
    "recovery_cashflows": "recovery_cashflows",
}
CURATED_COLUMNS = {
    "exposures": (
        "exposure_id", "bank_id", "customer_id", "snapshot_date", "product_type",
        "industry_sector", "region", "rating_grade", "exposure_at_default",
        "outstanding_balance", "currency", "origination_date", "maturity_date",
        "default_flag", "default_date", "batch_id",
    ),
    "rating_history": ("exposure_id", "bank_id", "observation_date", "rating_grade", "batch_id"),
    "collateral": (
        "collateral_id", "exposure_id", "bank_id", "collateral_type", "collateral_value",
        "valuation_date", "currency", "batch_id",
    ),
    "recovery_cashflows": (
        "cashflow_id", "exposure_id", "bank_id", "payment_date", "recovery_amount",
        "recovery_type", "adjustment_reason", "batch_id",
    ),
}
DATE_COLUMNS = {
    "exposures": ("snapshot_date", "origination_date", "maturity_date", "default_date"),
    "rating_history": ("observation_date",),
    "collateral": ("valuation_date",),
    "recovery_cashflows": ("payment_date",),
}


@dataclass
class ValidationOutcome:
    batch_id: str
    dataset_type: str
    rows_received: int
    rows_valid: int
    rows_rejected: int
    rows_warned: int
    quality_score: float
    findings: pd.DataFrame
    valid_rows: pd.DataFrame
    rejected_rows: pd.DataFrame


def _json_default(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _record_json(row: pd.Series) -> str:
    payload = {}
    for key, value in row.to_dict().items():
        if str(key).startswith("_"):
            continue
        payload[str(key)] = _json_default(value)
    return json.dumps(payload, ensure_ascii=False)


def evaluate_findings(df: pd.DataFrame, ctx: ValidationContext) -> pd.DataFrame:
    """Execute all checks and enrich findings with rule and traceability metadata."""
    working = df.reset_index(drop=True)
    raw_findings: list[dict[str, object]] = []
    for check in CHECKS[ctx.dataset_type]:
        raw_findings.extend(check(working, ctx))

    if not raw_findings:
        return pd.DataFrame(
            columns=[
                "quality_result_id", "batch_id", "dataset_type", "bank_id", "reporting_date",
                "record_id", "rule_id", "rule_name", "category", "severity", "field_name",
                "failed_value", "reason", "execution_timestamp", "row_index",
            ]
        )

    findings = pd.DataFrame(raw_findings)
    findings["row_index"] = findings["row_index"].astype(int)
    metadata = findings["rule_id"].map(
        lambda rule_id: RULE_BY_ID.get(rule_id)  # type: ignore[arg-type]
    )
    if metadata.isna().any():
        missing = sorted(set(findings.loc[metadata.isna(), "rule_id"]))
        raise KeyError(f"Unknown validation rule(s): {missing}")
    findings["rule_name"] = metadata.map(lambda rule: rule.rule_name)
    findings["category"] = metadata.map(lambda rule: rule.category)
    findings["severity"] = metadata.map(lambda rule: rule.severity)

    date_column = DATE_FIELD[ctx.dataset_type]
    record_dates = pd.to_datetime(working[date_column], errors="coerce").fillna(
        pd.Timestamp(ctx.reporting_date)
    ).dt.date
    record_banks = working["bank_id"].where(working["bank_id"].notna(), ctx.bank_id)
    findings["bank_id"] = findings["row_index"].map(record_banks)
    findings["reporting_date"] = findings["row_index"].map(record_dates)
    findings["batch_id"] = ctx.batch_id
    findings["dataset_type"] = ctx.dataset_type
    findings["execution_timestamp"] = pd.Timestamp(ctx.execution_timestamp)
    findings["quality_result_id"] = [f"QR-{uuid.uuid4().hex}" for _ in findings.index]
    return findings


def _quarantine_frame(rejected: pd.DataFrame, findings: pd.DataFrame, ctx: ValidationContext) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    error_findings = findings[findings["severity"] == "ERROR"]
    for row_index, record in rejected.iterrows():
        related = error_findings[error_findings["row_index"] == row_index]
        unique_reasons: list[str] = []
        for reason in related["reason"].tolist():
            if reason not in unique_reasons:
                unique_reasons.append(reason)
        records.append(
            {
                "quarantine_id": f"Q-{uuid.uuid4().hex}",
                "batch_id": ctx.batch_id,
                "dataset_type": ctx.dataset_type,
                "bank_id": record.get("bank_id") if pd.notna(record.get("bank_id")) else ctx.bank_id,
                "reporting_date": pd.to_datetime(record.get(DATE_FIELD[ctx.dataset_type]), errors="coerce").date()
                if pd.notna(record.get(DATE_FIELD[ctx.dataset_type]))
                else ctx.reporting_date,
                "record_id": str(related.iloc[0]["record_id"]) if not related.empty else None,
                "rule_ids": ", ".join(sorted(set(related["rule_id"].astype(str).tolist()))),
                "severity": "ERROR",
                "reason": " | ".join(unique_reasons[:5]),
                "record_json": _record_json(record),
                "quarantined_at": pd.Timestamp(ctx.execution_timestamp),
            }
        )
    return pd.DataFrame(records)


def load_outcome(
    con: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    ctx: ValidationContext,
) -> ValidationOutcome:
    """Run validation, persist findings/quarantine and insert only valid records."""
    working = df.reset_index(drop=True)
    findings = evaluate_findings(working, ctx)
    error_rows = set(findings.loc[findings["severity"] == "ERROR", "row_index"].tolist())
    warning_rows = set(findings.loc[findings["severity"] == "WARNING", "row_index"].tolist())

    valid_rows = working.loc[~working.index.isin(error_rows)].copy()
    rejected_rows = working.loc[working.index.isin(error_rows)].copy()
    retained_warning_rows = warning_rows - error_rows
    score = round(100.0 * len(valid_rows) / len(working), 2) if len(working) else 0.0

    result_columns = [
        "quality_result_id", "batch_id", "dataset_type", "bank_id", "reporting_date",
        "record_id", "rule_id", "rule_name", "category", "severity", "field_name",
        "failed_value", "reason", "execution_timestamp",
    ]
    if not findings.empty:
        insert_dataframe(
            con,
            findings,
            "quality_results",
            columns=result_columns,
            date_columns=("reporting_date",),
            registration_name="_quality_results",
        )
        quarantine = _quarantine_frame(rejected_rows, findings, ctx)
        if not quarantine.empty:
            insert_dataframe(
                con,
                quarantine,
                "quarantine_records",
                columns=(
                    "quarantine_id", "batch_id", "dataset_type", "bank_id", "reporting_date",
                    "record_id", "rule_ids", "severity", "reason", "record_json", "quarantined_at",
                ),
                date_columns=("reporting_date",),
                registration_name="_quarantine",
            )

    if not valid_rows.empty:
        valid_rows = valid_rows.copy()
        valid_rows["batch_id"] = ctx.batch_id
        insert_dataframe(
            con,
            valid_rows,
            CURATED_TABLE[ctx.dataset_type],
            columns=CURATED_COLUMNS[ctx.dataset_type],
            date_columns=DATE_COLUMNS[ctx.dataset_type],
            registration_name="_curated",
        )

    return ValidationOutcome(
        batch_id=ctx.batch_id,
        dataset_type=ctx.dataset_type,
        rows_received=len(working),
        rows_valid=len(valid_rows),
        rows_rejected=len(rejected_rows),
        rows_warned=len(retained_warning_rows),
        quality_score=score,
        findings=findings,
        valid_rows=valid_rows,
        rejected_rows=rejected_rows,
    )
