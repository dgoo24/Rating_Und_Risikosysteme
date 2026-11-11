"""Data quality navigation page."""
from __future__ import annotations

from dashboard import data_quality
from dashboard.pages._shell import start

start(data_quality.render)
