"""Shared data access, caching, formatting and layout helpers for the dashboard.

The dashboard is deliberately read-only: it reads the same curated DuckDB tables
as the PDF/Excel reporting layer and never mutates the database. Expensive module
results are cached per reporting date and scope.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
import streamlit as st

from benchmarking.benchmark_engine import (
    HistoricalBenchmarkResult,
    build_benchmark_result,
    build_historical_benchmark,
)
from config.settings import DISCLAIMER, REPORT_DIR
from modules.loss_estimation.reporting import LossModuleResult, build_loss_result
from modules.rating_scoring.reporting import RatingModuleResult, build_rating_result
from quality.quality_report import quality_by_period
from reporting.context import QualitySummary, build_quality_summary
from reporting.data_access import (
    data_version_info,
    load_all_inputs,
    load_report_log,
    reporting_dates,
)

CACHE_TTL = "10m"


@st.cache_data(ttl=CACHE_TTL, max_entries=2, show_spinner="Loading curated data...")
def load_data() -> dict[str, pd.DataFrame]:
    """Load every curated table once per cache window."""
    data = load_all_inputs()
    data["data_version"] = data_version_info()
    return data


def all_banks(data: dict[str, pd.DataFrame]) -> list[str]:
    institutions = data.get("institutions", pd.DataFrame())
    if institutions.empty or "bank_id" not in institutions.columns:
        return []
    return institutions["bank_id"].astype(str).tolist()


def bank_names(data: dict[str, pd.DataFrame]) -> dict[str, str]:
    institutions = data.get("institutions", pd.DataFrame())
    if institutions.empty:
        return {}
    return dict(zip(institutions["bank_id"].astype(str), institutions["bank_name"].astype(str)))


def bank_label_map(data: dict[str, pd.DataFrame]) -> dict[str, str]:
    names = bank_names(data)
    return {bank_id: f"{bank_id} - {names.get(bank_id, bank_id)}" for bank_id in all_banks(data)}


def render_scope_filters(data: dict[str, pd.DataFrame]) -> None:
    """Render global sidebar filters used by every page."""
    dates = reporting_dates(data.get("exposures"))
    banks = all_banks(data)
    sectors = sorted(
        data["exposures"]["industry_sector"].dropna().astype(str).unique().tolist()
    ) if not data.get("exposures", pd.DataFrame()).empty else []

    with st.sidebar:
        st.markdown("## Reporting scope")
        if not dates:
            st.error("No quarter-end reporting dates are available.")
            st.stop()
        current = st.session_state.get("global_reporting_date")
        index = dates.index(current) if current in dates else len(dates) - 1
        st.selectbox(
            "Reporting date",
            options=dates,
            index=index,
            format_func=lambda value: pd.Timestamp(value).strftime("%d %b %Y"),
            key="global_reporting_date",
        )
        labels = bank_label_map(data)
        current_banks = st.session_state.get("global_bank_ids")
        default_banks = [bank for bank in (current_banks or banks) if bank in banks]
        st.multiselect(
            "Institutions",
            options=banks,
            default=default_banks,
            format_func=lambda bank_id: labels.get(bank_id, bank_id),
            key="global_bank_ids",
            help="An empty selection is interpreted as the full reporting community.",
        )
        st.multiselect(
            "Industry sectors",
            options=sectors,
            default=st.session_state.get("global_sectors", []),
            placeholder="All sectors",
            key="global_sectors",
        )
        st.divider()
        version = data.get("data_version") or {}
        run = version.get("pipeline_run") or {}
        st.caption(
            f"Data version: {run.get('pipeline_run_id', 'unavailable')}\n\n"
            f"Completed batches: {version.get('batch_count', 0):,}"
        )
        st.caption(DISCLAIMER)


def scope(data: dict[str, pd.DataFrame] | None = None) -> tuple[pd.Timestamp, list[str], list[str]]:
    """Return the effective reporting date, bank IDs and sectors."""
    if data is None:
        data = load_data()
    dates = reporting_dates(data.get("exposures"))
    selected_date = st.session_state.get("global_reporting_date")
    report = (
        pd.Timestamp(selected_date).normalize()
        if selected_date is not None
        else (dates[-1] if dates else pd.Timestamp.today().normalize())
    )
    selected_banks = [str(bank) for bank in st.session_state.get("global_bank_ids", [])]
    effective_banks = selected_banks or all_banks(data)
    sectors = [str(sector) for sector in st.session_state.get("global_sectors", [])]
    return report, effective_banks, sectors


def scope_caption(report: pd.Timestamp, banks: Sequence[str], sectors: Sequence[str]) -> None:
    sector_text = ", ".join(sectors) if sectors else "all industry sectors"
    st.caption(
        f"Scope: {report.strftime('%d %b %Y')} | {len(banks)} institution(s) | {sector_text}"
    )


@st.cache_data(ttl=CACHE_TTL, max_entries=24, show_spinner=False)
def get_rating_module(
    report_iso: str, banks: tuple[str, ...], sectors: tuple[str, ...]
) -> RatingModuleResult:
    data = load_data()
    return build_rating_result(
        data["exposures"],
        data["rating_history"],
        pd.Timestamp(report_iso),
        bank_ids=list(banks) or None,
        sectors=list(sectors) or None,
    )


@st.cache_data(ttl=CACHE_TTL, max_entries=24, show_spinner=False)
def get_loss_module(
    report_iso: str, banks: tuple[str, ...], sectors: tuple[str, ...]
) -> LossModuleResult:
    data = load_data()
    return build_loss_result(
        data["exposures"],
        data["collateral"],
        data["recovery_cashflows"],
        pd.Timestamp(report_iso),
        bank_ids=list(banks) or None,
        sectors=list(sectors) or None,
    )


@st.cache_data(ttl=CACHE_TTL, max_entries=24, show_spinner=False)
def get_benchmark(
    report_iso: str,
    sectors: tuple[str, ...],
    peer_group_override: str | None = None,
):
    data = load_data()
    return build_benchmark_result(
        data["exposures"],
        data["rating_history"],
        data["collateral"],
        data["recovery_cashflows"],
        data["institutions"],
        pd.Timestamp(report_iso),
        sectors=list(sectors) or None,
        peer_group_override=peer_group_override,
    )


@st.cache_data(ttl=CACHE_TTL, max_entries=4, show_spinner=False)
def get_historical_benchmark(
    sectors: tuple[str, ...], peer_group_override: str | None = None
) -> HistoricalBenchmarkResult:
    data = load_data()
    return build_historical_benchmark(
        data["exposures"],
        data["rating_history"],
        data["collateral"],
        data["recovery_cashflows"],
        data["institutions"],
        sectors=list(sectors) or None,
        peer_group_override=peer_group_override,
    )


@st.cache_data(ttl=CACHE_TTL, max_entries=24, show_spinner=False)
def get_quality_summary(report_iso: str, banks: tuple[str, ...]) -> QualitySummary:
    """Quality summary for one reporting date and institution scope."""
    data = load_data()
    report = pd.Timestamp(report_iso).normalize()
    batch = data["batches"].copy()
    findings = data["quality_findings"].copy()
    quarantine = data["quarantine"].copy()
    if not batch.empty:
        batch = batch[pd.to_datetime(batch["reporting_date"]).dt.normalize() == report]
    if not findings.empty:
        findings = findings[pd.to_datetime(findings["reporting_date"]).dt.normalize() == report]
    if not quarantine.empty:
        quarantine = quarantine[
            pd.to_datetime(quarantine["reporting_date"]).dt.normalize() == report
        ]
    if banks:
        batch = batch[batch["bank_id"].isin(banks)]
        findings = findings[findings["bank_id"].isin(banks)]
        quarantine = quarantine[quarantine["bank_id"].isin(banks)]
    return build_quality_summary(
        batch, findings, quarantine, data["rule_catalog"]
    )


def quality_trend(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return quality_by_period(data.get("quality_findings", pd.DataFrame()))


def filter_benchmark_banks(detail: pd.DataFrame, banks: Sequence[str]) -> pd.DataFrame:
    if detail.empty:
        return detail.copy()
    return detail[detail["bank_id"].astype(str).isin([str(bank) for bank in banks])].copy()


def fmt_eur(value: object, compact: bool = True) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    number = float(value)
    if compact:
        if abs(number) >= 1_000_000_000:
            return f"EUR {number / 1_000_000_000:,.2f}bn"
        if abs(number) >= 1_000_000:
            return f"EUR {number / 1_000_000:,.1f}m"
        if abs(number) >= 1_000:
            return f"EUR {number / 1_000:,.1f}k"
    return f"EUR {number:,.0f}"


def fmt_pct(value: object, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value) * 100:,.{digits}f}%"


def fmt_int(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{int(value):,}"


def fmt_days(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.0f} days"


def metric_row(items: Sequence[tuple[str, str, str | None]]) -> None:
    """Render a responsive row of bordered metrics.

    ``items`` contains ``(label, value, help)`` triples.
    """
    with st.container(horizontal=True):
        for label, value, help_text in items:
            st.metric(label, value, border=True, help=help_text)


def percent_column(label: str, help_text: str | None = None):
    return st.column_config.NumberColumn(label, format="percent", help=help_text)


def money_column(label: str, help_text: str | None = None):
    return st.column_config.NumberColumn(label, format="compact", help=help_text)


def empty_state(message: str) -> None:
    st.info(message)


def render_download(path: str | Path, label: str, key: str, mime: str | None = None) -> None:
    """Render a download button when the artefact exists on disk."""
    file_path = Path(path)
    if not file_path.exists():
        return
    st.download_button(
        label,
        data=file_path.read_bytes(),
        file_name=file_path.name,
        mime=mime,
        icon=":material/download:",
        key=key,
    )


def format_dataframe_dates(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_datetime(result[column], errors="coerce").dt.date
    return result


def report_artifacts(report: pd.Timestamp | None = None) -> pd.DataFrame:
    """Report log entries, optionally restricted to one reporting date."""
    log = load_report_log()
    if log.empty:
        return log
    if report is not None and "reporting_date" in log.columns:
        log = log[pd.to_datetime(log["reporting_date"]).dt.normalize() == pd.Timestamp(report).normalize()]
    return log.sort_values("generated_at", ascending=False).reset_index(drop=True)


def existing_report_downloads(report: pd.Timestamp) -> list[tuple[str, Path, str]]:
    """Find common report artefacts for one date without relying on the log."""
    label = pd.Timestamp(report).date().isoformat()
    candidates: list[tuple[str, Path, str]] = []
    community_pdf = REPORT_DIR / label / "community" / f"risk_report_community_{label}.pdf"
    if community_pdf.exists():
        candidates.append(("Community PDF", community_pdf, "application/pdf"))
    institution_dir = REPORT_DIR / label / "institutions"
    if institution_dir.exists():
        for path in sorted(institution_dir.glob("*.pdf")):
            candidates.append((f"Institution PDF - {path.stem.replace('risk_report_', '').replace('_' + label, '')}", path, "application/pdf"))
    return candidates


def csv_bundle_path(report: pd.Timestamp) -> Path:
    from config.settings import EXPORT_DIR

    label = pd.Timestamp(report).date().isoformat()
    return EXPORT_DIR / label / "csv" / "community" / "csv_bundle.zip"


def excel_paths(report: pd.Timestamp) -> list[Path]:
    from config.settings import EXPORT_DIR

    label = pd.Timestamp(report).date().isoformat()
    directory = EXPORT_DIR / label / "excel"
    return sorted(directory.glob("*.xlsx")) if directory.exists() else []


def qlik_paths(report: pd.Timestamp) -> list[Path]:
    from config.settings import QLIK_DIR

    label = pd.Timestamp(report).date().isoformat()
    directory = QLIK_DIR / label
    return sorted(directory.glob("*")) if directory.exists() else []


def read_bytes(path: str | Path) -> bytes:
    return Path(path).read_bytes()


def download_zip(files: Sequence[Path], filename: str) -> bytes:
    buffer = io.BytesIO()
    import zipfile

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if Path(path).is_file():
                archive.write(path, arcname=Path(path).name)
    return buffer.getvalue()
