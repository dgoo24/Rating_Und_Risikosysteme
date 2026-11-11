"""Structured execution logging for the local pipeline."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from config.settings import LOG_DIR

_LOGGER_NAME = "risk_reporting_pipeline"
_EVENT_FILE = LOG_DIR / "pipeline_events.jsonl"


def get_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def log_event(event: str, **fields: object) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "event": event,
        **fields,
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with Path(_EVENT_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")
