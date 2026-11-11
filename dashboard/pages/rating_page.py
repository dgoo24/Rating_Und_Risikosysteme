"""Rating & scoring navigation page."""
from __future__ import annotations

from dashboard import rating_dashboard
from dashboard.pages._shell import start

start(rating_dashboard.render)
