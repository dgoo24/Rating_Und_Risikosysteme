"""Tests for ETL type normalisation and declarative source mapping.

Expected values are computed by hand from the documented parsing rules
(see etl/transformations.py docstrings and the mapping configuration).
"""
from __future__ import annotations

import pandas as pd
import pytest

from etl.transformations import (
    parse_flag,
    parse_number,
    record_id_series,
    standardize_frame,
)
from ingestion.source_mapping import mapping_for


# ---------------------------------------------------------------------------
# Number / flag parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "locale", "expected"),
    [
        ("1.234,56", "de", 1234.56),
        ("1,234.56", "en", 1234.56),
        ("1.500,50", "de", 1500.50),
        ("-42,75", "de", -42.75),
        ("(500)", "en", -500.0),
        ("n/a", "en", None),
        ("", "en", None),
        (None, "en", None),
        (2.5, "en", 2.5),
        (7, "de", 7.0),
        ("1 000 000,25", "de", 1000000.25),
    ],
)
def test_parse_number(raw, locale, expected):
    assert parse_number(raw, locale) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ja", True),
        ("J", True),
        ("1", True),
        ("yes", True),
        ("ausfall", True),
        ("nein", False),
        ("0", False),
        ("performing", False),
        ("ok", False),
        ("vielleicht", None),
        (None, False),
    ],
)
def test_parse_flag(raw, expected):
    assert parse_flag(raw) == expected


def test_record_id_series_rating_history():
    # Each key component falls back independently: a missing exposure_id keeps
    # the observation date so findings still identify the affected snapshot.
    frame = pd.DataFrame(
        {
            "exposure_id": ["E1", None, "E2"],
            "observation_date": pd.to_datetime(["2026-06-30", "2026-06-30", None]),
        }
    )
    ids = record_id_series(frame, "rating_history")
    assert ids.tolist() == ["E1@2026-06-30", "MISSING_ID@2026-06-30", "E2@MISSING_DATE"]


def test_record_id_series_exposures_missing_id_becomes_placeholder():
    frame = pd.DataFrame({"exposure_id": ["E1", None]})
    ids = record_id_series(frame, "exposures")
    assert ids.tolist() == ["E1", "MISSING_ID"]


# ---------------------------------------------------------------------------
# Declarative source mapping (standardize_frame)
# ---------------------------------------------------------------------------


def _german_exposure_raw() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "EngagementID": "E-1",
                "InstitutsID": "SSK002",
                "Kundennummer": "K-1",
                "Stichtag": "30.06.2026",
                "Produktart": "IMMOBILIENKREDIT",
                "Branche": "HANDEL",
                "Region": "NORD",
                "Ratingklasse": "b",
                "EaD_EUR": "1.500,50",
                "Saldo_EUR": "1.480,25",
                "Waehrung": "eur",
                "Ursprungsdatum": "15.01.2020",
                "Faelligkeitsdatum": "30.06.2030",
                "Ausfall": "ja",
                "Ausfalldatum": "",
            }
        ]
    )


def test_standardize_frame_german_excel_mapping():
    mapping = mapping_for("SSK002", "exposures")
    canonical = standardize_frame(_german_exposure_raw(), mapping)

    row = canonical.iloc[0]
    assert row["exposure_id"] == "E-1"
    assert row["bank_id"] == "SSK002"
    assert row["snapshot_date"] == pd.Timestamp("2026-06-30")
    assert row["product_type"] == "MORTGAGE"  # value map IMMOBILIENKREDIT
    assert row["industry_sector"] == "TRADE"  # value map HANDEL
    assert row["region"] == "NORD"
    assert row["rating_grade"] == "B"  # upper-cased
    assert row["exposure_at_default"] == 1500.50  # German decimal comma
    assert row["outstanding_balance"] == 1480.25
    assert row["currency"] == "EUR"
    assert row["origination_date"] == pd.Timestamp("2020-01-15")
    assert row["maturity_date"] == pd.Timestamp("2030-06-30")
    assert bool(row["default_flag"]) is True  # 'ja'
    assert pd.isna(row["default_date"])


def test_standardize_frame_constant_bank_id():
    raw = pd.DataFrame(
        [
            {
                "Engagement-Nr": "E-9",
                "Kd.-Nr": "K-9",
                "Stichtag": "15.03.2026",
                "Produkt": "FIRMENKREDIT",
                "Wirtschaftszweig": "DIENSTLEISTUNGEN",
                "Region": "SUED",
                "Rating": "C",
                "EAD": "250,75",
                "Offener Saldo": "240,00",
                "Währung": "EUR",
                "Ursprung": "01.02.2024",
                "Fälligkeit": "01.02.2029",
                "Ausfall": "nein",
                "Ausfall-Datum": "",
            }
        ]
    )
    mapping = mapping_for("SSK004", "exposures")
    canonical = standardize_frame(raw, mapping)

    row = canonical.iloc[0]
    assert row["bank_id"] == "SSK004"  # injected constant, no source column
    assert row["exposure_at_default"] == 250.75
    assert row["product_type"] == "COMMERCIAL"  # FIRMENKREDIT
    assert row["industry_sector"] == "SERVICES"  # DIENSTLEISTUNGEN
    assert bool(row["default_flag"]) is False


def test_standardize_frame_canonical_identity_mapping():
    raw = pd.DataFrame(
        [
            {
                "exposure_id": "E-1",
                "bank_id": "SSK001",
                "customer_id": "K-1",
                "snapshot_date": "2026-06-30",
                "product_type": "MORTGAGE",
                "industry_sector": "TRADE",
                "region": "NORTH",
                "rating_grade": "A",
                "exposure_at_default": "100.5",
                "outstanding_balance": "90.0",
                "currency": "EUR",
                "origination_date": "2020-01-15",
                "maturity_date": "2030-06-30",
                "default_flag": "false",
                "default_date": "",
            }
        ]
    )
    mapping = mapping_for("SSK001", "exposures")
    canonical = standardize_frame(raw, mapping)

    row = canonical.iloc[0]
    assert row["exposure_at_default"] == 100.5
    assert row["snapshot_date"] == pd.Timestamp("2026-06-30")
    assert bool(row["default_flag"]) is False
    # Every canonical field must be present after standardisation.
    assert set(mapping.fields).issubset(canonical.columns)


def test_standardize_frame_raises_for_missing_mapped_column():
    mapping = mapping_for("SSK002", "exposures")
    raw = pd.DataFrame({"EngagementID": ["E-1"]})
    with pytest.raises(ValueError, match="missing mapped column"):
        standardize_frame(raw, mapping)


def test_mapping_for_unknown_source_raises():
    with pytest.raises(KeyError, match="No source mapping"):
        mapping_for("SSK999", "exposures")
