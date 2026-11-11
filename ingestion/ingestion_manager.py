"""Ingestion orchestration: RAW -> STAGING -> DATA QUALITY -> CURATED."""
from __future__ import annotations

import hashlib
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import duckdb
import numpy as np
import pandas as pd

from config.institutions import INSTITUTIONS as CONFIG_INSTITUTIONS
from config.models import IngestionBatchMetadata, Institution
from config.settings import DB_PATH, RAW_DIR
from config.source_catalog import INSTITUTIONS_FILE, SOURCE_CATALOG, SourceFile
from database.connection import initialize_database, insert_dataframe, utc_now
from etl.pipeline_logger import get_logger, log_event
from etl.transformations import standardize_frame
from ingestion.adapters import adapter_for
from ingestion.source_mapping import DATE_FIELDS, FIELDS_BY_DATASET, mapping_for
from quality.context import ValidationContext
from quality.rules import seed_rule_catalog
from quality.validation_engine import load_outcome

LOGGER = get_logger()

DATASET_ORDER = {"exposures": 0, "rating_history": 1, "collateral": 2, "recovery_cashflows": 3}
DATE_FIELD = {
    "exposures": "snapshot_date",
    "rating_history": "observation_date",
    "collateral": "valuation_date",
    "recovery_cashflows": "payment_date",
}
STAGING_TABLE = {
    "exposures": "staging_exposures",
    "rating_history": "staging_rating_history",
    "collateral": "staging_collateral",
    "recovery_cashflows": "staging_recovery_cashflows",
}


class IngestionError(RuntimeError):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}-{utc_now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8].upper()}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bank_name(con: duckdb.DuckDBPyConnection, bank_id: str) -> str:
    row = con.execute("SELECT bank_name FROM institutions WHERE bank_id = ?", [bank_id]).fetchone()
    if row:
        return str(row[0])
    for institution in CONFIG_INSTITUTIONS:
        if institution.bank_id == bank_id:
            return institution.bank_name
    return bank_id


def load_institutions(con: duckdb.DuckDBPyConnection) -> int:
    """Load and validate the institution reference file."""
    if INSTITUTIONS_FILE.exists():
        frame = pd.read_csv(INSTITUTIONS_FILE, dtype=str)
        records = [Institution.model_validate(row.to_dict()).model_dump() for _, row in frame.iterrows()]
    else:
        records = [
            Institution(
                bank_id=inst.bank_id,
                bank_name=inst.bank_name,
                region=inst.region,
                peer_group=inst.peer_group,
            ).model_dump()
            for inst in CONFIG_INSTITUTIONS
        ]
    frame = pd.DataFrame(records)
    con.execute("DELETE FROM institutions")
    insert_dataframe(con, frame, "institutions", columns=("bank_id", "bank_name", "region", "peer_group"))
    log_event("institutions_loaded", institutions=len(frame))
    return len(frame)


def _reporting_date(mapped: pd.DataFrame, dataset_type: str, import_timestamp: datetime) -> date:
    field = DATE_FIELD[dataset_type]
    values = pd.to_datetime(mapped[field], errors="coerce")
    limit = pd.Timestamp(import_timestamp).normalize()
    valid = values[values.notna() & (values <= limit)]
    if valid.empty:
        return date.today()
    return valid.max().date()


