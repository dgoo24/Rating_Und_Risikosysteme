"""Seite Datenqualität."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.common import (
    empty_state,
    fmt_int,
    fmt_pct,
    get_quality_summary,
    load_data,
    metric_row,
    percent_column,
    scope,
    scope_caption,
)
from quality.quality_report import quality_by_period

SEVERITY_COLORS = alt.Scale(
    domain=["ERROR", "WARNING"],
    range=["#E6001E", "#F5A623"],
)


def render() -> None:
    st.title("Datenqualität")
    data = load_data()
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)

    quality = get_quality_summary(report.isoformat(), tuple(banks))
    metric_row(
        [
            ("Qualitäts-Score", fmt_pct(quality.overall_score / 100 if quality.overall_score else None), "Gültige Zeilen / empfangene Zeilen über alle abgeschlossenen Batches."),
            ("Abgeschlossene Batches", fmt_int(quality.batches_completed), "Batches, die den Pipeline-Abschluss erreicht haben."),
            ("Empfangene Zeilen", fmt_int(quality.rows_received), "Von den Quelldateien gelieferte Zeilen."),
            ("Abgelehnte Zeilen", fmt_int(quality.rows_rejected), "Durch Qualitätsregeln blockierte Zeilen."),
            ("Fehlerbefunde", fmt_int(quality.error_count), "Blockierende Befunde aus der Regelausführung."),
            ("Warnbefunde", fmt_int(quality.warning_count), "Nicht blockierende Befunde, die zur Prüfung verbleiben."),
            ("Quarantäne-Datensätze", fmt_int(quality.quarantined_records), "Isolierte statt geladene Datensätze."),
        ]
    )
    st.caption(
        "Der Score ist eine Vollständigkeitsmessung auf Zeilenebene, keine Zertifizierung. Ein Datensatz "
        "kann mehrere Befunde erzeugen, bevor er in Quarantäne geht. Exakte Definitionen enthält das Regelwerk."
    )

    if quality.batches_completed == 0:
        empty_state(
            "Für den ausgewählten Berichtsstichtag existieren keine abgeschlossenen Qualitäts-Batches. "
            "Nutzen Sie den Stichtagsfilter, um einen anderen Zeitraum zu prüfen."
        )

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Befunde nach Kategorie")
            if quality.by_category.empty:
                empty_state("Für den ausgewählten Umfang liegen keine Befunde vor.")
            else:
                chart = (
                    alt.Chart(quality.by_category)
                    .mark_bar()
                    .encode(
                        x=alt.X("findings:Q", title="Befunde"),
                        y=alt.Y("category:N", title=None, sort="-x"),
                        color=alt.Color("severity:N", title="Schweregrad", scale=SEVERITY_COLORS),
                        tooltip=["category", "severity", "findings", "affected_records"],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Befunde im Zeitverlauf")
            findings_all = data["quality_findings"]
            if not findings_all.empty:
                findings_all = findings_all[
                    findings_all["bank_id"].astype(str).isin(banks)
                ].copy()
            trend = quality_by_period(findings_all)
            if trend.empty:
                empty_state("Es ist kein Qualitätsverlauf verfügbar.")
            else:
                trend["period"] = pd.to_datetime(trend["reporting_date"]).dt.to_period("Q").astype(str)
                grouped = (
                    trend.groupby(["period", "bank_id"], as_index=False)
                    .agg(errors=("errors", "sum"), warnings=("warnings", "sum"))
                )
                long = grouped.melt(id_vars=["period", "bank_id"], var_name="severity", value_name="findings")
                long["severity"] = long["severity"].map({"errors": "Fehler", "warnings": "Warnungen"})
                chart = (
                    alt.Chart(long)
                    .mark_bar()
                    .encode(
                        x=alt.X("period:N", title="Berichtsquartal"),
                        y=alt.Y("findings:Q", title="Befunde", stack=True),
                        color=alt.Color("severity:N", title="Schweregrad", scale=alt.Scale(
                            domain=["Fehler", "Warnungen"], range=["#E6001E", "#F5A623"]
                        )),
                        tooltip=["period", "bank_id", "severity", "findings"],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)

    if not quality.by_bank.empty:
        with st.container(border=True):
            st.subheader("Qualität nach Institut")
            display = quality.by_bank.copy()
            st.dataframe(
                display,
                hide_index=True,
                column_config={
                    "bank_id": st.column_config.TextColumn("Institut"),
                    "batches": st.column_config.NumberColumn("Batches"),
                    "rows_received": st.column_config.NumberColumn("Empfangen", format="localized"),
                    "rows_valid": st.column_config.NumberColumn("Gültig", format="localized"),
                    "rows_rejected": st.column_config.NumberColumn("Abgelehnt", format="localized"),
                    "quality_score": st.column_config.NumberColumn("Qualitäts-Score", format="%.2f%%"),
                    "error_findings": st.column_config.NumberColumn("Fehler"),
                    "warning_findings": st.column_config.NumberColumn("Warnungen"),
                },
            )

    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.subheader("Befunde je Regel")
            if quality.by_rule.empty:
                empty_state("Für den ausgewählten Umfang liegen keine Regelbefunde vor.")
            else:
                st.dataframe(
                    quality.by_rule,
                    hide_index=True,
                    column_config={
                        "rule_id": st.column_config.TextColumn("Regel"),
                        "rule_name": st.column_config.TextColumn("Name"),
                        "dataset_type": st.column_config.TextColumn("Datensatz"),
                        "category": st.column_config.TextColumn("Kategorie"),
                        "severity": st.column_config.TextColumn("Schweregrad"),
                        "findings": st.column_config.NumberColumn("Befunde"),
                        "affected_records": st.column_config.NumberColumn("Datensätze"),
                    },
                )
    with right:
        with st.container(border=True):
            st.subheader("Quarantäne nach Datensatz")
            if quality.quarantine.empty:
                empty_state("Für den ausgewählten Umfang liegen keine Quarantäne-Datensätze vor.")
            else:
                st.dataframe(
                    quality.quarantine,
                    hide_index=True,
                    column_config={
                        "bank_id": st.column_config.TextColumn("Institut"),
                        "dataset_type": st.column_config.TextColumn("Datensatz"),
                        "quarantined_records": st.column_config.NumberColumn("Datensätze"),
                    },
                )

    with st.expander("Befunddetails und Quarantäne-Register", on_change="rerun") as details:
        if details.open:
            if quality.findings.empty:
                empty_state("Für diesen Umfang sind keine Befunddetails verfügbar.")
            else:
                st.markdown("**Befunde**")
                severities = st.multiselect(
                    "Schweregrad",
                    options=sorted(quality.findings["severity"].dropna().unique().tolist()),
                    default=sorted(quality.findings["severity"].dropna().unique().tolist()),
                    key="quality_severities",
                )
                datasets = st.multiselect(
                    "Datensatz",
                    options=sorted(quality.findings["dataset_type"].dropna().unique().tolist()),
                    default=sorted(quality.findings["dataset_type"].dropna().unique().tolist()),
                    key="quality_datasets",
                )
                finding_display = quality.findings[
                    quality.findings["severity"].isin(severities)
                    & quality.findings["dataset_type"].isin(datasets)
                ]
                st.dataframe(
                    finding_display[
                        [
                            "quality_result_id", "batch_id", "dataset_type", "bank_id", "record_id",
                            "rule_id", "rule_name", "category", "severity", "field_name",
                            "failed_value", "reason", "execution_timestamp",
                        ]
                    ],
                    hide_index=True,
                )
            if not quality.quarantine_records.empty:
                st.markdown("**Quarantäne-Register**")
                st.dataframe(
                    quality.quarantine_records[
                        [
                            "quarantine_id", "batch_id", "dataset_type", "bank_id", "record_id",
                            "rule_ids", "severity", "reason", "quarantined_at", "record_json",
                        ]
                    ],
                    hide_index=True,
                )

    with st.expander("Regelwerk"):
        if quality.catalog.empty:
            empty_state("Das Regelwerk ist leer.")
        else:
            st.dataframe(
                quality.catalog,
                hide_index=True,
                column_config={
                    "rule_id": st.column_config.TextColumn("Regel"),
                    "rule_name": st.column_config.TextColumn("Name"),
                    "dataset_type": st.column_config.TextColumn("Datensatz"),
                    "category": st.column_config.TextColumn("Kategorie"),
                    "severity": st.column_config.TextColumn("Schweregrad"),
                    "description": st.column_config.TextColumn("Beschreibung"),
                },
            )
