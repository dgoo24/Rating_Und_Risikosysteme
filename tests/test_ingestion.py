"""Tests for source adapters and the ingestion batch lifecycle.

The lifecycle test ingests a deliberately flawed CSV (invalid rating, duplicate
record, non-quarter-end snapshot with a missing recommended field) and checks
the documented outcome: 5 rows received, 2 rejected (ERROR), 3 valid,
1 row retained with warnings, quality score 60.0.
"""
from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from config.source_catalog import SourceFile
from ingestion.adapters import adapter_for
from ingestion.csv_adapter import CSVAdapter
from ingestion.database_adapter import DatabaseAdapter
from ingestion.excel_adapter import ExcelAdapter
from ingestion.ingestion_manager import (
    ingest_source,
    load_institutions,
)
from tests.conftest import EXPOSURE_COLUMNS

CSV_CONTENT = (
    "exposure_id,bank_id,customer_id,snapshot_date,product_type,industry_sector,region,"
    "rating_grade,exposure_at_default,outstanding_balance,currency,origination_date,"
    "maturity_date,default_flag,default_date\n"
    "EXP001,SSK001,C001,2026-06-30,MORTGAGE,MANUFACTURING,NORTH,A,1000.0,950.0,EUR,"
    "2020-01-15,2030-06-30,false,\n"
    "EXP002,SSK001,C002,2026-06-30,COMMERCIAL,TRADE,NORTH,B,2000.0,1900.0,EUR,"
    "2021-06-01,2028-06-01,false,\n"
    "EXP003,SSK001,C003,2026-06-30,SME,SERVICES,NORTH,G,500.0,450.0,EUR,"
    "2022-01-01,2029-01-01,false,\n"
    "EXP002,SSK001,C002,2026-06-30,COMMERCIAL,TRADE,NORTH,B,2000.0,1900.0,EUR,"
    "2021-06-01,2028-06-01,false,\n"
    "EXP004,SSK001,C004,2026-06-15,CONSUMER,HEALTHCARE,NORTH,C,300.0,,EUR,"
    "2023-03-01,2028-03-01,false,\n"
)


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def _landing(monkeypatch, tmp_path):
    monkeypatch.setattr("config.source_catalog.LANDING_DIR", tmp_path)


def test_csv_adapter_reads_comma_separated_files(monkeypatch, tmp_path):
    _landing(monkeypatch, tmp_path)
    (tmp_path / "a.csv").write_text(CSV_CONTENT, encoding="utf-8")
    source = SourceFile("SSK001", "exposures", "csv", "a.csv", "CORE_BANKING_TEST")
    frame = CSVAdapter().read(source)
    assert frame.shape == (5, 15)
    assert frame.iloc[0]["exposure_id"] == "EXP001"
    assert frame.iloc[0]["exposure_at_default"] == "1000.0"  # read as strings


def test_csv_adapter_reads_semicolon_separated_files_for_ssk003(monkeypatch, tmp_path):
    _landing(monkeypatch, tmp_path)
    content = "EXPOSURE_ID;INSTITUTE;REPORT_DATE\nE-1;SSK003;30.06.2026\nE-2;SSK003;30.06.2026\n"
    (tmp_path / "b.csv").write_text(content, encoding="utf-8")
    source = SourceFile("SSK003", "exposures", "csv", "b.csv", "CORE_BANKING_TEST")
    frame = CSVAdapter().read(source)
    assert list(frame.columns) == ["EXPOSURE_ID", "INSTITUTE", "REPORT_DATE"]
    assert len(frame) == 2


def test_excel_adapter_reads_configured_sheet(monkeypatch, tmp_path):
    _landing(monkeypatch, tmp_path)
    frame = pd.DataFrame({"col_a": ["x", "y"], "col_b": [1.5, 2.5]})
    frame.to_excel(tmp_path / "c.xlsx", sheet_name="Portfolio", index=False)
    source = SourceFile("SSK002", "exposures", "excel", "c.xlsx", "CORE_BANKING_TEST", sheet_name="Portfolio")
    result = ExcelAdapter().read(source)
    assert list(result.columns) == ["col_a", "col_b"]
    assert result["col_a"].tolist() == ["x", "y"]
    assert result["col_b"].tolist() == [1.5, 2.5]


def test_database_adapter_reads_prepared_table(monkeypatch, tmp_path):
    _landing(monkeypatch, tmp_path)
    source_path = tmp_path / "src.duckdb"
    with duckdb.connect(str(source_path)) as con:
        con.execute("CREATE TABLE portfolio_export (EXPOSURE_ID VARCHAR, EAD DOUBLE)")
        con.execute("INSERT INTO portfolio_export VALUES ('E-1', 100.0), ('E-2', 200.0)")
    source = SourceFile(
        "SSK005", "exposures", "duckdb", "src.duckdb", "CORE_BANKING_TEST",
        table_name="portfolio_export",
    )
    result = DatabaseAdapter().read(source)
    assert len(result) == 2
    assert sorted(result["EXPOSURE_ID"].tolist()) == ["E-1", "E-2"]


def test_adapter_for_rejects_unknown_kind():
    with pytest.raises(ValueError, match="Unsupported source adapter"):
        adapter_for("ftp")


def test_adapter_missing_file_raises(monkeypatch, tmp_path):
    _landing(monkeypatch, tmp_path)
    source = SourceFile("SSK001", "exposures", "csv", "missing.csv", "TEST")
    with pytest.raises(FileNotFoundError):
        CSVAdapter().read(source)


def test_database_adapter_requires_table_name(monkeypatch, tmp_path):
    _landing(monkeypatch, tmp_path)
    source_path = tmp_path / "src.duckdb"
    duckdb.connect(str(source_path)).close()
    source = SourceFile("SSK005", "exposures", "duckdb", "src.duckdb", "TEST")
    with pytest.raises(ValueError, match="No table configured"):
        DatabaseAdapter().read(source)


