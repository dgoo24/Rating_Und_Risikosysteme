"""Reporting-Seite: bedarfsgesteuerte Berichtserstellung, Artefakte und Verteilungsprotokoll.

Die Seite ist der Dashboard-Einstieg in die von beiden Risikomodulen gemeinsam
genutzte Berichts-Engine. Sie triggert denselben ``generate_reports``-Service
wie die Kommandozeile, sodass PDF-, Excel-, CSV- und Qlik-Ausgaben immer aus
identischem Code entstehen.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from config.settings import (
    DEFAULT_OBSERVATION_MONTHS,
    DISCLAIMER,
    REPORT_DIR,
)
from dashboard.common import (
    bank_names,
    csv_bundle_path,
    download_zip,
    empty_state,
    excel_paths,
    fmt_int,
    fmt_pct,
    get_quality_summary,
    load_data,
    metric_row,
    qlik_paths,
    render_download,
    report_artifacts,
    scope,
    scope_caption,
)
from config.collateral_haircuts import COLLATERAL_HAIRCUTS, COLLATERAL_HAIRCUT_DESCRIPTION
from config.rating_pd_mapping import RATING_PD_MAPPING, RATING_PD_DESCRIPTION
from reporting.report_service import generate_reports

FORMAT_OPTIONS = {
    "pdf": "PDF-Bericht",
    "excel": "Excel-Arbeitsmappe",
    "csv": "CSV-Paket",
    "qlik": "Qlik-Datensätze",
}


def _generate_section(report: pd.Timestamp, banks: list[str], sectors: list[str]) -> None:
    st.subheader("Berichtsartefakte erstellen")
    st.caption(
        "Die Erstellung nutzt denselben Berichtsservice wie die Kommandozeile "
        "(`python -m reporting.cli`). Jedes Artefakt wird mit seiner Datenversion und den "
        "beigetragenen Batch-IDs im Berichtsprotokoll erfasst."
    )
    col1, col2 = st.columns(2)
    with col1:
        formats = st.pills(
            "Ausgabeformate",
            options=list(FORMAT_OPTIONS),
            format_func=lambda value: FORMAT_OPTIONS[value],
            selection_mode="multi",
            default=list(FORMAT_OPTIONS),
            key="report_formats",
        )
    with col2:
        include_community = st.toggle("Berichtsgemeinschafts-Bericht", value=True, key="report_community")
        include_institutions = st.toggle("Institutsberichte", value=True, key="report_institutions")
        simulate_distribution = st.toggle("Verteilung simulieren", value=True, key="report_distribution")

    if st.button(
        "Berichte erstellen",
        type="primary",
        icon=":material/play_arrow:",
        disabled=not formats,
        width="stretch",
    ):
        progress = st.progress(0.0, "Kuratierte Daten werden geladen und der Berichtskontext aufgebaut ...")
        try:
            with st.spinner("Berichtsartefakte werden erstellt ..."):
                summary = generate_reports(
                    reporting_date=report,
                    bank_ids=banks,
                    sectors=sectors,
                    output_formats=formats,
                    include_community=include_community,
                    include_institutions=include_institutions,
                    simulate_dist=simulate_distribution,
                )
            st.session_state["last_report_summary"] = summary
        except Exception as exc:
            st.error(f"Die Berichterstellung ist fehlgeschlagen: {exc}")
            return
        progress.progress(1.0, "Abgeschlossen.")

    summary = st.session_state.get("last_report_summary")
    if summary is None:
        return
    if summary.get("failures"):
        st.error(
            f"{len(summary['failures'])} Artefakt(e) sind fehlgeschlagen. Details stehen im Berichtsprotokoll."
        )
    else:
        st.success(
            f"{len(summary['generated'])} Artefakt(e) für den {summary['reporting_date']} aus "
            f"Datenversion {summary['data_version']} erstellt."
        )
    metric_row(
        [
            ("Erstellte Artefakte", fmt_int(len(summary.get("generated", []))), "In diesem Lauf erzeugte PDF-, Excel-, CSV- und Qlik-Ausgaben."),
            ("Fehlgeschlagene Artefakte", fmt_int(len(summary.get("failures", []))), "Artefakte, die nicht erzeugt werden konnten."),
            ("Datenversion", str(summary.get("data_version", "k. A.")), "Pipeline-Lauf-ID, auf der die Berichte beruhen."),
            ("Verteilung", "Simuliert" if summary.get("distribution_manifest") else "Nicht simuliert", "Ausschließlich lokale Simulation; es wird kein externer Kanal kontaktiert."),
        ]
    )
    for item in summary.get("generated", []):
        path = Path(str(item["path"]))
        if path.is_file():
            render_download(
                path,
                f"Herunterladen: {path.name}",
                f"gen_{item['report_id']}",
                "application/pdf" if path.suffix == ".pdf" else None,
            )
        else:
            st.caption(f"{item['file_format']}: {path}")


def _artefact_section(report: pd.Timestamp, banks: list[str]) -> None:
    st.subheader("Bestehende Artefakte")
    names = {}
    data = st.session_state.get("_report_names")
    if data:
        names = bank_names(data)
    community_pdf = REPORT_DIR / report.date().isoformat() / "community" / (
        f"risk_report_community_{report.date().isoformat()}.pdf"
    )
    institution_dir = REPORT_DIR / report.date().isoformat() / "institutions"
    institution_pdfs = (
        sorted(institution_dir.glob("*.pdf")) if institution_dir.exists() else []
    )
    excel_files = excel_paths(report)
    bundle = csv_bundle_path(report)
    qlik_files = qlik_paths(report)
    if not community_pdf.exists() and not institution_pdfs and not excel_files and not bundle.exists():
        empty_state("Für diesen Berichtsstichtag existieren noch keine Artefakte. Erstellen Sie oben Berichte.")
        return

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**PDF-Berichte**")
            if community_pdf.exists():
                render_download(community_pdf, "Berichtsgemeinschaft (alle Institute)", "pdf_community", "application/pdf")
            visible = [
                path for path in institution_pdfs
                if not banks or path.stem.split("_")[2] in banks
            ]
            for path in visible:
                bank_id = path.stem.replace("risk_report_", "").replace(f"_{report.date().isoformat()}", "")
                label = f"{bank_id} - {names.get(bank_id, 'Institut')} (Institutsbericht)"
                render_download(path, label, f"pdf_{bank_id}", "application/pdf")
            if not community_pdf.exists() and not visible:
                st.caption("Für die ausgewählten Institute wurden keine PDF-Berichte gefunden.")
    with right:
        with st.container(border=True):
            st.markdown("**Excel-Arbeitsmappen**")
            if excel_files:
                for path in excel_files:
                    render_download(path, path.name, f"xlsx_{path.stem}")
            else:
                st.caption("Es wurden keine Excel-Arbeitsmappen gefunden.")
            st.markdown("**CSV-Paket**")
            if bundle.exists():
                render_download(bundle, "CSV-Paket (ZIP)", "csv_bundle", "application/zip")
            else:
                st.caption("Es wurde kein CSV-Paket gefunden.")

    with st.container(border=True):
        st.markdown("**Qlik-Datensätze**")
        if qlik_files:
            st.caption(
                "Standardisierte CSV-Datensätze für die direkte Übernahme in eine Qlik-Sense-Installation. "
                "Das Beispielladeskript liegt im Repository (qlik/load_script.qvs). "
                "In diesem Prototyp ist kein Qlik-Server angebunden."
            )
            file_table = pd.DataFrame(
                [
                    {
                        "file": path.name,
                        "size_kb": round(path.stat().st_size / 1024, 1),
                    }
                    for path in qlik_files
                    if path.is_file()
                ]
            )
            if not file_table.empty:
                st.dataframe(
                    file_table,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "file": st.column_config.TextColumn("Datei"),
                        "size_kb": st.column_config.NumberColumn("Größe (KB)", format="%.1f"),
                    },
                )
            st.download_button(
                "Qlik-Datensätze herunterladen (ZIP)",
                data=download_zip([path for path in qlik_files if path.is_file() and path.suffix == ".csv"], "qlik_datasets.zip"),
                file_name="qlik_datasets.zip",
                mime="application/zip",
                icon=":material/download:",
                width="stretch",
                key="qlik_zip",
            )
        else:
            st.caption("Für diesen Berichtsstichtag wurden keine Qlik-Exporte gefunden.")


def _log_section(report: pd.Timestamp, banks: list[str]) -> None:
    st.subheader("Berichterstellungsprotokoll")
    log = report_artifacts(report)
    if log.empty:
        empty_state("Für diesen Berichtsstichtag existieren keine Protokolleinträge.")
        return
    if banks:
        mask = log["bank_id"].isna() | log["bank_id"].astype(str).isin(banks)
        log = log[mask]
    display = log[
        [
            "report_id", "report_type", "module", "file_format", "bank_id", "reporting_date",
            "generated_at", "status", "data_version", "file_path",
        ]
    ]
    st.dataframe(
        display,
        hide_index=True,
        column_config={
            "report_id": st.column_config.TextColumn("Berichts-ID"),
            "report_type": st.column_config.TextColumn("Typ"),
            "module": st.column_config.TextColumn("Modul"),
            "file_format": st.column_config.TextColumn("Format"),
            "bank_id": st.column_config.TextColumn("Institut"),
            "reporting_date": st.column_config.DateColumn("Berichtsstichtag", format="DD.MM.YYYY"),
            "generated_at": st.column_config.DatetimeColumn("Erstellt", format="DD.MM.YYYY HH:mm"),
            "status": st.column_config.TextColumn("Status"),
            "data_version": st.column_config.TextColumn("Datenversion"),
            "file_path": st.column_config.TextColumn("Datei"),
        },
    )


def _distribution_section(report: pd.Timestamp) -> None:
    st.subheader("Simulierte Verteilung")
    data = load_data()
    distribution = data.get("distribution_log", pd.DataFrame())
    if distribution.empty:
        st.info(
            "Es existieren noch keine Verteilungseinträge. Die Verteilung wird simuliert, "
            "wenn Berichte mit aktiviertem Schalter 'Verteilung simulieren' erstellt werden."
        )
    else:
        grouped = (
            distribution.groupby(["recipient_group", "status"], as_index=False)
            .agg(entries=("distribution_id", "count"), reports=("report_id", "nunique"))
        )
        st.dataframe(
            grouped,
            hide_index=True,
            column_config={
                "recipient_group": st.column_config.TextColumn("Empfängergruppe"),
                "status": st.column_config.TextColumn("Status"),
                "entries": st.column_config.NumberColumn("Einträge"),
                "reports": st.column_config.NumberColumn("Berichte"),
            },
        )
        st.caption(
            f"Einträge insgesamt: {fmt_int(len(distribution))}. Der Kanal ist immer SIMULATED_LOCAL_FILE; "
            "es werden keine E-Mails, Freigaben oder externen Systeme kontaktiert."
        )
        with st.expander("Verteilungseinträge"):
            st.dataframe(
                distribution[
                    ["distribution_id", "report_id", "recipient_group", "channel", "status", "distributed_at"]
                ],
                hide_index=True,
            )
    manifests = sorted((REPORT_DIR / "distribution").glob("*/distribution_manifest_*.json"))
    if manifests:
        latest = manifests[-1]
        try:
            manifest = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = None
        if manifest:
            with st.expander(f"Aktuellstes Verteilungsmanifest ({latest.name})"):
                st.json({
                    key: manifest[key]
                    for key in ("generated_at", "reporting_date", "recipient_groups", "notes")
                    if key in manifest
                })
    st.caption(
        "Die Verteilung ist ein Erweiterungspunkt: Ein künftiger E-Mail- oder Enterprise-Kanal "
        "kann über dieselbe Manifest-Schnittstelle ergänzt werden. Der Prototyp verschickt "
        "bewusst nichts und legt keine Zugangsdaten offen."
    )


def _assumptions_section() -> None:
    with st.expander("Annahmen, Parameterwerte und Kennzahlendefinitionen"):
        st.markdown(
            f"- **Disclaimer:** {DISCLAIMER}\n"
            f"- **PD 12M (Modellschätzung):** {RATING_PD_DESCRIPTION} Zuordnung: "
            + ", ".join(f"{key} = {value:.1%}" for key, value in sorted(RATING_PD_MAPPING.items()))
            + "\n- **Sicherheiten-Haircuts:** "
            + COLLATERAL_HAIRCUT_DESCRIPTION
            + " Zuordnung: "
            + ", ".join(f"{key} = {value:.0%}" for key, value in sorted(COLLATERAL_HAIRCUTS.items()))
            + f"\n- **Ausfallbeobachtungsfenster:** {DEFAULT_OBSERVATION_MONTHS} Monate ab dem performenden Portfolio zu Beginn des Fensters."
            "\n- **Verlustquote:** (EAD im Ausfall - beobachtete Verwertungszahlungen) / EAD im Ausfall. "
            "Sicherheitenwerte werden gesondert ausgewiesen und nicht zu den Barverwertungen "
            "addiert, sodass Verwertungen und Sicherheitsverwertungen nie doppelt gezählt werden.\n"
            "- **Benchmarking:** Vergleichsgruppenwerte sind gewichtete Aggregate aus Zählern und "
            "Nennern der Vergleichsgruppe unter Ausschluss des Instituts selbst; ein relativer "
            "Abstand von ±10 % gilt als im Rahmen.\n"
            "- Vollständige Definitionen: `docs/metric_definitions.md` und `docs/data_quality_rules.md`."
        )


def render() -> None:
    st.title("Reporting")
    data = load_data()
    st.session_state["_report_names"] = data
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)
    quality = get_quality_summary(report.isoformat(), tuple(banks))

    tab_generate, tab_artefacts, tab_log = st.tabs(
        ["Erstellen", "Artefakte", "Protokoll & Verteilung"]
    )
    with tab_generate:
        _generate_section(report, banks, sectors)
        if quality.overall_score and quality.overall_score < 97:
            st.warning(
                f"Der Datenqualitäts-Score für diesen Berichtsstichtag beträgt "
                f"{fmt_pct(quality.overall_score / 100)}. "
                "Die Berichte bleiben gültig, sollten aber zusammen mit dem Abschnitt "
                "Datenqualität gelesen werden."
            )
    with tab_artefacts:
        _artefact_section(report, banks)
    with tab_log:
        _log_section(report, banks)
        _distribution_section(report)
        _assumptions_section()
