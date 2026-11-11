"""Helpers for constructing traceable validation findings."""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from etl.transformations import record_id_series
from quality.context import ValidationContext


def format_value(value: object) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    return str(value)


def missing_mask(series: pd.Series) -> pd.Series:
    textual = series.astype("string")
    return series.isna() | textual.str.strip().fillna("").eq("")


def finding_rows(
    df: pd.DataFrame,
    mask: pd.Series,
    rule_id: str,
    reason: str | pd.Series,
    field_name: str,
    ctx: ValidationContext,
) -> list[dict[str, object]]:
    if df.empty:
        return []
    ids = record_id_series(df, ctx.dataset_type)
    findings: list[dict[str, object]] = []
    for position in df.index[mask.fillna(False)]:
        if isinstance(reason, pd.Series):
            row_reason = str(reason.loc[position])
        else:
            row_reason = reason
        findings.append(
            {
                "row_index": int(position),
                "record_id": str(ids.loc[position]),
                "rule_id": rule_id,
                "field_name": field_name,
                "failed_value": format_value(df.at[position, field_name]) if field_name in df.columns else None,
                "reason": row_reason,
            }
        )
    return findings


def key_tuples(df: pd.DataFrame, fields: Iterable[str]) -> list[tuple[str, ...]]:
    """Normalise composite keys to strings for set comparisons."""
    field_list = list(fields)
    result: list[tuple[str, ...]] = []
    for _, row in df.iterrows():
        parts: list[str] = []
        complete = True
        for field in field_list:
            value = row.get(field)
            if value is None or pd.isna(value):
                complete = False
                break
            if isinstance(value, pd.Timestamp):
                parts.append(value.strftime("%Y-%m-%d"))
            else:
                parts.append(str(value).strip())
        result.append(tuple(parts) if complete else tuple())
    return result


def duplicate_within_batch(df: pd.DataFrame, fields: Iterable[str]) -> pd.Series:
    field_list = list(fields)
    complete = pd.Series(True, index=df.index)
    for field in field_list:
        complete &= ~missing_mask(df[field])
    mask = pd.Series(False, index=df.index)
    if complete.any():
        mask.loc[complete] = df.loc[complete].duplicated(subset=field_list, keep="first")
    return mask


def future_mask(series: pd.Series, reference: pd.Timestamp) -> pd.Series:
    values = pd.to_datetime(series, errors="coerce")
    return values.notna() & (values > reference)


def stale_mask(series: pd.Series, reference: pd.Timestamp, years: float) -> pd.Series:
    values = pd.to_datetime(series, errors="coerce")
    cutoff = reference - pd.DateOffset(days=int(round(365.25 * years)))
    return values.notna() & (values < cutoff)


def date_key(date_value: object) -> str | None:
    if date_value is None or pd.isna(date_value):
        return None
    return pd.Timestamp(date_value).strftime("%Y-%m-%d")
