"""Report and distribution audit logging."""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from config.settings import DB_PATH
from database.connection import connect, utc_now


def new_report_id(prefix: str = "RPT") -> str:
    return f"{prefix}-{utc_now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8].upper()}"


def new_distribution_id() -> str:
    return f"DIST-{utc_now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8].upper()}"


def log_report(
    report_id: str,
    report_type: str,
    module: str | None,
    file_format: str,
    bank_id: str | None,
    reporting_date: object,
    file_path: str | Path,
    status: str,
    data_version: str | None = None,
    batch_ids: list[str] | None = None,
    error_message: str | None = None,
    db_path: str | Path | None = None,
) -> None:
    path = Path(file_path)
    with connect(db_path or DB_PATH) as con:
        con.execute(
            """
            INSERT OR REPLACE INTO report_log
            (report_id, report_type, module, file_format, bank_id, reporting_date,
             file_path, generated_at, status, data_version, batch_ids, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                report_id,
                report_type,
                module,
                file_format,
                bank_id,
                str(reporting_date),
                str(path),
                utc_now(),
                status,
                data_version,
                ", ".join(batch_ids or [])[:4000] or None,
                error_message[:4000] if error_message else None,
            ],
        )


def log_distribution(
    distribution_id: str,
    report_id: str | None,
    channel: str,
    recipient_group: str,
    status: str,
    detail: str,
    distributed_at: datetime | None = None,
    db_path: str | Path | None = None,
) -> None:
    with connect(db_path or DB_PATH) as con:
        con.execute(
            """
            INSERT OR REPLACE INTO distribution_log
            (distribution_id, report_id, channel, recipient_group, status, distributed_at, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                distribution_id,
                report_id,
                channel,
                recipient_group,
                status,
                distributed_at or utc_now(),
                detail[:4000],
            ],
        )
