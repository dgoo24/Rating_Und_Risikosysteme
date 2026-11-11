"""Executive overview page."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from benchmarking.benchmark_engine import benchmark_health_flags
from dashboard.common import (
    bank_names,
    empty_state,
    filter_benchmark_banks,
    fmt_days,
    fmt_eur,
    fmt_int,
    fmt_pct,
    get_benchmark,
    get_loss_module,
    get_quality_summary,
    get_rating_module,
    load_data,
    metric_row,
    percent_column,
    scope,
    scope_caption,
)


def _best_worst(frame: pd.DataFrame, column: str, names: dict[str, str], higher_is_better: bool) -> tuple[str, str]:
    data = frame.dropna(subset=[column])
    if data.empty:
        return "n/a", "n/a"
    ordered = data.sort_values(column, ascending=not higher_is_better)
    first = ordered.iloc[0]
    last = ordered.iloc[-1]
    return (
        f"{names.get(str(first['bank_id']), first['bank_id'])} ({fmt_pct(first[column])})",
        f"{names.get(str(last['bank_id']), last['bank_id'])} ({fmt_pct(last[column])})",
    )


def render() -> None:
    st.title("Executive overview")
    data = load_data()
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)

    rating = get_rating_module(report.isoformat(), tuple(banks), tuple(sectors))
    loss = get_loss_module(report.isoformat(), tuple(banks), tuple(sectors))
    quality = get_quality_summary(report.isoformat(), tuple(banks))
    benchmark = get_benchmark(report.isoformat(), tuple(sectors))

    rating_kpis = rating.kpis
    loss_kpis = loss.kpis
    pd_trend = rating.pd_trend.dropna(subset=["weighted_pd"])
    default_trend = rating.default_trend.dropna(subset=["observed_default_rate"])

    metric_row(
        [
            ("Total EAD", fmt_eur(rating_kpis.get("total_ead")), "Current exposure at default for the selected scope."),
            ("Weighted PD 12M (model estimate)", fmt_pct(rating_kpis.get("portfolio_pd")), "Sum(EAD x configured PD) / Sum(EAD)."),
            ("Investment-grade share", fmt_pct(rating_kpis.get("investment_grade_share")), "EAD rated A or B / rated EAD."),
            ("Observed 12M default rate", fmt_pct(rating_kpis.get("default_rate_12m")), "Observed defaults / performing exposures at observation start."),
        ]
    )
    metric_row(
        [
            ("Observed 12M recovery rate", fmt_pct(loss_kpis.get("recovery_rate")), "Recovery cashflows / EAD at default for the 12M cohort."),
            ("Observed 12M loss rate", fmt_pct(loss_kpis.get("loss_rate")), "Loss amount / EAD at default for the 12M cohort."),
            ("Adjusted collateral coverage", fmt_pct(loss_kpis.get("collateral_coverage")), "Haircut-adjusted collateral / current EAD."),
            ("Data quality score", fmt_pct(quality.overall_score / 100 if quality.overall_score else None), "Valid rows / received rows across completed batches."),
        ]
    )

    st.caption(
        "Model-based PD and observed default/loss rates answer different questions and are shown separately. "
        "Observed rates are cohort statistics, not forecasts."
    )

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Portfolio PD trend")
            if pd_trend.empty:
                empty_state("No PD trend is available for the selected scope.")
            else:
                chart = (
                    alt.Chart(pd_trend)
                    .mark_line(point=True, strokeWidth=2)
                    .encode(
                        x=alt.X("snapshot_date:T", title="Reporting date"),
                        y=alt.Y("weighted_pd:Q", title="Weighted PD 12M", axis=alt.Axis(format=".1%")),
                        tooltip=[
                            alt.Tooltip("snapshot_date:T", title="Date", format="%d %b %Y"),
                            alt.Tooltip("weighted_pd:Q", title="Weighted PD", format=".2%"),
                            alt.Tooltip("ead:Q", title="EAD", format=",.0f"),
                        ],
                    )
                    .properties(height=260)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Observed 12M default rate trend")
            if default_trend.empty:
                empty_state("No default-rate trend is available for the selected scope.")
            else:
                chart = (
                    alt.Chart(default_trend)
                    .mark_line(point=True, strokeWidth=2, color="#C0504D")
                    .encode(
                        x=alt.X("reporting_date:T", title="Reporting date"),
                        y=alt.Y("observed_default_rate:Q", title="Observed default rate", axis=alt.Axis(format=".1%")),
                        tooltip=[
                            alt.Tooltip("reporting_date:T", title="Date", format="%d %b %Y"),
                            alt.Tooltip("observed_default_rate:Q", title="Default rate", format=".2%"),
                            alt.Tooltip("default_count:Q", title="Defaults", format=",.0f"),
                            alt.Tooltip("base_exposures:Q", title="Base exposures", format=",.0f"),
                        ],
                    )
                    .properties(height=260)
                )
                st.altair_chart(chart)

    st.subheader("Institution scorecard")
    names = bank_names(data)
    by_bank = rating.pd_by_bank.copy()
    if not loss.by_bank.empty:
        by_bank = by_bank.merge(
            loss.by_bank[["bank_id", "recovery_rate", "loss_rate"]], on="bank_id", how="left"
        )
    if not loss.collateral_by_bank.empty:
        by_bank = by_bank.merge(
            loss.collateral_by_bank[["bank_id", "coverage_ratio", "secured_ead_share"]],
            on="bank_id",
            how="left",
        )
    if not rating.default_by_bank.empty:
        by_bank = by_bank.merge(
            rating.default_by_bank[["bank_id", "observed_default_rate", "model_pd_weighted"]],
            on="bank_id",
            how="left",
        )
    detail = filter_benchmark_banks(benchmark.detail, banks)
    health = benchmark_health_flags(detail)
    if not health.empty:
        by_bank = by_bank.merge(
            health[["bank_id", "better", "worse", "in_line"]], on="bank_id", how="left"
        )
    by_bank["bank_name"] = by_bank["bank_id"].astype(str).map(names).fillna(by_bank["bank_id"])
    by_bank = by_bank.sort_values("weighted_pd", ascending=False)
    display_columns = [
        "bank_id", "bank_name", "ead", "weighted_pd", "observed_default_rate",
        "recovery_rate", "loss_rate", "coverage_ratio", "better", "worse", "in_line",
    ]
    display = by_bank[[column for column in display_columns if column in by_bank.columns]]
    st.dataframe(
        display,
        hide_index=True,
        column_config={
            "bank_id": st.column_config.TextColumn("Institution"),
            "bank_name": st.column_config.TextColumn("Name"),
            "ead": st.column_config.NumberColumn("Current EAD", format="compact"),
            "weighted_pd": percent_column("Weighted PD 12M"),
            "observed_default_rate": percent_column("Observed 12M default rate"),
            "recovery_rate": percent_column("Recovery rate"),
            "loss_rate": percent_column("Loss rate"),
            "coverage_ratio": percent_column("Collateral coverage"),
            "better": st.column_config.NumberColumn("Benchmark better"),
            "worse": st.column_config.NumberColumn("Benchmark worse"),
            "in_line": st.column_config.NumberColumn("Benchmark in line"),
        },
    )

    st.subheader("What stands out")
    best_pd, worst_pd = _best_worst(rating.pd_by_bank, "weighted_pd", names, higher_is_better=False)
    best_recovery, worst_recovery = _best_worst(loss.by_bank, "recovery_rate", names, higher_is_better=True)
    best_loss, worst_loss = _best_worst(loss.by_bank, "loss_rate", names, higher_is_better=False)
    best_coverage, worst_coverage = _best_worst(
        loss.collateral_by_bank, "coverage_ratio", names, higher_is_better=True
    )
    with st.container(border=True):
        st.markdown(
            f"- **Highest weighted PD:** {worst_pd}. Lowest: {best_pd}.\n"
            f"- **Highest observed recovery rate:** {best_recovery}. Lowest: {worst_recovery}.\n"
            f"- **Highest observed loss rate:** {worst_loss}. Lowest: {best_loss}.\n"
            f"- **Strongest collateral coverage:** {best_coverage}. Weakest: {worst_coverage}.\n"
            f"- **Benchmark outcomes:** {benchmark.kpis.get('better', 0)} better, "
            f"{benchmark.kpis.get('worse', 0)} worse and {benchmark.kpis.get('in_line', 0)} in line "
            "across the selected institutions."
        )
        st.caption(
            "Differences may reflect portfolio mix, rating composition, collateral quality and random "
            "variation in a small synthetic cohort. They are not causal statements."
        )

    version = data.get("data_version") or {}
    latest_import = version.get("latest_import")
    st.caption(
        f"Data version {((version.get('pipeline_run') or {}).get('pipeline_run_id', 'unavailable'))} | "
        f"Latest import {pd.Timestamp(latest_import).strftime('%d %b %Y %H:%M') if latest_import is not None and pd.notna(latest_import) else 'n/a'} | "
        f"Quality findings {fmt_int(quality.finding_count)} | Quarantined records {fmt_int(quality.quarantined_records)}"
    )
    st.caption(f"Observed cohort window: {rating.kpis.get('migration_start')} to {rating.kpis.get('migration_end')}. "
               f"Loss cohort starts {loss.window_start.date() if loss.window_start is not None else 'n/a'}.")
    st.caption(f"Average recovery lag: {fmt_days(loss_kpis.get('weighted_average_days'))}.")
