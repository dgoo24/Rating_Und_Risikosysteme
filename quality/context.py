"""Shared validation context assembled from the database and batch metadata."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class ValidationContext:
    batch_id: str
    dataset_type: str
    bank_id: str
    reporting_date: date
    execution_timestamp: datetime
    reference_bank_ids: set[str] = field(default_factory=set)
    existing_exposure_keys: set[tuple[str, str]] = field(default_factory=set)
    existing_rating_keys: set[tuple[str, str]] = field(default_factory=set)
    existing_collateral_keys: set[tuple[str, str]] = field(default_factory=set)
    existing_cashflow_ids: set[str] = field(default_factory=set)
    exposure_bank_map: dict[str, str] = field(default_factory=dict)
    exposure_ead_map: dict[str, float] = field(default_factory=dict)
    existing_recovery_by_exposure: dict[str, float] = field(default_factory=dict)
