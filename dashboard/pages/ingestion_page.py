"""Data ingestion navigation page."""
from __future__ import annotations

from dashboard import ingestion_dashboard
from dashboard.pages._shell import start

start(ingestion_dashboard.render)
