"""Seite Verlustschätzung."""
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

SEVERITY_LABELS = {
    "LOW": "Niedrig",
    "MODERATE": "Mittel",
    "HIGH": "Hoch",
    "FULL_LOSS": "Totalschaden",
}


def render() -> None:
    st.title("Verlustschätzung")
    data = load_data()
    report, banks, sectors = scope(data)
    scope_caption(report, banks, sectors)
    loss = get_loss_module(report.isoformat(), tuple(banks), tuple(sectors))
    benchmark = get_benchmark(report.isoformat(), tuple(sectors))
    kpis = loss.kpis

    metric_row(
        [
            ("Beobachtete Verwertungsquote 12M", fmt_pct(kpis.get("recovery_rate")), "Verwertungszahlungen / EAD im Ausfall."),
            ("Beobachtete Verlustquote 12M", fmt_pct(kpis.get("loss_rate")), "Verlustbetrag / EAD im Ausfall."),
            ("Verlustbetrag", fmt_eur(kpis.get("loss_amount")), "EAD im Ausfall abzüglich Verwertungszahlungen."),
            ("Ausfälle in der Kohorte", fmt_int(kpis.get("default_count")), "Anzahl ausgefallener Positionen mit EAD im Ausfall."),
        ]
    )
    metric_row(
        [
            ("EAD im Ausfall", fmt_eur(kpis.get("ead_at_default")), "Haftungsvolumen im Ausfall der Kohorte."),
            ("Besicherungsquote (nach Haircuts)", fmt_pct(kpis.get("collateral_coverage")), "Sicherheitenwert nach Haircuts / aktuelles EAD."),
            ("Besicherter EAD-Anteil", fmt_pct(kpis.get("secured_ead_share")), "Besichertes EAD (auf Positionsebene gedeckelt) / aktuelles EAD."),
            ("Gewichteter Verwertungsverzug", fmt_days(kpis.get("weighted_average_days")), "Zahlungsgewichtete Tage seit Ausfall."),
        ]
    )
    st.caption(
        f"Ausfallkohorte: {loss.window_start.date()} bis {loss.window_end.date() if hasattr(loss, 'window_end') else report.date()} "
        f"({loss.window_months} Monate). Verwertungs- und Verlustquoten sind beobachtete Statistiken auf "
        "Barmittelbasis für diese Kohorte; es handelt sich nicht um regulatorische LGD-Schätzungen."
    )

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Verteilung der Verwertungsquoten")
            distribution = loss.recovery_distribution.dropna(subset=["share_ead"])
            if distribution.empty:
                empty_state("Es ist keine Verwertungsverteilung verfügbar.")
            else:
                chart = (
                    alt.Chart(distribution)
                    .mark_bar()
                    .encode(
                        x=alt.X("recovery_bucket:N", title="Verwertungsquoten-Segment", sort=None),
                        y=alt.Y("share_ead:Q", title="Anteil des EAD", axis=alt.Axis(format=".0%")),
                        color=alt.Color("recovery_bucket:N", legend=None),
                        tooltip=[
                            "recovery_bucket",
                            alt.Tooltip("default_count:Q", title="Ausfälle", format=",.0f"),
                            alt.Tooltip("ead_at_default:Q", title="EAD im Ausfall", format=",.0f"),
                            alt.Tooltip("share_ead:Q", title="Anteil des EAD", format=".2%"),
                            alt.Tooltip("average_recovery_rate:Q", title="Ø Verwertungsquote", format=".2%"),
                        ],
                    )
                    .properties(height=290)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Verteilung der Verlustschwere")
            severity = loss.loss_severity[loss.loss_severity["default_count"] > 0].copy()
            if severity.empty:
                empty_state("Es sind keine Details zur Verlustschwere verfügbar.")
            else:
                severity["severity_label"] = severity["severity"].map(SEVERITY_LABELS).fillna(severity["severity"])
                chart = (
                    alt.Chart(severity)
                    .mark_bar()
                    .encode(
                        x=alt.X("severity_label:N", title="Verlustschwere", sort=list(SEVERITY_LABELS.values())),
                        y=alt.Y("share_ead:Q", title="Anteil des EAD", axis=alt.Axis(format=".0%")),
                        color=alt.Color("severity_label:N", legend=None),
                        tooltip=[
                            "severity_label",
                            alt.Tooltip("default_count:Q", title="Ausfälle", format=",.0f"),
                            alt.Tooltip("loss_amount:Q", title="Verlustbetrag", format=",.0f"),
                            alt.Tooltip("share_ead:Q", title="Anteil des EAD", format=".2%"),
                        ],
                    )
                    .properties(height=290)
                )
                st.altair_chart(chart)

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Verwertung und Verlust nach Institut")
            by_bank = loss.by_bank.copy()
            if by_bank.empty:
                empty_state("Es sind keine institutsbezogenen Verlustdetails verfügbar.")
            else:
                long = by_bank.melt(
                    id_vars=["bank_id", "default_count"],
                    value_vars=["recovery_rate", "loss_rate"],
                    var_name="measure",
                    value_name="rate",
                )
                long["measure"] = long["measure"].map(
                    {"recovery_rate": "Verwertungsquote", "loss_rate": "Verlustquote"}
                )
                chart = (
                    alt.Chart(long)
                    .mark_bar()
                    .encode(
                        x=alt.X("bank_id:N", title="Institut", sort="-y"),
                        y=alt.Y("rate:Q", title="Quote", axis=alt.Axis(format=".0%")),
                        color=alt.Color("measure:N", title="Messgröße", scale=alt.Scale(
                            domain=["Verwertungsquote", "Verlustquote"], range=["#13795B", "#E6001E"]
                        )),
                        xOffset="measure:N",
                        tooltip=["bank_id", "measure", alt.Tooltip("rate:Q", format=".2%"), "default_count"],
                    )
                    .properties(height=290)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Besicherungsquote nach Sicherheitenart")
            coverage = loss.collateral_by_primary_type.dropna(subset=["coverage_ratio"])
            if coverage.empty:
                empty_state("Es sind keine Details zur Besicherungsquote verfügbar.")
            else:
                chart = (
                    alt.Chart(coverage)
                    .mark_bar()
                    .encode(
                        x=alt.X("coverage_ratio:Q", title="Besicherungsquote", axis=alt.Axis(format=".0%")),
                        y=alt.Y("primary_collateral_type:N", title=None, sort="-x"),
                        tooltip=[
                            "primary_collateral_type",
                            alt.Tooltip("coverage_ratio:Q", title="Besicherungsquote", format=".2%"),
                            alt.Tooltip("ead:Q", title="EAD", format=",.0f"),
                            alt.Tooltip("secured_ead_share:Q", title="Besicherter EAD-Anteil", format=".2%"),
                        ],
                    )
                    .properties(height=290)
                )
                st.altair_chart(chart)

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.subheader("Kumulierte Verwertungsquote")
            curve = loss.recovery_curve.dropna(subset=["cumulative_recovery_rate"])
            if curve.empty:
                empty_state("Es ist keine Verwertungskurve verfügbar.")
            else:
                chart = (
                    alt.Chart(curve)
                    .mark_line(point=True, strokeWidth=2)
                    .encode(
                        x=alt.X("months_since_default:Q", title="Monate seit Ausfall"),
                        y=alt.Y("cumulative_recovery_rate:Q", title="Kumulierte Verwertungsquote", axis=alt.Axis(format=".0%")),
                        tooltip=[
                            alt.Tooltip("months_since_default:Q", title="Monate"),
                            alt.Tooltip("cumulative_recovery_rate:Q", title="Verwertungsquote", format=".2%"),
                            alt.Tooltip("cumulative_recoveries:Q", title="Verwertungen", format=",.0f"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)
    with right:
        with st.container(border=True):
            st.subheader("Verwertungszahlungen nach Quartal")
            cashflows = loss.cashflow_by_quarter.copy()
            if cashflows.empty:
                empty_state("Es sind keine Verwertungszahlungen verfügbar.")
            else:
                chart = (
                    alt.Chart(cashflows)
                    .mark_bar()
                    .encode(
                        x=alt.X("payment_period:N", title="Zahlungsquartal"),
                        y=alt.Y("recovered_amount:Q", title="Verwerteter Betrag"),
                        tooltip=[
                            "payment_period",
                            alt.Tooltip("cashflow_count:Q", title="Zahlungsströme", format=",.0f"),
                            alt.Tooltip("recovered_amount:Q", title="Verwerteter Betrag", format=",.0f"),
                            alt.Tooltip("cumulative_share:Q", title="Kumulierter Anteil", format=".2%"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(chart)

    with st.container(border=True):
        st.subheader("Verlust- und Verwertungsdetails nach Institut")
        by_bank = loss.by_bank.copy()
        if by_bank.empty:
            empty_state("Es sind keine institutsbezogenen Details verfügbar.")
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
                    "bank_id": st.column_config.TextColumn("Institut"),
                    "default_count": st.column_config.NumberColumn("Ausfälle"),
                    "ead_at_default": st.column_config.NumberColumn("EAD im Ausfall", format="compact"),
                    "total_recoveries": st.column_config.NumberColumn("Verwertungen", format="compact"),
                    "recovery_count": st.column_config.NumberColumn("Zahlungsströme"),
                    "loss_amount": st.column_config.NumberColumn("Verlustbetrag", format="compact"),
                    "recovery_rate": percent_column("Verwertungsquote"),
                    "loss_rate": percent_column("Verlustquote"),
                    "coverage_ratio": percent_column("Besicherungsquote"),
                    "secured_ead_share": percent_column("Besicherter EAD-Anteil"),
                },
            )

    with st.expander("Sicherheiten, Zahlungsströme und Verlustdetails"):
        st.markdown("**Sicherheitenmix nach Art**")
        st.dataframe(
            loss.collateral_type_mix,
            hide_index=True,
            column_config={
                "collateral_value": st.column_config.NumberColumn("Sicherheitenwert", format="compact"),
                "adjusted_collateral_value": st.column_config.NumberColumn("Adjustierter Wert", format="compact"),
                "haircut_reduction": st.column_config.NumberColumn("Haircut-Abschlag", format="compact"),
                "average_haircut": percent_column("Ø Haircut"),
                "share_value": percent_column("Wertanteil"),
                "share_adjusted_value": percent_column("Anteil (adjustiert)"),
            },
        )
        st.markdown("**Verwertungsart-Mix**")
        st.dataframe(
            loss.recovery_type_mix,
            hide_index=True,
            column_config={
                "recovered_amount": st.column_config.NumberColumn("Verwerteter Betrag", format="compact"),
                "share_amount": percent_column("Betragsanteil"),
                "average_amount": st.column_config.NumberColumn("Ø Betrag", format="compact"),
            },
        )
        st.markdown("**Zeit bis zur ersten Verwertung**")
        st.dataframe(
            loss.time_to_recovery,
            hide_index=True,
            column_config={
                "ead_at_default": st.column_config.NumberColumn("EAD im Ausfall", format="compact"),
                "recovered_amount": st.column_config.NumberColumn("Verwerteter Betrag", format="compact"),
                "share_count": percent_column("Anteil der Ausfälle"),
                "share_ead": percent_column("Anteil des EAD"),
            },
        )
        st.markdown("**Verluste nach Ausfallquartal**")
        st.dataframe(
            loss.loss_by_default_quarter,
            hide_index=True,
            column_config={
                "ead_at_default": st.column_config.NumberColumn("EAD im Ausfall", format="compact"),
                "total_recoveries": st.column_config.NumberColumn("Verwertungen", format="compact"),
                "loss_amount": st.column_config.NumberColumn("Verlustbetrag", format="compact"),
                "recovery_rate": percent_column("Verwertungsquote"),
                "loss_rate": percent_column("Verlustquote"),
            },
        )
        st.markdown("**Veraltete Sicherheitenbewertungen**")
        if loss.stale_collateral.empty:
            empty_state("Keine Sicherheit überschreitet die konfigurierte Alterswarnschwelle der Bewertung.")
        else:
            st.dataframe(
                loss.stale_collateral,
                hide_index=True,
                column_config={
                    "collateral_value": st.column_config.NumberColumn("Sicherheitenwert", format="compact"),
                    "adjusted_collateral_value": st.column_config.NumberColumn("Adjustierter Wert", format="compact"),
                    "valuation_age_years": st.column_config.NumberColumn("Alter der Bewertung (Jahre)", format="%.1f"),
                    "haircut": percent_column("Haircut"),
                },
            )

    st.subheader("Benchmark-Vergleich")
    detail = filter_benchmark_banks(benchmark.detail, banks)
    detail = detail[detail["module"] == "loss"]
    if detail.empty:
        empty_state("Es sind keine Verlust-Benchmark-Zeilen verfügbar.")
    else:
        metrics = detail[["metric_id", "metric_name"]].drop_duplicates().sort_values("metric_id")
        metric_ids = metrics["metric_id"].tolist()
        selected_metric = st.selectbox(
            "Benchmark-Kennzahl",
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
                "bank_value": "Institutswert",
                "peer_value": "Vergleichsgruppenwert",
                "peer_median": "Median der Vergleichsgruppe",
                "portfolio_value": "Community-Wert",
                "gap": "Abstand zu Vergleichsgruppe",
                "relative_gap": "Relativer Abstand",
                "rank_in_peer_group": "Rang in der Vergleichsgruppe",
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
                "Vergleichsgruppe": st.column_config.TextColumn("Flag"),
                "Community-Flag": st.column_config.TextColumn("Flag"),
            },
        )
        st.caption(
            "Vergleichsgruppenwerte verwenden summierte Zähler und Nenner der Vergleichsgruppe und schließen "
            "das Institut selbst aus. Community-Werte umfassen alle verfügbaren Institute."
        )
