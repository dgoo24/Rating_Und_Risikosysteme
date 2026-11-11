"""CSV source adapter with configurable delimiter support."""
from __future__ import annotations

import pandas as pd

from config.source_catalog import SourceFile


class CSVAdapter:
    def read(self, source: SourceFile) -> pd.DataFrame:
        if not source.path.exists():
            raise FileNotFoundError(f"Source file not found: {source.path}")
        # SSK003 uses semicolon-separated files; other CSV sources use commas.
        sep = ";" if source.bank_id == "SSK003" else ","
        return pd.read_csv(
            source.path,
            sep=sep,
            dtype=str,
            encoding="utf-8",
            keep_default_na=True,
        )
