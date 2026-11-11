"""Excel source adapter using OpenPyXL through pandas."""
from __future__ import annotations

import pandas as pd

from config.source_catalog import SourceFile


class ExcelAdapter:
    def read(self, source: SourceFile) -> pd.DataFrame:
        if not source.path.exists():
            raise FileNotFoundError(f"Source file not found: {source.path}")
        return pd.read_excel(
            source.path,
            sheet_name=source.sheet_name or 0,
            dtype=object,
        )
