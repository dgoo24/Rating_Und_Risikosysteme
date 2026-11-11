"""Rating migration analysis between two reporting snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from modules.rating_scoring.calculations import RATING_ORDER, as_timestamp, prepare_exposures


@dataclass
class MigrationResult:
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    matrix_counts: pd.DataFrame
    matrix_pct: pd.DataFrame
    summary: dict[str, object]
    transitions: pd.DataFrame
    by_bank: pd.DataFrame


def _empty_result(start: pd.Timestamp, end: pd.Timestamp) -> MigrationResult:
    return empty_migration_result(start, end)


def empty_migration_result(start: object, end: object) -> MigrationResult:
    start_ts = as_timestamp(start)
    end_ts = as_timestamp(end)
    matrix = pd.DataFrame(0, index=RATING_ORDER, columns=RATING_ORDER)
    return MigrationResult(
        start_date=start_ts,
        end_date=end_ts,
        matrix_counts=matrix,
        matrix_pct=matrix.astype(float),
        summary={
            "start_date": start_ts,
            "end_date": end_ts,
            "base_count": 0,
            "target_count": 0,
            "matched_count": 0,
            "upgrades": 0,
            "downgrades": 0,
            "unchanged": 0,
            "entries": 0,
            "exits": 0,
            "upgrade_rate": None,
            "downgrade_rate": None,
        },
        transitions=pd.DataFrame(),
        by_bank=pd.DataFrame(),
    )


def _summarize_transitions(merged: pd.DataFrame) -> dict[str, object]:
    matched = merged[merged["matched"]].copy()
    counts = matched["transition"].value_counts() if not matched.empty else pd.Series(dtype="int64")
    matched_count = len(matched)
    upgrades = int(counts.get("UPGRADE", 0))
    downgrades = int(counts.get("DOWNGRADE", 0))
    unchanged = int(counts.get("UNCHANGED", 0))
    return {
        "matched_count": matched_count,
        "upgrades": upgrades,
        "downgrades": downgrades,
        "unchanged": unchanged,
        "upgrade_rate": upgrades / matched_count if matched_count else None,
        "downgrade_rate": downgrades / matched_count if matched_count else None,
    }


def calculate_migration(
    rating_history: pd.DataFrame,
    start_date: object,
    end_date: object,
    bank_ids: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    exposures: pd.DataFrame | None = None,
) -> MigrationResult:
    start = as_timestamp(start_date)
    end = as_timestamp(end_date)
    if start >= end:
        raise ValueError("Migration start date must be earlier than end date")

    history = rating_history.copy()
    history["observation_date"] = pd.to_datetime(history["observation_date"], errors="coerce").dt.normalize()
    history["rating_grade"] = history["rating_grade"].astype("string").str.upper()
    history["bank_id"] = history["bank_id"].astype("string")
    history = history[history["rating_grade"].isin(RATING_ORDER)]

    allowed_exposures: set[str] | None = None
    if sectors:
        if exposures is None or exposures.empty:
            return _empty_result(start, end)
        exposure_frame = prepare_exposures(exposures)
        exposure_frame = exposure_frame[exposure_frame["industry_sector"].isin(list(sectors))]
        allowed_exposures = set(exposure_frame["exposure_id"].astype(str))

    base = history[history["observation_date"] == start][["exposure_id", "bank_id", "rating_grade"]].copy()
    target = history[history["observation_date"] == end][["exposure_id", "bank_id", "rating_grade"]].copy()
    if bank_ids:
        base = base[base["bank_id"].isin(list(bank_ids))]
        target = target[target["bank_id"].isin(list(bank_ids))]
    if allowed_exposures is not None:
        base = base[base["exposure_id"].astype(str).isin(allowed_exposures)]
        target = target[target["exposure_id"].astype(str).isin(allowed_exposures)]
    if base.empty and target.empty:
        return _empty_result(start, end)

    merged = base.merge(target, on="exposure_id", how="outer", suffixes=("_start", "_end"), indicator=True)
    merged["bank_id"] = merged["bank_id_start"].where(merged["bank_id_start"].notna(), merged["bank_id_end"])
    merged["matched"] = merged["rating_grade_start"].notna() & merged["rating_grade_end"].notna()

    start_rank = merged["rating_grade_start"].map({rating: index for index, rating in enumerate(RATING_ORDER, start=1)})
    end_rank = merged["rating_grade_end"].map({rating: index for index, rating in enumerate(RATING_ORDER, start=1)})
    merged["transition"] = "NOT_MATCHED"
    merged.loc[merged["matched"] & (start_rank == end_rank), "transition"] = "UNCHANGED"
    merged.loc[merged["matched"] & (end_rank < start_rank), "transition"] = "UPGRADE"
    merged.loc[merged["matched"] & (end_rank > start_rank), "transition"] = "DOWNGRADE"
    merged["period_status"] = merged["_merge"].map(
        {"both": "MATCHED", "left_only": "EXIT", "right_only": "ENTRY"}
    )

    matched = merged[merged["matched"]]
    matrix_counts = pd.crosstab(matched["rating_grade_start"], matched["rating_grade_end"])
    matrix_counts = matrix_counts.reindex(index=RATING_ORDER, columns=RATING_ORDER, fill_value=0)
    row_sums = matrix_counts.sum(axis=1).astype(float)
    matrix_pct = matrix_counts.astype(float).div(row_sums.where(row_sums > 0), axis=0).fillna(0.0)

    summary = {
        "start_date": start,
        "end_date": end,
        "base_count": int(len(base)),
        "target_count": int(len(target)),
        "entries": int((merged["period_status"] == "ENTRY").sum()),
        "exits": int((merged["period_status"] == "EXIT").sum()),
        **_summarize_transitions(merged),
    }

    by_bank_rows: list[dict[str, object]] = []
    for bank_id, group in merged.groupby("bank_id", dropna=True):
        bank_summary = _summarize_transitions(group)
        by_bank_rows.append(
            {
                "bank_id": bank_id,
                "base_count": int((group["_merge"] != "right_only").sum()),
                "target_count": int((group["_merge"] != "left_only").sum()),
                "entries": int((group["period_status"] == "ENTRY").sum()),
                "exits": int((group["period_status"] == "EXIT").sum()),
                **bank_summary,
            }
        )
    by_bank = pd.DataFrame(by_bank_rows).sort_values("bank_id").reset_index(drop=True) if by_bank_rows else pd.DataFrame()

    transitions = merged[
        [
            "exposure_id", "bank_id", "rating_grade_start", "rating_grade_end",
            "transition", "period_status",
        ]
    ].rename(columns={"rating_grade_start": "base_rating", "rating_grade_end": "target_rating"})
    return MigrationResult(
        start_date=start,
        end_date=end,
        matrix_counts=matrix_counts,
        matrix_pct=matrix_pct,
        summary=summary,
        transitions=transitions.reset_index(drop=True),
        by_bank=by_bank,
    )


def migration_matrix_long(matrix: pd.DataFrame) -> pd.DataFrame:
    if matrix.empty:
        return pd.DataFrame(columns=["base_rating", "target_rating", "transition_count"])
    result = matrix.stack().reset_index()
    result.columns = ["base_rating", "target_rating", "transition_count"]
    return result
