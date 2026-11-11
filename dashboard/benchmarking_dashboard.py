"""Benchmarking page shared by both risk modules.

Every comparison is institution vs peer group vs overall reporting community.
Peer values are weighted aggregates of peer numerators and denominators and
always exclude the institution itself from its own peer reference.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from config.peer_groups import PEER_GROUPS
from dashboard.common import (
    empty_state,
    filter_benchmark_banks,
    fmt_pct,
    get_benchmark,
    get_historical_benchmark,
    load_data,
    metric_row,
    percent_column,
    scope,
    scope_caption,
)
from benchmarking.benchmark_engine import benchmark_health_flags

FLAG_COLORS = alt.Scale(
    domain=["BETTER", "IN_LINE", "WORSE", "NO_BENCHMARK", "INFORMATION"],
    range=["#13795B", "#667085", "#B42318", "#D8E0EA", "#DCE8F7"],
)


def _selected_reference_group() -> str | None:
    """Ask for an optional single reference group used for every comparison."""
    basis = st.segmented_control(
        "Peer group basis",
        ["Configured peer groups", "Single reference group"],
        default="Configured peer groups",
        help=(
            "Configured groups use the institutional peer-group definitions. The what-if mode "
            "benchmarks every institution against the members of one selected reference group."
        ),
        key="benchmark_peer_basis",
    )
    if basis != "Single reference group":
        return None
    options = sorted(PEER_GROUPS)
    labels = {
        group: f"{group} - {PEER_GROUPS[group].description}" for group in options
    }
    return st.selectbox(
        "Reference group",
        options=options,
        format_func=lambda group: labels.get(group, group),
        key="benchmark_reference_group",
    )


def _metric_picker(detail: pd.DataFrame, key: str, default: str) -> str | None:
    metrics = detail[["metric_id", "metric_name", "module"]].drop_duplicates().sort_values(
        ["module", "metric_id"]
    )
    if metrics.empty:
        return None
    metric_ids = metrics["metric_id"].tolist()
    index = metric_ids.index(default) if default in metric_ids else 0
    return st.selectbox(
        "Benchmark metric",
        options=metric_ids,
        index=index,
        format_func=lambda value: metrics.set_index("metric_id").loc[value, "metric_name"],
        key=key,
    )


def render() -> None:
    st.title("Benchmarking")
    data = load_data()
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)

    reference_group = _selected_reference_group()
    benchmark = get_benchmark(report.isoformat(), tuple(sectors), reference_group)
    detail = filter_benchmark_banks(benchmark.detail, banks)

    if detail.empty:
        empty_state(
            "No benchmark rows are available for the selected scope. Generate synthetic data "
            "and run the ingestion pipeline first."
        )
        return

    kpis = benchmark.kpis
    metric_row(
        [
            ("Institutions benchmarked", f"{kpis.get('banks', 0)}", "Institutions with at least one comparable metric."),
            ("Metrics compared", f"{kpis.get('metrics', 0)}", "Rating & scoring and loss estimation metrics."),
            ("Better than peers", f"{kpis.get('better', 0)}", "Metrics where the institution beats its peer reference."),
            ("Worse than peers", f"{kpis.get('worse', 0)}", "Metrics where the institution trails its peer reference."),
            ("In line with peers", f"{kpis.get('in_line', 0)}", "Metrics within the configured 10% relative tolerance."),
        ]
    )
    st.caption(
        "Peer values aggregate peer numerators and denominators (weighted), never the unweighted "
        "mean of bank ratios, and exclude the institution itself. Portfolio values cover all "
        "institutions that report the metric."
        + (
            f" What-if mode: every institution is compared against {reference_group} members."
            if reference_group
            else ""
        )
    )

    with st.container(border=True):
        st.subheader("Institution vs peer group vs community")
        selected_metric = _metric_picker(detail, "benchmark_metric", "PD_12M_WEIGHTED")
        if selected_metric is None:
            empty_state("No benchmark metric is available.")
        else:
            selected = detail[detail["metric_id"] == selected_metric].copy()
            selected = selected.sort_values("bank_value")
            long = selected.melt(
                id_vars=["bank_id", "bank_name", "peer_group"],
                value_vars=["bank_value", "peer_value", "portfolio_value"],
                var_name="measure",
                value_name="value",
            )
            long["measure"] = long["measure"].map(
                {
                    "bank_value": "Institution",
                    "peer_value": "Peer group (excl. self)",
                    "portfolio_value": "Reporting community",
                }
            )
            chart = (
                alt.Chart(long)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("bank_id:N", title="Institution"),
                    y=alt.Y("value:Q", title="Metric value", axis=alt.Axis(format=".1%")),
                    color=alt.Color("measure:N", title="Reference", scale=alt.Scale(
                        domain=["Institution", "Peer group (excl. self)", "Reporting community"],
                        range=["#0B5CAD", "#0F8A7E", "#A4467A"],
                    )),
                    xOffset="measure:N",
                    tooltip=[
                        alt.Tooltip("bank_id:N", title="Institution"),
                        alt.Tooltip("bank_name:N", title="Name"),
                        alt.Tooltip("peer_group:N", title="Peer group"),
                        "measure",
                        alt.Tooltip("value:Q", title="Value", format=".2%"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(chart)
            metric_definition = benchmark.catalog[
                benchmark.catalog["metric_id"] == selected_metric
            ]
            if not metric_definition.empty:
                row = metric_definition.iloc[0]
                st.caption(
                    f"Definition: {row['description']} "
                    f"Direction: {'higher is better' if row['higher_is_better'] else 'lower is better' if row['higher_is_better'] is not None else 'informational'}."
                )

    left, right = st.columns([2, 3])
    with left:
        with st.container(border=True):
            st.subheader("Benchmark outcomes by institution")
            health = benchmark_health_flags(benchmark.detail)
            health = filter_benchmark_banks(health, banks)
            if health.empty:
                empty_state("No benchmark outcomes are available.")
            else:
                long = health.melt(
                    id_vars=["bank_id"],
                    value_vars=["better", "worse", "in_line"],
                    var_name="outcome",
                    value_name="count",
                )
                long["outcome"] = long["outcome"].map(
                    {"better": "BETTER", "worse": "WORSE", "in_line": "IN_LINE"}
                )
                chart = (
                    alt.Chart(long)
                    .mark_bar()
                    .encode(
                        x=alt.X("count:Q", title="Metrics", stack=True),
                        y=alt.Y("bank_id:N", title="Institution", sort="-x"),
                        color=alt.Color(
                            "outcome:N",
                            title="Outcome vs peers",
                            scale=alt.Scale(
                                domain=["BETTER", "IN_LINE", "WORSE"],
                                range=["#13795B", "#667085", "#B42318"],
                            ),
                        ),
                        tooltip=["bank_id", "outcome", "count"],
                    )
                    .properties(height=240)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Largest gaps to peer reference")
            gaps = benchmark.top_gaps.copy()
            gaps = filter_benchmark_banks(gaps, banks)
            if gaps.empty:
                empty_state("No peer gaps are available for the selected scope.")
            else:
                gaps["label"] = gaps["bank_id"].astype(str) + " - " + gaps["metric_name"].astype(str)
                gaps["gap_pct"] = gaps["relative_gap"]
                chart = (
                    alt.Chart(gaps.head(12))
                    .mark_bar()
                    .encode(
                        x=alt.X("gap_pct:Q", title="Relative gap to peers", axis=alt.Axis(format=".0%")),
                        y=alt.Y("label:N", sort="-x", title=None),
                        color=alt.Color(
                            "performance_flag:N",
                            title="Outcome",
                            scale=FLAG_COLORS,
                        ),
                        tooltip=[
                            alt.Tooltip("bank_id:N", title="Institution"),
                            alt.Tooltip("metric_name:N", title="Metric"),
                            alt.Tooltip("bank_value:Q", title="Institution", format=".2%"),
                            alt.Tooltip("peer_value:Q", title="Peers", format=".2%"),
                            alt.Tooltip("relative_gap:Q", title="Relative gap", format=".2%"),
                            alt.Tooltip("performance_flag:N", title="Outcome"),
                        ],
                    )
                    .properties(height=300)
                )
                st.altair_chart(chart)

    st.subheader("Peer group aggregates")
    group_summary = benchmark.peer_group_summary.copy()
    if group_summary.empty:
        empty_state("No peer group aggregates are available.")
    else:
        group_metrics = sorted(group_summary["metric_id"].unique().tolist())
        selected_group_metric = st.selectbox(
            "Peer group metric",
            options=group_metrics,
            index=group_metrics.index("PD_12M_WEIGHTED")
            if "PD_12M_WEIGHTED" in group_metrics
            else 0,
            format_func=lambda value: str(
                group_summary.loc[group_summary["metric_id"] == value, "metric_name"].iloc[0]
            ),
            key="peer_group_metric",
        )
        view = group_summary[group_summary["metric_id"] == selected_group_metric].copy()
        st.dataframe(
            view,
            hide_index=True,
            column_config={
                "peer_group": st.column_config.TextColumn("Peer group"),
                "metric_name": st.column_config.TextColumn("Metric"),
                "bank_count": st.column_config.NumberColumn("Members"),
                "numerator": st.column_config.NumberColumn("Numerator", format="compact"),
                "denominator": st.column_config.NumberColumn("Denominator", format="compact"),
                "peer_value": percent_column("Weighted peer value"),
            },
        )
        st.caption(
            "Peer group values divide the summed numerator by the summed denominator of all "
            "member institutions. Unweighted averages of bank ratios are deliberately avoided."
        )

    st.subheader("Historical benchmark comparison")
    historical = get_historical_benchmark(tuple(sectors), reference_group)
    if historical.detail.empty:
        empty_state("No historical benchmark periods are available.")
    else:
        hist_detail = historical.detail[
            historical.detail["metric_id"] == (selected_metric or "PD_12M_WEIGHTED")
        ].copy()
        hist_detail = filter_benchmark_banks(hist_detail, banks)
        hist_detail["reporting_date"] = pd.to_datetime(hist_detail["reporting_date"])
        bank_lines = hist_detail[hist_detail["bank_value"].notna()]
        portfolio_lines = (
            hist_detail[["reporting_date", "portfolio_value"]]
            .dropna()
            .drop_duplicates("reporting_date")
        )
        portfolio_lines["series"] = "Reporting community"
        bank_source = bank_lines.copy()
        bank_source["series"] = bank_source["bank_id"].astype(str)
        combined = pd.concat(
            [
                bank_source[["reporting_date", "bank_value", "series"]].rename(
                    columns={"bank_value": "value"}
                ),
                portfolio_lines.rename(columns={"portfolio_value": "value"})[
                    ["reporting_date", "value", "series"]
                ],
            ],
            ignore_index=True,
        )
        line = (
            alt.Chart(combined)
            .mark_line(point=True, strokeWidth=2)
            .encode(
                x=alt.X("reporting_date:T", title="Reporting date"),
                y=alt.Y("value:Q", title="Metric value", axis=alt.Axis(format=".1%")),
                color=alt.Color("series:N", title="Series"),
                strokeDash=alt.condition(
                    alt.datum.series == "Reporting community",
                    alt.value([5, 5]),
                    alt.value([1, 0]),
                ),
                tooltip=[
                    alt.Tooltip("reporting_date:T", title="Date", format="%d %b %Y"),
                    "series",
                    alt.Tooltip("value:Q", title="Value", format=".2%"),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(line)

        flags = historical.kpis.copy()
        if flags.empty:
            empty_state("No historical outcome counts are available.")
        else:
            flags_long = flags.melt(
                id_vars=["reporting_date"],
                value_vars=["better", "worse", "in_line"],
                var_name="outcome",
                value_name="count",
            )
            flags_long["outcome"] = flags_long["outcome"].map(
                {"better": "BETTER", "worse": "WORSE", "in_line": "IN_LINE"}
            )
            flags_long["reporting_date"] = pd.to_datetime(flags_long["reporting_date"])
            chart = (
                alt.Chart(flags_long)
                .mark_bar()
                .encode(
                    x=alt.X("reporting_date:T", title="Reporting date", timeUnit="yearquarter"),
                    y=alt.Y("count:Q", title="Benchmark outcomes", stack=True),
                    color=alt.Color(
                        "outcome:N",
                        title="Outcome vs peers",
                        scale=alt.Scale(
                            domain=["BETTER", "IN_LINE", "WORSE"],
                            range=["#13795B", "#667085", "#B42318"],
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip("reporting_date:T", title="Date", format="%d %b %Y"),
                        "outcome",
                        "count",
                    ],
                )
                .properties(height=260)
            )
            st.altair_chart(chart)

    with st.container(border=True):
        st.subheader("Benchmark detail")
        view = detail.copy()
        view = view.sort_values(["metric_id", "bank_id"])
        display = view[
            [
                "bank_id", "bank_name", "peer_group", "metric_name", "bank_value", "peer_value",
                "peer_median", "portfolio_value", "gap", "relative_gap", "rank_in_peer_group",
                "performance_flag", "portfolio_performance_flag",
            ]
        ].rename(
            columns={
                "bank_id": "Institution",
                "bank_name": "Name",
                "peer_group": "Peer group",
                "metric_name": "Metric",
                "bank_value": "Institution value",
                "peer_value": "Peer value",
                "peer_median": "Peer median",
                "portfolio_value": "Community value",
                "gap": "Gap to peers",
                "relative_gap": "Relative gap",
                "rank_in_peer_group": "Peer rank",
                "performance_flag": "Peer flag",
                "portfolio_performance_flag": "Community flag",
            }
        )
        st.dataframe(
            display,
            hide_index=True,
            column_config={
                "Institution": st.column_config.TextColumn("Institution"),
                "Name": st.column_config.TextColumn("Name"),
                "Peer group": st.column_config.TextColumn("Peer group"),
                "Metric": st.column_config.TextColumn("Metric"),
                "Institution value": percent_column("Institution"),
                "Peer value": percent_column("Peer value"),
                "Peer median": percent_column("Peer median"),
                "Community value": percent_column("Community"),
                "Gap to peers": percent_column("Gap to peers"),
                "Relative gap": percent_column("Relative gap"),
                "Peer rank": st.column_config.NumberColumn("Peer rank"),
                "Peer flag": st.column_config.TextColumn("Peer flag"),
                "Community flag": st.column_config.TextColumn("Community flag"),
            },
        )

    with st.expander("Metric catalog"):
        st.dataframe(
            benchmark.catalog,
            hide_index=True,
            column_config={
                "metric_id": st.column_config.TextColumn("Metric"),
                "metric_name": st.column_config.TextColumn("Name"),
                "module": st.column_config.TextColumn("Module"),
                "unit": st.column_config.TextColumn("Unit"),
                "higher_is_better": st.column_config.TextColumn("Direction"),
                "description": st.column_config.TextColumn("Definition"),
            },
        )

    if reference_group:
        st.info(
            "What-if mode is active: peer references were recomputed against the selected "
            "reference group for every institution. This changes the peer columns only; "
            "institution and community values are unaffected."
        )
