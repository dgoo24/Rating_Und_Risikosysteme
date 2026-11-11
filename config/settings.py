"""Central configuration for the Automated Risk Portfolio Reporting prototype.

All paths can be overridden through environment variables. The project deliberately
uses local files and DuckDB so that the demonstration is fully reproducible without
external services.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


def _path(env_name: str, default: str) -> Path:
    raw = os.getenv(env_name, default)
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SYNTHETIC_DIR = _path("RISK_SYNTHETIC_DIR", "data/synthetic")
LANDING_DIR = SYNTHETIC_DIR / "landing"
MASTER_DIR = SYNTHETIC_DIR / "master"
EXPORT_DIR = _path("RISK_EXPORT_DIR", "data/exports")
QLIK_DIR = EXPORT_DIR / "qlik"
REPORT_DIR = _path("RISK_REPORT_DIR", "reports")
DISTRIBUTION_DIR = REPORT_DIR / "distribution"
LOG_DIR = BASE_DIR / "logs"
DB_PATH = _path("RISK_DB_PATH", "data/processed/risk_portfolio.duckdb")
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"

for _directory in (
    RAW_DIR,
    PROCESSED_DIR,
    SYNTHETIC_DIR,
    LANDING_DIR,
    MASTER_DIR,
    EXPORT_DIR,
    QLIK_DIR,
    REPORT_DIR,
    DISTRIBUTION_DIR,
    LOG_DIR,
):
    _directory.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Reporting / data assumptions
# ---------------------------------------------------------------------------
CURRENCY = "EUR"
RATING_SCALE: tuple[str, ...] = ("A", "B", "C", "D", "E", "F")
DEFAULT_OBSERVATION_MONTHS = 12
COLLATERAL_VALUATION_WARNING_YEARS = 3
QUALITY_SCORE_WARNING_THRESHOLD = 97.0
QUALITY_SCORE_CRITICAL_THRESHOLD = 90.0
DEMO_CUTOFF_DATE = date(2026, 9, 30)

# Synthetic source snapshots: nine quarter-ends from 2024-09-30 to 2026-09-30.
SNAPSHOT_DATES: tuple[str, ...] = (
    "2024-09-30",
    "2024-12-31",
    "2025-03-31",
    "2025-06-30",
    "2025-09-30",
    "2025-12-31",
    "2026-03-31",
    "2026-06-30",
    "2026-09-30",
)

DISCLAIMER = (
    "SYNTHETISCHE DEMONSTRATIONSDATEN - KEINE REGULATORISCHE "
    "BERICHTSERSTATTUNG UND KEINE ECHTEN SPARKASSEN- ODER KUNDENDATEN"
)


@dataclass(frozen=True)
class ReportSettings:
    title: str = "Risikoportfolio-Berichtswesen"
    organisation_label: str = "Fiktionale Sparkassen-Berichtsgemeinschaft"
    page_size: str = "A4"
    include_charts: bool = True


REPORT_SETTINGS = ReportSettings()


def ensure_directories() -> None:
    """Create runtime directories (safe to call repeatedly)."""
    for directory in (
        RAW_DIR,
        PROCESSED_DIR,
        SYNTHETIC_DIR,
        LANDING_DIR,
        MASTER_DIR,
        EXPORT_DIR,
        QLIK_DIR,
        REPORT_DIR,
        DISTRIBUTION_DIR,
        LOG_DIR,
        DB_PATH.parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)
