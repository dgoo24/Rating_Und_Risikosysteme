"""Seite Datenübernahme."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from dashboard.common import (
    empty_state,
    fmt_int,
    get_quality_summary,
    load_data,
    metric_row,
    percent_column,
    scope,
    scope_caption,
)


def render() -> None:
    st.title("Datenübernahme")
    data = load_data()
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)

    batches = data["batches"].copy()
    runs = data["pipeline_runs"].copy()
    if batches.empty:
        empty_state("Es sind keine Aufnahme-Batches verfügbar. Starten Sie zuerst die Aufnahmepipeline.")
        return
    batches["reporting_date"] = pd.to_datetime(batches["reporting_date"], errors="coerce").dt.normalize()
    batches["import_timestamp"] = pd.to_datetime(batches["import_timestamp"], errors="coerce")

    view = st.segmented_control(
        "Historienfenster",
        ["Ausgewählter Berichtsstichtag", "Gesamte Batch-Historie"],
        default="Ausgewählter Berichtsstichtag",
        key="ingestion_view",
    )
    scoped = batches if view == "Gesamte Batch-Historie" else batches[batches["reporting_date"] == report]
    scoped = scoped[scoped["bank_id"].astype(str).isin(banks)]
    if scoped.empty:
        empty_state("Keine Batches passen zum ausgewählten Berichtsstichtag und den Instituten.")
        return

    completed = scoped[scoped["status"] == "COMPLETED"]
    skipped = scoped[scoped["status"] == "SKIPPED_DUPLICATE"]
    quality = get_quality_summary(report.isoformat(), tuple(banks))

    metric_row(
        [
            ("Abgeschlossene Batches", fmt_int(len(completed)), "In die kuratierte Schicht geladene Batches."),
            ("Empfangene Zeilen", fmt_int(completed["rows_received"].sum()), "Rohdaten-Zeilen über alle abgeschlossenen Batches."),
            ("Gültige Zeilen", fmt_int(completed["rows_valid"].sum()), "Zeilen, die die blockierenden Qualitätsregeln bestanden haben."),
            ("Abgelehnte Zeilen", fmt_int(completed["rows_rejected"].sum()), "Zeilen, die gegen blockierende Qualitätsregeln verstoßen haben."),
            ("Zeilen mit Warnung", fmt_int(completed["rows_warned"].sum()), "Zeilen mit nicht blockierenden Qualitätsbefunden."),
            ("Übersprungene Duplikate", fmt_int(len(skipped)), "Dateien, die übersprungen wurden, weil der Quell-Hash bereits geladen war."),
        ]
    )

    st.caption(
        "Jede Quelldatei wird vor dem Laden gehasht. Ein wiederholter Datei-Hash wird als "
        "SKIPPED_DUPLICATE erfasst statt stillschweigend angehängt - dadurch bleibt die Pipeline "
        "idempotent."
    )

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Zeilen nach Datensatz")
            chart_data = (
                completed.groupby("dataset_type", as_index=False)
                .agg(received=("rows_received", "sum"), valid=("rows_valid", "sum"), rejected=("rows_rejected", "sum"))
                .melt(id_vars="dataset_type", var_name="measure", value_name="rows")
            )
            if chart_data.empty:
                empty_state("Im Umfang liegen keine abgeschlossenen Batches vor.")
            else:
                chart_data["measure"] = chart_data["measure"].map(
                    {"received": "Empfangen", "valid": "Gültig", "rejected": "Abgelehnt"}
                )
                chart = (
                    alt.Chart(chart_data)
                    .mark_bar()
                    .encode(
                        x=alt.X("dataset_type:N", title="Datensatz", sort="-y"),
                        y=alt.Y("rows:Q", title="Zeilen"),
                        color=alt.Color("measure:N", title="Messgröße", scale=alt.Scale(
                            domain=["Empfangen", "Gültig", "Abgelehnt"],
                            range=["#454957", "#13795B", "#E6001E"],
                        )),
                        xOffset="measure:N",
                        tooltip=["dataset_type", "measure", alt.Tooltip("rows:Q", format=",.0f")],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Qualitäts-Scores der Batches")
            score_data = completed.dropna(subset=["quality_score"]).sort_values("import_timestamp")
            if score_data.empty:
                empty_state("Es sind keine Qualitäts-Scores verfügbar.")
            else:
                chart = (
                    alt.Chart(score_data)
                    .mark_circle(size=90, opacity=0.85)
                    .encode(
                        x=alt.X("import_timestamp:T", title="Importzeitpunkt"),
                        y=alt.Y("quality_score:Q", title="Qualitäts-Score", scale=alt.Scale(domain=[90, 100])),
                        color=alt.Color("dataset_type:N", title="Datensatz"),
                        tooltip=[
                            alt.Tooltip("batch_id:N", title="Batch"),
                            alt.Tooltip("bank_id:N", title="Institut"),
                            alt.Tooltip("dataset_type:N", title="Datensatz"),
                            alt.Tooltip("quality_score:Q", title="Score", format=".2f"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)

    with st.container(border=True):
        st.subheader("Batch-Register")
        display = scoped.sort_values(["reporting_date", "bank_id", "dataset_type"], ascending=[False, True, True]).copy()
        st.dataframe(
            display[
                [
                    "batch_id", "reporting_date", "bank_id", "dataset_type", "source_system",
                    "status", "rows_received", "rows_valid", "rows_rejected", "rows_warned",
                    "quality_score", "import_timestamp", "pipeline_run_id", "source_file",
                ]
            ],
            hide_index=True,
            column_config={
                "batch_id": st.column_config.TextColumn("Batch"),
                "reporting_date": st.column_config.DateColumn("Berichtsstichtag", format="DD.MM.YYYY"),
                "bank_id": st.column_config.TextColumn("Institut"),
                "dataset_type": st.column_config.TextColumn("Datensatz"),
                "source_system": st.column_config.TextColumn("Quellsystem"),
                "status": st.column_config.TextColumn("Status"),
                "rows_received": st.column_config.NumberColumn("Empfangen", format="localized"),
                "rows_valid": st.column_config.NumberColumn("Gültig", format="localized"),
                "rows_rejected": st.column_config.NumberColumn("Abgelehnt", format="localized"),
                "rows_warned": st.column_config.NumberColumn("Warnungen", format="localized"),
                "quality_score": st.column_config.NumberColumn("Qualitäts-Score", format="%.2f"),
                "import_timestamp": st.column_config.DatetimeColumn("Importiert", format="DD.MM.YYYY HH:mm"),
                "pipeline_run_id": st.column_config.TextColumn("Pipeline-Lauf"),
                "source_file": st.column_config.TextColumn("Quelldatei"),
            },
        )

    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.subheader("Pipeline-Läufe")
            if runs.empty:
                empty_state("Es wurden keine Pipeline-Läufe aufgezeichnet.")
            else:
                run_display = runs.sort_values("started_at", ascending=False).copy()
                run_display["duration_seconds"] = (
                    pd.to_datetime(run_display["finished_at"]) - pd.to_datetime(run_display["started_at"])
                ).dt.total_seconds()
                st.dataframe(
                    run_display[
                        [
                            "pipeline_run_id", "started_at", "finished_at", "status", "batches_attempted",
                            "batches_completed", "rows_received", "rows_valid", "rows_rejected", "duration_seconds",
                        ]
                    ],
                    hide_index=True,
                    column_config={
                        "pipeline_run_id": st.column_config.TextColumn("Pipeline-Lauf"),
                        "started_at": st.column_config.DatetimeColumn("Gestartet", format="DD.MM.YYYY HH:mm"),
                        "finished_at": st.column_config.DatetimeColumn("Beendet", format="DD.MM.YYYY HH:mm"),
                        "status": st.column_config.TextColumn("Status"),
                        "batches_attempted": st.column_config.NumberColumn("Versucht"),
                        "batches_completed": st.column_config.NumberColumn("Abgeschlossen"),
                        "rows_received": st.column_config.NumberColumn("Empfangen", format="localized"),
                        "rows_valid": st.column_config.NumberColumn("Gültig", format="localized"),
                        "rows_rejected": st.column_config.NumberColumn("Abgelehnt", format="localized"),
                        "duration_seconds": st.column_config.NumberColumn("Dauer (s)", format="%.1f"),
                    },
                )
    with right:
        with st.container(border=True):
            st.subheader("Quellsystem-Abdeckung")
            coverage = (
                completed.groupby(["source_system", "dataset_type"], as_index=False)
                .agg(batches=("batch_id", "nunique"), rows=("rows_valid", "sum"))
                .sort_values(["source_system", "dataset_type"])
            )
            st.dataframe(
                coverage,
                hide_index=True,
                column_config={
                    "source_system": st.column_config.TextColumn("Quellsystem"),
                    "dataset_type": st.column_config.TextColumn("Datensatz"),
                    "batches": st.column_config.NumberColumn("Batches"),
                    "rows": st.column_config.NumberColumn("Gültige Zeilen", format="localized"),
                },
            )
            st.caption(
                f"Qualitätsbefunde für den ausgewählten Stichtag: {fmt_int(quality.finding_count)}; "
                f"Quarantäne-Datensätze: {fmt_int(quality.quarantined_records)}."
            )

    with st.expander("Prüffelder auf Dateiebene"):
        st.markdown(
            "Jeder Batch führt den Quelldateinamen, den SHA-256-Datei-Hash, den Archivpfad der "
            "Rohdaten und die Batch-ID mit. Diese Felder sichern die Reproduzierbarkeit und "
            "erlauben es, einen transformierten Datensatz bis zur ursprünglichen Lieferung "
            "zurückzuverfolgen. Duplikat-Hashes werden mit dem Status `SKIPPED_DUPLICATE` erfasst."
        )
        hashes = scoped[["batch_id", "file_hash", "raw_archive_path", "error_message"]]
        st.dataframe(hashes, hide_index=True)
