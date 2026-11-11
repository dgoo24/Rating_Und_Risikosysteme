"""Benchmarking-Seite, gemeinsam von beiden Risikomodulen genutzt.

Jeder Vergleich lautet Institut vs. Vergleichsgruppe vs. gesamter
Berichtsgemeinschaft. Vergleichsgruppenwerte sind gewichtete Aggregate aus
Zählern und Nennern und schließen das Institut selbst stets aus seiner
eigenen Vergleichsreferenz aus.
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
    range=["#13795B", "#6B6B6B", "#E6001E", "#E3E5E8", "#F7D9DD"],
)


def _selected_reference_group() -> str | None:
    """Fragt eine optionale einzelne Referenzgruppe für alle Vergleiche ab."""
    basis = st.segmented_control(
        "Vergleichsbasis",
        ["Konfigurierte Vergleichsgruppen", "Einzelne Referenzgruppe"],
        default="Konfigurierte Vergleichsgruppen",
        help=(
            "Konfigurierte Gruppen nutzen die institutsbezogenen Vergleichsgruppendefinitionen. "
            "Der Was-wäre-wenn-Modus benchmarkt jedes Institut gegen die Mitglieder einer "
            "ausgewählten Referenzgruppe."
        ),
        key="benchmark_peer_basis",
    )
    if basis != "Einzelne Referenzgruppe":
        return None
    options = sorted(PEER_GROUPS)
    labels = {
        group: f"{group} - {PEER_GROUPS[group].description}" for group in options
    }
    return st.selectbox(
        "Referenzgruppe",
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
        "Benchmark-Kennzahl",
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
            "Für den ausgewählten Umfang sind keine Benchmark-Zeilen verfügbar. Erzeugen Sie "
            "zunächst synthetische Daten und starten Sie die Aufnahmepipeline."
        )
        return

    kpis = benchmark.kpis
    metric_row(
        [
            ("Institute im Benchmark", f"{kpis.get('banks', 0)}", "Institute mit mindestens einer vergleichbaren Kennzahl."),
            ("Verglichene Kennzahlen", f"{kpis.get('metrics', 0)}", "Kennzahlen aus Rating & Scoring und Verlustschätzung."),
            ("Besser als Vergleichsgruppe", f"{kpis.get('better', 0)}", "Kennzahlen, bei denen das Institut seine Vergleichsreferenz schlägt."),
            ("Schlechter als Vergleichsgruppe", f"{kpis.get('worse', 0)}", "Kennzahlen, bei denen das Institut hinter seiner Vergleichsreferenz zurückliegt."),
            ("Im Rahmen der Vergleichsgruppe", f"{kpis.get('in_line', 0)}", "Kennzahlen innerhalb der konfigurierten relativen Toleranz von 10 %."),
        ]
    )
    st.caption(
        "Vergleichsgruppenwerte aggregieren Zähler und Nenner (gewichtet), nie den ungewichteten "
        "Mittelwert der Institutquoten, und schließen das Institut selbst aus. Community-Werte "
        "decken alle Institute ab, die die Kennzahl melden."
        + (
            f" Was-wäre-wenn-Modus: jedes Institut wird gegen die Mitglieder von {reference_group} verglichen."
            if reference_group
            else ""
        )
    )

    with st.container(border=True):
        st.subheader("Institut vs. Vergleichsgruppe vs. Berichtsgemeinschaft")
        selected_metric = _metric_picker(detail, "benchmark_metric", "PD_12M_WEIGHTED")
        if selected_metric is None:
            empty_state("Es ist keine Benchmark-Kennzahl verfügbar.")
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
                    "bank_value": "Institut",
                    "peer_value": "Vergleichsgruppe (ohne Selbst)",
                    "portfolio_value": "Berichtsgemeinschaft",
                }
            )
            chart = (
                alt.Chart(long)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("bank_id:N", title="Institut"),
                    y=alt.Y("value:Q", title="Kennzahlenwert", axis=alt.Axis(format=".1%")),
                    color=alt.Color("measure:N", title="Referenz", scale=alt.Scale(
                        domain=["Institut", "Vergleichsgruppe (ohne Selbst)", "Berichtsgemeinschaft"],
                        range=["#E6001E", "#454957", "#B7BFC9"],
                    )),
                    xOffset="measure:N",
                    tooltip=[
                        alt.Tooltip("bank_id:N", title="Institut"),
                        alt.Tooltip("bank_name:N", title="Name"),
                        alt.Tooltip("peer_group:N", title="Vergleichsgruppe"),
                        "measure",
                        alt.Tooltip("value:Q", title="Wert", format=".2%"),
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
                    f"Richtung: {'höher ist besser' if row['higher_is_better'] else 'niedriger ist besser' if row['higher_is_better'] is not None else 'informativ'}."
                )

    left, right = st.columns([2, 3])
    with left:
        with st.container(border=True):
            st.subheader("Benchmark-Ergebnisse nach Institut")
            health = benchmark_health_flags(benchmark.detail)
            health = filter_benchmark_banks(health, banks)
            if health.empty:
                empty_state("Es sind keine Benchmark-Ergebnisse verfügbar.")
            else:
                long = health.melt(
                    id_vars=["bank_id"],
                    value_vars=["better", "worse", "in_line"],
                    var_name="outcome",
                    value_name="count",
                )
                long["outcome"] = long["outcome"].map(
                    {"better": "BESSER", "worse": "SCHLECHTER", "in_line": "IM RAHMEN"}
                )
                chart = (
                    alt.Chart(long)
                    .mark_bar()
                    .encode(
                        x=alt.X("count:Q", title="Kennzahlen", stack=True),
                        y=alt.Y("bank_id:N", title="Institut", sort="-x"),
                        color=alt.Color(
                            "outcome:N",
                            title="Ergebnis vs. Vergleichsgruppe",
                            scale=alt.Scale(
                                domain=["BESSER", "IM RAHMEN", "SCHLECHTER"],
                                range=["#13795B", "#6B6B6B", "#E6001E"],
                            ),
                        ),
                        tooltip=["bank_id", "outcome", "count"],
                    )
                    .properties(height=240)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Größte Abstände zur Vergleichsreferenz")
            gaps = benchmark.top_gaps.copy()
            gaps = filter_benchmark_banks(gaps, banks)
            if gaps.empty:
                empty_state("Für den ausgewählten Umfang sind keine Abstände verfügbar.")
            else:
                gaps["label"] = gaps["bank_id"].astype(str) + " - " + gaps["metric_name"].astype(str)
                gaps["gap_pct"] = gaps["relative_gap"]
                chart = (
                    alt.Chart(gaps.head(12))
                    .mark_bar()
                    .encode(
                        x=alt.X("gap_pct:Q", title="Relativer Abstand zur Vergleichsgruppe", axis=alt.Axis(format=".0%")),
                        y=alt.Y("label:N", sort="-x", title=None),
                        color=alt.Color(
                            "performance_flag:N",
                            title="Ergebnis",
                            scale=FLAG_COLORS,
                        ),
                        tooltip=[
                            alt.Tooltip("bank_id:N", title="Institut"),
                            alt.Tooltip("metric_name:N", title="Kennzahl"),
                            alt.Tooltip("bank_value:Q", title="Institut", format=".2%"),
                            alt.Tooltip("peer_value:Q", title="Vergleichsgruppe", format=".2%"),
                            alt.Tooltip("relative_gap:Q", title="Relativer Abstand", format=".2%"),
                            alt.Tooltip("performance_flag:N", title="Ergebnis"),
                        ],
                    )
                    .properties(height=300)
                )
                st.altair_chart(chart)

    st.subheader("Aggregierte Vergleichsgruppen")
    group_summary = benchmark.peer_group_summary.copy()
    if group_summary.empty:
        empty_state("Es sind keine Vergleichsgruppen-Aggregate verfügbar.")
    else:
        group_metrics = sorted(group_summary["metric_id"].unique().tolist())
        selected_group_metric = st.selectbox(
            "Kennzahl der Vergleichsgruppe",
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
                "peer_group": st.column_config.TextColumn("Vergleichsgruppe"),
                "metric_name": st.column_config.TextColumn("Kennzahl"),
                "bank_count": st.column_config.NumberColumn("Mitglieder"),
                "numerator": st.column_config.NumberColumn("Zähler", format="compact"),
                "denominator": st.column_config.NumberColumn("Nenner", format="compact"),
                "peer_value": percent_column("Gewichteter Gruppenwert"),
            },
        )
        st.caption(
            "Vergleichsgruppenwerte teilen die Summe der Zähler durch die Summe der Nenner aller "
            "Mitglieder. Ungewichtete Durchschnitte der Institutquoten werden bewusst vermieden."
        )

    st.subheader("Historischer Benchmark-Vergleich")
    historical = get_historical_benchmark(tuple(sectors), reference_group)
    if historical.detail.empty:
        empty_state("Es sind keine historischen Benchmark-Zeiträume verfügbar.")
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
        portfolio_lines["series"] = "Berichtsgemeinschaft"
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
                x=alt.X("reporting_date:T", title="Berichtsstichtag"),
                y=alt.Y("value:Q", title="Kennzahlenwert", axis=alt.Axis(format=".1%")),
                color=alt.Color("series:N", title="Verlauf"),
                strokeDash=alt.condition(
                    alt.datum.series == "Berichtsgemeinschaft",
                    alt.value([5, 5]),
                    alt.value([1, 0]),
                ),
                tooltip=[
                    alt.Tooltip("reporting_date:T", title="Datum", format="%d.%m.%Y"),
                    "series",
                    alt.Tooltip("value:Q", title="Wert", format=".2%"),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(line)

        flags = historical.kpis.copy()
        if flags.empty:
            empty_state("Es sind keine historischen Ergebniszahlen verfügbar.")
        else:
            flags_long = flags.melt(
                id_vars=["reporting_date"],
                value_vars=["better", "worse", "in_line"],
                var_name="outcome",
                value_name="count",
            )
            flags_long["outcome"] = flags_long["outcome"].map(
                {"better": "BESSER", "worse": "SCHLECHTER", "in_line": "IM RAHMEN"}
            )
            flags_long["reporting_date"] = pd.to_datetime(flags_long["reporting_date"])
            chart = (
                alt.Chart(flags_long)
                .mark_bar()
                .encode(
                    x=alt.X("reporting_date:T", title="Berichtsstichtag", timeUnit="yearquarter"),
                    y=alt.Y("count:Q", title="Benchmark-Ergebnisse", stack=True),
                    color=alt.Color(
                        "outcome:N",
                        title="Ergebnis vs. Vergleichsgruppe",
                        scale=alt.Scale(
                            domain=["BESSER", "IM RAHMEN", "SCHLECHTER"],
                            range=["#13795B", "#6B6B6B", "#E6001E"],
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip("reporting_date:T", title="Datum", format="%d.%m.%Y"),
                        "outcome",
                        "count",
                    ],
                )
                .properties(height=260)
            )
            st.altair_chart(chart)

    with st.container(border=True):
        st.subheader("Benchmark-Details")
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
                "bank_id": "Institut",
                "bank_name": "Name",
                "peer_group": "Vergleichsgruppe",
                "metric_name": "Kennzahl",
                "bank_value": "Institutswert",
                "peer_value": "Vergleichsgruppenwert",
                "peer_median": "Median der Vergleichsgruppe",
                "portfolio_value": "Community-Wert",
                "gap": "Abstand zu Vergleichsgruppe",
                "relative_gap": "Relativer Abstand",
                "rank_in_peer_group": "Rang in der Vergleichsgruppe",
                "performance_flag": "Vergleichsgruppen-Flag",
                "portfolio_performance_flag": "Community-Flag",
            }
        )
        st.dataframe(
            display,
            hide_index=True,
            column_config={
                "Institut": st.column_config.TextColumn("Institut"),
                "Name": st.column_config.TextColumn("Name"),
                "Vergleichsgruppe": st.column_config.TextColumn("Vergleichsgruppe"),
                "Kennzahl": st.column_config.TextColumn("Kennzahl"),
                "Institutswert": percent_column("Institut"),
                "Vergleichsgruppenwert": percent_column("Vergleichsgruppe"),
                "Median der Vergleichsgruppe": percent_column("Median"),
                "Community-Wert": percent_column("Community"),
                "Abstand zu Vergleichsgruppe": percent_column("Abstand"),
                "Relativer Abstand": percent_column("Relativer Abstand"),
                "Rang in der Vergleichsgruppe": st.column_config.NumberColumn("Rang (VGrp.)"),
                "Vergleichsgruppen-Flag": st.column_config.TextColumn("Flag"),
                "Community-Flag": st.column_config.TextColumn("Flag"),
            },
        )

    with st.expander("Kennzahlenkatalog"):
        st.dataframe(
            benchmark.catalog,
            hide_index=True,
            column_config={
                "metric_id": st.column_config.TextColumn("Kennzahl"),
                "metric_name": st.column_config.TextColumn("Name"),
                "module": st.column_config.TextColumn("Modul"),
                "unit": st.column_config.TextColumn("Einheit"),
                "higher_is_better": st.column_config.TextColumn("Richtung"),
                "description": st.column_config.TextColumn("Definition"),
            },
        )

    if reference_group:
        st.info(
            "Der Was-wäre-wenn-Modus ist aktiv: die Vergleichsreferenzen wurden für jedes Institut "
            "gegen die ausgewählte Referenzgruppe neu berechnet. Das verändert ausschließlich die "
            "Vergleichsspalten; Instituts- und Community-Werte bleiben unverändert."
        )