def _insert_batch(
    con: duckdb.DuckDBPyConnection,
    batch_id: str,
    source: SourceFile,
    bank_name: str,
    reporting_date: date,
    import_timestamp: datetime,
    file_hash: str,
    pipeline_run_id: str,
    status: str = "PROCESSING",
) -> None:
    metadata = IngestionBatchMetadata(
        batch_id=batch_id,
        bank_id=source.bank_id,
        bank_name=bank_name,
        reporting_date=reporting_date,
        source_system=source.source_system,
        dataset_type=source.dataset_type,  # type: ignore[arg-type]
        source_file=str(source.path),
        import_timestamp=import_timestamp,
        status=status,
        pipeline_run_id=pipeline_run_id,
        file_hash=file_hash,
    )
    con.execute(
        """
        INSERT INTO ingestion_batches
        (batch_id, bank_id, bank_name, reporting_date, source_system, dataset_type,
         source_file, import_timestamp, status, pipeline_run_id, file_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            metadata.batch_id, metadata.bank_id, metadata.bank_name, metadata.reporting_date,
            metadata.source_system, metadata.dataset_type, metadata.source_file,
            metadata.import_timestamp, metadata.status, metadata.pipeline_run_id, metadata.file_hash,
        ],
    )


def _update_batch(con: duckdb.DuckDBPyConnection, batch_id: str, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{name} = ?" for name in fields)
    con.execute(f"UPDATE ingestion_batches SET {assignments} WHERE batch_id = ?", [*fields.values(), batch_id])


def _archive_raw(raw: pd.DataFrame, source: SourceFile, batch_id: str) -> Path:
    archive_dir = RAW_DIR / batch_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = archive_dir / f"{source.dataset_type}_raw.parquet"
    raw.to_parquet(parquet_path, index=False)
    if source.adapter != "duckdb" and source.path.exists():
        shutil.copy2(source.path, archive_dir / source.path.name)
    return parquet_path


def _staging_frame(mapped: pd.DataFrame, source: SourceFile, batch_id: str) -> pd.DataFrame:
    staging = mapped.reset_index(drop=True).copy()
    staging.insert(0, "staging_row_number", np.arange(1, len(staging) + 1))
    staging.insert(0, "batch_id", batch_id)
    return staging


def _key_set(frame: pd.DataFrame, fields: Iterable[str]) -> set[tuple[str, ...]]:
    key_fields = list(fields)
    result: set[tuple[str, ...]] = set()
    for _, row in frame.iterrows():
        values: list[str] = []
        complete = True
        for field in key_fields:
            value = row[field]
            if value is None or pd.isna(value):
                complete = False
                break
            values.append(pd.Timestamp(value).strftime("%Y-%m-%d") if isinstance(value, (pd.Timestamp, datetime, date)) else str(value))
        if complete:
            result.add(tuple(values))
    return result


def build_validation_context(
    con: duckdb.DuckDBPyConnection,
    source: SourceFile,
    batch_id: str,
    reporting_date: date,
    execution_timestamp: datetime,
) -> ValidationContext:
    ref_ids = {row[0] for row in con.execute("SELECT bank_id FROM institutions").fetchall()}

    exposures_frame = con.execute("SELECT exposure_id, bank_id, snapshot_date, exposure_at_default FROM exposures").df()
    exposure_bank_map = (
        exposures_frame.drop_duplicates("exposure_id").set_index("exposure_id")["bank_id"].astype(str).to_dict()
        if not exposures_frame.empty
        else {}
    )
    exposure_ead_map = (
        exposures_frame.groupby("exposure_id")["exposure_at_default"].max().fillna(0.0).astype(float).to_dict()
        if not exposures_frame.empty
        else {}
    )
    existing_exposure_keys = _key_set(exposures_frame, ("exposure_id", "snapshot_date")) if not exposures_frame.empty else set()

    rating_frame = con.execute("SELECT exposure_id, observation_date FROM rating_history").df()
    existing_rating_keys = _key_set(rating_frame, ("exposure_id", "observation_date")) if not rating_frame.empty else set()

    collateral_frame = con.execute("SELECT collateral_id, valuation_date FROM collateral").df()
    existing_collateral_keys = _key_set(collateral_frame, ("collateral_id", "valuation_date")) if not collateral_frame.empty else set()

    cashflow_frame = con.execute("SELECT cashflow_id, exposure_id, recovery_amount FROM recovery_cashflows").df()
    existing_cashflow_ids = set(cashflow_frame["cashflow_id"].astype(str)) if not cashflow_frame.empty else set()
    existing_recovery_by_exposure = (
        cashflow_frame.groupby("exposure_id")["recovery_amount"].sum().fillna(0.0).astype(float).to_dict()
        if not cashflow_frame.empty
        else {}
    )

    return ValidationContext(
        batch_id=batch_id,
        dataset_type=source.dataset_type,
        bank_id=source.bank_id,
        reporting_date=reporting_date,
        execution_timestamp=execution_timestamp,
        reference_bank_ids=ref_ids,
        existing_exposure_keys=existing_exposure_keys,
        existing_rating_keys=existing_rating_keys,
        existing_collateral_keys=existing_collateral_keys,
        existing_cashflow_ids=existing_cashflow_ids,
        exposure_bank_map=exposure_bank_map,
        exposure_ead_map=exposure_ead_map,
        existing_recovery_by_exposure=existing_recovery_by_exposure,
    )


def ingest_source(
    con: duckdb.DuckDBPyConnection,
    source: SourceFile,
    pipeline_run_id: str,
    force: bool = False,
) -> dict[str, Any]:
    batch_id = _new_id("BATCH")
    import_timestamp = utc_now()
    bank_name = _bank_name(con, source.bank_id)
    LOGGER.info("Ingesting %s/%s from %s", source.bank_id, source.dataset_type, source.filename)
    log_event("batch_started", batch_id=batch_id, bank_id=source.bank_id, dataset_type=source.dataset_type)

    if not source.path.exists():
        raise IngestionError(f"Source not found: {source.path}")

    adapter = adapter_for(source.adapter)
    raw = adapter.read(source)
    file_hash = _sha256(source.path)
    reporting_date = date.today()
    _insert_batch(con, batch_id, source, bank_name, reporting_date, import_timestamp, file_hash, pipeline_run_id)

    try:
        raw_archive = _archive_raw(raw, source, batch_id)
        mapping = mapping_for(source.bank_id, source.dataset_type)
        mapped = standardize_frame(raw, mapping)
        reporting_date = _reporting_date(mapped, source.dataset_type, import_timestamp)
        _update_batch(con, batch_id, reporting_date=reporting_date, raw_archive_path=str(raw_archive))

        seen = con.execute(
            """
            SELECT batch_id FROM ingestion_batches
            WHERE file_hash = ? AND bank_id = ? AND dataset_type = ?
              AND status = 'COMPLETED' AND batch_id <> ?
            ORDER BY import_timestamp DESC LIMIT 1
            """,
            [file_hash, source.bank_id, source.dataset_type, batch_id],
        ).fetchone()
        if seen and not force:
            _update_batch(
                con,
                batch_id,
                status="SKIPPED_DUPLICATE",
                error_message=f"Identical source file already imported in batch {seen[0]}",
            )
            log_event("batch_skipped_duplicate", batch_id=batch_id, prior_batch=seen[0])
            LOGGER.info("Skipped duplicate source %s (prior batch %s)", source.filename, seen[0])
            return {
                "batch_id": batch_id,
                "bank_id": source.bank_id,
                "dataset_type": source.dataset_type,
                "status": "SKIPPED_DUPLICATE",
                "rows_received": 0,
                "rows_valid": 0,
                "rows_rejected": 0,
                "quality_score": None,
            }

        staging = _staging_frame(mapped, source, batch_id)
        staging_columns = ["batch_id", "staging_row_number", *FIELDS_BY_DATASET[source.dataset_type]]
        insert_dataframe(
            con,
            staging,
            STAGING_TABLE[source.dataset_type],
            columns=staging_columns,
            date_columns=DATE_FIELDS[source.dataset_type],
            registration_name="_staging_df",
        )

        context = build_validation_context(con, source, batch_id, reporting_date, import_timestamp)
        outcome = load_outcome(con, mapped, context)
        _update_batch(
            con,
            batch_id,
            status="COMPLETED",
            rows_received=outcome.rows_received,
            rows_valid=outcome.rows_valid,
            rows_rejected=outcome.rows_rejected,
            rows_warned=outcome.rows_warned,
            quality_score=outcome.quality_score,
            error_message=None,
        )
        result = {
            "batch_id": batch_id,
            "bank_id": source.bank_id,
            "dataset_type": source.dataset_type,
            "status": "COMPLETED",
            "rows_received": outcome.rows_received,
            "rows_valid": outcome.rows_valid,
            "rows_rejected": outcome.rows_rejected,
            "rows_warned": outcome.rows_warned,
            "quality_score": outcome.quality_score,
        }
        log_event("batch_completed", **result)
        LOGGER.info(
            "Completed %s: %s valid / %s received, %s rejected, score %.2f",
            batch_id, outcome.rows_valid, outcome.rows_received, outcome.rows_rejected, outcome.quality_score,
        )
        return result
    except Exception as exc:
        _update_batch(con, batch_id, status="FAILED", error_message=str(exc)[:2000])
        log_event("batch_failed", batch_id=batch_id, bank_id=source.bank_id, dataset_type=source.dataset_type, error=str(exc))
        LOGGER.error("Batch %s failed: %s", batch_id, exc)
        raise IngestionError(str(exc)) from exc


def run_pipeline(
    bank_ids: list[str] | None = None,
    dataset_types: list[str] | None = None,
    force: bool = False,
    reset_db: bool = False,
) -> dict[str, Any]:
    """Run all configured sources and record the pipeline execution."""
    initialize_database(reset=reset_db)
    pipeline_run_id = _new_id("RUN")
    started_at = utc_now()
    log_event("pipeline_started", pipeline_run_id=pipeline_run_id, reset_db=reset_db)
    con = duckdb.connect(str(DB_PATH))
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    try:
        seed_rule_catalog(con)
        load_institutions(con)
        con.execute(
            """
            INSERT INTO pipeline_runs (pipeline_run_id, started_at, status, environment)
            VALUES (?, ?, 'RUNNING', 'local-duckdb')
            """,
            [pipeline_run_id, started_at],
        )
        sources = sorted(
            SOURCE_CATALOG,
            key=lambda source: (DATASET_ORDER[source.dataset_type], source.bank_id),
        )
        if bank_ids:
            sources = [source for source in sources if source.bank_id in bank_ids]
        if dataset_types:
            sources = [source for source in sources if source.dataset_type in dataset_types]

        for source in sources:
            if not source.path.exists():
                LOGGER.warning("Source unavailable, skipping: %s", source.path)
                failures.append({"source": str(source.path), "error": "File not found"})
                continue
            try:
                results.append(ingest_source(con, source, pipeline_run_id, force=force))
            except Exception as exc:  # continue with independent sources
                failures.append({"source": str(source.path), "error": str(exc)})

        totals = {
            "batches_attempted": len(results) + len(failures),
            "batches_completed": sum(1 for result in results if result["status"] == "COMPLETED"),
            "rows_received": int(sum(result["rows_received"] for result in results)),
            "rows_valid": int(sum(result["rows_valid"] for result in results)),
            "rows_rejected": int(sum(result["rows_rejected"] for result in results)),
        }
        final_status = "FAILED" if failures and not results else ("PARTIAL" if failures else "COMPLETED")
        finished_at = utc_now()
        con.execute(
            """
            UPDATE pipeline_runs
            SET finished_at = ?, status = ?, batches_attempted = ?, batches_completed = ?,
                rows_received = ?, rows_valid = ?, rows_rejected = ?, notes = ?
            WHERE pipeline_run_id = ?
            """,
            [
                finished_at, final_status, totals["batches_attempted"], totals["batches_completed"],
                totals["rows_received"], totals["rows_valid"], totals["rows_rejected"],
                "; ".join(f"{failure['source']}: {failure['error']}" for failure in failures)[:4000] or None,
                pipeline_run_id,
            ],
        )
        summary = {
            "pipeline_run_id": pipeline_run_id,
            "status": final_status,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "batches": results,
            "failures": failures,
            **totals,
        }
        log_event("pipeline_completed", pipeline_run_id=pipeline_run_id, status=final_status, **totals)
        return summary
    finally:
        con.close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the automated ingestion and data-quality pipeline")
    parser.add_argument("--force", action="store_true", help="Reprocess sources even if the same file was imported before")
    parser.add_argument("--reset-db", action="store_true", help="Recreate the local DuckDB database before ingestion")
    parser.add_argument("--bank", action="append", help="Optional bank filter (repeatable)")
    parser.add_argument("--dataset", action="append", help="Optional dataset_type filter (repeatable)")
    args = parser.parse_args()
    summary = run_pipeline(
        bank_ids=args.bank,
        dataset_types=args.dataset,
        force=args.force,
        reset_db=args.reset_db,
    )
    print("\nPipeline summary")
    print(f"  Run ID   : {summary['pipeline_run_id']}")
    print(f"  Status   : {summary['status']}")
    print(f"  Batches  : {summary['batches_attempted']} attempted, {summary['batches_completed']} completed")
    print(f"  Rows     : {summary['rows_received']:,} received, {summary['rows_valid']:,} valid, {summary['rows_rejected']:,} rejected")
    if summary["failures"]:
        print("\nFailures:")
        for failure in summary["failures"]:
            print(f"  - {failure['source']}: {failure['error']}")
    print("\nNext: streamlit run app.py")


if __name__ == "__main__":
    main()
