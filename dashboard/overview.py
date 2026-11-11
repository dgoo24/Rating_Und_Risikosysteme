"""Überblicksseite."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from benchmarking.benchmark_engine import benchmark_health_flags
from dashboard.common import (
    SPARKASSE_RED,
    bank_names,
    empty_state,
    filter_benchmark_banks,
    fmt_datetime_de,
    fmt_date_de,
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
        return "k. A.", "k. A."
    ordered = data.sort_values(column, ascending=not higher_is_better)
    first = ordered.iloc[0]
    last = ordered.iloc[-1]
    return (
        f"{names.get(str(first['bank_id']), first['bank_id'])} ({fmt_pct(first[column])})",
        f"{names.get(str(last['bank_id']), last['bank_id'])} ({fmt_pct(last[column])})",
    )


def render() -> None:
    st.title("Überblick")
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
            ("Haftungsvolumen (EAD)", fmt_eur(rating_kpis.get("total_ead")), "Aktuelles Haftungsvolumen (EAD) für den ausgewählten Umfang."),
            ("PD 12M (Modellschätzung, gewichtet)", fmt_pct(rating_kpis.get("portfolio_pd")), "Summe(EAD x konfigurierte PD) / Summe(EAD)."),
            ("Investment-Grade-Anteil", fmt_pct(rating_kpis.get("investment_grade_share")), "EAD mit Rating A oder B / geratetes EAD."),
            ("Beobachtete Ausfallquote 12M", fmt_pct(rating_kpis.get("default_rate_12m")), "Beobachtete Ausfälle / performende Positionen zu Beobachtungsbeginn."),
        ]
    )
    metric_row(
        [
            ("Beobachtete Verwertungsquote 12M", fmt_pct(loss_kpis.get("recovery_rate")), "Verwertungszahlungen / EAD im Ausfall der 12M-Kohorte."),
            ("Beobachtete Verlustquote 12M", fmt_pct(loss_kpis.get("loss_rate")), "Verlustbetrag / EAD im Ausfall der 12M-Kohorte."),
            ("Besicherungsquote (nach Haircuts)", fmt_pct(loss_kpis.get("collateral_coverage")), "Sicherheitenwert nach Haircuts / aktuelles EAD."),
            ("Datenqualitäts-Score", fmt_pct(quality.overall_score / 100 if quality.overall_score else None), "Gültige Zeilen / empfangene Zeilen über alle abgeschlossenen Batches."),
        ]
    )

    st.caption(
        "Die modellbasierte PD und die beobachteten Ausfall- bzw. Verlustquoten beantworten "
        "unterschiedliche Fragen und werden getrennt ausgewiesen. Beobachtete Quoten sind "
        "Kohortenstatistiken, keine Prognosen."
    )

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Portfolio-PD-Verlauf")
            if pd_trend.empty:
                empty_state("Für den ausgewählten Umfang ist kein PD-Verlauf verfügbar.")
            else:
                chart = (
                    alt.Chart(pd_trend)
                    .mark_line(point=True, strokeWidth=2)
                    .encode(
                        x=alt.X("snapshot_date:T", title="Berichtsstichtag"),
                        y=alt.Y("weighted_pd:Q", title="PD 12M (gewichtet)", axis=alt.Axis(format=".1%")),
                        tooltip=[
                            alt.Tooltip("snapshot_date:T", title="Datum", format="%d.%m.%Y"),
                            alt.Tooltip("weighted_pd:Q", title="Gewichtete PD", format=".2%"),
                            alt.Tooltip("ead:Q", title="EAD", format=",.0f"),
                        ],
                    )
                    .properties(height=260)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Verlauf der beobachteten Ausfallquote 12M")
            if default_trend.empty:
                empty_state("Für den ausgewählten Umfang ist kein Ausfallquoten-Verlauf verfügbar.")
            else:
                chart = (
                    alt.Chart(default_trend)
                    .mark_line(point=True, strokeWidth=2, color=SPARKASSE_RED)
                    .encode(
                        x=alt.X("reporting_date:T", title="Berichtsstichtag"),
                        y=alt.Y("observed_default_rate:Q", title="Beobachtete Ausfallquote", axis=alt.Axis(format=".1%")),
                        tooltip=[
                            alt.Tooltip("reporting_date:T", title="Datum", format="%d.%m.%Y"),
                            alt.Tooltip("observed_default_rate:Q", title="Ausfallquote", format=".2%"),
                            alt.Tooltip("default_count:Q", title="Ausfälle", format=",.0f"),
                            alt.Tooltip("base_exposures:Q", title="Basispositionen", format=",.0f"),
                        ],
                    )
                    .properties(height=260)
                )
                st.altair_chart(chart)

    st.subheader("Instituts-Scorecard")
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
            "bank_id": st.column_config.TextColumn("Institut"),
            "bank_name": st.column_config.TextColumn("Name"),
            "ead": st.column_config.NumberColumn("Aktuelles EAD", format="compact"),
            "weighted_pd": percent_column("PD 12M (gewichtet)"),
            "observed_default_rate": percent_column("Ausfallquote 12M (beobachtet)"),
            "recovery_rate": percent_column("Verwertungsquote"),
            "loss_rate": percent_column("Verlustquote"),
            "coverage_ratio": percent_column("Besicherungsquote"),
            "better": st.column_config.NumberColumn("Benchmark: besser"),
            "worse": st.column_config.NumberColumn("Benchmark: schlechter"),
            "in_line": st.column_config.NumberColumn("Benchmark: im Rahmen"),
        },
    )

    st.subheader("Was ins Auge fällt")
    best_pd, worst_pd = _best_worst(rating.pd_by_bank, "weighted_pd", names, higher_is_better=False)
    best_recovery, worst_recovery = _best_worst(loss.by_bank, "recovery_rate", names, higher_is_better=True)
    best_loss, worst_loss = _best_worst(loss.by_bank, "loss_rate", names, higher_is_better=False)
    best_coverage, worst_coverage = _best_worst(
        loss.collateral_by_bank, "coverage_ratio", names, higher_is_better=True
    )
    with st.container(border=True):
        st.markdown(
            f"- **Höchste gewichtete PD:** {worst_pd}. Niedrigste: {best_pd}.\n"
            f"- **Höchste beobachtete Verwertungsquote:** {best_recovery}. Niedrigste: {worst_recovery}.\n"
            f"- **Höchste beobachtete Verlustquote:** {worst_loss}. Niedrigste: {best_loss}.\n"
            f"- **Stärkste Besicherungsquote:** {best_coverage}. Schwächste: {worst_coverage}.\n"
            f"- **Benchmark-Ergebnisse:** {benchmark.kpis.get('better', 0)} besser, "
            f"{benchmark.kpis.get('worse', 0)} schlechter und {benchmark.kpis.get('in_line', 0)} im Rahmen "
            "über die ausgewählten Institute hinweg."
        )
        st.caption(
            "Unterschiede können auf Portfoliostruktur, Ratingzusammensetzung, Sicherheitenqualität und "
            "zufällige Variation in einer kleinen synthetischen Kohorte zurückgehen. Es handelt sich "
            "um keine kausalen Aussagen."
        )

    version = data.get("data_version") or {}
    latest_import = version.get("latest_import")
    st.caption(
        f"Datenstand {((version.get('pipeline_run') or {}).get('pipeline_run_id', 'nicht verfügbar'))} | "
        f"Letzter Import {fmt_datetime_de(latest_import)} | "
        f"Qualitätsbefunde {fmt_int(quality.finding_count)} | Quarantäne-Datensätze {fmt_int(quality.quarantined_records)}"
    )
    st.caption(f"Beobachtungsfenster der Kohorte: {rating.kpis.get('migration_start')} bis {rating.kpis.get('migration_end')}. "
               f"Verlustkohorte beginnt {fmt_date_de(loss.window_start) if loss.window_start is not None else 'k. A.'}.")
    st.caption(f"Durchschnittlicher Verwertungsverzug: {fmt_days(loss_kpis.get('weighted_average_days'))}.")
