"""Rating and scoring page."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from config.rating_pd_mapping import RATING_SCALE
from dashboard.common import (
    empty_state,
    filter_benchmark_banks,
    fmt_eur,
    fmt_int,
    fmt_pct,
    get_benchmark,
    get_rating_module,
    metric_row,
    percent_column,
    scope,
    scope_caption,
)


def render() -> None:
    st.title("Rating and scoring")
    data = get_rating_placeholder()
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)
    rating = get_rating_module(report.isoformat(), tuple(banks), tuple(sectors))
    benchmark = get_benchmark(report.isoformat(), tuple(sectors))
    kpis = rating.kpis

    metric_row(
        [
            ("Current EAD", fmt_eur(kpis.get("total_ead")), "Sum of positive exposure at default."),
            ("Weighted PD 12M", fmt_pct(kpis.get("portfolio_pd")), "Model-based, exposure-weighted PD."),
            ("Investment-grade share", fmt_pct(kpis.get("investment_grade_share")), "EAD rated A or B."),
            ("Observed 12M default rate", fmt_pct(kpis.get("default_rate_12m")), "Cohort count rate, distinct from model PD."),
        ]
    )
    metric_row(
        [
            ("Observed 12M model PD", fmt_pct(kpis.get("model_pd_12m")), "Weighted configured PD over the default cohort's base EAD."),
            ("Rating upgrade rate", fmt_pct(kpis.get("upgrade_rate")), "Upgrades / matched rating observations."),
            ("Rating downgrade rate", fmt_pct(kpis.get("downgrade_rate")), "Downgrades / matched rating observations."),
            ("Exposures in scope", fmt_int(kpis.get("exposure_count")), "Current exposure rows."),
        ]
    )
    st.caption(
        f"Observed default cohort: {kpis.get('migration_start')} to {kpis.get('migration_end')} for migration; "
        f"12M default observation starts {rating.default_summary.iloc[0]['observation_start'] if not rating.default_summary.empty else 'n/a'}. "
        "Model PD is a configured estimate, not an observed default frequency."
    )

    left, right = st.columns([2, 3])
    with left:
        with st.container(border=True):
            st.subheader("EAD distribution by rating")
            distribution = rating.distribution.copy()
            if distribution.empty:
                empty_state("No rating distribution is available.")
            else:
                chart = (
                    alt.Chart(distribution)
                    .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                    .encode(
                        x=alt.X("rating_grade:N", title="Rating", sort=list(RATING_SCALE)),
                        y=alt.Y("share_ead:Q", title="Share of EAD", axis=alt.Axis(format=".0%")),
                        color=alt.Color("rating_grade:N", legend=None),
                        tooltip=[
                            alt.Tooltip("rating_grade:N", title="Rating"),
                            alt.Tooltip("exposure_count:Q", title="Exposures", format=",.0f"),
                            alt.Tooltip("ead:Q", title="EAD", format=",.0f"),
                            alt.Tooltip("share_ead:Q", title="Share of EAD", format=".2%"),
                            alt.Tooltip("pd_rate:Q", title="Configured PD", format=".2%"),
                        ],
                    )
                    .properties(height=300)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Portfolio PD trend")
            trend = rating.pd_trend.dropna(subset=["weighted_pd"])
            if trend.empty:
                empty_state("No PD trend is available.")
            else:
                base = alt.Chart(trend).encode(
                    x=alt.X("snapshot_date:T", title="Reporting date"),
                    tooltip=[
                        alt.Tooltip("snapshot_date:T", format="%d %b %Y", title="Date"),
                        alt.Tooltip("weighted_pd:Q", title="Weighted PD", format=".2%"),
                        alt.Tooltip("expected_default_ead:Q", title="Expected default EAD", format=",.0f"),
                    ],
                )
                line = base.mark_line(point=True, strokeWidth=2).encode(
                    y=alt.Y("weighted_pd:Q", title="Weighted PD 12M", axis=alt.Axis(format=".1%")),
                )
                st.altair_chart(line.properties(height=300))

    st.subheader("Observed default experience by rating")
    default_by_rating = rating.default_by_rating.copy()
    if default_by_rating.empty:
        empty_state("No observed default cohort is available for the selected scope.")
    else:
        default_by_rating = default_by_rating.set_index("rating_grade").reindex(RATING_SCALE).dropna(how="all").reset_index()
        long = default_by_rating.melt(
            id_vars=["rating_grade", "base_exposures", "default_count"],
            value_vars=["observed_default_rate", "model_pd_weighted"],
            var_name="measure",
            value_name="rate",
        )
        long["measure"] = long["measure"].map(
            {"observed_default_rate": "Observed default rate", "model_pd_weighted": "Model PD (weighted)"}
        )
        chart = (
            alt.Chart(long)
            .mark_bar()
            .encode(
                x=alt.X("rating_grade:N", title="Rating at observation start", sort=list(RATING_SCALE)),
                y=alt.Y("rate:Q", title="Rate", axis=alt.Axis(format=".1%")),
                color=alt.Color("measure:N", title="Measure", scale=alt.Scale(
                    domain=["Observed default rate", "Model PD (weighted)"], range=["#C0504D", "#0B5CAD"]
                )),
                xOffset="measure:N",
                tooltip=[
                    alt.Tooltip("rating_grade:N", title="Rating"),
                    "measure",
                    alt.Tooltip("rate:Q", title="Rate", format=".2%"),
                    alt.Tooltip("base_exposures:Q", title="Base exposures", format=",.0f"),
                    alt.Tooltip("default_count:Q", title="Defaults", format=",.0f"),
                ],
            )
            .properties(height=300)
        )
        st.altair_chart(chart)

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Default rate by institution")
            by_bank = rating.default_by_bank.copy()
            if by_bank.empty:
                empty_state("No institution default detail is available.")
            else:
                long = by_bank.melt(
                    id_vars=["bank_id", "base_exposures", "default_count"],
                    value_vars=["observed_default_rate", "model_pd_weighted"],
                    var_name="measure",
                    value_name="rate",
                )
                long["measure"] = long["measure"].map(
                    {"observed_default_rate": "Observed", "model_pd_weighted": "Model"}
                )
                chart = (
                    alt.Chart(long)
                    .mark_bar()
                    .encode(
                        x=alt.X("bank_id:N", title="Institution", sort="-y"),
                        y=alt.Y("rate:Q", title="Rate", axis=alt.Axis(format=".1%")),
                        color=alt.Color("measure:N", title="Measure"),
                        xOffset="measure:N",
                        tooltip=["bank_id", "measure", alt.Tooltip("rate:Q", format=".2%")],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("PD by industry sector")
            sector_pd = rating.pd_by_sector.dropna(subset=["weighted_pd"]).sort_values("weighted_pd", ascending=False)
            if sector_pd.empty:
                empty_state("No sector detail is available.")
            else:
                chart = (
                    alt.Chart(sector_pd)
                    .mark_bar()
                    .encode(
                        x=alt.X("weighted_pd:Q", title="Weighted PD", axis=alt.Axis(format=".1%")),
                        y=alt.Y("industry_sector:N", title=None, sort="-x"),
                        tooltip=[
                            "industry_sector",
                            alt.Tooltip("weighted_pd:Q", title="Weighted PD", format=".2%"),
                            alt.Tooltip("ead:Q", title="EAD", format=",.0f"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)

    with st.container(border=True):
        st.subheader("Rating distribution detail")
        st.dataframe(
            rating.distribution,
            hide_index=True,
            column_config={
                "rating_grade": st.column_config.TextColumn("Rating"),
                "exposure_count": st.column_config.NumberColumn("Exposures", format="localized"),
                "ead": st.column_config.NumberColumn("EAD", format="compact"),
                "share_count": percent_column("Share of count"),
                "share_ead": percent_column("Share of EAD"),
                "pd_rate": percent_column("Configured PD"),
                "expected_default_ead": st.column_config.NumberColumn("Expected default EAD", format="compact"),
            },
        )

    st.subheader("Rating migration")
    migration = rating.migration
    if migration.matrix_counts.empty or migration.summary.get("matched_count", 0) == 0:
        empty_state("No matched rating observations are available for the migration period.")
    else:
        st.caption(
            f"Matched observations: {migration.summary['matched_count']:,} between "
            f"{migration.start_date.date()} and {migration.end_date.date()}. "
            f"Upgrades {migration.summary['upgrades']:,}; downgrades {migration.summary['downgrades']:,}; "
            f"unchanged {migration.summary['unchanged']:,}. Entries and exits are excluded from the matrix."
        )
        counts = migration.matrix_counts.stack().reset_index()
        counts.columns = ["base_rating", "target_rating", "count"]
        shares = migration.matrix_pct.stack().reset_index()
        shares.columns = ["base_rating", "target_rating", "share"]
        matrix = counts.merge(shares, on=["base_rating", "target_rating"])
        matrix["base_rating_order"] = matrix["base_rating"].map({rating_: index for index, rating_ in enumerate(RATING_SCALE)})
        matrix["target_rating_order"] = matrix["target_rating"].map({rating_: index for index, rating_ in enumerate(RATING_SCALE)})
        base = alt.Chart(matrix).encode(
            x=alt.X("target_rating:N", title="Rating at end", sort=list(RATING_SCALE)),
            y=alt.Y("base_rating:N", title="Rating at start", sort=list(RATING_SCALE)),
        )
        heatmap = base.mark_rect().encode(
            color=alt.Color("share:Q", title="Row share", scale=alt.Scale(scheme="blues")),
            tooltip=[
                alt.Tooltip("base_rating:N", title="From"),
                alt.Tooltip("target_rating:N", title="To"),
                alt.Tooltip("count:Q", title="Exposures", format=",.0f"),
                alt.Tooltip("share:Q", title="Row share", format=".2%"),
            ],
        )
        text = base.mark_text(baseline="middle").encode(
            text=alt.Text("count:Q", format=",.0f"),
            color=alt.condition(alt.datum.share > 0.4, alt.value("white"), alt.value("#172033")),
        )
        st.altair_chart((heatmap + text).properties(height=320))

        with st.expander("Migration by institution"):
            if migration.by_bank.empty:
                empty_state("No institution migration detail is available.")
            else:
                st.dataframe(
                    migration.by_bank,
                    hide_index=True,
                    column_config={
                        "bank_id": st.column_config.TextColumn("Institution"),
                        "base_count": st.column_config.NumberColumn("Start observations"),
                        "target_count": st.column_config.NumberColumn("End observations"),
                        "matched_count": st.column_config.NumberColumn("Matched"),
                        "upgrades": st.column_config.NumberColumn("Upgrades"),
                        "downgrades": st.column_config.NumberColumn("Downgrades"),
                        "unchanged": st.column_config.NumberColumn("Unchanged"),
                        "upgrade_rate": percent_column("Upgrade rate"),
                        "downgrade_rate": percent_column("Downgrade rate"),
                    },
                )

    st.subheader("Benchmark comparison")
    detail = filter_benchmark_banks(benchmark.detail, banks)
    detail = detail[detail["module"] == "rating"]
    if detail.empty:
        empty_state("No rating benchmark rows are available.")
    else:
        metrics = detail[["metric_id", "metric_name"]].drop_duplicates().sort_values("metric_id")
        metric_ids = metrics["metric_id"].tolist()
        selected_metric = st.selectbox(
            "Benchmark metric",
            options=metric_ids,
            index=metric_ids.index("PD_12M_WEIGHTED") if "PD_12M_WEIGHTED" in metric_ids else 0,
            format_func=lambda value: metrics.set_index("metric_id").loc[value, "metric_name"],
            key="rating_benchmark_metric",
        )
        selected = detail[detail["metric_id"] == selected_metric].copy()
        selected = selected.sort_values("bank_value", ascending=not bool(selected.iloc[0]["higher_is_better"]))
        display = selected[
            [
                "bank_id", "bank_name", "bank_value", "peer_group", "peer_value", "peer_median",
                "portfolio_value", "gap", "relative_gap", "rank_in_peer_group",
                "portfolio_rank", "performance_flag", "portfolio_performance_flag",
            ]
        ].rename(
            columns={
                "bank_value": "Institution value",
                "peer_value": "Peer group value",
                "peer_median": "Peer median",
                "portfolio_value": "Portfolio value",
                "gap": "Gap to peers",
                "relative_gap": "Relative gap",
                "rank_in_peer_group": "Peer rank",
                "portfolio_rank": "Portfolio rank",
                "performance_flag": "Peer flag",
                "portfolio_performance_flag": "Portfolio flag",
            }
        )
        st.dataframe(
            display,
            hide_index=True,
            column_config={
                "bank_id": st.column_config.TextColumn("Institution"),
                "bank_name": st.column_config.TextColumn("Name"),
                "Institution value": percent_column("Institution"),
                "peer_group": st.column_config.TextColumn("Peer group"),
                "Peer group value": percent_column("Peer group"),
                "Peer median": percent_column("Peer median"),
                "Portfolio value": percent_column("Portfolio"),
                "Gap to peers": percent_column("Gap to peers"),
                "Relative gap": percent_column("Relative gap"),
                "Peer rank": st.column_config.NumberColumn("Peer rank"),
                "Portfolio rank": st.column_config.NumberColumn("Portfolio rank"),
                "Peer flag": st.column_config.TextColumn("Peer flag"),
                "Portfolio flag": st.column_config.TextColumn("Portfolio flag"),
            },
        )
        st.caption(
            "Peer values are weighted aggregates of peer numerators and denominators and exclude the "
            "institution itself. Portfolio values include all institutions for the metric."
        )


def get_rating_placeholder() -> dict[str, pd.DataFrame]:
    """Load cached data lazily to keep the page importable without a database."""
    from dashboard.common import load_data

    return load_data()
