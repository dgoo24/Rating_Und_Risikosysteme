"""Gemeinsamer Datenzugriff, Caching, Formatierung und Layout für das Dashboard.

Das Dashboard ist bewusst nur lesend: Es greift auf dieselben kuratierten
DuckDB-Tabellen zu wie die PDF-/Excel-Berichtsebene und verändert die
Datenbank nie. Teure Modulergebnisse werden pro Berichtsstichtag und Umfang
zwischengespeichert.

Alle Benutzeroberflächen-Texte sind deutsch; Zahlen und Datumswerte folgen der
deutschen Konvention (Dezimalkomma, Punkt als Tausendertrennzeichen,
TT.MM.JJJJ). Die Navigation läuft über eine horizontale Kopfzeile; die
globalen Umfangsfilter liegen direkt im Hauptbereich der Seite.
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

# Sparkassenrot und die begleitenden Neutraltöne des Corporate Designs.
SPARKASSE_RED = "#E6001E"
SPARKASSE_DARK = "#262626"
SPARKASSE_GRAY = "#6B6B6B"

_BRAND_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display: none !important;}
.rr-brand {
    display: flex; align-items: center; gap: 14px;
    background: linear-gradient(90deg, #E6001E 0%, #A3001F 100%);
    color: #FFFFFF; border-radius: 10px;
    padding: 12px 20px; margin-bottom: 6px;
    box-shadow: 0 2px 10px rgba(166, 0, 25, 0.18);
}
.rr-brand svg {width: 34px; height: 34px; flex: 0 0 auto;}
.rr-brand-title {font-size: 1.24rem; font-weight: 700; letter-spacing: 0.2px; display: block; line-height: 1.25;}
.rr-brand-sub {font-size: 0.82rem; opacity: 0.93; display: block; margin-top: 2px;}
.rr-brand-badge {
    margin-left: auto; font-size: 0.66rem; font-weight: 700; letter-spacing: 1.4px;
    border: 1px solid rgba(255, 255, 255, 0.7); padding: 3px 10px; border-radius: 999px;
    text-transform: uppercase; white-space: nowrap;
}
.rr-scope-title {
    display: flex; align-items: center; gap: 9px;
    color: #262626; font-size: 0.8rem; font-weight: 700;
    letter-spacing: 1.6px; text-transform: uppercase; margin: 8px 0 0 0;
}
.rr-scope-accent {width: 4px; height: 16px; border-radius: 2px; background: #E6001E; flex: 0 0 auto;}
.rr-scope-names {color: #6B6B6B; font-size: 0.77rem; margin: 0 0 4px 0; line-height: 1.55;}
[data-testid="stMetric"] {border-color: #F1C9CE !important;}
[data-testid="stMetricLabel"] p {color: #454957; font-weight: 600;}
[data-testid="stMetricValue"] {color: #262626; font-weight: 700;}
.rr-footer {text-align: center; color: #6B6B6B; font-size: 0.78rem; line-height: 1.6;}
.rr-footer strong {color: #8C0011;}
</style>
"""

_BRAND_HTML = """
<div class="rr-brand">
    <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <rect x="2" y="25" width="8" height="13" rx="2" fill="#FFFFFF" opacity="0.72"/>
        <rect x="16" y="16" width="8" height="22" rx="2" fill="#FFFFFF" opacity="0.87"/>
        <rect x="30" y="4" width="8" height="34" rx="2" fill="#FFFFFF"/>
    </svg>
    <div>
        <span class="rr-brand-title">Risikoportfolio-Berichtswesen</span>
        <span class="rr-brand-sub">Automatisierte Berichtsplattform &middot; Rating und Risikosysteme</span>
    </div>
    <span class="rr-brand-badge">Demo-Daten</span>
</div>
"""


@st.cache_data(ttl=CACHE_TTL, max_entries=2, show_spinner="Lade kuratierte Daten ...")
def load_data() -> dict[str, pd.DataFrame]:
    """Lädt jede kuratierte Tabelle einmal pro Cache-Zeitfenster."""
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


