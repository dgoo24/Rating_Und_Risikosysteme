"""Reporting layer tests: context assembly, exports and end-to-end generation.

Expected values are hand-computed from the fixture portfolio documented in
``tests/conftest.py`` (see the module docstrings of the rating/loss test
modules for the full derivations). The ``generate_reports`` integration test
seeds a temporary DuckDB with the fixture data, redirects all output paths and
the report audit log, and asserts the generated artefact inventory.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from benchmarking.benchmark_engine import build_benchmark_result
from database.connection import insert_dataframe, query_df
from quality.validation_engine import CURATED_COLUMNS, DATE_COLUMNS
from reporting.audit import log_report
from reporting.context import build_report_context
from reporting.csv_export import export_csv_bundle
from reporting.excel_export import export_excel
from reporting.pdf_report import build_pdf_report
from reporting.qlik_export import export_qlik_bundle, load_script_text
from reporting.distribution import simulate_distribution
from reporting.report_service import generate_reports

from .conftest import REPORT_DATE

EXCEL_SHEETS = [
    "Overview", "Assumptions", "Report_Metadata", "Rating_Distribution",
    "Default_Rates", "PD_Detail", "Rating_Migration", "Loss_Summary",
    "Recovery_Rates", "Collateral", "Recovery_Cashflows", "Benchmarking",
    "Metric_Definitions", "Data_Quality",
]


# ---------------------------------------------------------------------------
# Report context
# ---------------------------------------------------------------------------


def test_build_report_context_community(portfolio):
    context = build_report_context(portfolio, REPORT_DATE)
    assert context.bank_id is None
    assert context.bank_name == "Reporting Community"
    assert context.peer_group is None
    rating = context.rating.kpis
    assert rating["exposure_count"] == 8
    assert rating["total_ead"] == pytest.approx(1900.0)
    assert rating["portfolio_pd"] == pytest.approx(13.9 / 1900.0)
    assert rating["default_rate_12m"] == pytest.approx(1.0 / 3.0)
    loss = context.loss.kpis
    assert loss["recovery_rate"] == pytest.approx(0.425)
    assert loss["loss_rate"] == pytest.approx(0.575)
    assert loss["collateral_coverage"] == pytest.approx(1320.5 / 1900.0)
    # No batches or findings were provided -> quality is neutral zero.
    assert context.quality.overall_score == 0.0
    assert context.quality.batches_completed == 0
    assert context.quality.finding_count == 0


def test_build_report_context_bank_scope(portfolio):
    benchmark = build_benchmark_result(
        portfolio["exposures"],
        portfolio["rating_history"],
        portfolio["collateral"],
        portfolio["recovery_cashflows"],
        portfolio["institutions"],
        REPORT_DATE,
    )
    context = build_report_context(
        portfolio, REPORT_DATE, bank_id="SSK001", benchmark_result=benchmark
    )
    assert context.bank_id == "SSK001"
    assert context.bank_name == "Muster-Sparkasse Nord (fiktiv)"
    assert context.peer_group == "PG_URBAN"
    assert context.rating.kpis["exposure_count"] == 3
    assert context.rating.kpis["total_ead"] == pytest.approx(600.0)
    assert context.rating.kpis["portfolio_pd"] == pytest.approx(1.6 / 600.0)
    assert context.loss.kpis["collateral_coverage"] == pytest.approx(570.5 / 600.0)
    # Benchmark detail is filtered to the selected institution.
    assert set(context.benchmark_detail["bank_id"]) == {"SSK001"}
    assert len(context.benchmark_detail) == 13


def test_build_report_context_unknown_bank_raises(portfolio):
    # Module contract: an empty scope (unknown bank) is rejected with a clear
    # error instead of silently producing an empty report.
    with pytest.raises(ValueError, match="No exposures available"):
        build_report_context(portfolio, REPORT_DATE, bank_id="SSK999")


# ---------------------------------------------------------------------------
# Excel, PDF and CSV exports
# ---------------------------------------------------------------------------


def test_export_excel_writes_all_sheets(portfolio, tmp_path):
    context = build_report_context(portfolio, REPORT_DATE)
    path = tmp_path / "community.xlsx"
    export_excel(context, path)
    assert path.exists()
    workbook = load_workbook(path, read_only=True)
    assert workbook.sheetnames == EXCEL_SHEETS
    workbook.close()


def test_build_pdf_report_produces_a_valid_document(portfolio, tmp_path):
    context = build_report_context(portfolio, REPORT_DATE)
    path = tmp_path / "community.pdf"
    build_pdf_report(context, path)
    assert path.exists()
    payload = path.read_bytes()
    assert payload.startswith(b"%PDF-")
    assert len(payload) > 10_000


def test_build_pdf_report_handles_bank_scope_without_benchmarks(portfolio, tmp_path):
    context = build_report_context(portfolio, REPORT_DATE, bank_id="SSK003")
    path = tmp_path / "ssk003.pdf"
    build_pdf_report(context, path)
    assert path.read_bytes().startswith(b"%PDF-")


def test_export_csv_bundle_writes_tables_and_zip(portfolio, tmp_path):
    context = build_report_context(portfolio, REPORT_DATE)
    files = export_csv_bundle(context, tmp_path / "csv")
    names = {path.name for path in files}
    assert "rating_distribution.csv" in names
    assert "report_manifest.csv" in names
    assert "csv_bundle.zip" in names
    with zipfile.ZipFile(tmp_path / "csv" / "csv_bundle.zip") as archive:
        archived = set(archive.namelist())
    assert "rating_distribution.csv" in archived
    assert "report_manifest.csv" in archived
    distribution = pd.read_csv(tmp_path / "csv" / "rating_distribution.csv")
    assert distribution["exposure_count"].sum() == 8
    manifest = pd.read_csv(tmp_path / "csv" / "report_manifest.csv")
    manifest_values = dict(zip(manifest["key"], manifest["value"]))
    assert manifest_values["reporting_date"] == "2026-06-30"
    assert manifest_values["scope"] == "Reporting Community"


# ---------------------------------------------------------------------------
# Qlik-ready export
# ---------------------------------------------------------------------------


def test_export_qlik_bundle_writes_star_schema(portfolio, tmp_path):
    context = build_report_context(portfolio, REPORT_DATE)
    output_dir = tmp_path / "qlik"
    files, script = export_qlik_bundle(context, portfolio, output_dir)
    assert script == output_dir / "load_script.qvs"
    assert script.exists()
    assert (output_dir / "README_QLIK.md").exists()

    names = {path.name for path in files}
    assert "dim_institution.csv" in names
    assert "fact_exposure_snapshot.csv" in names
    assert "fact_rating_distribution.csv" in names
    assert "load_script.qvs" in names
    assert "README_QLIK.md" in names

    institutions = pd.read_csv(output_dir / "dim_institution.csv")
    assert len(institutions) == 3
    assert set(institutions["bank_id"]) == {"SSK001", "SSK003", "SSK005"}

    exposures = pd.read_csv(output_dir / "fact_exposure_snapshot.csv")
    assert len(exposures) == 15  # every fixture row, both snapshots plus EXP009

    distribution = pd.read_csv(output_dir / "fact_rating_distribution.csv")
    # 3 banks x 6 grades plus the ALL community rows.
    assert len(distribution) == 24
    community = distribution[distribution["bank_id"] == "ALL"].set_index("rating_grade")
    assert int(community.loc["A", "exposure_count"]) == 2
    assert community.loc["A", "ead"] == pytest.approx(600.0)
    assert community.loc["C", "ead"] == pytest.approx(600.0)
    assert "snapshot_date" in distribution.columns


def test_load_script_text_references_every_table():
    script = load_script_text("qlik/data")
    assert script.startswith("// Automated Risk Portfolio Reporting Pipeline")
    assert "SET vDataPath='qlik/data';" in script
    for table in ("dim_institution", "fact_exposure_snapshot", "fact_benchmark", "assumptions"):
        assert f"FROM [$(vDataPath)/{table}.csv]" in script
    assert "not regulatory reporting" in script


# ---------------------------------------------------------------------------
# End-to-end generation with a temporary database
# ---------------------------------------------------------------------------


def seed_database(db_path: Path, portfolio: dict[str, pd.DataFrame]) -> None:
    from database.connection import connect

    with connect(db_path) as con:
        insert_dataframe(con, portfolio["institutions"], "institutions",
                         columns=("bank_id", "bank_name", "region", "peer_group"))
        for dataset, table in (
            ("exposures", "exposures"),
            ("rating_history", "rating_history"),
            ("collateral", "collateral"),
            ("recovery_cashflows", "recovery_cashflows"),
        ):
            frame = portfolio[dataset].copy()
            frame["batch_id"] = "BATCH-TEST-0001"
            insert_dataframe(
                con, frame, table,
                columns=CURATED_COLUMNS[dataset],
                date_columns=DATE_COLUMNS[dataset],
            )


def test_generate_reports_end_to_end(portfolio, tmp_path, monkeypatch):
    db_path = tmp_path / "curated.duckdb"
    seed_database(db_path, portfolio)

    report_dir = tmp_path / "reports"
    export_dir = tmp_path / "exports"
    qlik_dir = tmp_path / "qlik"
    monkeypatch.setattr("reporting.report_service.REPORT_DIR", report_dir)
    monkeypatch.setattr("reporting.report_service.EXPORT_DIR", export_dir)
    monkeypatch.setattr("reporting.report_service.QLIK_DIR", qlik_dir)
    monkeypatch.setattr("reporting.audit.DB_PATH", db_path)

    summary = generate_reports(
        reporting_date=REPORT_DATE,
        bank_ids=["SSK001"],
        output_formats=("pdf", "excel", "csv", "qlik"),
        simulate_dist=False,
        db_path=db_path,
    )

    assert summary["failures"] == []
    assert len(summary["generated"]) == 6
    assert summary["reporting_date"] == "2026-06-30"
    assert summary["distribution_entries"] == 0

    date_label = "2026-06-30"
    expected_files = [
        report_dir / date_label / "community" / f"risk_report_community_{date_label}.pdf",
        report_dir / date_label / "institutions" / f"risk_report_SSK001_{date_label}.pdf",
        export_dir / date_label / "excel" / f"risk_report_community_{date_label}.xlsx",
        export_dir / date_label / "excel" / f"risk_report_SSK001_{date_label}.xlsx",
        export_dir / date_label / "csv" / "community" / "csv_bundle.zip",
        qlik_dir / date_label / "load_script.qvs",
    ]
    for path in expected_files:
        assert path.exists(), path
    assert (report_dir / date_label / "generation_summary.json").exists()

    # The community PDF is a real document and the summary JSON is valid.
    assert (expected_files[0]).read_bytes().startswith(b"%PDF-")
    payload = json.loads((report_dir / date_label / "generation_summary.json").read_text(encoding="utf-8"))
    assert payload["reporting_date"] == date_label
    assert len(payload["generated"]) == 6
    assert "SYNTHETIC DEMONSTRATION DATA" in payload["disclaimer"]

    # The report audit log recorded one GENERATED row per artefact.
    log = query_df("SELECT report_type, file_format, bank_id, status FROM report_log", db_path=db_path)
    assert len(log) == 6
    assert (log["status"] == "GENERATED").all()
    portfolio_rows = log[log["report_type"] == "PORTFOLIO_REPORT"]
    assert set(portfolio_rows["file_format"]) == {"PDF", "XLSX", "CSV_BUNDLE"}
    # The Qlik star-schema export is audited under its own report type.
    qlik_rows = log[log["report_type"] == "QLIK_EXPORT"]
    assert len(qlik_rows) == 1
    assert qlik_rows.iloc[0]["file_format"] == "QLIK_CSV"
    assert portfolio_rows["bank_id"].isna().all()
    institution_rows = log[log["report_type"] == "INSTITUTION_REPORT"]
    assert set(institution_rows["file_format"]) == {"PDF", "XLSX"}
    assert (institution_rows["bank_id"] == "SSK001").all()

    # The seeded fixture data flows through to the generated community Excel.
    workbook = load_workbook(
        export_dir / date_label / "excel" / f"risk_report_community_{date_label}.xlsx",
        read_only=True,
    )
    assert workbook.sheetnames == EXCEL_SHEETS
    workbook.close()


def test_generate_reports_rejects_unknown_formats(portfolio, tmp_path, monkeypatch):
    db_path = tmp_path / "curated.duckdb"
    seed_database(db_path, portfolio)
    monkeypatch.setattr("reporting.report_service.REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr("reporting.report_service.EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr("reporting.report_service.QLIK_DIR", tmp_path / "qlik")
    monkeypatch.setattr("reporting.audit.DB_PATH", db_path)
    with pytest.raises(ValueError, match="Unsupported output format"):
        generate_reports(output_formats=("pdf", "word"), db_path=db_path)
    with pytest.raises(ValueError, match="At least one output format"):
        generate_reports(output_formats=(), db_path=db_path)


def test_generate_reports_requires_a_reporting_date(portfolio, tmp_path, monkeypatch):
    db_path = tmp_path / "empty.duckdb"
    # An empty database (schema only) has no reporting dates at all.
    from database.connection import connect

    connect(db_path).close()
    monkeypatch.setattr("reporting.report_service.REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr("reporting.report_service.EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr("reporting.report_service.QLIK_DIR", tmp_path / "qlik")
    with pytest.raises(ValueError, match="No reporting dates found"):
        generate_reports(db_path=db_path)


def test_log_report_writes_to_explicit_path(tmp_path):
    from database.connection import connect

    db_path = tmp_path / "audit.duckdb"
    connect(db_path).close()
    log_report(
        report_id="RPT-TEST-0002",
        report_type="INSTITUTION_REPORT",
        module="ALL",
        file_format="XLSX",
        bank_id="SSK001",
        reporting_date=REPORT_DATE,
        file_path="reports/y.xlsx",
        status="GENERATED",
        db_path=db_path,
    )
    rows = query_df(
        "SELECT report_id, report_type, bank_id, status FROM report_log", db_path=db_path
    )
    assert rows.to_dict("records") == [
        {"report_id": "RPT-TEST-0002", "report_type": "INSTITUTION_REPORT",
         "bank_id": "SSK001", "status": "GENERATED"}
    ]


def test_simulate_distribution_writes_audited_manifest(tmp_path, monkeypatch):
    # Regression: the default output directory is derived from the reporting
    # date, which is a midnight Timestamp. Its str() contains colons, which
    # are illegal in Windows file names - the label must be ISO date only.
    from database.connection import connect

    db_path = tmp_path / "audit.duckdb"
    connect(db_path).close()
    distribution_dir = tmp_path / "distribution"
    monkeypatch.setattr("reporting.distribution.DISTRIBUTION_DIR", distribution_dir)
    monkeypatch.setattr("reporting.audit.DB_PATH", db_path)

    reports = [
        {
            "report_id": "RPT-TEST-0001",
            "report_type": "PORTFOLIO_REPORT",
            "file_format": "PDF",
            "bank_id": None,
            "path": "reports/2026-06-30/community/risk_report.pdf",
        }
    ]
    entries, manifest_path = simulate_distribution(reports, REPORT_DATE)

    assert manifest_path.parent == distribution_dir / "2026-06-30"
    assert manifest_path.exists()
    assert len(entries) == 4  # one per fictional recipient group
    assert {entry["status"] for entry in entries} == {"SIMULATED"}

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["reporting_date"] == "2026-06-30"
    assert payload["simulation"] is True
    assert len(payload["entries"]) == 4

    log = query_df(
        "SELECT status, channel, recipient_group FROM distribution_log", db_path=db_path
    )
    assert len(log) == 4
    assert (log["status"] == "SIMULATED").all()
    assert (log["channel"] == "SIMULATED_LOCAL_FILE").all()
    assert set(log["recipient_group"]) == {
        "Fictional Risk Committee",
        "Fictional Board Reporting",
        "Fictional Internal Audit",
        "Fictional Peer Review Group",
    }


def test_cli_prints_summary_and_exits_zero(tmp_path, monkeypatch, capsys):
    import reporting.cli as cli

    recorded: dict[str, object] = {}

    def fake_generate_reports(**kwargs):
        recorded.update(kwargs)
        return {
            "reporting_date": "2026-06-30",
            "data_version": "unknown",
            "output_formats": ["pdf"],
            "generated": [{"file_format": "PDF", "path": "reports/x.pdf"}],
            "failures": [],
            "community_pdf": "reports/x.pdf",
            "distribution_manifest": None,
        }

    monkeypatch.setattr(cli, "generate_reports", fake_generate_reports)
    monkeypatch.setattr(
        "sys.argv",
        ["reporting.cli", "--reporting-date", "2026-06-30", "--bank", "SSK001",
         "--formats", "pdf", "--no-distribution"],
    )
    cli.main()
    assert recorded["reporting_date"] == "2026-06-30"
    assert recorded["bank_ids"] == ["SSK001"]
    assert recorded["output_formats"] == ["pdf"]
    assert recorded["simulate_dist"] is False
    out = capsys.readouterr().out
    assert "1 generated, 0 failed" in out
    assert "not simulated" in out
