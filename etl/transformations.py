"""Reusable type normalisation and mapping transformations."""
from __future__ import annotations

import re
from typing import Iterable

import numpy as np
import pandas as pd

from ingestion.source_mapping import SourceMapping

ID_FIELDS = {
    "exposure_id",
    "customer_id",
    "bank_id",
    "collateral_id",
    "cashflow_id",
}
FLAG_TRUE = {"1", "true", "t", "y", "yes", "ja", "j", "default", "ausfall", "in default"}
FLAG_FALSE = {"0", "false", "f", "n", "no", "nein", "performant", "performing", "ok"}


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    text = str(value).strip()
    return text if text else None


def parse_number(value: object, locale: str = "en") -> float | None:
    """Parse a numeric value, including German thousands/decimal notation."""
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return None if pd.isna(value) else float(value)
    text = str(value).strip().replace("\u00a0", " ").replace(" ", "")
    if text in {"", "-", "–", "n/a", "NULL", "null", "None"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace("EUR", "").replace("€", "")
    if locale == "de":
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    text = re.sub(r"[^0-9eE+\-.]", "", text)
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def parse_number_series(series: pd.Series, locale: str = "en") -> pd.Series:
    return pd.Series([parse_number(value, locale) for value in series], index=series.index, dtype="float64")


def parse_date_series(series: pd.Series, locale: str = "iso") -> pd.Series:
    if series.empty:
        return pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    result = pd.to_datetime(series, errors="coerce", dayfirst=(locale == "de"), format="mixed")
    return result.dt.normalize()


def parse_flag(value: object) -> bool | None:
    text = clean_text(value)
    if text is None:
        return False
    lowered = text.lower()
    if lowered in FLAG_TRUE:
        return True
    if lowered in FLAG_FALSE:
        return False
    return None


def parse_flag_series(series: pd.Series) -> pd.Series:
    return pd.Series([parse_flag(value) for value in series], index=series.index, dtype="boolean")


def apply_value_map(series: pd.Series, mapping: dict[str, str] | None) -> pd.Series:
    normalized = series.map(lambda value: clean_text(value).upper() if clean_text(value) else None)
    if not mapping:
        return normalized
    upper_mapping = {str(key).upper(): value for key, value in mapping.items()}
    return normalized.map(lambda value: upper_mapping.get(value, value) if value is not None else None)


def standardize_frame(raw: pd.DataFrame, mapping: SourceMapping) -> pd.DataFrame:
    """Apply source mapping, constants, locale parsing and canonical typing."""
    missing = [source_col for source_col in mapping.column_map.values() if source_col not in raw.columns]
    if missing:
        raise ValueError(
            f"Source {mapping.source.filename} is missing mapped column(s): {', '.join(sorted(missing))}"
        )

    renamed = raw.rename(columns={source: canonical for canonical, source in mapping.column_map.items()})
    canonical = pd.DataFrame(index=raw.index)

    for field in mapping.fields:
        if field in renamed.columns:
            canonical[field] = renamed[field]
        elif field in mapping.constants:
            canonical[field] = mapping.constants[field]
        else:
            canonical[field] = None

    for field in mapping.date_columns:
        canonical[field] = parse_date_series(canonical[field], locale=mapping.date_locale)
    for field in mapping.numeric_columns:
        canonical[field] = parse_number_series(canonical[field], locale=mapping.number_locale)

    for field in ("rating_grade", "currency"):
        if field in canonical.columns:
            canonical[field] = canonical[field].map(lambda value: clean_text(value).upper() if clean_text(value) else None)

    for field, value_map in mapping.value_maps.items():
        if field in canonical.columns:
            canonical[field] = apply_value_map(canonical[field], value_map)

    for field in ("product_type", "industry_sector", "region", "collateral_type", "recovery_type"):
        if field in canonical.columns:
            canonical[field] = canonical[field].map(lambda value: clean_text(value).upper() if clean_text(value) else None)

    for field in ID_FIELDS:
        if field in canonical.columns:
            canonical[field] = canonical[field].map(clean_text)

    if mapping.source.dataset_type == "exposures":
        canonical["default_flag"] = parse_flag_series(canonical["default_flag"])
    canonical["adjustment_reason"] = canonical.get("adjustment_reason", pd.Series(None, index=canonical.index, dtype="object"))
    canonical["adjustment_reason"] = canonical["adjustment_reason"].map(clean_text)
    return canonical


def canonical_columns(dataset_type: str) -> list[str]:
    from ingestion.source_mapping import FIELDS_BY_DATASET

    fields = list(FIELDS_BY_DATASET[dataset_type])
    if dataset_type == "recovery_cashflows":
        fields.append("adjustment_reason")
    return fields


def record_id_series(df: pd.DataFrame, dataset_type: str) -> pd.Series:
    if dataset_type == "rating_history":
        return (
            df["exposure_id"].fillna("MISSING_ID").astype(str)
            + "@"
            + df["observation_date"].dt.strftime("%Y-%m-%d").fillna("MISSING_DATE")
        )
    id_col = {
        "exposures": "exposure_id",
        "collateral": "collateral_id",
        "recovery_cashflows": "cashflow_id",
    }[dataset_type]
    return df[id_col].fillna("MISSING_ID").astype(str)


def ensure_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    result = df.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = None
    return result
