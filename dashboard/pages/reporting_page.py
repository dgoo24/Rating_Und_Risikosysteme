"""Reporting navigation page."""
from __future__ import annotations

from dashboard import reporting_dashboard
from dashboard.pages._shell import start

start(reporting_dashboard.render)
