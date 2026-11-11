"""Physical source catalogue for the fictional Sparkassen landing zone.

The generator writes these files and the ingestion layer reads the same
catalogue. Different file formats, column names and naming conventions are
deliberate to exercise the mapping layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config.settings import LANDING_DIR

INSTITUTIONS_FILE = LANDING_DIR / "institutions.csv"


@dataclass(frozen=True)
class SourceFile:
    bank_id: str
    dataset_type: str
    adapter: str  # csv | excel | duckdb
    filename: str
    source_system: str
    sheet_name: str | None = None
    table_name: str | None = None

    @property
    def path(self) -> Path:
        return LANDING_DIR / self.filename


SOURCE_CATALOG: tuple[SourceFile, ...] = (
    # SSK001: canonical English column names, CSV
    SourceFile("SSK001", "exposures", "csv", "sparkasse_a_exposures.csv", "CORE_BANKING_A"),
    SourceFile("SSK001", "rating_history", "csv", "sparkasse_a_rating_history.csv", "RATING_ENGINE_A"),
    SourceFile("SSK001", "collateral", "csv", "sparkasse_a_collateral.csv", "COLLATERAL_DB_A"),
    SourceFile("SSK001", "recovery_cashflows", "csv", "sparkasse_a_recoveries.csv", "WORKOUT_SYSTEM_A"),
    # SSK002: German column names, Excel workbooks
    SourceFile("SSK002", "exposures", "excel", "sparkasse_b_credit_data.xlsx", "CORE_BANKING_B", sheet_name="Portfolio"),
    SourceFile("SSK002", "rating_history", "excel", "sparkasse_b_rating_history.xlsx", "RATING_ENGINE_B", sheet_name="Ratings"),
    SourceFile("SSK002", "collateral", "excel", "sparkasse_b_securities.xlsx", "COLLATERAL_DB_B", sheet_name="Sicherheiten"),
    SourceFile("SSK002", "recovery_cashflows", "excel", "sparkasse_b_recoveries.xlsx", "WORKOUT_SYSTEM_B", sheet_name="Zahlungen"),
    # SSK003: semicolon-separated, code-oriented fields, German number format
    SourceFile("SSK003", "exposures", "csv", "sparkasse_c_portfolio.csv", "CORE_BANKING_C",),
    SourceFile("SSK003", "rating_history", "csv", "sparkasse_c_ratings.csv", "RATING_ENGINE_C"),
    SourceFile("SSK003", "collateral", "csv", "sparkasse_c_collateral.csv", "COLLATERAL_DB_C"),
    SourceFile("SSK003", "recovery_cashflows", "csv", "sparkasse_c_recoveries.csv", "WORKOUT_SYSTEM_C"),
    # SSK004: local German names, mixed Excel/CSV
    SourceFile("SSK004", "exposures", "excel", "sparkasse_d_engagements.xlsx", "CORE_BANKING_D", sheet_name="Engagements"),
    SourceFile("SSK004", "rating_history", "csv", "sparkasse_d_ratings.csv", "RATING_ENGINE_D"),
    SourceFile("SSK004", "collateral", "excel", "sparkasse_d_security.xlsx", "COLLATERAL_DB_D", sheet_name="Sicherheiten"),
    SourceFile("SSK004", "recovery_cashflows", "csv", "sparkasse_d_recoveries.csv", "WORKOUT_SYSTEM_D"),
    # SSK005: prepared database tables in an isolated source DuckDB file
    SourceFile("SSK005", "exposures", "duckdb", "sparkasse_e_source.duckdb", "CORE_BANKING_E", table_name="portfolio_export"),
    SourceFile("SSK005", "rating_history", "duckdb", "sparkasse_e_source.duckdb", "RATING_ENGINE_E", table_name="rating_history_export"),
    SourceFile("SSK005", "collateral", "duckdb", "sparkasse_e_source.duckdb", "COLLATERAL_DB_E", table_name="collateral_export"),
    SourceFile("SSK005", "recovery_cashflows", "duckdb", "sparkasse_e_source.duckdb", "WORKOUT_SYSTEM_E", table_name="recovery_export"),
)


def sources_for_bank(bank_id: str) -> list[SourceFile]:
    return [source for source in SOURCE_CATALOG if source.bank_id == bank_id]


def source_for(bank_id: str, dataset_type: str) -> SourceFile:
    for source in SOURCE_CATALOG:
        if source.bank_id == bank_id and source.dataset_type == dataset_type:
            return source
    raise KeyError(f"No source configured for {bank_id}/{dataset_type}")