def render_brand_header() -> None:
    """Rendert den Sparkasse-inspirierten Marken-Header und die Basis-Styles."""
    st.markdown(_BRAND_CSS + _BRAND_HTML, unsafe_allow_html=True)


def render_footer(data: dict[str, pd.DataFrame]) -> None:
    """Rendert den Seitenfuß mit Datenstand und Disclaimer."""
    version = data.get("data_version") or {}
    run = version.get("pipeline_run") or {}
    run_id = run.get("pipeline_run_id", "nicht verfügbar")
    batches = int(version.get("batch_count", 0) or 0)
    st.divider()
    st.markdown(
        f'<div class="rr-footer">Datenstand: {run_id} &middot; abgeschlossene Batches: {batches}<br>'
        f"<strong>{DISCLAIMER}</strong></div>",
        unsafe_allow_html=True,
    )


_DE_MONTHS = {
    1: "Jan.", 2: "Feb.", 3: "Mär.", 4: "Apr.", 5: "Mai", 6: "Jun.",
    7: "Jul.", 8: "Aug.", 9: "Sep.", 10: "Okt.", 11: "Nov.", 12: "Dez.",
}


def _stichtag_label(value: object) -> str:
    """Kompakte Monats-/Jahresbezeichnung für die Stichtags-Pills (z. B. 'Sep. 2026')."""
    try:
        moment = pd.Timestamp(value)
        return f"{_DE_MONTHS.get(moment.month, '')} {moment.year}"
    except (TypeError, ValueError):
        return str(value)


def _reset_scope() -> None:
    """Setzt die globalen Umfangsfilter auf die Standardwerte zurück."""
    for key in ("global_reporting_date", "global_bank_ids", "global_sectors"):
        st.session_state.pop(key, None)


def render_scope_filters(data: dict[str, pd.DataFrame]) -> None:
    """Rendert die globalen Umfangsfilter als kompakte Pill-Auswahl im Hauptbereich."""
    dates = reporting_dates(data.get("exposures"))
    banks = all_banks(data)
    sectors = sorted(
        data["exposures"]["industry_sector"].dropna().astype(str).unique().tolist()
    ) if not data.get("exposures", pd.DataFrame()).empty else []
    if not dates:
        st.error("Es sind keine Quartalsstichtage verfügbar.")
        st.stop()

    names = bank_names(data)
    current_date = st.session_state.get("global_reporting_date")
    default_date = current_date if current_date in dates else dates[-1]
    current_banks = st.session_state.get("global_bank_ids")
    default_banks = [bank for bank in (current_banks or banks) if bank in banks]

    with st.container(border=True):
        head_left, head_right = st.columns([0.76, 0.24])
        head_left.markdown(
            '<p class="rr-scope-title"><span class="rr-scope-accent"></span>Berichtsumfang</p>',
            unsafe_allow_html=True,
        )
        head_right.button(
            "Zurücksetzen",
            key="scope_reset",
            on_click=_reset_scope,
            icon=":material/restart_alt:",
            type="tertiary",
            width="stretch",
        )

        st.pills(
            "Berichtsstichtag",
            options=dates,
            default=default_date,
            required=True,
            format_func=_stichtag_label,
            key="global_reporting_date",
            help="Alle Ansichten folgen dem ausgewählten Berichtsstichtag.",
            wrap=True,
        )
        selected_banks = st.pills(
            "Institute",
            options=banks,
            selection_mode="multi",
            default=default_banks,
            key="global_bank_ids",
            help="Mehrfachauswahl – eine leere Auswahl gilt als gesamte Berichtsgemeinschaft.",
            wrap=True,
        ) or []
        if selected_banks:
            st.markdown(
                '<p class="rr-scope-names">'
                + " · ".join(names.get(bank, bank) for bank in selected_banks)
                + "</p>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<p class="rr-scope-names">Leere Auswahl – alle Institute der Berichtsgemeinschaft.</p>',
                unsafe_allow_html=True,
            )
        st.pills(
            "Wirtschaftssektoren",
            options=sectors,
            selection_mode="multi",
            default=st.session_state.get("global_sectors") or None,
            key="global_sectors",
            help="Mehrfachauswahl – eine leere Auswahl umfasst alle Wirtschaftssektoren.",
            wrap=True,
        )


