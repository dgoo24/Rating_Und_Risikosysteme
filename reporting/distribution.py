"""Simulated report distribution.

No email, file share, API or other external channel is used. Distribution is a
local simulation that records fictional recipient groups and writes an audit
manifest. The word SIMULATED is part of every status and channel value.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from config.settings import DISCLAIMER, DISTRIBUTION_DIR
from database.connection import utc_now
from reporting.audit import log_distribution, new_distribution_id

FICTIONAL_RECIPIENTS = (
    "Fiktiver Risikoausschuss",
    "Fiktives Vorstands-Reporting",
    "Fiktive Interne Revision",
    "Fiktive Peer-Review-Gruppe",
)


def _date_label(reporting_date: object) -> str:
    """ISO date label that is safe as a file name on every platform."""
    return pd.Timestamp(reporting_date).date().isoformat()


def simulate_distribution(
    reports: list[dict[str, object]],
    reporting_date: object,
    output_dir: Path | None = None,
    recipients: tuple[str, ...] = FICTIONAL_RECIPIENTS,
) -> tuple[list[dict[str, object]], Path]:
    date_label = _date_label(reporting_date)
    directory = output_dir or (DISTRIBUTION_DIR / date_label)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now()
    entries: list[dict[str, object]] = []
    for report in reports:
        report_id = str(report.get("report_id", ""))
        path = str(report.get("path", ""))
        bank_id = report.get("bank_id")
        for recipient in recipients:
            distribution_id = new_distribution_id()
            detail = (
                f"Nur SIMULIERTE Verteilung. Es wurde kein externes System kontaktiert. "
                F"Fiktive Empfängergruppe: {recipient}. Lokales Artefakt: {path}"
            )
            log_distribution(
                distribution_id=distribution_id,
                report_id=report_id or None,
                channel="SIMULATED_LOCAL_FILE",
                recipient_group=recipient,
                status="SIMULATED",
                detail=detail,
                distributed_at=timestamp,
            )
            entries.append(
                {
                    "distribution_id": distribution_id,
                    "report_id": report_id,
                    "report_type": report.get("report_type"),
                    "file_format": report.get("file_format"),
                    "bank_id": bank_id,
                    "recipient_group": recipient,
                    "channel": "SIMULATED_LOCAL_FILE",
                    "status": "SIMULATED",
                    "distributed_at": timestamp.isoformat(),
                    "artefact_path": path,
                    "detail": "Keine externe Übertragung. Ausschließlich Demonstrations-Prüfeintrag.",
                }
            )
    manifest = {
        "disclaimer": DISCLAIMER,
        "simulation": True,
        "generated_at": timestamp.isoformat(),
        "reporting_date": date_label,
        "recipient_groups": list(recipients),
        "entries": entries,
        "notes": [
            "Dieses Manifest dokumentiert ausschließlich eine simulierte lokale Verteilung.",
            "Es wurden keine E-Mails, Dateifreigaben, APIs oder externen Empfänger kontaktiert.",
            "Die Empfängergruppen sind fiktiv und existieren nur für diese Demonstration.",
        ],
    }
    manifest_path = directory / f"distribution_manifest_{timestamp:%Y%m%d_%H%M%S}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return entries, manifest_path