# ---------------------------------------------------------------------------
# Ingestion lifecycle (RAW -> STAGING -> QUALITY -> CURATED)
# ---------------------------------------------------------------------------


@pytest.fixture
def prepared_env(monkeypatch, tmp_path, tmp_db):
    """Landing zone, raw archive and institutions redirected to tmp locations."""
    landing = tmp_path / "landing"
    landing.mkdir()
    raw = tmp_path / "raw"
    (landing / "test_exposures.csv").write_text(CSV_CONTENT, encoding="utf-8")
    monkeypatch.setattr("config.source_catalog.LANDING_DIR", landing)
    monkeypatch.setattr("ingestion.ingestion_manager.RAW_DIR", raw)
    monkeypatch.setattr(
        "ingestion.ingestion_manager.INSTITUTIONS_FILE", landing / "institutions.csv"
    )
    monkeypatch.setattr("ingestion.ingestion_manager.log_event", lambda *args, **kwargs: None)
    load_institutions(tmp_db)
    source = SourceFile("SSK001", "exposures", "csv", "test_exposures.csv", "CORE_BANKING_TEST")
    return source, raw


def count(tmp_db, table: str) -> int:
    return int(tmp_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_ingest_source_completes_with_expected_quality_outcome(prepared_env, tmp_db):
    source, raw = prepared_env
    result = ingest_source(tmp_db, source, "RUN-TEST-0001")

    assert result["status"] == "COMPLETED"
    assert result["batch_id"].startswith("BATCH-")
    assert result["rows_received"] == 5
    assert result["rows_valid"] == 3
    assert result["rows_rejected"] == 2
    assert result["rows_warned"] == 1  # EXP004: non-quarter-end + missing balance
    assert result["quality_score"] == 60.0  # 3 valid of 5 received

    # Curated layer keeps only the valid rows; staging keeps everything.
    assert count(tmp_db, "exposures") == 3
    assert count(tmp_db, "staging_exposures") == 5
    assert count(tmp_db, "quarantine_records") == 2
    assert count(tmp_db, "quality_results") == 4  # CONS-EXP-002, UNIQ-EXP-001,
    # CONS-EXP-004 (warning), COMP-EXP-006 (warning)

    curated = tmp_db.execute(
        "SELECT exposure_id FROM exposures ORDER BY exposure_id"
    ).fetchall()
    assert [row[0] for row in curated] == ["EXP001", "EXP002", "EXP004"]

    quarantined = tmp_db.execute(
        "SELECT record_id FROM quarantine_records ORDER BY record_id"
    ).fetchall()
    assert [row[0] for row in quarantined] == ["EXP002", "EXP003"]

    # Raw archive and batch bookkeeping exist.
    assert (raw / result["batch_id"] / "exposures_raw.parquet").exists()
    batch = tmp_db.execute(
        "SELECT status, rows_received, rows_valid, rows_rejected, quality_score, reporting_date"
        " FROM ingestion_batches WHERE batch_id = ?",
        [result["batch_id"]],
    ).fetchone()
    assert batch[0] == "COMPLETED"
    assert (batch[1], batch[2], batch[3], batch[4]) == (5, 3, 2, 60.0)
    assert batch[5] == pd.Timestamp("2026-06-30").date()


def test_ingest_source_is_idempotent_for_identical_files(prepared_env, tmp_db):
    source, _ = prepared_env
    first = ingest_source(tmp_db, source, "RUN-TEST-0001")
    assert first["status"] == "COMPLETED"

    second = ingest_source(tmp_db, source, "RUN-TEST-0001")
    assert second["status"] == "SKIPPED_DUPLICATE"
    assert second["rows_received"] == 0
    assert second["quality_score"] is None
    assert count(tmp_db, "exposures") == 3  # curated rows unchanged

    statuses = [
        row[0]
        for row in tmp_db.execute(
            "SELECT status FROM ingestion_batches ORDER BY import_timestamp"
        ).fetchall()
    ]
    assert statuses == ["COMPLETED", "SKIPPED_DUPLICATE"]


def test_ingest_source_force_reprocesses_without_overwriting_curated(prepared_env, tmp_db):
    source, _ = prepared_env
    first = ingest_source(tmp_db, source, "RUN-TEST-0001")
    assert first["status"] == "COMPLETED"

    forced = ingest_source(tmp_db, source, "RUN-TEST-0001", force=True)
    assert forced["status"] == "COMPLETED"
    # All rows already exist in curated data (UNIQ-EXP-002) or fail again:
    # nothing is overwritten and nothing new becomes valid.
    assert forced["rows_valid"] == 0
    assert forced["rows_rejected"] == 5
    assert forced["quality_score"] == 0.0
    assert count(tmp_db, "exposures") == 3
    assert count(tmp_db, "quarantine_records") == 7  # 2 first run + 5 forced run


def test_ingest_source_missing_source_raises(prepared_env, tmp_db):
    source, _ = prepared_env
    missing = SourceFile("SSK001", "exposures", "csv", "does_not_exist.csv", "TEST")
    from ingestion.ingestion_manager import IngestionError

    with pytest.raises(IngestionError, match="Source not found"):
        ingest_source(tmp_db, missing, "RUN-TEST-0001")


def test_curated_exposure_columns_are_canonical(prepared_env, tmp_db):
    source, _ = prepared_env
    ingest_source(tmp_db, source, "RUN-TEST-0001")
    columns = [row[0] for row in tmp_db.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name = 'exposures' ORDER BY ordinal_position"
    ).fetchall()]
    assert set(EXPOSURE_COLUMNS).issubset(columns)
