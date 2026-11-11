"""Data quality page."""
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


def render() -> None:
    st.title("Data quality")
    data = load_data()
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)

    quality = get_quality_summary(report.isoformat(), tuple(banks))
    metric_row(
        [
            ("Quality score", f"{quality.overall_score:,.2f}%", "Valid rows / received rows for completed batches."),
            ("Completed batches", fmt_int(quality.batches_completed), "Batches that passed pipeline completion."),
            ("Rows received", fmt_int(quality.rows_received), "Rows delivered by source files."),
            ("Rows rejected", fmt_int(quality.rows_rejected), "Rows blocked by quality rules."),
            ("Error findings", fmt_int(quality.error_count), "Blocking findings recorded by rule execution."),
            ("Warning findings", fmt_int(quality.warning_count), "Non-blocking findings retained for review."),
            ("Quarantined records", fmt_int(quality.quarantined_records), "Records isolated rather than loaded."),
        ]
    )
    st.caption(
        "The score is a row-level completeness measure, not a certification. A record can generate several "
        "findings before it is quarantined. See the rule catalog for exact definitions."
    )

    if quality.batches_completed == 0:
        empty_state(
            "No completed quality batches exist for the selected reporting date. "
            "Use the reporting-date filter to inspect another period."
        )

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Findings by category")
            if quality.by_category.empty:
                empty_state("No findings for the selected scope.")
            else:
                chart = (
                    alt.Chart(quality.by_category)
                    .mark_bar()
                    .encode(
                        x=alt.X("findings:Q", title="Findings"),
                        y=alt.Y("category:N", title=None, sort="-x"),
                        color=alt.Color("severity:N", title="Severity", scale=alt.Scale(
                            domain=["ERROR", "WARNING"], range=["#B42318", "#D08A1D"]
                        )),
                        tooltip=["category", "severity", "findings", "affected_records"],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Findings over time")
            findings_all = data["quality_findings"]
            if not findings_all.empty:
                findings_all = findings_all[
                    findings_all["bank_id"].astype(str).isin(banks)
                ].copy()
            trend = quality_by_period(findings_all)
            if trend.empty:
                empty_state("No quality trend is available.")
            else:
                trend["period"] = pd.to_datetime(trend["reporting_date"]).dt.to_period("Q").astype(str)
                grouped = (
                    trend.groupby(["period", "bank_id"], as_index=False)
                    .agg(errors=("errors", "sum"), warnings=("warnings", "sum"))
                )
                long = grouped.melt(id_vars=["period", "bank_id"], var_name="severity", value_name="findings")
                chart = (
                    alt.Chart(long)
                    .mark_bar()
                    .encode(
                        x=alt.X("period:N", title="Reporting quarter"),
                        y=alt.Y("findings:Q", title="Findings", stack=True),
                        color=alt.Color("severity:N", title="Severity", scale=alt.Scale(
                            domain=["errors", "warnings"], range=["#B42318", "#D08A1D"]
                        )),
                        tooltip=["period", "bank_id", "severity", "findings"],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)

    if not quality.by_bank.empty:
        with st.container(border=True):
            st.subheader("Quality by institution")
            display = quality.by_bank.copy()
            st.dataframe(
                display,
                hide_index=True,
                column_config={
                    "bank_id": st.column_config.TextColumn("Institution"),
                    "batches": st.column_config.NumberColumn("Batches"),
                    "rows_received": st.column_config.NumberColumn("Received", format="localized"),
                    "rows_valid": st.column_config.NumberColumn("Valid", format="localized"),
                    "rows_rejected": st.column_config.NumberColumn("Rejected", format="localized"),
                    "quality_score": st.column_config.NumberColumn("Quality score", format="%.2f%%"),
                    "error_findings": st.column_config.NumberColumn("Errors"),
                    "warning_findings": st.column_config.NumberColumn("Warnings"),
                },
            )

    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.subheader("Rule-level findings")
            if quality.by_rule.empty:
                empty_state("No rule-level findings for the selected scope.")
            else:
                st.dataframe(
                    quality.by_rule,
                    hide_index=True,
                    column_config={
                        "rule_id": st.column_config.TextColumn("Rule"),
                        "rule_name": st.column_config.TextColumn("Name"),
                        "dataset_type": st.column_config.TextColumn("Dataset"),
                        "category": st.column_config.TextColumn("Category"),
                        "severity": st.column_config.TextColumn("Severity"),
                        "findings": st.column_config.NumberColumn("Findings"),
                        "affected_records": st.column_config.NumberColumn("Records"),
                    },
                )
    with right:
        with st.container(border=True):
            st.subheader("Quarantine by dataset")
            if quality.quarantine.empty:
                empty_state("No quarantined records for the selected scope.")
            else:
                st.dataframe(
                    quality.quarantine,
                    hide_index=True,
                    column_config={
                        "bank_id": st.column_config.TextColumn("Institution"),
                        "dataset_type": st.column_config.TextColumn("Dataset"),
                        "quarantined_records": st.column_config.NumberColumn("Records"),
                    },
                )

    with st.expander("Finding detail and quarantine records", on_change="rerun") as details:
        if details.open:
            if quality.findings.empty:
                empty_state("No finding detail is available for this scope.")
            else:
                st.markdown("**Findings**")
                severities = st.multiselect(
                    "Severity",
                    options=sorted(quality.findings["severity"].dropna().unique().tolist()),
                    default=sorted(quality.findings["severity"].dropna().unique().tolist()),
                    key="quality_severities",
                )
                datasets = st.multiselect(
                    "Dataset",
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
                st.markdown("**Quarantine register**")
                st.dataframe(
                    quality.quarantine_records[
                        [
                            "quarantine_id", "batch_id", "dataset_type", "bank_id", "record_id",
                            "rule_ids", "severity", "reason", "quarantined_at", "record_json",
                        ]
                    ],
                    hide_index=True,
                )

    with st.expander("Rule catalog"):
        if quality.catalog.empty:
            empty_state("The rule catalog is empty.")
        else:
            st.dataframe(
                quality.catalog,
                hide_index=True,
                column_config={
                    "rule_id": st.column_config.TextColumn("Rule"),
                    "rule_name": st.column_config.TextColumn("Name"),
                    "dataset_type": st.column_config.TextColumn("Dataset"),
                    "category": st.column_config.TextColumn("Category"),
                    "severity": st.column_config.TextColumn("Severity"),
                    "description": st.column_config.TextColumn("Description"),
                },
            )
