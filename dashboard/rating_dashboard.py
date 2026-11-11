"""Seite Rating und Scoring."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from config.rating_pd_mapping import RATING_SCALE
from dashboard.common import (
    SPARKASSE_RED,
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
    st.title("Rating und Scoring")
    data = get_rating_placeholder()
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)
    rating = get_rating_module(report.isoformat(), tuple(banks), tuple(sectors))
    benchmark = get_benchmark(report.isoformat(), tuple(sectors))
    kpis = rating.kpis

    metric_row(
        [
            ("Haftungsvolumen (EAD)", fmt_eur(kpis.get("total_ead")), "Summe der positiven Haftungsvolumina (EAD)."),
            ("PD 12M (gewichtet)", fmt_pct(kpis.get("portfolio_pd")), "Modellbasierte, EAD-gewichtete PD."),
            ("Investment-Grade-Anteil", fmt_pct(kpis.get("investment_grade_share")), "EAD mit Rating A oder B."),
            ("Beobachtete Ausfallquote 12M", fmt_pct(kpis.get("default_rate_12m")), "Kohortenanzahlquote, abweichend von der Modell-PD."),
        ]
    )
    metric_row(
        [
            ("Modell-PD 12M der Kohorte", fmt_pct(kpis.get("model_pd_12m")), "Gewichtete konfigurierte PD über dem Basis-EAD der Ausfallkohorte."),
            ("Hochstufungsquote", fmt_pct(kpis.get("upgrade_rate")), "Hochstufungen / übereinstimmende Ratingbeobachtungen."),
            ("Herabstufungsquote", fmt_pct(kpis.get("downgrade_rate")), "Herabstufungen / übereinstimmende Ratingbeobachtungen."),
            ("Positionen im Umfang", fmt_int(kpis.get("exposure_count")), "Positionen im aktuellen Stichtagsbestand."),
        ]
    )
    st.caption(
        f"Beobachtete Ausfallkohorte: {kpis.get('migration_start')} bis {kpis.get('migration_end')} für die Migration; "
        f"die 12M-Ausfallbeobachtung startet {rating.default_summary.iloc[0]['observation_start'] if not rating.default_summary.empty else 'k. A.'}. "
        "Die Modell-PD ist eine konfigurierte Schätzung, keine beobachtete Ausfallhäufigkeit."
    )

    left, right = st.columns([2, 3])
    with left:
        with st.container(border=True):
            st.subheader("EAD-Verteilung nach Rating")
            distribution = rating.distribution.copy()
            if distribution.empty:
                empty_state("Es ist keine Ratingverteilung verfügbar.")
            else:
                chart = (
                    alt.Chart(distribution)
                    .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                    .encode(
                        x=alt.X("rating_grade:N", title="Rating", sort=list(RATING_SCALE)),
                        y=alt.Y("share_ead:Q", title="Anteil des EAD", axis=alt.Axis(format=".0%")),
                        color=alt.Color("rating_grade:N", legend=None),
                        tooltip=[
                            alt.Tooltip("rating_grade:N", title="Rating"),
                            alt.Tooltip("exposure_count:Q", title="Positionen", format=",.0f"),
                            alt.Tooltip("ead:Q", title="EAD", format=",.0f"),
                            alt.Tooltip("share_ead:Q", title="Anteil des EAD", format=".2%"),
                            alt.Tooltip("pd_rate:Q", title="Konfigurierte PD", format=".2%"),
                        ],
                    )
                    .properties(height=300)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Portfolio-PD-Verlauf")
            trend = rating.pd_trend.dropna(subset=["weighted_pd"])
            if trend.empty:
                empty_state("Es ist kein PD-Verlauf verfügbar.")
            else:
                base = alt.Chart(trend).encode(
                    x=alt.X("snapshot_date:T", title="Berichtsstichtag"),
                    tooltip=[
                        alt.Tooltip("snapshot_date:T", format="%d.%m.%Y", title="Datum"),
                        alt.Tooltip("weighted_pd:Q", title="Gewichtete PD", format=".2%"),
                        alt.Tooltip("expected_default_ead:Q", title="Erwartetes Ausfall-EAD", format=",.0f"),
                    ],
                )
                line = base.mark_line(point=True, strokeWidth=2).encode(
                    y=alt.Y("weighted_pd:Q", title="PD 12M (gewichtet)", axis=alt.Axis(format=".1%")),
                )
                st.altair_chart(line.properties(height=300))

    st.subheader("Beobachtete Ausfallerfahrung nach Rating")
    default_by_rating = rating.default_by_rating.copy()
    if default_by_rating.empty:
        empty_state("Für den ausgewählten Umfang ist keine beobachtete Ausfallkohorte verfügbar.")
    else:
        default_by_rating = default_by_rating.set_index("rating_grade").reindex(RATING_SCALE).dropna(how="all").reset_index()
        long = default_by_rating.melt(
            id_vars=["rating_grade", "base_exposures", "default_count"],
            value_vars=["observed_default_rate", "model_pd_weighted"],
            var_name="measure",
            value_name="rate",
        )
        long["measure"] = long["measure"].map(
            {"observed_default_rate": "Beobachtete Ausfallquote", "model_pd_weighted": "Modell-PD (gewichtet)"}
        )
        chart = (
            alt.Chart(long)
            .mark_bar()
            .encode(
                x=alt.X("rating_grade:N", title="Rating zu Beobachtungsbeginn", sort=list(RATING_SCALE)),
                y=alt.Y("rate:Q", title="Quote", axis=alt.Axis(format=".1%")),
                color=alt.Color("measure:N", title="Messgröße", scale=alt.Scale(
                    domain=["Beobachtete Ausfallquote", "Modell-PD (gewichtet)"], range=[SPARKASSE_RED, "#454957"]
                )),
                xOffset="measure:N",
                tooltip=[
                    alt.Tooltip("rating_grade:N", title="Rating"),
                    "measure",
                    alt.Tooltip("rate:Q", title="Quote", format=".2%"),
                    alt.Tooltip("base_exposures:Q", title="Basispositionen", format=",.0f"),
                    alt.Tooltip("default_count:Q", title="Ausfälle", format=",.0f"),
                ],
            )
            .properties(height=300)
        )
        st.altair_chart(chart)

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Ausfallquote nach Institut")
            by_bank = rating.default_by_bank.copy()
            if by_bank.empty:
                empty_state("Es sind keine institutsbezogenen Ausfalldetails verfügbar.")
            else:
                long = by_bank.melt(
                    id_vars=["bank_id", "base_exposures", "default_count"],
                    value_vars=["observed_default_rate", "model_pd_weighted"],
                    var_name="measure",
                    value_name="rate",
                )
                long["measure"] = long["measure"].map(
                    {"observed_default_rate": "Beobachtet", "model_pd_weighted": "Modell"}
                )
                chart = (
                    alt.Chart(long)
                    .mark_bar()
                    .encode(
                        x=alt.X("bank_id:N", title="Institut", sort="-y"),
                        y=alt.Y("rate:Q", title="Quote", axis=alt.Axis(format=".1%")),
                        color=alt.Color("measure:N", title="Messgröße"),
                        xOffset="measure:N",
                        tooltip=["bank_id", "measure", alt.Tooltip("rate:Q", format=".2%")],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("PD nach Wirtschaftssektor")
            sector_pd = rating.pd_by_sector.dropna(subset=["weighted_pd"]).sort_values("weighted_pd", ascending=False)
            if sector_pd.empty:
                empty_state("Es sind keine Sektor-Details verfügbar.")
            else:
                chart = (
                    alt.Chart(sector_pd)
                    .mark_bar()
                    .encode(
                        x=alt.X("weighted_pd:Q", title="Gewichtete PD", axis=alt.Axis(format=".1%")),
                        y=alt.Y("industry_sector:N", title=None, sort="-x"),
                        tooltip=[
                            "industry_sector",
                            alt.Tooltip("weighted_pd:Q", title="Gewichtete PD", format=".2%"),
                            alt.Tooltip("ead:Q", title="EAD", format=",.0f"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)

    with st.container(border=True):
        st.subheader("Details zur Ratingverteilung")
        st.dataframe(
            rating.distribution,
            hide_index=True,
            column_config={
                "rating_grade": st.column_config.TextColumn("Rating"),
                "exposure_count": st.column_config.NumberColumn("Positionen", format="localized"),
                "ead": st.column_config.NumberColumn("EAD", format="compact"),
                "share_count": percent_column("Anteil (Anzahl)"),
                "share_ead": percent_column("Anteil EAD"),
                "pd_rate": percent_column("Konfigurierte PD"),
                "expected_default_ead": st.column_config.NumberColumn("Erwartetes Ausfall-EAD", format="compact"),
            },
        )

    st.subheader("Ratingmigration")
    migration = rating.migration
    if migration.matrix_counts.empty or migration.summary.get("matched_count", 0) == 0:
        empty_state("Für den Migrationszeitraum sind keine übereinstimmenden Ratingbeobachtungen verfügbar.")
    else:
        st.caption(
            f"Übereinstimmende Beobachtungen: {fmt_int(migration.summary['matched_count'])} zwischen "
            f"{migration.start_date.date()} und {migration.end_date.date()}. "
            f"Hochstufungen {fmt_int(migration.summary['upgrades'])}; Herabstufungen {fmt_int(migration.summary['downgrades'])}; "
            f"unverändert {fmt_int(migration.summary['unchanged'])}. Zugänge und Abgänge sind in der Matrix nicht enthalten."
        )
        counts = migration.matrix_counts.stack().reset_index()
        counts.columns = ["base_rating", "target_rating", "count"]
        shares = migration.matrix_pct.stack().reset_index()
        shares.columns = ["base_rating", "target_rating", "share"]
        matrix = counts.merge(shares, on=["base_rating", "target_rating"])
        matrix["base_rating_order"] = matrix["base_rating"].map({rating_: index for index, rating_ in enumerate(RATING_SCALE)})
        matrix["target_rating_order"] = matrix["target_rating"].map({rating_: index for index, rating_ in enumerate(RATING_SCALE)})
        base = alt.Chart(matrix).encode(
            x=alt.X("target_rating:N", title="Rating am Ende", sort=list(RATING_SCALE)),
            y=alt.Y("base_rating:N", title="Rating zu Beginn", sort=list(RATING_SCALE)),
        )
        heatmap = base.mark_rect().encode(
            color=alt.Color("share:Q", title="Zeilenteil", scale=alt.Scale(scheme="reds")),
            tooltip=[
                alt.Tooltip("base_rating:N", title="Von"),
                alt.Tooltip("target_rating:N", title="Nach"),
                alt.Tooltip("count:Q", title="Positionen", format=",.0f"),
                alt.Tooltip("share:Q", title="Zeilenteil", format=".2%"),
            ],
        )
        text = base.mark_text(baseline="middle").encode(
            text=alt.Text("count:Q", format=",.0f"),
            color=alt.condition(alt.datum.share > 0.4, alt.value("white"), alt.value("#262626")),
        )
        st.altair_chart((heatmap + text).properties(height=320))

        with st.expander("Migration nach Institut"):
            if migration.by_bank.empty:
                empty_state("Es sind keine institutsbezogenen Migrationsdetails verfügbar.")
            else:
                st.dataframe(
                    migration.by_bank,
                    hide_index=True,
                    column_config={
                        "bank_id": st.column_config.TextColumn("Institut"),
                        "base_count": st.column_config.NumberColumn("Beobachtungen zu Beginn"),
                        "target_count": st.column_config.NumberColumn("Beobachtungen am Ende"),
                        "matched_count": st.column_config.NumberColumn("Übereinstimmend"),
                        "upgrades": st.column_config.NumberColumn("Hochstufungen"),
                        "downgrades": st.column_config.NumberColumn("Herabstufungen"),
                        "unchanged": st.column_config.NumberColumn("Unverändert"),
                        "upgrade_rate": percent_column("Hochstufungsquote"),
                        "downgrade_rate": percent_column("Herabstufungsquote"),
                    },
                )

    st.subheader("Benchmark-Vergleich")
    detail = filter_benchmark_banks(benchmark.detail, banks)
    detail = detail[detail["module"] == "rating"]
    if detail.empty:
        empty_state("Es sind keine Rating-Benchmark-Zeilen verfügbar.")
    else:
        metrics = detail[["metric_id", "metric_name"]].drop_duplicates().sort_values("metric_id")
        metric_ids = metrics["metric_id"].tolist()
        selected_metric = st.selectbox(
            "Benchmark-Kennzahl",
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
                "bank_value": "Institutswert",
                "peer_value": "Vergleichsgruppenwert",
                "peer_median": "Median der Vergleichsgruppe",
                "portfolio_value": "Community-Wert",
                "gap": "Abstand zu Vergleichsgruppe",
                "relative_gap": "Relativer Abstand",
                "rank_in_peer_group": "Rang in der Vergleichsgruppe",
                "portfolio_rank": "Rang im Portfolio",
                "performance_flag": "Vergleichsgruppe",
                "portfolio_performance_flag": "Community-Flag",
            }
        )
        st.dataframe(
            display,
            hide_index=True,
            column_config={
                "bank_id": st.column_config.TextColumn("Institut"),
                "bank_name": st.column_config.TextColumn("Name"),
                "Institutswert": percent_column("Institut"),
                "peer_group": st.column_config.TextColumn("Vergleichsgruppe"),
                "Vergleichsgruppenwert": percent_column("Vergleichsgruppe"),
                "Median der Vergleichsgruppe": percent_column("Median"),
                "Community-Wert": percent_column("Community"),
                "Abstand zu Vergleichsgruppe": percent_column("Abstand"),
                "Relativer Abstand": percent_column("Relativer Abstand"),
                "Rang in der Vergleichsgruppe": st.column_config.NumberColumn("Rang (VGrp.)"),
                "Rang im Portfolio": st.column_config.NumberColumn("Rang (Portfolio)"),
                "Vergleichsgruppe": st.column_config.TextColumn("Flag"),
                "Community-Flag": st.column_config.TextColumn("Flag"),
            },
        )
        st.caption(
            "Vergleichsgruppenwerte sind gewichtete Aggregate aus Zählern und Nennern der Vergleichsgruppe "
            "und schließen das Institut selbst aus. Community-Werte umfassen alle Institute der Kennzahl."
        )


def get_rating_placeholder() -> dict[str, pd.DataFrame]:
    """Lädt zwischengespeicherte Daten lazy, damit die Seite ohne Datenbank importierbar bleibt."""
    from dashboard.common import load_data

    return load_data()
