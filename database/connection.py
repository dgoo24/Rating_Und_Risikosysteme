"""DuckDB connection and query utilities.

The rest of the application accesses the database exclusively through this
module. A future PostgreSQL adapter can implement the same small interface
without changing the analytical modules.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import duckdb
import pandas as pd

from config.settings import DB_PATH, SCHEMA_PATH


def _schema_sql() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def initialize_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_schema_sql())


def connect(db_path: str | Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection and ensure the schema exists for writable use."""
    path = Path(db_path) if db_path is not None else DB_PATH
    if read_only:
        if str(path) != ":memory:" and not path.exists():
            raise FileNotFoundError(f"Database does not exist: {path}")
        return duckdb.connect(str(path), read_only=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = str(path) == ":memory:" or not path.exists()
    con = duckdb.connect(str(path))
    if is_new or not read_only:
        initialize_schema(con)
    return con


def initialize_database(db_path: str | Path | None = None, reset: bool = False) -> Path:
    """Create the schema, optionally removing the existing local database first."""
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if reset and str(path) != ":memory:":
        for candidate in (path, Path(str(path) + ".wal")):
            if candidate.exists():
                candidate.unlink()
    with connect(path) as con:
        initialize_schema(con)
    return path


def query_df(
    sql: str,
    params: Sequence[object] | None = None,
    db_path: str | Path | None = None,
    read_only: bool = False,
) -> pd.DataFrame:
    """Execute a SELECT and return a pandas DataFrame."""
    with connect(db_path, read_only=read_only) as con:
        return con.execute(sql, params or []).df()


def execute_statement(
    sql: str,
    params: Sequence[object] | None = None,
    db_path: str | Path | None = None,
) -> None:
    with connect(db_path) as con:
        con.execute(sql, params or [])


def table_names(db_path: str | Path | None = None) -> list[str]:
    with connect(db_path) as con:
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
    return [row[0] for row in rows]


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def dataframe_for_insert(
    df: pd.DataFrame,
    columns: Iterable[str] | None = None,
    date_columns: Iterable[str] = (),
) -> pd.DataFrame:
    """Select target columns and convert date columns to Python date/NULL values.

    DuckDB can ingest pandas date values directly, but normalising date objects
    avoids ambiguous datetime/DATE casts and keeps the API portable.
    """
    selected = list(columns) if columns is not None else list(df.columns)
    out = df.loc[:, selected].copy()
    for column in date_columns:
        if column not in out.columns:
            continue
        out[column] = [
            None if _is_missing(value) else (value.date() if isinstance(value, datetime) else value)
            for value in out[column]
        ]
    for column in out.columns:
        if out[column].dtype == object:
            out[column] = out[column].map(lambda value: None if _is_missing(value) else value)
    return out


def insert_dataframe(
    con: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    table: str,
    columns: Iterable[str],
    date_columns: Iterable[str] = (),
    registration_name: str = "_insert_df",
) -> None:
    if df.empty:
        return
    selected = list(columns)
    prepared = dataframe_for_insert(df, selected, date_columns)
    con.register(registration_name, prepared)
    try:
        col_sql = ", ".join(selected)
        con.execute(f"INSERT INTO {table} ({col_sql}) SELECT {col_sql} FROM {registration_name}")
    finally:
        con.unregister(registration_name)


def truncate_table(con: duckdb.DuckDBPyConnection, table: str) -> None:
    con.execute(f"DELETE FROM {table}")


def utc_now() -> datetime:
    """Naive UTC timestamp (kept naive to match DuckDB TIMESTAMP columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return date.today()
