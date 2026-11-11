"""Shared bootstrap for the st.navigation page entry points."""
from __future__ import annotations

from collections.abc import Callable

import streamlit as st

PAGE_CONFIG: dict[str, object] = dict(
    page_title="Risk Portfolio Reporting",
    page_icon=":material/account_balance:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def start(render: Callable[[], None]) -> None:
    """Configure the page, render global scope filters and run the page body.

    ``st.set_page_config`` must be the first Streamlit command of a page
    script. Calling it again after the entry point ran it inline is a harmless
    no-op, so the same bootstrap works on first load and page switches.
    """
    from dashboard import common

    st.set_page_config(**PAGE_CONFIG)
    common.render_scope_filters(common.load_data())
    render()
