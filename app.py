"""Streamlit dashboard entry point for the Automated Risk Portfolio Reporting prototype.

Start with:
    streamlit run app.py

The dashboard is read-only towards the curated DuckDB database and covers both
specialized risk modules (Rating & Scoring, Loss Estimation) plus the shared
infrastructure (ingestion, data quality, benchmarking, reporting). Page bodies
live in the ``dashboard`` package; ``dashboard/pages`` contains the thin
navigation entry points registered below.
"""
from __future__ import annotations

import streamlit as st

from dashboard.pages._shell import PAGE_CONFIG
from reporting.data_access import database_exists

st.set_page_config(**PAGE_CONFIG)

if not database_exists():
    st.error(
        "The curated database does not exist yet. Generate synthetic data and run the "
        "ingestion pipeline first:"
    )
    st.code(
        "python -m synthetic_data.generate_data\n"
        "python -m etl.pipeline",
        language="bash",
    )
    st.stop()

pages = [
    st.Page("dashboard/pages/overview_page.py", title="Executive overview", icon=":material/dashboard:", default=True),
    st.Page("dashboard/pages/ingestion_page.py", title="Data ingestion", icon=":material/input:"),
    st.Page("dashboard/pages/data_quality_page.py", title="Data quality", icon=":material/verified:"),
    st.Page("dashboard/pages/rating_page.py", title="Rating & scoring", icon=":material/grade:"),
    st.Page("dashboard/pages/loss_page.py", title="Loss estimation", icon=":material/trending_down:"),
    st.Page("dashboard/pages/benchmarking_page.py", title="Benchmarking", icon=":material/compare_arrows:"),
    st.Page("dashboard/pages/reporting_page.py", title="Reporting", icon=":material/description:"),
]

st.navigation(pages).run()
