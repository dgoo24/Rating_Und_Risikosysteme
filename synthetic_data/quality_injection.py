"""Controlled quality-defect injection for the synthetic landing zone.

Defects are injected after the clean simulation and before file export. They are
recorded in a manifest so that the demonstration can be checked against expected
data-quality findings.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from config.source_catalog import source_for


def _choose(
    df: pd.DataFrame,
    rng: np.random.Generator,
    used: set[int],
    mask: pd.Series | None = None,
) -> int | None:
    candidates = np.array(df.index if mask is None else df.index[mask.fillna(False)])
    candidates = [int(index) for index in candidates if int(index) not in used]
    if not candidates:
        return None
    chosen = int(rng.choice(candidates))
    used.add(chosen)
    return chosen


def _issue(
    bank_id: str,
    dataset_type: str,
    issue_type: str,
    record_id: str,
    expected_rule_id: str,
    severity: str = "ERROR",
) -> dict[str, Any]:
    return {
        "bank_id": bank_id,
        "dataset_type": dataset_type,
        "issue_type": issue_type,
        "record_id": record_id,
        "expected_rule_id": expected_rule_id,
        "severity": severity,
        "source_file": source_for(bank_id, dataset_type).filename,
    }


def _append_duplicate(df: pd.DataFrame, index: int, **changes: Any) -> pd.DataFrame:
    duplicate = df.loc[[index]].copy()
    for column, value in changes.items():
        duplicate[column] = value
    duplicate.index = [int(df.index.max()) + 1]
    return pd.concat([df, duplicate], ignore_index=False)


def inject_quality_issues(
    bank_id: str,
    exposures: pd.DataFrame,
    rating_history: pd.DataFrame,
    collateral: pd.DataFrame,
    recoveries: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    """Return corrupted copies of all source datasets plus an issue manifest."""
    ex = exposures.copy().reset_index(drop=True)
    rat = rating_history.copy().reset_index(drop=True)
    col = collateral.copy().reset_index(drop=True)
    rec = recoveries.copy().reset_index(drop=True)
    issues: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ exposures
    used: set[int] = set()
    idx = _choose(ex, rng, used)
    if idx is not None:
        issues.append(_issue(bank_id, "exposures", "duplicate_exposure", str(ex.at[idx, "exposure_id"]), "UNIQ-EXP-001"))
        ex = _append_duplicate(ex, idx, exposure_at_default=float(ex.at[idx, "exposure_at_default"] or 0) * 1.01)

    idx = _choose(ex, rng, used)
    if idx is not None:
        issues.append(_issue(bank_id, "exposures", "missing_rating", str(ex.at[idx, "exposure_id"]), "COMP-EXP-005"))
        ex.at[idx, "rating_grade"] = None

    idx = _choose(ex, rng, used)
    if idx is not None:
        issues.append(_issue(bank_id, "exposures", "invalid_rating", str(ex.at[idx, "exposure_id"]), "CONS-EXP-002"))
        ex.at[idx, "rating_grade"] = rng.choice(["AAA", "X1", "DEFAULT"])

    idx = _choose(ex, rng, used)
    if idx is not None:
        issues.append(_issue(bank_id, "exposures", "negative_ead", str(ex.at[idx, "exposure_id"]), "PLAUS-EXP-001"))
        ex.at[idx, "exposure_at_default"] = -abs(float(ex.at[idx, "exposure_at_default"] or 1000.0))

    if bank_id != "SSK004":
        idx = _choose(ex, rng, used, ex["bank_id"].notna())
        if idx is not None:
            issues.append(_issue(bank_id, "exposures", "missing_bank_id", str(ex.at[idx, "exposure_id"]), "COMP-EXP-002"))
            ex.at[idx, "bank_id"] = None

    if bank_id in {"SSK001", "SSK005"}:
        idx = _choose(ex, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "exposures", "missing_snapshot_date", str(ex.at[idx, "exposure_id"]), "COMP-EXP-003"))
            ex.at[idx, "snapshot_date"] = pd.NaT
    elif bank_id == "SSK002":
        idx = _choose(ex, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "exposures", "invalid_bank_id", str(ex.at[idx, "exposure_id"]), "CONS-EXP-001"))
            ex.at[idx, "bank_id"] = "SSK999"
    elif bank_id == "SSK003":
        idx = _choose(ex, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "exposures", "missing_ead", str(ex.at[idx, "exposure_id"]), "COMP-EXP-004"))
            ex.at[idx, "exposure_at_default"] = None
        idx = _choose(ex, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "exposures", "future_snapshot_date", str(ex.at[idx, "exposure_id"]), "PLAUS-EXP-006"))
            ex.at[idx, "snapshot_date"] = pd.Timestamp("2099-12-31")
        idx = _choose(ex, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "exposures", "non_quarter_snapshot", str(ex.at[idx, "exposure_id"]), "CONS-EXP-004", "WARNING"))
            ex.at[idx, "snapshot_date"] = pd.Timestamp("2026-08-15")
    elif bank_id == "SSK004":
        idx = _choose(ex, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "exposures", "maturity_before_origination", str(ex.at[idx, "exposure_id"]), "PLAUS-EXP-003"))
            ex.at[idx, "maturity_date"] = pd.Timestamp(ex.at[idx, "origination_date"]) - pd.Timedelta(days=30)

    if bank_id == "SSK005":
        idx = _choose(ex, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "exposures", "unsupported_currency", str(ex.at[idx, "exposure_id"]), "CONS-EXP-003"))
            ex.at[idx, "currency"] = "USD"

    # ------------------------------------------------------------------ rating history
    used = set()
    idx = _choose(rat, rng, used)
    if idx is not None:
        issues.append(_issue(bank_id, "rating_history", "duplicate_rating_record", str(rat.at[idx, "exposure_id"]), "UNIQ-RAT-001"))
        rat = _append_duplicate(rat, idx)

    if bank_id in {"SSK001", "SSK003", "SSK005"}:
        idx = _choose(rat, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "rating_history", "invalid_rating", str(rat.at[idx, "exposure_id"]), "CONS-RAT-002"))
            rat.at[idx, "rating_grade"] = "Z"
    elif bank_id in {"SSK002", "SSK004"}:
        idx = _choose(rat, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "rating_history", "missing_rating", str(rat.at[idx, "exposure_id"]), "COMP-RAT-004"))
            rat.at[idx, "rating_grade"] = None

    used_ratings = set(rat.index)
    ghost = pd.DataFrame([{
        "exposure_id": f"EXP-GHOST-{bank_id}-01",
        "bank_id": bank_id,
        "observation_date": pd.Timestamp("2026-06-30"),
        "rating_grade": "B",
    }])
    rat = pd.concat([rat, ghost], ignore_index=True)
    issues.append(_issue(bank_id, "rating_history", "orphan_exposure", f"EXP-GHOST-{bank_id}-01", "CONS-RAT-003"))

    # ------------------------------------------------------------------ collateral
    used = set()
    idx = _choose(col, rng, used)
    if idx is not None:
        issues.append(_issue(bank_id, "collateral", "duplicate_collateral", str(col.at[idx, "collateral_id"]), "UNIQ-COL-001"))
        col = _append_duplicate(col, idx)

    idx = _choose(col, rng, used)
    if idx is not None:
        issues.append(_issue(bank_id, "collateral", "negative_collateral_value", str(col.at[idx, "collateral_id"]), "PLAUS-COL-001"))
        col.at[idx, "collateral_value"] = -abs(float(col.at[idx, "collateral_value"] or 1000.0))

    if bank_id in {"SSK001", "SSK003"}:
        used_extra = used
        ghost_col = pd.DataFrame([{
            "collateral_id": f"COL-GHOST-{bank_id}-01",
            "exposure_id": f"EXP-GHOST-{bank_id}-01",
            "bank_id": bank_id,
            "collateral_type": "REAL_ESTATE",
            "collateral_value": 500000.0,
            "valuation_date": pd.Timestamp("2026-06-30"),
            "currency": "EUR",
        }])
        col = pd.concat([col, ghost_col], ignore_index=True)
        issues.append(_issue(bank_id, "collateral", "orphan_exposure", f"COL-GHOST-{bank_id}-01", "CONS-COL-003"))
    elif bank_id in {"SSK002", "SSK004", "SSK005"}:
        idx = _choose(col, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "collateral", "missing_collateral_value", str(col.at[idx, "collateral_id"]), "COMP-COL-004"))
            col.at[idx, "collateral_value"] = None

    if bank_id == "SSK002":
        idx = _choose(col, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "collateral", "future_valuation", str(col.at[idx, "collateral_id"]), "PLAUS-COL-002"))
            col.at[idx, "valuation_date"] = pd.Timestamp("2099-12-31")
    if bank_id == "SSK004":
        idx = _choose(col, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "collateral", "stale_valuation", str(col.at[idx, "collateral_id"]), "PLAUS-COL-003", "WARNING"))
            col.at[idx, "valuation_date"] = pd.Timestamp("2018-01-01")
    if bank_id == "SSK005":
        idx = _choose(col, rng, used)
        if idx is not None:
            issues.append(_issue(bank_id, "collateral", "unsupported_currency", str(col.at[idx, "collateral_id"]), "CONS-COL-002"))
            col.at[idx, "currency"] = "CHF"

    # ------------------------------------------------------------------ recovery cashflows
    used = set()
    idx = _choose(rec, rng, used)
    if idx is not None:
        issues.append(_issue(bank_id, "recovery_cashflows", "duplicate_cashflow_id", str(rec.at[idx, "cashflow_id"]), "UNIQ-REC-001"))
        rec = _append_duplicate(rec, idx)

    idx = _choose(rec, rng, used)
    if idx is not None:
        issues.append(_issue(bank_id, "recovery_cashflows", "negative_recovery", str(rec.at[idx, "cashflow_id"]), "PLAUS-REC-001"))
        rec.at[idx, "recovery_amount"] = -abs(float(rec.at[idx, "recovery_amount"] or 1000.0))

    if bank_id in {"SSK001", "SSK004"}:
        ghost_rec = pd.DataFrame([{
            "cashflow_id": f"CF-GHOST-{bank_id}-01",
            "exposure_id": f"EXP-GHOST-{bank_id}-01",
            "bank_id": bank_id,
            "payment_date": pd.Timestamp("2026-06-30"),
            "recovery_amount": 100000.0,
            "recovery_type": "CASH",
            "adjustment_reason": None,
        }])
        rec = pd.concat([rec, ghost_rec], ignore_index=True)
        issues.append(_issue(bank_id, "recovery_cashflows", "orphan_exposure", f"CF-GHOST-{bank_id}-01", "CONS-REC-002"))

    if bank_id in {"SSK002", "SSK003", "SSK005"} and not rec.empty:
        exposure_ead = (
            ex.dropna(subset=["exposure_id", "exposure_at_default"])
            .groupby("exposure_id", as_index=False)["exposure_at_default"]
            .max()
            .set_index("exposure_id")["exposure_at_default"]
        )
        valid_defaulted = rec.merge(exposure_ead.rename("max_ead"), left_on="exposure_id", right_index=True, how="left")
        valid_defaulted = valid_defaulted[valid_defaulted["max_ead"].notna()]
        if not valid_defaulted.empty:
            row = valid_defaulted.iloc[0]
            next_id = max(
                [int(str(cf).split("-")[-1]) for cf in rec["cashflow_id"].astype(str) if str(cf).split("-")[-1].isdigit()] or [0]
            ) + 1
            over = pd.DataFrame([{
                "cashflow_id": f"CF-{bank_id}-{next_id:06d}",
                "exposure_id": row["exposure_id"],
                "bank_id": bank_id,
                "payment_date": pd.Timestamp("2026-08-31"),
                "recovery_amount": float(row["max_ead"]) * 1.35,
                "recovery_type": "CASH",
                "adjustment_reason": None,
            }])
            rec = pd.concat([rec, over], ignore_index=True)
            issues.append(_issue(bank_id, "recovery_cashflows", "recovery_exceeds_ead", str(row["exposure_id"]), "PLAUS-REC-003"))

    if bank_id == "SSK003" and not rec.empty:
        next_id = max(
            [int(str(cf).split("-")[-1]) for cf in rec["cashflow_id"].astype(str) if str(cf).split("-")[-1].isdigit()] or [0]
        ) + 1
        future = pd.DataFrame([{
            "cashflow_id": f"CF-{bank_id}-{next_id:06d}",
            "exposure_id": rec.iloc[0]["exposure_id"],
            "bank_id": bank_id,
            "payment_date": pd.Timestamp("2099-12-31"),
            "recovery_amount": 5000.0,
            "recovery_type": "CASH",
            "adjustment_reason": None,
        }])
        rec = pd.concat([rec, future], ignore_index=True)
        issues.append(_issue(bank_id, "recovery_cashflows", "future_payment_date", f"CF-{bank_id}-{next_id:06d}", "PLAUS-REC-002"))

    return (
        {"exposures": ex, "rating_history": rat, "collateral": col, "recovery_cashflows": rec},
        issues,
    )
