"""Streamlit-Dashboard-Einstiegspunkt des Prototyps für automatisiertes
Risikoportfolio-Berichtswesen.

Start mit:
    streamlit run app.py

Das Dashboard liest die kuratierte DuckDB-Datenbank ausschließlich lesend und
bietet neben den beiden Fachmodulen (Rating & Scoring, Verlustschätzung) auch
die gemeinsam genutzte Infrastruktur (Datenübernahme, Datenqualität,
Benchmarking, Reporting). Die Seiteninhalte liegen im Paket ``dashboard``;
``dashboard/pages`` enthält die schlanken Navigations-Einstiegspunkte.

Die Navigation läuft als horizontale Kopfzeile - auf eine Seitenleiste wird
vollständig verzichtet.
"""
from __future__ import annotations

import streamlit as st

from dashboard.pages._shell import PAGE_CONFIG
from reporting.data_access import database_exists

st.set_page_config(**PAGE_CONFIG)

if not database_exists():
    st.error(
        "Die kuratierte Datenbank existiert noch nicht. Erzeugen Sie zunächst "
        "synthetische Daten und starten Sie danach die Aufnahmepipeline:"
    )
    st.code(
        "python -m synthetic_data.generate_data\n"
        "python -m etl.pipeline",
        language="bash",
    )
    st.stop()

pages = [
    st.Page("dashboard/pages/overview_page.py", title="Überblick", icon=":material/dashboard:", default=True),
    st.Page("dashboard/pages/ingestion_page.py", title="Datenübernahme", icon=":material/input:"),
    st.Page("dashboard/pages/data_quality_page.py", title="Datenqualität", icon=":material/verified:"),
    st.Page("dashboard/pages/rating_page.py", title="Rating & Scoring", icon=":material/grade:"),
    st.Page("dashboard/pages/loss_page.py", title="Verlustschätzung", icon=":material/trending_down:"),
    st.Page("dashboard/pages/benchmarking_page.py", title="Benchmarking", icon=":material/compare_arrows:"),
    st.Page("dashboard/pages/reporting_page.py", title="Reporting", icon=":material/description:"),
]

st.navigation(pages, position="top").run()
