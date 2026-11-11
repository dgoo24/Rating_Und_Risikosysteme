"""CSV export bundle for downstream analysis and audit review."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from config.settings import DISCLAIMER
from reporting.context import ReportContext


def _write(frame: pd.DataFrame, directory: Path, filename: str) -> Path | None:
    if frame is None or frame.empty:
        return None
    path = directory / filename
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _migration_frames(context: ReportContext) -> list[tuple[str, pd.DataFrame]]:
    counts = context.rating.migration.matrix_counts.reset_index().rename(columns={"index": "base_rating"})
    pct = context.rating.migration.matrix_pct.reset_index().rename(columns={"index": "base_rating"})
    summary = pd.DataFrame([context.rating.migration.summary])
    return [
        ("rating_migration_counts.csv", counts),
        ("rating_migration_pct.csv", pct),
        ("rating_migration_summary.csv", summary),
        ("rating_migration_by_bank.csv", context.rating.migration.by_bank),
    ]


def export_csv_bundle(context: ReportContext, output_dir: Path, create_zip: bool = True) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tables: list[tuple[str, pd.DataFrame]] = [
        ("institutions.csv", context.institutions),
        ("rating_distribution.csv", context.rating.distribution),
        ("pd_by_rating.csv", context.rating.pd_by_rating),
        ("pd_by_bank.csv", context.rating.pd_by_bank),
        ("pd_by_sector.csv", context.rating.pd_by_sector),
        ("pd_trend.csv", context.rating.pd_trend),
        ("default_summary.csv", context.rating.default_summary),
        ("default_by_rating.csv", context.rating.default_by_rating),
        ("default_by_bank.csv", context.rating.default_by_bank),
        ("default_by_sector.csv", context.rating.default_by_sector),
        ("default_trend.csv", context.rating.default_trend),
        ("loss_summary.csv", pd.DataFrame([context.loss.summary])),
        ("loss_by_bank.csv", context.loss.by_bank),
        ("loss_by_rating.csv", context.loss.by_rating),
        ("loss_by_product.csv", context.loss.by_product),
        ("loss_by_sector.csv", context.loss.by_sector),
        ("loss_by_collateral_type.csv", context.loss.by_collateral_type),
        ("loss_by_default_quarter.csv", context.loss.loss_by_default_quarter),
        ("loss_distribution.csv", context.loss.loss_distribution),
        ("loss_severity.csv", context.loss.loss_severity),
        ("recovery_by_default_quarter.csv", context.loss.recovery_by_default_quarter),
        ("recovery_distribution.csv", context.loss.recovery_distribution),
        ("recovery_curve.csv", context.loss.recovery_curve),
        ("recovery_cashflows_by_quarter.csv", context.loss.cashflow_by_quarter),
        ("recovery_type_mix.csv", context.loss.recovery_type_mix),
        ("time_to_recovery.csv", context.loss.time_to_recovery),
        ("collateral_by_bank.csv", context.loss.collateral_by_bank),
        ("collateral_by_rating.csv", context.loss.collateral_by_rating),
        ("collateral_by_product.csv", context.loss.collateral_by_product),
        ("collateral_by_primary_type.csv", context.loss.collateral_by_primary_type),
        ("collateral_type_mix.csv", context.loss.collateral_type_mix),
        ("stale_collateral.csv", context.loss.stale_collateral),
        ("benchmark_detail.csv", context.benchmark_detail),
        ("quality_by_bank.csv", context.quality.by_bank),
        ("quality_by_category.csv", context.quality.by_category),
        ("quality_by_rule.csv", context.quality.by_rule),
        ("quarantine_summary.csv", context.quality.quarantine),
    ]
    tables.extend(_migration_frames(context))
    written: list[Path] = []
    for filename, frame in tables:
        path = _write(frame, output_dir, filename)
        if path is not None:
            written.append(path)

    manifest_rows = [
        {"key": "disclaimer", "value": DISCLAIMER},
        {"key": "reporting_date", "value": context.reporting_date.date().isoformat()},
        {"key": "scope", "value": context.bank_name},
        {"key": "peer_group", "value": context.peer_group or "COMMUNITY"},
        {"key": "generated_at", "value": str(context.generated_at)},
        {"key": "pipeline_run", "value": str((context.data_version.get("pipeline_run") or {}).get("pipeline_run_id", "n/a"))},
        {"key": "quality_score", "value": context.quality.overall_score},
        {"key": "batch_count", "value": context.data_version.get("batch_count", 0)},
        {"key": "rows_received", "value": context.data_version.get("rows_received", 0)},
        {"key": "rows_valid", "value": context.data_version.get("rows_valid", 0)},
        {"key": "rows_rejected", "value": context.data_version.get("rows_rejected", 0)},
    ]
    manifest = pd.DataFrame(manifest_rows)
    manifest_path = _write(manifest, output_dir, "report_manifest.csv")
    if manifest_path:
        written.append(manifest_path)

    if create_zip and written:
        zip_path = output_dir / "csv_bundle.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in written:
                archive.write(path, arcname=path.name)
        written.append(zip_path)
    return written
