"""Aggregations for data-quality dashboards and reports."""
from __future__ import annotations

import pandas as pd


def quality_score(received: float, valid: float) -> float:
    return round(100.0 * valid / received, 2) if received else 0.0


def overall_quality_score(batches: pd.DataFrame) -> float:
    if batches.empty:
        return 0.0
    completed = batches[batches["status"] == "COMPLETED"]
    return quality_score(completed["rows_received"].sum(), completed["rows_valid"].sum())


def quality_by_bank(batches: pd.DataFrame, findings: pd.DataFrame) -> pd.DataFrame:
    if batches.empty:
        return pd.DataFrame(
            columns=["bank_id", "batches", "rows_received", "rows_valid", "rows_rejected", "quality_score", "error_findings", "warning_findings"]
        )
    completed = batches[batches["status"] == "COMPLETED"]
    base = (
        completed.groupby("bank_id", as_index=False)
        .agg(
            batches=("batch_id", "nunique"),
            rows_received=("rows_received", "sum"),
            rows_valid=("rows_valid", "sum"),
            rows_rejected=("rows_rejected", "sum"),
        )
    )
    base["quality_score"] = [
        quality_score(received, valid)
        for received, valid in zip(base["rows_received"], base["rows_valid"])
    ]
    if findings.empty:
        base["error_findings"] = 0
        base["warning_findings"] = 0
    else:
        errors = findings[findings["severity"] == "ERROR"].groupby("bank_id").size().rename("error_findings")
        warnings = findings[findings["severity"] == "WARNING"].groupby("bank_id").size().rename("warning_findings")
        base = base.merge(errors, on="bank_id", how="left").merge(warnings, on="bank_id", how="left")
        base[["error_findings", "warning_findings"]] = base[["error_findings", "warning_findings"]].fillna(0).astype(int)
    return base.sort_values("bank_id").reset_index(drop=True)


def quality_by_period(findings: pd.DataFrame) -> pd.DataFrame:
    if findings.empty:
        return pd.DataFrame(columns=["reporting_date", "bank_id", "errors", "warnings", "affected_records"])
    summary = (
        findings.assign(
            errors=(findings["severity"] == "ERROR").astype(int),
            warnings=(findings["severity"] == "WARNING").astype(int),
        )
        .groupby(["reporting_date", "bank_id"], as_index=False)
        .agg(errors=("errors", "sum"), warnings=("warnings", "sum"), affected_records=("record_id", "nunique"))
    )
    return summary.sort_values(["reporting_date", "bank_id"], ascending=[False, True]).reset_index(drop=True)


def quality_by_category(findings: pd.DataFrame) -> pd.DataFrame:
    if findings.empty:
        return pd.DataFrame(columns=["category", "severity", "findings", "affected_records"])
    return (
        findings.groupby(["category", "severity"], as_index=False)
        .agg(findings=("quality_result_id", "count"), affected_records=("record_id", "nunique"))
        .sort_values(["findings"], ascending=False)
        .reset_index(drop=True)
    )


def quality_by_rule(findings: pd.DataFrame) -> pd.DataFrame:
    if findings.empty:
        return pd.DataFrame(columns=["rule_id", "rule_name", "dataset_type", "category", "severity", "findings", "affected_records"])
    return (
        findings.groupby(["rule_id", "rule_name", "dataset_type", "category", "severity"], as_index=False)
        .agg(findings=("quality_result_id", "count"), affected_records=("record_id", "nunique"))
        .sort_values(["severity", "findings"], ascending=[True, False])
        .reset_index(drop=True)
    )


def quarantine_summary(quarantine: pd.DataFrame) -> pd.DataFrame:
    if quarantine.empty:
        return pd.DataFrame(columns=["bank_id", "dataset_type", "quarantined_records"])
    return (
        quarantine.groupby(["bank_id", "dataset_type"], as_index=False)
        .agg(quarantined_records=("quarantine_id", "nunique"))
        .sort_values("quarantined_records", ascending=False)
        .reset_index(drop=True)
    )
