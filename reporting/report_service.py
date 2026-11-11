"""End-to-end report generation service.

Generates a community report and optional institution reports, writes PDF, Excel,
CSV and Qlik-ready outputs, records report_log entries and simulates distribution.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from benchmarking.benchmark_engine import build_benchmark_result
from config.settings import (
    DISCLAIMER,
    EXPORT_DIR,
    QLIK_DIR,
    REPORT_DIR,
)
from database.connection import utc_now
from reporting.audit import log_report, new_report_id
from reporting.context import ReportContext, build_report_context
from reporting.csv_export import export_csv_bundle
from reporting.data_access import (
    data_version_info,
    latest_reporting_date,
    load_all_inputs,
)
from reporting.distribution import simulate_distribution
from reporting.excel_export import export_excel
from reporting.pdf_report import build_pdf_report
from reporting.qlik_export import export_qlik_bundle


def _safe_log(report: dict[str, object], status: str, error: str | None = None) -> None:
    log_report(
        report_id=str(report["report_id"]),
        report_type=str(report["report_type"]),
        module=str(report.get("module") or "ALL"),
        file_format=str(report["file_format"]),
        bank_id=str(report["bank_id"]) if report.get("bank_id") else None,
        reporting_date=report["reporting_date"],
        file_path=str(report["path"]),
        status=status,
        data_version=str(report.get("data_version") or ""),
        batch_ids=report.get("batch_ids") or [],
        error_message=error,
    )


def _artefact(
    report_type: str,
    file_format: str,
    bank_id: str | None,
    reporting_date: object,
    path: Path,
    data_version: str,
    batch_ids: list[str],
    module: str = "ALL",
) -> dict[str, object]:
    return {
        "report_id": new_report_id("RPT"),
        "report_type": report_type,
        "file_format": file_format,
        "bank_id": bank_id,
        "reporting_date": reporting_date,
        "path": str(path),
        "data_version": data_version,
        "batch_ids": batch_ids,
        "module": module,
    }


def generate_reports(
    reporting_date: object | None = None,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    output_formats: Iterable[str] = ("pdf", "excel", "csv", "qlik"),
    include_community: bool = True,
    include_institutions: bool = True,
    simulate_dist: bool = True,
    db_path: str | Path | None = None,
) -> dict[str, object]:
    """Generate selected reporting artefacts and audit all outcomes."""
    formats = {str(value).lower() for value in output_formats}
    allowed = {"pdf", "excel", "csv", "qlik"}
    unknown = formats - allowed
    if unknown:
        raise ValueError(f"Unsupported output format(s): {sorted(unknown)}")
    if not formats:
        raise ValueError("At least one output format is required")

    data = load_all_inputs(db_path=db_path)
    data["data_version"] = data_version_info(db_path=db_path)
    report = pd.Timestamp(reporting_date).normalize() if reporting_date is not None else latest_reporting_date(db_path)
    if report is None:
        raise ValueError("No reporting dates found. Run the synthetic generator and ingestion pipeline first.")

    if data["institutions"].empty:
        raise ValueError("Institution master is empty. Run the ingestion pipeline first.")

    selected_banks = list(bank_ids) if bank_ids else data["institutions"]["bank_id"].astype(str).tolist()
    selected_banks = [bank for bank in selected_banks if bank in set(data["institutions"]["bank_id"].astype(str))]
    sector_list = list(sectors) if sectors else []
    data_version = str((data["data_version"].get("pipeline_run") or {}).get("pipeline_run_id", "unknown"))
    batch_ids = data["data_version"].get("batch_ids", [])
    generated_at = utc_now()

    date_label = report.date().isoformat()
    community_pdf_dir = REPORT_DIR / date_label / "community"
    institution_pdf_dir = REPORT_DIR / date_label / "institutions"
    excel_dir = EXPORT_DIR / date_label / "excel"
    csv_dir = EXPORT_DIR / date_label / "csv"
    qlik_dir = QLIK_DIR / date_label

    benchmark = build_benchmark_result(
        data["exposures"],
        data["rating_history"],
        data["collateral"],
        data["recovery_cashflows"],
        data["institutions"],
        report,
        sectors=sector_list or None,
    )

    generated: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    warnings: list[str] = []
    context_summary: list[dict[str, object]] = []

    def _build_context(bank_id: str | None) -> ReportContext:
        return build_report_context(
            data,
            report,
            bank_id=bank_id,
            sectors=sector_list or None,
            benchmark_result=benchmark,
            generated_at=generated_at,
        )

    def _generate_pdf(context: ReportContext, path: Path, report_type: str) -> None:
        artefact = _artefact(report_type, "PDF", context.bank_id, report, path, data_version, batch_ids)
        try:
            build_pdf_report(context, path)
            _safe_log(artefact, "GENERATED")
            generated.append(artefact)
        except Exception as exc:  # keep other artefacts independent
            _safe_log(artefact, "FAILED", str(exc))
            failures.append({"artefact": str(path), "error": str(exc)})

    def _generate_excel(context: ReportContext, path: Path, report_type: str) -> None:
        artefact = _artefact(report_type, "XLSX", context.bank_id, report, path, data_version, batch_ids)
        try:
            export_excel(context, path)
            _safe_log(artefact, "GENERATED")
            generated.append(artefact)
        except Exception as exc:
            _safe_log(artefact, "FAILED", str(exc))
            failures.append({"artefact": str(path), "error": str(exc)})

    if include_community:
        try:
            community_context = _build_context(None)
            context_summary.append(
                {
                    "scope": "COMMUNITY",
                    "bank_id": None,
                    "exposures": int(len(community_context.rating.exposures)),
                    "ead": community_context.rating.kpis.get("total_ead"),
                    "default_rate": community_context.rating.kpis.get("default_rate_12m"),
                    "recovery_rate": community_context.loss.kpis.get("recovery_rate"),
                    "loss_rate": community_context.loss.kpis.get("loss_rate"),
                }
            )
            if "pdf" in formats:
                _generate_pdf(
                    community_context,
                    community_pdf_dir / f"risk_report_community_{date_label}.pdf",
                    "PORTFOLIO_REPORT",
                )
            if "excel" in formats:
                _generate_excel(
                    community_context,
                    excel_dir / f"risk_report_community_{date_label}.xlsx",
                    "PORTFOLIO_REPORT",
                )
            if "csv" in formats:
                csv_path = csv_dir / "community"
                try:
                    files = export_csv_bundle(community_context, csv_path)
                    artefact = _artefact(
                        "PORTFOLIO_REPORT", "CSV_BUNDLE", None, report,
                        csv_path / "csv_bundle.zip", data_version, batch_ids,
                    )
                    _safe_log(artefact, "GENERATED")
                    generated.append(artefact)
                    if not files:
                        warnings.append("CSV bundle contained no data tables.")
                except Exception as exc:
                    artefact = _artefact(
                        "PORTFOLIO_REPORT", "CSV_BUNDLE", None, report,
                        csv_path / "csv_bundle.zip", data_version, batch_ids,
                    )
                    _safe_log(artefact, "FAILED", str(exc))
                    failures.append({"artefact": str(csv_path), "error": str(exc)})
            if "qlik" in formats:
                try:
                    files, script = export_qlik_bundle(community_context, data, qlik_dir)
                    artefact = _artefact(
                        "QLIK_EXPORT", "QLIK_CSV", None, report,
                        qlik_dir, data_version, batch_ids,
                    )
                    _safe_log(artefact, "GENERATED")
                    generated.append(artefact)
                    context_summary.append({"scope": "QLIK", "files": len(files), "script": str(script)})
                except Exception as exc:
                    artefact = _artefact("QLIK_EXPORT", "QLIK_CSV", None, report, qlik_dir, data_version, batch_ids)
                    _safe_log(artefact, "FAILED", str(exc))
                    failures.append({"artefact": str(qlik_dir), "error": str(exc)})
        except Exception as exc:
            failures.append({"artefact": "COMMUNITY_CONTEXT", "error": str(exc)})

    if include_institutions:
        for bank_id in selected_banks:
            try:
                context = _build_context(bank_id)
                context_summary.append(
                    {
                        "scope": "INSTITUTION",
                        "bank_id": bank_id,
                        "bank_name": context.bank_name,
                        "exposures": int(len(context.rating.exposures)),
                        "ead": context.rating.kpis.get("total_ead"),
                        "default_rate": context.rating.kpis.get("default_rate_12m"),
                        "recovery_rate": context.loss.kpis.get("recovery_rate"),
                        "loss_rate": context.loss.kpis.get("loss_rate"),
                    }
                )
                if "pdf" in formats:
                    _generate_pdf(
                        context,
                        institution_pdf_dir / f"risk_report_{bank_id}_{date_label}.pdf",
                        "INSTITUTION_REPORT",
                    )
                if "excel" in formats:
                    _generate_excel(
                        context,
                        excel_dir / f"risk_report_{bank_id}_{date_label}.xlsx",
                        "INSTITUTION_REPORT",
                    )
            except Exception as exc:
                failures.append({"artefact": f"INSTITUTION_CONTEXT_{bank_id}", "error": str(exc)})

    distribution_entries: list[dict[str, object]] = []
    distribution_manifest = None
    if simulate_dist and generated:
        distribution_entries, distribution_manifest = simulate_distribution(
            generated,
            report,
        )

    summary = {
        "disclaimer": DISCLAIMER,
        "reporting_date": date_label,
        "generated_at": generated_at.isoformat(),
        "output_formats": sorted(formats),
        "data_version": data_version,
        "batch_count": data["data_version"].get("batch_count", 0),
        "contexts": context_summary,
        "generated": generated,
        "failures": failures,
        "warnings": warnings,
        "distribution_entries": len(distribution_entries),
        "distribution_manifest": str(distribution_manifest) if distribution_manifest else None,
        "community_pdf": str(community_pdf_dir / f"risk_report_community_{date_label}.pdf") if include_community and "pdf" in formats else None,
        "community_excel": str(excel_dir / f"risk_report_community_{date_label}.xlsx") if include_community and "excel" in formats else None,
        "csv_bundle": str(csv_dir / "community" / "csv_bundle.zip") if include_community and "csv" in formats else None,
        "qlik_dir": str(qlik_dir) if include_community and "qlik" in formats else None,
    }
    summary_path = REPORT_DIR / date_label / "generation_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return summary
