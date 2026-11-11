"""Loss estimation page."""
from __future__ import annotations

import altair as alt
import streamlit as st

from dashboard.common import (
    empty_state,
    filter_benchmark_banks,
    fmt_days,
    fmt_eur,
    fmt_int,
    fmt_pct,
    get_benchmark,
    get_loss_module,
    load_data,
    metric_row,
    percent_column,
    scope,
    scope_caption,
)


def render() -> None:
    st.title("Loss estimation")
    data = load_data()
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)
    loss = get_loss_module(report.isoformat(), tuple(banks), tuple(sectors))
    benchmark = get_benchmark(report.isoformat(), tuple(sectors))
    kpis = loss.kpis

    metric_row(
        [
            ("Observed 12M recovery rate", fmt_pct(kpis.get("recovery_rate")), "Recovery cashflows / EAD at default."),
            ("Observed 12M loss rate", fmt_pct(kpis.get("loss_rate")), "Loss amount / EAD at default."),
            ("Loss amount", fmt_eur(kpis.get("loss_amount")), "EAD at default less recovery cashflows."),
            ("Defaults in cohort", fmt_int(kpis.get("default_count")), "Distinct defaulted exposures with EAD at default."),
        ]
    )
    metric_row(
        [
            ("EAD at default", fmt_eur(kpis.get("ead_at_default")), "Exposure at default for the cohort."),
            ("Adjusted collateral coverage", fmt_pct(kpis.get("collateral_coverage")), "Haircut-adjusted collateral / current EAD."),
            ("Secured EAD share", fmt_pct(kpis.get("secured_ead_share")), "Secured EAD (capped at exposure EAD) / current EAD."),
            ("Weighted recovery lag", fmt_days(kpis.get("weighted_average_days")), "Cashflow-weighted days since default."),
        ]
    )
    st.caption(
        f"Default cohort: {loss.window_start.date()} to {loss.window_end.date() if hasattr(loss, 'window_end') else report.date()} "
        f"({loss.window_months} months). Recovery and loss rates are observed cash-basis statistics for this cohort; "
        "they are not regulatory LGD estimates."
    )

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Recovery distribution")
            distribution = loss.recovery_distribution.dropna(subset=["share_ead"])
            if distribution.empty:
                empty_state("No recovery distribution is available.")
            else:
                chart = (
                    alt.Chart(distribution)
                    .mark_bar()
                    .encode(
                        x=alt.X("recovery_bucket:N", title="Recovery bucket", sort=None),
                        y=alt.Y("share_ead:Q", title="Share of EAD", axis=alt.Axis(format=".0%")),
                        color=alt.Color("recovery_bucket:N", legend=None),
                        tooltip=[
                            "recovery_bucket",
                            alt.Tooltip("default_count:Q", title="Defaults", format=",.0f"),
                            alt.Tooltip("ead_at_default:Q", title="EAD at default", format=",.0f"),
                            alt.Tooltip("share_ead:Q", title="Share of EAD", format=".2%"),
                            alt.Tooltip("average_recovery_rate:Q", title="Average recovery", format=".2%"),
                        ],
                    )
                    .properties(height=290)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Loss severity distribution")
            severity = loss.loss_severity[loss.loss_severity["default_count"] > 0]
            if severity.empty:
                empty_state("No loss severity detail is available.")
            else:
                chart = (
                    alt.Chart(severity)
                    .mark_bar()
                    .encode(
                        x=alt.X("severity:N", title="Loss severity", sort=["LOW", "MODERATE", "HIGH", "FULL_LOSS"]),
                        y=alt.Y("share_ead:Q", title="Share of EAD", axis=alt.Axis(format=".0%")),
                        color=alt.Color("severity:N", legend=None),
                        tooltip=[
                            "severity",
                            alt.Tooltip("default_count:Q", title="Defaults", format=",.0f"),
                            alt.Tooltip("loss_amount:Q", title="Loss amount", format=",.0f"),
                            alt.Tooltip("share_ead:Q", title="Share of EAD", format=".2%"),
                        ],
                    )
                    .properties(height=290)
                )
                st.altair_chart(chart)

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Recovery and loss by institution")
            by_bank = loss.by_bank.copy()
            if by_bank.empty:
                empty_state("No institution loss detail is available.")
            else:
                long = by_bank.melt(
                    id_vars=["bank_id", "default_count"],
                    value_vars=["recovery_rate", "loss_rate"],
                    var_name="measure",
                    value_name="rate",
                )
                long["measure"] = long["measure"].map(
                    {"recovery_rate": "Recovery rate", "loss_rate": "Loss rate"}
                )
                chart = (
                    alt.Chart(long)
                    .mark_bar()
                    .encode(
                        x=alt.X("bank_id:N", title="Institution", sort="-y"),
                        y=alt.Y("rate:Q", title="Rate", axis=alt.Axis(format=".0%")),
                        color=alt.Color("measure:N", title="Measure", scale=alt.Scale(
                            domain=["Recovery rate", "Loss rate"], range=["#13795B", "#B42318"]
                        )),
                        xOffset="measure:N",
                        tooltip=["bank_id", "measure", alt.Tooltip("rate:Q", format=".2%"), "default_count"],
                    )
                    .properties(height=290)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Adjusted collateral coverage by type")
            coverage = loss.collateral_by_primary_type.dropna(subset=["coverage_ratio"])
            if coverage.empty:
                empty_state("No collateral coverage detail is available.")
            else:
                chart = (
                    alt.Chart(coverage)
                    .mark_bar()
                    .encode(
                        x=alt.X("coverage_ratio:Q", title="Coverage ratio", axis=alt.Axis(format=".0%")),
                        y=alt.Y("primary_collateral_type:N", title=None, sort="-x"),
                        tooltip=[
                            "primary_collateral_type",
                            alt.Tooltip("coverage_ratio:Q", title="Coverage", format=".2%"),
                            alt.Tooltip("ead:Q", title="EAD", format=",.0f"),
                            alt.Tooltip("secured_ead_share:Q", title="Secured EAD share", format=".2%"),
                        ],
                    )
                    .properties(height=290)
                )
                st.altair_chart(chart)

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Cumulative recovery curve")
            curve = loss.recovery_curve.dropna(subset=["cumulative_recovery_rate"])
            if curve.empty:
                empty_state("No recovery curve is available.")
            else:
                chart = (
                    alt.Chart(curve)
                    .mark_line(point=True, strokeWidth=2)
                    .encode(
                        x=alt.X("months_since_default:Q", title="Months since default"),
                        y=alt.Y("cumulative_recovery_rate:Q", title="Cumulative recovery rate", axis=alt.Axis(format=".0%")),
                        tooltip=[
                            alt.Tooltip("months_since_default:Q", title="Months"),
                            alt.Tooltip("cumulative_recovery_rate:Q", title="Recovery rate", format=".2%"),
                            alt.Tooltip("cumulative_recoveries:Q", title="Recoveries", format=",.0f"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Recovery cashflows by quarter")
            cashflows = loss.cashflow_by_quarter.copy()
            if cashflows.empty:
                empty_state("No recovery cashflows are available.")
            else:
                chart = (
                    alt.Chart(cashflows)
                    .mark_bar()
                    .encode(
                        x=alt.X("payment_period:N", title="Payment quarter"),
                        y=alt.Y("recovered_amount:Q", title="Recovered amount"),
                        tooltip=[
                            "payment_period",
                            alt.Tooltip("cashflow_count:Q", title="Cashflows", format=",.0f"),
                            alt.Tooltip("recovered_amount:Q", title="Recovered amount", format=",.0f"),
                            alt.Tooltip("cumulative_share:Q", title="Cumulative share", format=".2%"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)

    with st.container(border=True):
        st.subheader("Loss and recovery detail by institution")
        by_bank = loss.by_bank.copy()
        if by_bank.empty:
            empty_state("No institution detail is available.")
        else:
            by_bank = by_bank.merge(
                loss.collateral_by_bank[["bank_id", "coverage_ratio", "secured_ead_share"]],
                on="bank_id",
                how="left",
            )
            st.dataframe(
                by_bank,
                hide_index=True,
                column_config={
                    "bank_id": st.column_config.TextColumn("Institution"),
                    "default_count": st.column_config.NumberColumn("Defaults"),
                    "ead_at_default": st.column_config.NumberColumn("EAD at default", format="compact"),
                    "total_recoveries": st.column_config.NumberColumn("Recoveries", format="compact"),
                    "recovery_count": st.column_config.NumberColumn("Cashflows"),
                    "loss_amount": st.column_config.NumberColumn("Loss amount", format="compact"),
                    "recovery_rate": percent_column("Recovery rate"),
                    "loss_rate": percent_column("Loss rate"),
                    "coverage_ratio": percent_column("Collateral coverage"),
                    "secured_ead_share": percent_column("Secured EAD share"),
                },
            )

    with st.expander("Collateral, cashflow and loss detail"):
        st.markdown("**Collateral type mix**")
        st.dataframe(
            loss.collateral_type_mix,
            hide_index=True,
            column_config={
                "collateral_value": st.column_config.NumberColumn("Collateral value", format="compact"),
                "adjusted_collateral_value": st.column_config.NumberColumn("Adjusted value", format="compact"),
                "haircut_reduction": st.column_config.NumberColumn("Haircut reduction", format="compact"),
                "average_haircut": percent_column("Average haircut"),
                "share_value": percent_column("Share of value"),
                "share_adjusted_value": percent_column("Share of adjusted value"),
            },
        )
        st.markdown("**Recovery type mix**")
        st.dataframe(
            loss.recovery_type_mix,
            hide_index=True,
            column_config={
                "recovered_amount": st.column_config.NumberColumn("Recovered amount", format="compact"),
                "share_amount": percent_column("Share of amount"),
                "average_amount": st.column_config.NumberColumn("Average amount", format="compact"),
            },
        )
        st.markdown("**Time to first recovery**")
        st.dataframe(
            loss.time_to_recovery,
            hide_index=True,
            column_config={
                "ead_at_default": st.column_config.NumberColumn("EAD at default", format="compact"),
                "recovered_amount": st.column_config.NumberColumn("Recovered amount", format="compact"),
                "share_count": percent_column("Share of defaults"),
                "share_ead": percent_column("Share of EAD"),
            },
        )
        st.markdown("**Losses by default quarter**")
        st.dataframe(
            loss.loss_by_default_quarter,
            hide_index=True,
            column_config={
                "ead_at_default": st.column_config.NumberColumn("EAD at default", format="compact"),
                "total_recoveries": st.column_config.NumberColumn("Recoveries", format="compact"),
                "loss_amount": st.column_config.NumberColumn("Loss amount", format="compact"),
                "recovery_rate": percent_column("Recovery rate"),
                "loss_rate": percent_column("Loss rate"),
            },
        )
        st.markdown("**Stale collateral valuations**")
        if loss.stale_collateral.empty:
            empty_state("No collateral items exceed the configured valuation-age warning threshold.")
        else:
            st.dataframe(
                loss.stale_collateral,
                hide_index=True,
                column_config={
                    "collateral_value": st.column_config.NumberColumn("Collateral value", format="compact"),
                    "adjusted_collateral_value": st.column_config.NumberColumn("Adjusted value", format="compact"),
                    "valuation_age_years": st.column_config.NumberColumn("Valuation age (years)", format="%.1f"),
                    "haircut": percent_column("Haircut"),
                },
            )

    st.subheader("Benchmark comparison")
    detail = filter_benchmark_banks(benchmark.detail, banks)
    detail = detail[detail["module"] == "loss"]
    if detail.empty:
        empty_state("No loss benchmark rows are available.")
    else:
        metrics = detail[["metric_id", "metric_name"]].drop_duplicates().sort_values("metric_id")
        metric_ids = metrics["metric_id"].tolist()
        selected_metric = st.selectbox(
            "Benchmark metric",
            options=metric_ids,
            index=metric_ids.index("RECOVERY_RATE_12M") if "RECOVERY_RATE_12M" in metric_ids else 0,
            format_func=lambda value: metrics.set_index("metric_id").loc[value, "metric_name"],
            key="loss_benchmark_metric",
        )
        selected = detail[detail["metric_id"] == selected_metric].copy()
        higher = selected.iloc[0]["higher_is_better"]
        selected = selected.sort_values("bank_value", ascending=not bool(higher))
        display = selected[
            [
                "bank_id", "bank_name", "bank_value", "peer_group", "peer_value", "peer_median",
                "portfolio_value", "gap", "relative_gap", "rank_in_peer_group", "performance_flag",
                "portfolio_performance_flag",
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
                "Peer flag": st.column_config.TextColumn("Peer flag"),
                "Portfolio flag": st.column_config.TextColumn("Portfolio flag"),
            },
        )
        st.caption(
            "Peer values use summed numerators and denominators of peer institutions and exclude the "
            "institution itself. Portfolio values include all available institutions."
        )
