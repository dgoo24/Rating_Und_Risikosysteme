"""Dashboard smoke tests using Streamlit's AppTest harness.

Each navigation page is executed against the real curated DuckDB database that
the synthetic generator and ingestion pipeline produce. The dashboard is
read-only, so these tests do not mutate any state. They are skipped when the
curated database has not been generated yet (fresh checkout).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from config.settings import DB_PATH

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "app.py"

PAGES = [
    "dashboard/pages/overview_page.py",
    "dashboard/pages/ingestion_page.py",
    "dashboard/pages/data_quality_page.py",
    "dashboard/pages/rating_page.py",
    "dashboard/pages/loss_page.py",
    "dashboard/pages/benchmarking_page.py",
    "dashboard/pages/reporting_page.py",
]

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="curated DuckDB not generated yet - run python -m synthetic_data.generate_data and python -m etl.pipeline",
)


def test_dashboard_entry_point_runs_default_page():
    at = AppTest.from_file(str(APP_PATH), default_timeout=900)
    at.run()
    assert not at.exception, [str(exc.value) for exc in at.exception]
    # The overview page renders its KPI metrics.
    assert len(at.metric) > 0


def test_every_dashboard_page_renders_without_exceptions():
    at = AppTest.from_file(str(APP_PATH), default_timeout=900)
    at.run()
    failures: list[tuple[str, str]] = []
    if at.exception:
        failures.append(("app.py (default page)", "\n".join(str(exc.value) for exc in at.exception)))
    for page in PAGES:
        at.switch_page(page)
        at.run()
        if at.exception:
            failures.append((page, "\n".join(str(exc.value) for exc in at.exception)))
    assert not failures, failures


def test_dashboard_reports_missing_database(monkeypatch, tmp_path):
    """Without a curated database the entry point stops with an error message."""
    monkeypatch.setattr("reporting.data_access.DB_PATH", tmp_path / "missing.duckdb")

    at = AppTest.from_file(str(APP_PATH), default_timeout=900)
    at.run()
    assert not at.exception
    assert len(at.error) == 1
    assert "kuratierte Datenbank" in at.error[0].value
