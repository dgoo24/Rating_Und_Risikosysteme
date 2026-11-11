"""Loss estimation navigation page."""
from __future__ import annotations

from dashboard import loss_dashboard
from dashboard.pages._shell import start

start(loss_dashboard.render)
