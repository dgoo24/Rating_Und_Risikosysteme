"""Executive overview navigation page."""
from __future__ import annotations

from dashboard import overview
from dashboard.pages._shell import start

start(overview.render)
