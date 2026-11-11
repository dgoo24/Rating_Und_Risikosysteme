"""Write canonical synthetic records using each bank's source conventions."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from config.source_catalog import SourceFile
from ingestion.source_mapping import SourceMapping

FLAG_STYLES = {
    "SSK001": ("Y", "N"),
    "SSK002": ("JA", "NEIN"),
    "SSK003": ("1", "0"),
    "SSK004": ("ja", "nein"),
    "SSK005": ("true", "false"),
}


def _format_date(value: object, locale: str) -> object:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    return timestamp.strftime("%d.%m.%Y" if locale == "de" else "%Y-%m-%d")


def _format_number(value: object, locale: str) -> object:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if locale == "de":
        return f"{number:.2f}".replace(".", ",")
    return number


def source_ready_frame(mapping: SourceMapping, df: pd.DataFrame, use_german_number_strings: bool) -> pd.DataFrame:
    """Project canonical records into the source schema for a bank."""
    output: dict[str, list[object]] = {}
    inverse_maps = mapping.inverse_value_maps()
    true_label, false_label = FLAG_STYLES[mapping.source.bank_id]
    number_strings = use_german_number_strings and mapping.number_locale == "de"

    for canonical in mapping.fields:
        if canonical not in mapping.column_map:
            continue
        source_col = mapping.column_map[canonical]
        if canonical not in df.columns:
            continue
        series = df[canonical]
        values: list[object] = []
        for value in series:
            if canonical in mapping.date_columns:
                values.append(_format_date(value, mapping.date_locale))
            elif canonical in mapping.numeric_columns:
                values.append(_format_number(value, "de") if number_strings else (None if pd.isna(value) else float(value)))
            elif canonical == "default_flag":
                if value is None or pd.isna(value):
                    values.append(None)
                elif mapping.source.bank_id == "SSK005":
                    values.append(bool(value))
                else:
                    values.append(true_label if bool(value) else false_label)
            else:
                if value is None or pd.isna(value):
                    values.append(None)
                elif canonical in mapping.value_maps:
                    inverse = inverse_maps.get(canonical, {})
                    values.append(inverse.get(str(value), str(value)))
                else:
                    values.append(value)
        output[source_col] = values
    return pd.DataFrame(output, index=df.index)


def write_file(mapping: SourceMapping, df: pd.DataFrame) -> Path:
    source = mapping.source
    target = source.path
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.adapter == "csv":
        ready = source_ready_frame(mapping, df, use_german_number_strings=True)
        ready.to_csv(target, sep=mapping.csv_sep, index=False, encoding="utf-8", lineterminator="\n")
    elif source.adapter == "excel":
        ready = source_ready_frame(mapping, df, use_german_number_strings=False)
        with pd.ExcelWriter(target, engine="xlsxwriter", datetime_format="DD.MM.YYYY") as writer:
            ready.to_excel(writer, sheet_name=source.sheet_name or "Daten", index=False)
    elif source.adapter == "duckdb":
        # Database sources are grouped by the caller into one source file.
        raise ValueError("DuckDB sources must be written through write_database_sources")
    else:
        raise ValueError(f"Unsupported adapter {source.adapter}")
    return target


def write_database_sources(
    grouped: dict[str, dict[str, pd.DataFrame]],
    mapping_by_dataset: dict[str, SourceMapping],
) -> Path | None:
    """Write SSK005 prepared tables to its isolated source DuckDB file."""
    if not grouped:
        return None
    first = next(iter(mapping_by_dataset.values()))
    target = first.source.path
    if target.exists():
        target.unlink()
    con = duckdb.connect(str(target))
    try:
        for dataset_type, frame in grouped.items():
            mapping = mapping_by_dataset[dataset_type]
            ready = source_ready_frame(mapping, frame, use_german_number_strings=False)
            table = mapping.source.table_name or dataset_type
            con.register("_source_df", ready)
            con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM _source_df")
            con.unregister("_source_df")
    finally:
        con.close()
    return target