def scope(data: dict[str, pd.DataFrame] | None = None) -> tuple[pd.Timestamp, list[str], list[str]]:
    """Liefert den wirksamen Berichtsstichtag, Instituts- und Sektorenumfang."""
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
    sector_text = ", ".join(sectors) if sectors else "alle Wirtschaftssektoren"
    st.caption(
        f"Umfang: {fmt_date_de(report)} | {len(banks)} Institut(e) | {sector_text}"
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
    """Qualitätsübersicht für einen Berichtsstichtag und Institutsumfang."""
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


def _de_number(number: float, digits: int = 0) -> str:
    """Formatiert eine Zahl deutsch: Punkt als Tausender-, Komma als Dezimaltrenner."""
    text = f"{number:,.{digits}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_date_de(value: object) -> str:
    """Datum im deutschen Format TT.MM.JJJJ."""
    if value is None:
        return ""
    try:
        return pd.Timestamp(value).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return str(value)


def fmt_datetime_de(value: object) -> str:
    """Zeitstempel im deutschen Format TT.MM.JJJJ HH:MM."""
    if value is None or pd.isna(value):
        return "k. A."
    try:
        return pd.Timestamp(value).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return str(value)


def fmt_eur(value: object, compact: bool = True) -> str:
    if value is None or pd.isna(value):
        return "k. A."
    number = float(value)
    if compact:
        if abs(number) >= 1_000_000_000:
            return f"{_de_number(number / 1_000_000_000, 2)} Mrd. EUR"
        if abs(number) >= 1_000_000:
            return f"{_de_number(number / 1_000_000, 1)} Mio. EUR"
        if abs(number) >= 1_000:
            return f"{_de_number(number, 0)} EUR"
    return f"{_de_number(number, 0)} EUR"


def fmt_pct(value: object, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "k. A."
    return f"{_de_number(float(value) * 100, digits)} %"


def fmt_int(value: object) -> str:
    if value is None or pd.isna(value):
        return "k. A."
    return _de_number(int(value), 0)


def fmt_days(value: object) -> str:
    if value is None or pd.isna(value):
        return "k. A."
    return f"{_de_number(float(value), 0)} Tage"


def metric_row(items: Sequence[tuple[str, str, str | None]]) -> None:
    """Rendert eine responsive Zeile umrandeter Kennzahlen.

    ``items`` enthält ``(Bezeichnung, Wert, Hilfe)``-Tripel.
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
    """Rendert eine Download-Schaltfläche, wenn das Artefakt existiert."""
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
    """Berichtsprotokolleinträge, optional auf einen Berichtsstichtag begrenzt."""
    log = load_report_log()
    if log.empty:
        return log
    if report is not None and "reporting_date" in log.columns:
        log = log[pd.to_datetime(log["reporting_date"]).dt.normalize() == pd.Timestamp(report).normalize()]
    return log.sort_values("generated_at", ascending=False).reset_index(drop=True)


def existing_report_downloads(report: pd.Timestamp) -> list[tuple[str, Path, str]]:
    """Findet häufige Berichtsartefakte für einen Stichtag ohne Protokoll."""
    label = pd.Timestamp(report).date().isoformat()
    candidates: list[tuple[str, Path, str]] = []
    community_pdf = REPORT_DIR / label / "community" / f"risk_report_community_{label}.pdf"
    if community_pdf.exists():
        candidates.append(("Community-PDF", community_pdf, "application/pdf"))
    institution_dir = REPORT_DIR / label / "institutions"
    if institution_dir.exists():
        for path in sorted(institution_dir.glob("*.pdf")):
            candidates.append((f"Instituts-PDF - {path.stem.replace('risk_report_', '').replace('_' + label, '')}", path, "application/pdf"))
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
