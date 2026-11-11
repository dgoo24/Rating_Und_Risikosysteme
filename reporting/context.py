"""Shared report context assembled from analytical modules and quality results."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from benchmarking.aggregation import benchmark_kpis
from benchmarking.benchmark_engine import BenchmarkResult
from modules.loss_estimation.reporting import LossModuleResult, build_loss_result
from modules.rating_scoring.reporting import RatingModuleResult, build_rating_result
from quality.quality_report import (
    overall_quality_score,
    quality_by_bank,
    quality_by_category,
    quality_by_rule,
    quarantine_summary,
)


@dataclass
class QualitySummary:
    overall_score: float
    rows_received: int
    rows_valid: int
    rows_rejected: int
    batches_completed: int
    batches_skipped: int
    finding_count: int
    error_count: int
    warning_count: int
    quarantined_records: int
    by_bank: pd.DataFrame
    by_rule: pd.DataFrame
    by_category: pd.DataFrame
    quarantine: pd.DataFrame
    catalog: pd.DataFrame
    findings: pd.DataFrame
    quarantine_records: pd.DataFrame


@dataclass
class ReportContext:
    reporting_date: pd.Timestamp
    bank_id: str | None
    bank_name: str
    peer_group: str | None
    generated_at: datetime
    institutions: pd.DataFrame
    rating: RatingModuleResult
    loss: LossModuleResult
    benchmark_detail: pd.DataFrame
    benchmark_kpis: dict[str, object]
    quality: QualitySummary
    data_version: dict[str, object]
    batches: pd.DataFrame


def _filter_bank(frame: pd.DataFrame, bank_id: str | None, columns: tuple[str, ...] = ("bank_id",)) -> pd.DataFrame:
    if frame.empty or bank_id is None:
        return frame
    for column in columns:
        if column in frame.columns:
            return frame[frame[column] == bank_id].copy()
    return frame.iloc[0:0].copy()


def build_quality_summary(
    batches: pd.DataFrame,
    findings: pd.DataFrame,
    quarantine: pd.DataFrame,
    rule_catalog: pd.DataFrame,
    bank_id: str | None = None,
) -> QualitySummary:
    batch_frame = _filter_bank(batches, bank_id)
    finding_frame = _filter_bank(findings, bank_id)
    quarantine_frame = _filter_bank(quarantine, bank_id)
    completed = batch_frame[batch_frame["status"] == "COMPLETED"] if not batch_frame.empty else batch_frame
    skipped = batch_frame[batch_frame["status"] == "SKIPPED_DUPLICATE"] if not batch_frame.empty else batch_frame
    error_count = int((finding_frame["severity"] == "ERROR").sum()) if not finding_frame.empty else 0
    warning_count = int((finding_frame["severity"] == "WARNING").sum()) if not finding_frame.empty else 0
    return QualitySummary(
        overall_score=overall_quality_score(batch_frame),
        rows_received=int(completed["rows_received"].sum()) if not completed.empty else 0,
        rows_valid=int(completed["rows_valid"].sum()) if not completed.empty else 0,
        rows_rejected=int(completed["rows_rejected"].sum()) if not completed.empty else 0,
        batches_completed=int(len(completed)),
        batches_skipped=int(len(skipped)),
        finding_count=int(len(finding_frame)),
        error_count=error_count,
        warning_count=warning_count,
        quarantined_records=int(quarantine_frame["quarantine_id"].nunique()) if not quarantine_frame.empty else 0,
        by_bank=quality_by_bank(batch_frame, finding_frame),
        by_rule=quality_by_rule(finding_frame),
        by_category=quality_by_category(finding_frame),
        quarantine=quarantine_summary(quarantine_frame),
        catalog=rule_catalog.copy(),
        findings=finding_frame,
        quarantine_records=quarantine_frame,
    )


def build_report_context(
    data: dict[str, pd.DataFrame],
    reporting_date: object,
    bank_id: str | None = None,
    sectors: Iterable[str] | None = None,
    benchmark_result: BenchmarkResult | None = None,
    generated_at: datetime | None = None,
) -> ReportContext:
    report = pd.Timestamp(reporting_date).normalize()
    sector_list = list(sectors) if sectors else []
    bank_list = [bank_id] if bank_id else []
    institutions = data["institutions"].copy()
    bank_name = bank_id or "Reporting Community"
    peer_group = None
    if bank_id and not institutions.empty:
        selected = institutions[institutions["bank_id"] == bank_id]
        if not selected.empty:
            bank_name = str(selected.iloc[0]["bank_name"])
            peer_group = str(selected.iloc[0]["peer_group"])

    rating = build_rating_result(
        data["exposures"],
        data["rating_history"],
        report,
        bank_ids=bank_list or None,
        sectors=sector_list or None,
    )
    loss = build_loss_result(
        data["exposures"],
        data["collateral"],
        data["recovery_cashflows"],
        report,
        bank_ids=bank_list or None,
        sectors=sector_list or None,
    )
    benchmark_detail = benchmark_result.detail.copy() if benchmark_result is not None else pd.DataFrame()
    if bank_id is not None and not benchmark_detail.empty:
        benchmark_detail = benchmark_detail[benchmark_detail["bank_id"] == bank_id].reset_index(drop=True)
    quality = build_quality_summary(
        data["batches"],
        data["quality_findings"],
        data["quarantine"],
        data["rule_catalog"],
        bank_id=bank_id,
    )
    batches = _filter_bank(data["batches"], bank_id)
    return ReportContext(
        reporting_date=report,
        bank_id=bank_id,
        bank_name=bank_name,
        peer_group=peer_group,
        generated_at=generated_at or datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0),
        institutions=institutions,
        rating=rating,
        loss=loss,
        benchmark_detail=benchmark_detail,
        benchmark_kpis=benchmark_kpis(benchmark_detail),
        quality=quality,
        data_version=data.get("data_version", {}),
        batches=batches,
    )
