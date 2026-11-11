"""Benchmarking navigation page."""
from __future__ import annotations

from dashboard import benchmarking_dashboard
from dashboard.pages._shell import start

start(benchmarking_dashboard.render)
