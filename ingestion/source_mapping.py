"""Source-to-canonical mapping layer.

Each fictional institution uses different names, formats and code values. The
mapping configuration is intentionally declarative so that a new source can be
onboarded without changing ETL business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from config.source_catalog import SourceFile, source_for

NumberLocale = Literal["en", "de"]


EXPOSURE_FIELDS = (
    "exposure_id",
    "bank_id",
    "customer_id",
    "snapshot_date",
    "product_type",
    "industry_sector",
    "region",
    "rating_grade",
    "exposure_at_default",
    "outstanding_balance",
    "currency",
    "origination_date",
    "maturity_date",
    "default_flag",
    "default_date",
)
RATING_HISTORY_FIELDS = ("exposure_id", "bank_id", "observation_date", "rating_grade")
COLLATERAL_FIELDS = (
    "collateral_id",
    "exposure_id",
    "bank_id",
    "collateral_type",
    "collateral_value",
    "valuation_date",
    "currency",
)
RECOVERY_FIELDS = (
    "cashflow_id",
    "exposure_id",
    "bank_id",
    "payment_date",
    "recovery_amount",
    "recovery_type",
    "adjustment_reason",
)

DATE_FIELDS = {
    "exposures": ("snapshot_date", "origination_date", "maturity_date", "default_date"),
    "rating_history": ("observation_date",),
    "collateral": ("valuation_date",),
    "recovery_cashflows": ("payment_date",),
}
NUMERIC_FIELDS = {
    "exposures": ("exposure_at_default", "outstanding_balance"),
    "rating_history": (),
    "collateral": ("collateral_value",),
    "recovery_cashflows": ("recovery_amount",),
}
FIELDS_BY_DATASET = {
    "exposures": EXPOSURE_FIELDS,
    "rating_history": RATING_HISTORY_FIELDS,
    "collateral": COLLATERAL_FIELDS,
    "recovery_cashflows": RECOVERY_FIELDS,
}

PRODUCT_DE = {
    "IMMOBILIENKREDIT": "MORTGAGE",
    "FIRMENKREDIT": "COMMERCIAL",
    "KMU_KREDIT": "SME",
    "PRIVATKREDIT": "CONSUMER",
    "KOMMUNALKREDIT": "MUNICIPAL",
}
SECTOR_DE = {
    "VERARBEITENDES_GEWERBE": "MANUFACTURING",
    "IMMOBILIEN": "REAL_ESTATE",
    "HANDEL": "TRADE",
    "DIENSTLEISTUNGEN": "SERVICES",
    "BAUGEWERBE": "CONSTRUCTION",
    "ENERGIE": "ENERGY",
    "OEFFENTLICHER_SEKTOR": "PUBLIC_SECTOR",
    "LANDWIRTSCHAFT": "AGRICULTURE",
    "GESUNDHEIT": "HEALTHCARE",
}
COLLATERAL_DE = {
    "IMMOBILIE": "REAL_ESTATE",
    "FINANZIELLE_SICHERHEIT": "FINANCIAL_COLLATERAL",
    "SONSTIGE": "OTHER",
}
RECOVERY_DE = {
    "ZAHLUNG": "CASH",
    "VERWERTUNG": "COLLATERAL_LIQUIDATION",
    "GARANTIE": "GUARANTEE",
}
PRODUCT_C = {
    "IMMO": "MORTGAGE",
    "FIRMA": "COMMERCIAL",
    "KMU": "SME",
    "PRIVAT": "CONSUMER",
    "KOMMUNE": "MUNICIPAL",
}
SECTOR_C = {
    "VERARB": "MANUFACTURING",
    "IMMO": "REAL_ESTATE",
    "HANDEL": "TRADE",
    "DIENST": "SERVICES",
    "BAU": "CONSTRUCTION",
    "ENERGIE": "ENERGY",
    "OEFF": "PUBLIC_SECTOR",
    "LANDW": "AGRICULTURE",
    "GESUND": "HEALTHCARE",
}
COLLATERAL_C = {"RE": "REAL_ESTATE", "FC": "FINANCIAL_COLLATERAL", "OT": "OTHER"}
RECOVERY_C = {"CASH": "CASH", "COLL": "COLLATERAL_LIQUIDATION", "GUAR": "GUARANTEE"}
PRODUCT_E = {
    "IMMO": "MORTGAGE",
    "KOM": "COMMERCIAL",
    "KMU": "SME",
    "PRIV": "CONSUMER",
    "MUN": "MUNICIPAL",
}
SECTOR_E = {
    "MANUF": "MANUFACTURING",
    "IMMO": "REAL_ESTATE",
    "TRADE": "TRADE",
    "SERV": "SERVICES",
    "CONSTR": "CONSTRUCTION",
    "ENERGY": "ENERGY",
    "PUBLIC": "PUBLIC_SECTOR",
    "AGRI": "AGRICULTURE",
    "HEALTH": "HEALTHCARE",
}
COLLATERAL_E = {"RE": "REAL_ESTATE", "FIN": "FINANCIAL_COLLATERAL", "OTH": "OTHER"}
RECOVERY_E = {"CASH": "CASH", "COLL": "COLLATERAL_LIQUIDATION", "GUAR": "GUARANTEE"}


@dataclass(frozen=True)
class SourceMapping:
    source: SourceFile
    column_map: dict[str, str]
    number_locale: NumberLocale = "en"
    date_locale: Literal["iso", "de"] = "iso"
    csv_sep: str = ","
    constants: dict[str, str] = field(default_factory=dict)
    value_maps: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def date_columns(self) -> tuple[str, ...]:
        return DATE_FIELDS[self.source.dataset_type]

    @property
    def numeric_columns(self) -> tuple[str, ...]:
        return NUMERIC_FIELDS[self.source.dataset_type]

    @property
    def fields(self) -> tuple[str, ...]:
        return FIELDS_BY_DATASET[self.source.dataset_type]

    def inverse_value_maps(self) -> dict[str, dict[str, str]]:
        return {
            field: {canonical: source for source, canonical in mapping.items()}
            for field, mapping in self.value_maps.items()
        }


def _mapping(
    bank_id: str,
    dataset_type: str,
    column_map: dict[str, str],
    number_locale: NumberLocale = "en",
    date_locale: Literal["iso", "de"] = "iso",
    csv_sep: str = ",",
    constants: dict[str, str] | None = None,
    value_maps: dict[str, dict[str, str]] | None = None,
) -> SourceMapping:
    return SourceMapping(
        source=source_for(bank_id, dataset_type),
        column_map=column_map,
        number_locale=number_locale,
        date_locale=date_locale,
        csv_sep=csv_sep,
        constants=constants or {},
        value_maps=value_maps or {},
    )


SOURCE_MAPPINGS: tuple[SourceMapping, ...] = (
    # SSK001 / canonical English
    _mapping("SSK001", "exposures", {field: field for field in EXPOSURE_FIELDS}),
    _mapping("SSK001", "rating_history", {field: field for field in RATING_HISTORY_FIELDS}),
    _mapping("SSK001", "collateral", {field: field for field in COLLATERAL_FIELDS}),
    _mapping("SSK001", "recovery_cashflows", {field: field for field in RECOVERY_FIELDS if field != "adjustment_reason"}),
    # SSK002 / German Excel
    _mapping(
        "SSK002",
        "exposures",
        {
            "exposure_id": "EngagementID",
            "bank_id": "InstitutsID",
            "customer_id": "Kundennummer",
            "snapshot_date": "Stichtag",
            "product_type": "Produktart",
            "industry_sector": "Branche",
            "region": "Region",
            "rating_grade": "Ratingklasse",
            "exposure_at_default": "EaD_EUR",
            "outstanding_balance": "Saldo_EUR",
            "currency": "Waehrung",
            "origination_date": "Ursprungsdatum",
            "maturity_date": "Faelligkeitsdatum",
            "default_flag": "Ausfall",
            "default_date": "Ausfalldatum",
        },
        number_locale="de",
        date_locale="de",
        value_maps={
            "product_type": PRODUCT_DE,
            "industry_sector": SECTOR_DE,
            "collateral_type": COLLATERAL_DE,
            "recovery_type": RECOVERY_DE,
        },
    ),
    _mapping(
        "SSK002",
        "rating_history",
        {"exposure_id": "EngagementID", "bank_id": "InstitutsID", "observation_date": "Stichtag", "rating_grade": "Ratingklasse"},
        number_locale="de",
        date_locale="de",
    ),
    _mapping(
        "SSK002",
        "collateral",
        {
            "collateral_id": "SicherheitenID",
            "exposure_id": "EngagementID",
            "bank_id": "InstitutsID",
            "collateral_type": "Sicherheitenart",
            "collateral_value": "Wert",
            "valuation_date": "Bewertungsdatum",
            "currency": "Waehrung",
        },
        number_locale="de",
        date_locale="de",
        value_maps={"collateral_type": COLLATERAL_DE},
    ),
    _mapping(
        "SSK002",
        "recovery_cashflows",
        {
            "cashflow_id": "ZahlungsID",
            "exposure_id": "EngagementID",
            "bank_id": "InstitutsID",
            "payment_date": "Zahlungsdatum",
            "recovery_amount": "Betrag",
            "recovery_type": "Art",
        },
        number_locale="de",
        date_locale="de",
        value_maps={"recovery_type": RECOVERY_DE},
    ),
    # SSK003 / semicolon, codes, German decimal comma
    _mapping(
        "SSK003",
        "exposures",
        {
            "exposure_id": "EXPOSURE_ID",
            "bank_id": "INSTITUTE",
            "customer_id": "CUSTOMER",
            "snapshot_date": "REPORT_DATE",
            "product_type": "PRODUCT",
            "industry_sector": "SECTOR",
            "region": "REGION",
            "rating_grade": "RATING",
            "exposure_at_default": "EAD",
            "outstanding_balance": "OUTSTANDING",
            "currency": "CCY",
            "origination_date": "START_DATE",
            "maturity_date": "END_DATE",
            "default_flag": "DEFAULT_FLAG",
            "default_date": "DEFAULT_DATE",
        },
        number_locale="de",
        date_locale="de",
        csv_sep=";",
        value_maps={"product_type": PRODUCT_C, "industry_sector": SECTOR_C},
    ),
    _mapping(
        "SSK003",
        "rating_history",
        {
            "exposure_id": "EXP_ID",
            "bank_id": "INSTITUTE",
            "observation_date": "OBS_DATE",
            "rating_grade": "RATING",
        },
        number_locale="de",
        date_locale="de",
        csv_sep=";",
    ),
    _mapping(
        "SSK003",
        "collateral",
        {
            "collateral_id": "COLL_ID",
            "exposure_id": "EXP_ID",
            "bank_id": "BANK",
            "collateral_type": "COLL_TYPE",
            "collateral_value": "VALUE",
            "valuation_date": "VAL_DATE",
            "currency": "CCY",
        },
        number_locale="de",
        date_locale="de",
        csv_sep=";",
        value_maps={"collateral_type": COLLATERAL_C},
    ),
    _mapping(
        "SSK003",
        "recovery_cashflows",
        {
            "cashflow_id": "CASHFLOW_ID",
            "exposure_id": "EXP_ID",
            "bank_id": "BANK",
            "payment_date": "PAY_DATE",
            "recovery_amount": "AMOUNT",
            "recovery_type": "TYPE",
        },
        number_locale="de",
        date_locale="de",
        csv_sep=";",
        value_maps={"recovery_type": RECOVERY_C},
    ),
    # SSK004 / local German names, no bank column in exposures (source constant)
    _mapping(
        "SSK004",
        "exposures",
        {
            "exposure_id": "Engagement-Nr",
            "customer_id": "Kd.-Nr",
            "snapshot_date": "Stichtag",
            "product_type": "Produkt",
            "industry_sector": "Wirtschaftszweig",
            "region": "Region",
            "rating_grade": "Rating",
            "exposure_at_default": "EAD",
            "outstanding_balance": "Offener Saldo",
            "currency": "Währung",
            "origination_date": "Ursprung",
            "maturity_date": "Fälligkeit",
            "default_flag": "Ausfall",
            "default_date": "Ausfall-Datum",
        },
        number_locale="de",
        date_locale="de",
        constants={"bank_id": "SSK004"},
        value_maps={"product_type": PRODUCT_DE, "industry_sector": SECTOR_DE},
    ),
    _mapping(
        "SSK004",
        "rating_history",
        {
            "exposure_id": "Engagement",
            "bank_id": "Institut",
            "observation_date": "Beobachtungsdatum",
            "rating_grade": "Rating",
        },
        number_locale="de",
        date_locale="de",
        value_maps={},
    ),
    _mapping(
        "SSK004",
        "collateral",
        {
            "collateral_id": "Sicherheit_Nr",
            "exposure_id": "Engagement",
            "bank_id": "Institut",
            "collateral_type": "Art",
            "collateral_value": "Verkehrswert",
            "valuation_date": "Bewertung",
            "currency": "Währung",
        },
        number_locale="de",
        date_locale="de",
        value_maps={"collateral_type": COLLATERAL_DE},
    ),
    _mapping(
        "SSK004",
        "recovery_cashflows",
        {
            "cashflow_id": "ZahlungsID",
            "exposure_id": "Engagement",
            "bank_id": "Institut",
            "payment_date": "Zahlungsdatum",
            "recovery_amount": "Betrag",
            "recovery_type": "Art",
        },
        number_locale="de",
        date_locale="de",
        value_maps={"recovery_type": RECOVERY_DE},
    ),
    # SSK005 / prepared DuckDB source tables
    _mapping(
        "SSK005",
        "exposures",
        {
            "exposure_id": "EXPOSURE_ID",
            "bank_id": "BANK_ID",
            "customer_id": "CUSTOMER_ID",
            "snapshot_date": "SNAP_DT",
            "product_type": "PROD",
            "industry_sector": "SECTOR",
            "region": "REGION",
            "rating_grade": "RATING",
            "exposure_at_default": "EAD",
            "outstanding_balance": "BALANCE",
            "currency": "CCY",
            "origination_date": "ORIG_DT",
            "maturity_date": "MAT_DT",
            "default_flag": "DEF_FLG",
            "default_date": "DEF_DT",
        },
        value_maps={"product_type": PRODUCT_E, "industry_sector": SECTOR_E},
    ),
    _mapping(
        "SSK005",
        "rating_history",
        {
            "exposure_id": "EXPOSURE_ID",
            "bank_id": "BANK_ID",
            "observation_date": "OBS_DATE",
            "rating_grade": "RATING",
        },
    ),
    _mapping(
        "SSK005",
        "collateral",
        {
            "collateral_id": "COLLATERAL_ID",
            "exposure_id": "EXPOSURE_ID",
            "bank_id": "BANK_ID",
            "collateral_type": "COLL_TYPE",
            "collateral_value": "VALUE",
            "valuation_date": "VAL_DATE",
            "currency": "CCY",
        },
        value_maps={"collateral_type": COLLATERAL_E},
    ),
    _mapping(
        "SSK005",
        "recovery_cashflows",
        {
            "cashflow_id": "CASHFLOW_ID",
            "exposure_id": "EXPOSURE_ID",
            "bank_id": "BANK_ID",
            "payment_date": "PAY_DATE",
            "recovery_amount": "AMOUNT",
            "recovery_type": "TYPE",
        },
        value_maps={"recovery_type": RECOVERY_E},
    ),
)

MAPPINGS_BY_KEY: dict[tuple[str, str], SourceMapping] = {
    (mapping.source.bank_id, mapping.source.dataset_type): mapping for mapping in SOURCE_MAPPINGS
}


def mapping_for(bank_id: str, dataset_type: str) -> SourceMapping:
    try:
        return MAPPINGS_BY_KEY[(bank_id, dataset_type)]
    except KeyError as exc:
        raise KeyError(f"No source mapping for {bank_id}/{dataset_type}") from exc
