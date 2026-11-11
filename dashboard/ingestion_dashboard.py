"""Data ingestion page."""
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
    st.title("Data ingestion")
    data = load_data()
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)

    batches = data["batches"].copy()
    runs = data["pipeline_runs"].copy()
    if batches.empty:
        empty_state("No ingestion batches are available. Run the ingestion pipeline first.")
        return
    batches["reporting_date"] = pd.to_datetime(batches["reporting_date"], errors="coerce").dt.normalize()
    batches["import_timestamp"] = pd.to_datetime(batches["import_timestamp"], errors="coerce")

    view = st.segmented_control(
        "History window",
        ["Selected reporting date", "All batch history"],
        default="Selected reporting date",
        key="ingestion_view",
    )
    scoped = batches if view == "All batch history" else batches[batches["reporting_date"] == report]
    scoped = scoped[scoped["bank_id"].astype(str).isin(banks)]
    if scoped.empty:
        empty_state("No batches match the selected reporting date and institutions.")
        return

    completed = scoped[scoped["status"] == "COMPLETED"]
    skipped = scoped[scoped["status"] == "SKIPPED_DUPLICATE"]
    quality = get_quality_summary(report.isoformat(), tuple(banks))

    metric_row(
        [
            ("Completed batches", fmt_int(len(completed)), "Batches loaded into the curated layer."),
            ("Rows received", fmt_int(completed["rows_received"].sum()), "Raw rows across completed batches."),
            ("Rows valid", fmt_int(completed["rows_valid"].sum()), "Rows that passed blocking quality rules."),
            ("Rows rejected", fmt_int(completed["rows_rejected"].sum()), "Rows that failed blocking quality rules."),
            ("Rows warned", fmt_int(completed["rows_warned"].sum()), "Rows with non-blocking quality findings."),
            ("Skipped duplicates", fmt_int(len(skipped)), "Files skipped because the source hash was already loaded."),
        ]
    )

    st.caption(
        "Each source file is hashed before loading. A repeated file hash is recorded as "
        "SKIPPED_DUPLICATE rather than silently appended, which keeps the pipeline idempotent."
    )

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Rows by dataset")
            chart_data = (
                completed.groupby("dataset_type", as_index=False)
                .agg(received=("rows_received", "sum"), valid=("rows_valid", "sum"), rejected=("rows_rejected", "sum"))
                .melt(id_vars="dataset_type", var_name="measure", value_name="rows")
            )
            if chart_data.empty:
                empty_state("No completed batches in scope.")
            else:
                chart = (
                    alt.Chart(chart_data)
                    .mark_bar()
                    .encode(
                        x=alt.X("dataset_type:N", title="Dataset", sort="-y"),
                        y=alt.Y("rows:Q", title="Rows"),
                        color=alt.Color("measure:N", title="Measure"),
                        xOffset="measure:N",
                        tooltip=["dataset_type", "measure", alt.Tooltip("rows:Q", format=",.0f")],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Batch quality scores")
            score_data = completed.dropna(subset=["quality_score"]).sort_values("import_timestamp")
            if score_data.empty:
                empty_state("No quality scores are available.")
            else:
                chart = (
                    alt.Chart(score_data)
                    .mark_circle(size=90, opacity=0.85)
                    .encode(
                        x=alt.X("import_timestamp:T", title="Import time"),
                        y=alt.Y("quality_score:Q", title="Quality score", scale=alt.Scale(domain=[90, 100])),
                        color=alt.Color("dataset_type:N", title="Dataset"),
                        tooltip=[
                            alt.Tooltip("batch_id:N", title="Batch"),
                            alt.Tooltip("bank_id:N", title="Institution"),
                            alt.Tooltip("dataset_type:N", title="Dataset"),
                            alt.Tooltip("quality_score:Q", title="Score", format=".2f"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)

    with st.container(border=True):
        st.subheader("Batch register")
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
                "reporting_date": st.column_config.DateColumn("Reporting date", format="DD MMM YYYY"),
                "bank_id": st.column_config.TextColumn("Institution"),
                "dataset_type": st.column_config.TextColumn("Dataset"),
                "source_system": st.column_config.TextColumn("Source system"),
                "status": st.column_config.TextColumn("Status"),
                "rows_received": st.column_config.NumberColumn("Received", format="localized"),
                "rows_valid": st.column_config.NumberColumn("Valid", format="localized"),
                "rows_rejected": st.column_config.NumberColumn("Rejected", format="localized"),
                "rows_warned": st.column_config.NumberColumn("Warned", format="localized"),
                "quality_score": st.column_config.NumberColumn("Quality score", format="%.2f"),
                "import_timestamp": st.column_config.DatetimeColumn("Imported", format="DD MMM YYYY HH:mm"),
                "pipeline_run_id": st.column_config.TextColumn("Pipeline run"),
                "source_file": st.column_config.TextColumn("Source file"),
            },
        )

    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.subheader("Pipeline runs")
            if runs.empty:
                empty_state("No pipeline runs have been recorded.")
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
                        "pipeline_run_id": st.column_config.TextColumn("Pipeline run"),
                        "started_at": st.column_config.DatetimeColumn("Started", format="DD MMM YYYY HH:mm"),
                        "finished_at": st.column_config.DatetimeColumn("Finished", format="DD MMM YYYY HH:mm"),
                        "status": st.column_config.TextColumn("Status"),
                        "batches_attempted": st.column_config.NumberColumn("Attempted"),
                        "batches_completed": st.column_config.NumberColumn("Completed"),
                        "rows_received": st.column_config.NumberColumn("Received", format="localized"),
                        "rows_valid": st.column_config.NumberColumn("Valid", format="localized"),
                        "rows_rejected": st.column_config.NumberColumn("Rejected", format="localized"),
                        "duration_seconds": st.column_config.NumberColumn("Duration (s)", format="%.1f"),
                    },
                )
    with right:
        with st.container(border=True):
            st.subheader("Source coverage")
            coverage = (
                completed.groupby(["source_system", "dataset_type"], as_index=False)
                .agg(batches=("batch_id", "nunique"), rows=("rows_valid", "sum"))
                .sort_values(["source_system", "dataset_type"])
            )
            st.dataframe(
                coverage,
                hide_index=True,
                column_config={
                    "source_system": st.column_config.TextColumn("Source system"),
                    "dataset_type": st.column_config.TextColumn("Dataset"),
                    "batches": st.column_config.NumberColumn("Batches"),
                    "rows": st.column_config.NumberColumn("Valid rows", format="localized"),
                },
            )
            st.caption(
                f"Data quality findings for the selected date: {quality.finding_count:,}; "
                f"quarantined records: {quality.quarantined_records:,}."
            )

    with st.expander("File-level audit fields"):
        st.markdown(
            "Every batch keeps the source file name, SHA-256 file hash, raw archive path and batch ID. "
            "These fields support reproducibility and allow a reviewer to trace a transformed record back to "
            "its original delivery. Duplicate hashes are recorded with status `SKIPPED_DUPLICATE`."
        )
        hashes = scoped[["batch_id", "file_hash", "raw_archive_path", "error_message"]]
        st.dataframe(hashes, hide_index=True)
