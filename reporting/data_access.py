"""Read-only data access helpers shared by dashboard and reporting."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.settings import DB_PATH
from database.connection import query_df


def database_exists(db_path: str | Path | None = None) -> bool:
    path = Path(db_path) if db_path is not None else DB_PATH
    return path.exists()


def load_table(table: str, db_path: str | Path | None = None) -> pd.DataFrame:
    if table not in {
        "institutions", "exposures", "rating_history", "collateral", "recovery_cashflows",
        "ingestion_batches", "pipeline_runs", "quality_results", "quarantine_records",
        "dq_rule_catalog", "report_log", "distribution_log",
    }:
        raise ValueError(f"Unsupported table: {table}")
    return query_df(f"SELECT * FROM {table}", db_path=db_path, read_only=True)


def load_institutions(db_path: str | Path | None = None) -> pd.DataFrame:
    return load_table("institutions", db_path)


def load_exposures(db_path: str | Path | None = None) -> pd.DataFrame:
    return load_table("exposures", db_path)


def load_rating_history(db_path: str | Path | None = None) -> pd.DataFrame:
    return load_table("rating_history", db_path)


def load_collateral(db_path: str | Path | None = None) -> pd.DataFrame:
    return load_table("collateral", db_path)


def load_recovery_cashflows(db_path: str | Path | None = None) -> pd.DataFrame:
    return load_table("recovery_cashflows", db_path)


def load_batches(db_path: str | Path | None = None) -> pd.DataFrame:
    frame = load_table("ingestion_batches", db_path)
    for column in ("reporting_date", "import_timestamp"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def load_pipeline_runs(db_path: str | Path | None = None) -> pd.DataFrame:
    frame = load_table("pipeline_runs", db_path)
    for column in ("started_at", "finished_at"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def load_quality_findings(db_path: str | Path | None = None) -> pd.DataFrame:
    frame = load_table("quality_results", db_path)
    if "reporting_date" in frame.columns:
        frame["reporting_date"] = pd.to_datetime(frame["reporting_date"], errors="coerce")
    return frame


def load_quarantine(db_path: str | Path | None = None) -> pd.DataFrame:
    frame = load_table("quarantine_records", db_path)
    if "reporting_date" in frame.columns:
        frame["reporting_date"] = pd.to_datetime(frame["reporting_date"], errors="coerce")
    return frame


def load_rule_catalog(db_path: str | Path | None = None) -> pd.DataFrame:
    return load_table("dq_rule_catalog", db_path)


def load_report_log(db_path: str | Path | None = None) -> pd.DataFrame:
    frame = load_table("report_log", db_path)
    if "reporting_date" in frame.columns:
        frame["reporting_date"] = pd.to_datetime(frame["reporting_date"], errors="coerce")
    if "generated_at" in frame.columns:
        frame["generated_at"] = pd.to_datetime(frame["generated_at"], errors="coerce")
    return frame


def load_distribution_log(db_path: str | Path | None = None) -> pd.DataFrame:
    frame = load_table("distribution_log", db_path)
    if "distributed_at" in frame.columns:
        frame["distributed_at"] = pd.to_datetime(frame["distributed_at"], errors="coerce")
    return frame


def reporting_dates(exposures: pd.DataFrame | None = None, db_path: str | Path | None = None) -> list[pd.Timestamp]:
    frame = exposures if exposures is not None else load_exposures(db_path)
    if frame.empty or "snapshot_date" not in frame.columns:
        return []
    dates = pd.to_datetime(frame["snapshot_date"], errors="coerce").dropna().dt.normalize().unique()
    return sorted(pd.Timestamp(value) for value in dates if pd.Timestamp(value).is_quarter_end)


def latest_reporting_date(db_path: str | Path | None = None) -> pd.Timestamp | None:
    dates = reporting_dates(db_path=db_path)
    return max(dates) if dates else None


def available_banks(db_path: str | Path | None = None) -> pd.DataFrame:
    institutions = load_institutions(db_path)
    return institutions.sort_values("bank_id").reset_index(drop=True)


def available_sectors(db_path: str | Path | None = None) -> list[str]:
    frame = query_df(
        "SELECT DISTINCT industry_sector FROM exposures WHERE industry_sector IS NOT NULL ORDER BY 1",
        db_path=db_path,
        read_only=True,
    )
    return frame["industry_sector"].astype(str).tolist()


def data_version_info(db_path: str | Path | None = None) -> dict[str, object]:
    runs = load_pipeline_runs(db_path)
    batches = load_batches(db_path)
    latest_run = None
    if not runs.empty:
        ordered = runs.sort_values("started_at", ascending=False)
        latest = ordered.iloc[0]
        latest_run = {
            "pipeline_run_id": latest.get("pipeline_run_id"),
            "status": latest.get("status"),
            "started_at": latest.get("started_at"),
            "finished_at": latest.get("finished_at"),
            "rows_received": latest.get("rows_received"),
            "rows_valid": latest.get("rows_valid"),
            "rows_rejected": latest.get("rows_rejected"),
        }
    completed = batches[batches["status"] == "COMPLETED"] if not batches.empty else batches
    return {
        "pipeline_run": latest_run,
        "batch_count": int(len(completed)),
        "rows_received": int(completed["rows_received"].sum()) if not completed.empty else 0,
        "rows_valid": int(completed["rows_valid"].sum()) if not completed.empty else 0,
        "rows_rejected": int(completed["rows_rejected"].sum()) if not completed.empty else 0,
        "latest_import": completed["import_timestamp"].max() if not completed.empty else None,
        "batch_ids": completed["batch_id"].astype(str).tolist() if not completed.empty else [],
    }


def load_all_inputs(db_path: str | Path | None = None) -> dict[str, pd.DataFrame]:
    return {
        "institutions": load_institutions(db_path),
        "exposures": load_exposures(db_path),
        "rating_history": load_rating_history(db_path),
        "collateral": load_collateral(db_path),
        "recovery_cashflows": load_recovery_cashflows(db_path),
        "batches": load_batches(db_path),
        "quality_findings": load_quality_findings(db_path),
        "quarantine": load_quarantine(db_path),
        "pipeline_runs": load_pipeline_runs(db_path),
        "rule_catalog": load_rule_catalog(db_path),
        "report_log": load_report_log(db_path),
        "distribution_log": load_distribution_log(db_path),
    }
