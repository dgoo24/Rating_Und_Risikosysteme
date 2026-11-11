"""Pydantic contracts for canonical entities and pipeline interactions.

The data-quality engine implements business rules. These models define the
structural contract of clean records and are also used to validate batch and
reporting requests.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DatasetType = Literal["exposures", "rating_history", "collateral", "recovery_cashflows"]


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class Institution(CanonicalModel):
    bank_id: str = Field(min_length=1)
    bank_name: str = Field(min_length=1)
    region: str = Field(min_length=1)
    peer_group: str = Field(min_length=1)


class ExposureRecord(CanonicalModel):
    exposure_id: str
    bank_id: str
    customer_id: str | None = None
    snapshot_date: date
    product_type: str | None = None
    industry_sector: str | None = None
    region: str | None = None
    rating_grade: str | None = None
    exposure_at_default: float | None = None
    outstanding_balance: float | None = None
    currency: str | None = None
    origination_date: date | None = None
    maturity_date: date | None = None
    default_flag: bool = False
    default_date: date | None = None
    batch_id: str | None = None


class RatingHistoryRecord(CanonicalModel):
    exposure_id: str
    bank_id: str
    observation_date: date
    rating_grade: str | None = None
    batch_id: str | None = None


class CollateralRecord(CanonicalModel):
    collateral_id: str
    exposure_id: str
    bank_id: str
    collateral_type: str | None = None
    collateral_value: float | None = None
    valuation_date: date
    currency: str | None = None
    batch_id: str | None = None


class RecoveryCashflowRecord(CanonicalModel):
    cashflow_id: str
    exposure_id: str
    bank_id: str
    payment_date: date
    recovery_amount: float | None = None
    recovery_type: str | None = None
    adjustment_reason: str | None = None
    batch_id: str | None = None


class IngestionBatchMetadata(CanonicalModel):
    batch_id: str
    bank_id: str
    bank_name: str
    reporting_date: date
    source_system: str
    dataset_type: DatasetType
    source_file: str
    import_timestamp: datetime
    status: str = "PROCESSING"
    pipeline_run_id: str | None = None
    file_hash: str | None = None


class PipelineRunRecord(CanonicalModel):
    pipeline_run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str = "RUNNING"
    environment: str = "local-duckdb"
    notes: str | None = None


class ReportRequest(CanonicalModel):
    bank_ids: list[str] = Field(default_factory=list)
    reporting_date: date
    modules: list[Literal["rating", "loss"]] = Field(default_factory=lambda: ["rating", "loss"])
    output_formats: list[Literal["pdf", "excel", "csv", "qlik"]] = Field(
        default_factory=lambda: ["pdf", "excel"]
    )

    @field_validator("modules", "output_formats")
    @classmethod
    def non_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one value is required")
        return value


class BenchmarkDefinition(CanonicalModel):
    metric_id: str
    metric_name: str
    unit: str
    higher_is_better: bool | None = None
    description: str = ""
