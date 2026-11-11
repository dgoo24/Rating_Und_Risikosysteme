"""Reporting page: on-demand report generation, artefacts and distribution log.

The page is the dashboard entry point into the shared reporting engine used by
both risk modules. It triggers the same ``generate_reports`` service as the
command-line interface, so PDF, Excel, CSV and Qlik-ready outputs are always
produced by identical code.
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
    "pdf": "PDF report",
    "excel": "Excel workbook",
    "csv": "CSV bundle",
    "qlik": "Qlik-ready datasets",
}


def _generate_section(report: pd.Timestamp, banks: list[str], sectors: list[str]) -> None:
    st.subheader("Generate report artefacts")
    st.caption(
        "Generation uses the same reporting service as the command line "
        "(`python -m reporting.cli`). Every artefact is recorded in the report log with its "
        "data version and contributing batch IDs."
    )
    col1, col2 = st.columns(2)
    with col1:
        formats = st.pills(
            "Output formats",
            options=list(FORMAT_OPTIONS),
            format_func=lambda value: FORMAT_OPTIONS[value],
            selection_mode="multi",
            default=list(FORMAT_OPTIONS),
            key="report_formats",
        )
    with col2:
        include_community = st.toggle("Community report", value=True, key="report_community")
        include_institutions = st.toggle("Institution reports", value=True, key="report_institutions")
        simulate_distribution = st.toggle("Simulate distribution", value=True, key="report_distribution")

    if st.button(
        "Generate reports",
        type="primary",
        icon=":material/play_arrow:",
        disabled=not formats,
        width="stretch",
    ):
        progress = st.progress(0.0, "Loading curated data and building report context...")
        try:
            with st.spinner("Generating report artefacts..."):
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
            st.error(f"Report generation failed: {exc}")
            return
        progress.progress(1.0, "Completed.")

    summary = st.session_state.get("last_report_summary")
    if summary is None:
        return
    if summary.get("failures"):
        st.error(
            f"{len(summary['failures'])} artefact(s) failed. See the report log for details."
        )
    else:
        st.success(
            f"{len(summary['generated'])} artefact(s) generated for {summary['reporting_date']} "
            f"from data version {summary['data_version']}."
        )
    metric_row(
        [
            ("Artefacts generated", fmt_int(len(summary.get("generated", []))), "PDF, Excel, CSV and Qlik outputs created in this run."),
            ("Failed artefacts", fmt_int(len(summary.get("failures", []))), "Artefacts that could not be produced."),
            ("Data version", str(summary.get("data_version", "n/a")), "Pipeline run ID backing the reports."),
            ("Distribution", "Simulated" if summary.get("distribution_manifest") else "Not simulated", "Local simulation only; no external channel is contacted."),
        ]
    )
    for item in summary.get("generated", []):
        path = Path(str(item["path"]))
        if path.is_file():
            render_download(
                path,
                f"Download {path.name}",
                f"gen_{item['report_id']}",
                "application/pdf" if path.suffix == ".pdf" else None,
            )
        else:
            st.caption(f"{item['file_format']}: {path}")


def _artefact_section(report: pd.Timestamp, banks: list[str]) -> None:
    st.subheader("Existing artefacts")
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
        empty_state("No artefacts exist yet for this reporting date. Generate reports above.")
        return

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**PDF reports**")
            if community_pdf.exists():
                render_download(community_pdf, "Community report (all institutions)", "pdf_community", "application/pdf")
            visible = [
                path for path in institution_pdfs
                if not banks or path.stem.split("_")[2] in banks
            ]
            for path in visible:
                bank_id = path.stem.replace("risk_report_", "").replace(f"_{report.date().isoformat()}", "")
                label = f"{bank_id} - {names.get(bank_id, 'institution')} report"
                render_download(path, label, f"pdf_{bank_id}", "application/pdf")
            if not community_pdf.exists() and not visible:
                st.caption("No PDF reports found for the selected institutions.")
    with right:
        with st.container(border=True):
            st.markdown("**Excel workbooks**")
            if excel_files:
                for path in excel_files:
                    render_download(path, path.name, f"xlsx_{path.stem}")
            else:
                st.caption("No Excel workbooks found.")
            st.markdown("**CSV bundle**")
            if bundle.exists():
                render_download(bundle, "CSV bundle (ZIP)", "csv_bundle", "application/zip")
            else:
                st.caption("No CSV bundle found.")

    with st.container(border=True):
        st.markdown("**Qlik-ready datasets**")
        if qlik_files:
            st.caption(
                "Standardized CSV datasets for direct ingestion into a Qlik Sense deployment. "
                "The sample load script is shipped with the repository (qlik/load_script.qvs). "
                "No Qlik server is connected in this prototype."
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
                st.dataframe(file_table, hide_index=True, width="stretch")
            st.download_button(
                "Download Qlik datasets (ZIP)",
                data=download_zip([path for path in qlik_files if path.is_file() and path.suffix == ".csv"], "qlik_datasets.zip"),
                file_name="qlik_datasets.zip",
                mime="application/zip",
                icon=":material/download:",
                width="stretch",
                key="qlik_zip",
            )
        else:
            st.caption("No Qlik exports found for this reporting date.")


def _log_section(report: pd.Timestamp, banks: list[str]) -> None:
    st.subheader("Report generation log")
    log = report_artifacts(report)
    if log.empty:
        empty_state("No report generation entries exist for this reporting date.")
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
            "report_id": st.column_config.TextColumn("Report ID"),
            "report_type": st.column_config.TextColumn("Type"),
            "module": st.column_config.TextColumn("Module"),
            "file_format": st.column_config.TextColumn("Format"),
            "bank_id": st.column_config.TextColumn("Institution"),
            "reporting_date": st.column_config.DateColumn("Reporting date", format="DD MMM YYYY"),
            "generated_at": st.column_config.DatetimeColumn("Generated", format="DD MMM YYYY HH:mm"),
            "status": st.column_config.TextColumn("Status"),
            "data_version": st.column_config.TextColumn("Data version"),
            "file_path": st.column_config.TextColumn("File"),
        },
    )


def _distribution_section(report: pd.Timestamp) -> None:
    st.subheader("Simulated distribution")
    data = load_data()
    distribution = data.get("distribution_log", pd.DataFrame())
    if distribution.empty:
        st.info(
            "No distribution entries exist yet. Distribution is simulated when reports are "
            "generated with the 'Simulate distribution' toggle enabled."
        )
    else:
        grouped = (
            distribution.groupby(["recipient_group", "status"], as_index=False)
            .agg(entries=("distribution_id", "count"), reports=("report_id", "nunique"))
        )
        st.dataframe(grouped, hide_index=True)
        st.caption(
            f"Total entries: {fmt_int(len(distribution))}. Channel is always SIMULATED_LOCAL_FILE; "
            "no email, share or external system is contacted."
        )
        with st.expander("Distribution entries"):
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
            with st.expander(f"Latest distribution manifest ({latest.name})"):
                st.json({
                    key: manifest[key]
                    for key in ("generated_at", "reporting_date", "recipient_groups", "notes")
                    if key in manifest
                })
    st.caption(
        "Distribution is an extension point: a future email or enterprise channel can be added by "
        "implementing the same manifest interface. The prototype deliberately does not send "
        "anything or expose credentials."
    )


def _assumptions_section() -> None:
    with st.expander("Assumptions, parameter values and metric definitions"):
        st.markdown(
            f"- **Disclaimer:** {DISCLAIMER}\n"
            f"- **PD 12M (model estimate):** {RATING_PD_DESCRIPTION} Mapping: "
            + ", ".join(f"{key} = {value:.1%}" for key, value in sorted(RATING_PD_MAPPING.items()))
            + "\n- **Collateral haircuts:** "
            + COLLATERAL_HAIRCUT_DESCRIPTION
            + " Mapping: "
            + ", ".join(f"{key} = {value:.0%}" for key, value in sorted(COLLATERAL_HAIRCUTS.items()))
            + f"\n- **Default observation window:** {DEFAULT_OBSERVATION_MONTHS} months from the performing portfolio at the start of the window."
            "\n- **Loss rate:** (EAD at default - observed recovery cashflows) / EAD at default. "
            "Collateral values are reported separately and are not added to cash recoveries, so "
            "recoveries and collateral realizations are never double-counted.\n"
            "- **Benchmarking:** peer values are weighted aggregates of peer numerators and "
            "denominators, excluding the institution itself; ±10% relative gap is reported as in "
            "line.\n"
            "- Full definitions: `docs/metric_definitions.md` and `docs/data_quality_rules.md`."
        )


def render() -> None:
    st.title("Reporting")
    data = load_data()
    st.session_state["_report_names"] = data
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)
    quality = get_quality_summary(report.isoformat(), tuple(banks))

    tab_generate, tab_artefacts, tab_log = st.tabs(
        ["Generate", "Artefacts", "Log and distribution"]
    )
    with tab_generate:
        _generate_section(report, banks, sectors)
        if quality.overall_score and quality.overall_score < 97:
            st.warning(
                f"Data quality score for this reporting date is {quality.overall_score:.2f}%. "
                "Reports remain valid but should be read together with the data quality section."
            )
    with tab_artefacts:
        _artefact_section(report, banks)
    with tab_log:
        _log_section(report, banks)
        _distribution_section(report)
        _assumptions_section()
