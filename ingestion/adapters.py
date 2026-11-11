"""Adapter contracts for heterogeneous source systems."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pandas as pd

from config.source_catalog import SourceFile


class SourceAdapter(Protocol):
    def read(self, source: SourceFile) -> pd.DataFrame: ...


def adapter_for(kind: str) -> SourceAdapter:
    from ingestion.csv_adapter import CSVAdapter
    from ingestion.database_adapter import DatabaseAdapter
    from ingestion.excel_adapter import ExcelAdapter

    adapters = {"csv": CSVAdapter(), "excel": ExcelAdapter(), "duckdb": DatabaseAdapter()}
    try:
        return adapters[kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported source adapter: {kind}") from exc
