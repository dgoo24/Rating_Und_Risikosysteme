"""Prepared database-table adapter.

The prototype reads an isolated source DuckDB file. The same adapter boundary
could be implemented for PostgreSQL, Oracle or a data-warehouse table.
"""
from __future__ import annotations

import duckdb
import pandas as pd

from config.source_catalog import SourceFile


class DatabaseAdapter:
    def read(self, source: SourceFile) -> pd.DataFrame:
        if not source.path.exists():
            raise FileNotFoundError(f"Source database not found: {source.path}")
        if not source.table_name:
            raise ValueError(f"No table configured for source {source.filename}")
        with duckdb.connect(str(source.path), read_only=True) as con:
            table = source.table_name.replace('"', "")
            return con.execute(f'SELECT * FROM "{table}"').df()
