"""Gemeinsames Bootstrap für die Seiteneinstiegspunkte der st.navigation."""
from __future__ import annotations

from collections.abc import Callable

import streamlit as st

PAGE_CONFIG: dict[str, object] = dict(
    page_title="Risikoportfolio-Berichtswesen",
    page_icon=":material/account_balance:",
    layout="wide",
)


def start(render: Callable[[], None]) -> None:
    """Seite konfigurieren, Marken-Header, Berichtsumfang und Seiteninhalt aufbauen.

    ``st.set_page_config`` muss der erste Streamlit-Befehl eines Seitenskripts
    sein. Ein erneuter Aufruf nach dem Einstiegspunkt ist ein harmloses
    No-Op, sodass dasselbe Bootstrap beim ersten Laden und bei Seitenwechseln
    funktioniert.
    """
    from dashboard import common

    st.set_page_config(**PAGE_CONFIG)
    data = common.load_data()
    common.render_brand_header()
    common.render_scope_filters(data)
    render()
    common.render_footer(data)
