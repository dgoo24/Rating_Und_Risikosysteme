"""Generate a reproducible synthetic multi-Sparkassen risk portfolio.

Run: python synthetic_data/generate_data.py
The generated source files contain deliberately controlled data-quality defects;
the clean simulation and an issue manifest are retained separately.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from config.institutions import INSTITUTIONS
from config.rating_pd_mapping import RATING_PD_MAPPING, RATING_SCALE
from config.settings import DEMO_CUTOFF_DATE, DISCLAIMER, LANDING_DIR, MASTER_DIR, SNAPSHOT_DATES
from config.source_catalog import INSTITUTIONS_FILE, SOURCE_CATALOG
from ingestion.source_mapping import SOURCE_MAPPINGS, mapping_for
from synthetic_data.exporters import write_database_sources, write_file
from synthetic_data.profiles import PROFILE_BY_BANK, PROFILES, BankProfile, PRODUCT_TYPES, SECTORS
from synthetic_data.quality_injection import inject_quality_issues

SEED = 20261110
PRODUCT_EAD = {
    "MORTGAGE": (650_000, 0.55),
    "COMMERCIAL": (1_400_000, 0.80),
    "SME": (380_000, 0.65),
    "CONSUMER": (28_000, 0.50),
    "MUNICIPAL": (3_500_000, 1.00),
}
PRODUCT_TERM_YEARS = {
    "MORTGAGE": (8, 25),
    "COMMERCIAL": (3, 12),
    "SME": (3, 10),
    "CONSUMER": (2, 7),
    "MUNICIPAL": (7, 20),
}
REGIONS = ("NORTH", "SOUTH", "WEST", "CENTRAL", "EAST")


def snapshots() -> list[pd.Timestamp]:
    return [pd.Timestamp(value) for value in SNAPSHOT_DATES]


def _generate_master(profile: BankProfile, rng: np.random.Generator, first_snapshot: pd.Timestamp, cutoff: pd.Timestamp) -> pd.DataFrame:
    n = profile.master_count
    seq = np.arange(1, n + 1)
    bank = profile.bank_id
    product = rng.choice(PRODUCT_TYPES, size=n, p=np.array(profile.product_weights) / sum(profile.product_weights))
    sector = rng.choice(SECTORS, size=n, p=np.array(profile.sector_weights) / sum(profile.sector_weights))
    region_primary = PROFILE_BY_BANK[bank].bank_id
    from config.institutions import BANK_REGIONS

    primary_region = BANK_REGIONS[bank]
    other_regions = [r for r in REGIONS if r != primary_region]
    region = np.where(rng.random(n) < 0.88, primary_region, rng.choice(other_regions, size=n))

    pre_period_days = rng.integers(30, 2300, size=n)
    within_period_days = rng.integers(0, (cutoff - first_snapshot).days + 1, size=n)
    use_pre_period = rng.random(n) < 0.68
    origination = np.where(
        use_pre_period,
        first_snapshot - pd.to_timedelta(pre_period_days, unit="D"),
        first_snapshot + pd.to_timedelta(within_period_days, unit="D"),
    )
    origination = pd.to_datetime(origination).normalize()

    low_years = np.array([PRODUCT_TERM_YEARS[p][0] for p in product])
    high_years = np.array([PRODUCT_TERM_YEARS[p][1] for p in product])
    term_days = rng.uniform(low_years, high_years) * 365.25
    maturity = pd.to_datetime(origination) + pd.to_timedelta(term_days, unit="D")
    maturity = maturity.normalize()

    means = np.array([PRODUCT_EAD[p][0] for p in product])
    sigmas = np.array([PRODUCT_EAD[p][1] for p in product])
    base_ead = np.exp(rng.normal(np.log(means), sigmas))
    base_ead = np.clip(base_ead, 2_000, 25_000_000)
    base_ead = np.round(base_ead / 100) * 100

    rating_codes = rng.choice(len(RATING_SCALE), size=n, p=np.array(profile.rating_probabilities) / sum(profile.rating_probabilities))
    balance_ratio = np.clip(rng.beta(5.5, 1.8, size=n), 0.50, 0.995)
    latent_risk = np.clip(rng.lognormal(mean=0.0, sigma=0.42, size=n), 0.35, 3.0)

    return pd.DataFrame(
        {
            "exposure_id": [f"EXP-{bank}-{value:05d}" for value in seq],
            "bank_id": bank,
            "customer_id": [f"CUST-{bank}-{max(1, value // 2):05d}" for value in seq],
            "product_type": product,
            "industry_sector": sector,
            "region": region,
            "origination_date": origination,
            "maturity_date": maturity,
            "base_ead": base_ead,
            "balance_ratio": balance_ratio,
            "rating_code": rating_codes,
            "latent_risk": latent_risk,
            "default_date": pd.NaT,
        }
    )


def _simulate_exposures(
    profile: BankProfile,
    master: pd.DataFrame,
    snapshot_dates: list[pd.Timestamp],
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rating_codes = master["rating_code"].to_numpy().copy()
    default_dates = pd.Series(pd.NaT, index=master.index, dtype="datetime64[ns]")
    pd_map = np.array([RATING_PD_MAPPING[rating] for rating in RATING_SCALE])
    exposure_rows: list[pd.DataFrame] = []
    previous_snapshot: pd.Timestamp | None = None
    benchmark_growth = 0.015

    for snapshot in snapshot_dates:
        active = (master["origination_date"] <= snapshot) & (master["maturity_date"] > snapshot)
        active_idx = master.index[active]

        if previous_snapshot is not None and len(active_idx) > 0:
            not_defaulted = default_dates.loc[active_idx].isna().to_numpy()
            transition_idx = active_idx[not_defaulted]
            if len(transition_idx) > 0:
                draw = rng.random(len(transition_idx))
                upgrade = 0.038 + profile.transition_upgrade_bias
                downgrade = 0.042 - profile.transition_upgrade_bias
                double = 0.006
                codes = rating_codes[transition_idx]
                codes = np.where(draw < upgrade, codes - 1, codes)
                codes = np.where((draw >= upgrade) & (draw < upgrade + downgrade), codes + 1, codes)
                codes = np.where(
                    (draw >= upgrade + downgrade) & (draw < upgrade + downgrade + double),
                    codes + 2,
                    codes,
                )
                codes = np.where(draw >= 1.0 - double, codes - 2, codes)
                rating_codes[transition_idx] = np.clip(codes, 0, len(RATING_SCALE) - 1)

        eligible = active_idx[default_dates.loc[active_idx].isna()]
        if len(eligible) > 0:
            annual_pd = pd_map[rating_codes[eligible]] * profile.risk_multiplier * master.loc[eligible, "latent_risk"].to_numpy() * 2.6
            quarterly_pd = np.clip(1.0 - np.power(np.maximum(1.0 - annual_pd, 0.0), 0.25), 0.0, 0.20)
            new_default = rng.random(len(eligible)) < quarterly_pd
            for index in eligible[new_default]:
                lower_bound = max(master.at[index, "origination_date"], (snapshot - pd.Timedelta(days=88)))
                available_days = max(1, (snapshot - lower_bound).days)
                offset = int(rng.integers(1, min(available_days, 88) + 1))
                default_dates.at[index] = snapshot - pd.Timedelta(days=offset)

        years_since_orig = (snapshot - master.loc[active_idx, "origination_date"]).dt.days / 365.25
        ead = master.loc[active_idx, "base_ead"] * (1.0 + benchmark_growth * np.clip(years_since_orig, 0, 12))
        ead = np.round(ead, 2)
        outstanding = np.round(ead * master.loc[active_idx, "balance_ratio"], 2)
        defaults_mask = default_dates.loc[active_idx].notna()

        frame = pd.DataFrame(
            {
                "exposure_id": master.loc[active_idx, "exposure_id"].to_numpy(),
                "bank_id": profile.bank_id,
                "customer_id": master.loc[active_idx, "customer_id"].to_numpy(),
                "snapshot_date": snapshot,
                "product_type": master.loc[active_idx, "product_type"].to_numpy(),
                "industry_sector": master.loc[active_idx, "industry_sector"].to_numpy(),
                "region": master.loc[active_idx, "region"].to_numpy(),
                "rating_grade": [RATING_SCALE[code] for code in rating_codes[active_idx]],
                "exposure_at_default": ead,
                "outstanding_balance": outstanding,
                "currency": "EUR",
                "origination_date": master.loc[active_idx, "origination_date"].to_numpy(),
                "maturity_date": master.loc[active_idx, "maturity_date"].to_numpy(),
                "default_flag": defaults_mask,
                "default_date": default_dates.loc[active_idx].to_numpy(),
            }
        )
        exposure_rows.append(frame)
        previous_snapshot = snapshot

    exposures = pd.concat(exposure_rows, ignore_index=True)
    exposures = exposures.sort_values(["exposure_id", "snapshot_date"]).reset_index(drop=True)
    exposures["default_flag"] = exposures["default_flag"].astype(bool)
    rating_history = exposures[["exposure_id", "bank_id", "snapshot_date", "rating_grade"]].rename(
        columns={"snapshot_date": "observation_date"}
    )
    rating_history = rating_history.drop_duplicates(["exposure_id", "observation_date"]).reset_index(drop=True)
    return exposures, rating_history


def _generate_collateral(
    profile: BankProfile,
    master: pd.DataFrame,
    exposures: pd.DataFrame,
    cutoff: pd.Timestamp,
    rng: np.random.Generator,
) -> pd.DataFrame:
    active_ids = exposures["exposure_id"].unique()
    candidates = master[master["exposure_id"].isin(active_ids)]
    selected = candidates[rng.random(len(candidates)) < profile.collateral_probability]
    collateral_types = ("REAL_ESTATE", "FINANCIAL_COLLATERAL", "OTHER")
    rows: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    first_active = exposures.groupby("exposure_id")["snapshot_date"].min()
    for _, exposure in selected.iterrows():
        exposure_id = str(exposure["exposure_id"])
        sequence = int(exposure_id.split("-")[-1])
        collateral_id = f"COL-{profile.bank_id}-{sequence:05d}"
        if collateral_id in used_ids:
            continue
        used_ids.add(collateral_id)
        collateral_type = str(rng.choice(collateral_types, p=np.array(profile.collateral_weights) / sum(profile.collateral_weights)))
        coverage = float(rng.uniform(0.42, 1.15))
        initial_value = float(exposure["base_ead"]) * coverage
        maturity = pd.Timestamp(exposure["maturity_date"])
        origin = pd.Timestamp(exposure["origination_date"])
        first_obs = pd.Timestamp(first_active.get(exposure_id, origin))
        valuation = max(origin, first_obs - pd.Timedelta(days=int(rng.integers(0, 181))))
        interval_low, interval_high = (330, 430)
        if rng.random() < profile.stale_valuation_probability:
            interval_low, interval_high = (560, 900)
        event = 0
        while valuation <= cutoff and valuation <= maturity + pd.Timedelta(days=180):
            if valuation >= origin:
                drift = 1.0 + float(rng.normal(0.006 * event, 0.045))
                value = max(initial_value * drift, 100.0)
                rows.append(
                    {
                        "collateral_id": collateral_id,
                        "exposure_id": exposure_id,
                        "bank_id": profile.bank_id,
                        "collateral_type": collateral_type,
                        "collateral_value": round(value, 2),
                        "valuation_date": valuation,
                        "currency": "EUR",
                    }
                )
            valuation = valuation + pd.Timedelta(days=int(rng.integers(interval_low, interval_high)))
            event += 1
    return pd.DataFrame(rows)


def _generate_recoveries(
    profile: BankProfile,
    exposures: pd.DataFrame,
    collateral: pd.DataFrame,
    cutoff: pd.Timestamp,
    rng: np.random.Generator,
) -> pd.DataFrame:
    defaults = (
        exposures[exposures["default_flag"] & exposures["default_date"].notna()]
        .sort_values("snapshot_date")
        .drop_duplicates("exposure_id")
        .copy()
    )
    if defaults.empty:
        return pd.DataFrame(
            columns=[
                "cashflow_id",
                "exposure_id",
                "bank_id",
                "payment_date",
                "recovery_amount",
                "recovery_type",
                "adjustment_reason",
            ]
        )
    collateral_by_exposure = collateral.groupby("exposure_id")["collateral_type"].first().to_dict()
    rows: list[dict[str, Any]] = []
    weights = np.array([0.35, 0.25, 0.16, 0.11, 0.08, 0.05])
    sequence = 1
    for _, default in defaults.iterrows():
        exposure_id = str(default["exposure_id"])
        default_date = pd.Timestamp(default["default_date"])
        ead = float(default["exposure_at_default"])
        collateral_type = collateral_by_exposure.get(exposure_id)
        boost = {"REAL_ESTATE": 0.06, "FINANCIAL_COLLATERAL": 0.03, "OTHER": 0.0}.get(collateral_type, -0.03)
        recovery_ratio = np.clip(profile.recovery_base + boost + float(rng.normal(0, 0.06)), 0.10, 0.85)
        target = ead * recovery_ratio
        if collateral_type == "REAL_ESTATE":
            recovery_type = str(rng.choice(["COLLATERAL_LIQUIDATION", "CASH", "GUARANTEE"], p=[0.55, 0.33, 0.12]))
        elif collateral_type == "FINANCIAL_COLLATERAL":
            recovery_type = str(rng.choice(["GUARANTEE", "CASH", "COLLATERAL_LIQUIDATION"], p=[0.40, 0.45, 0.15]))
        elif collateral_type == "OTHER":
            recovery_type = str(rng.choice(["COLLATERAL_LIQUIDATION", "CASH"], p=[0.50, 0.50]))
        else:
            recovery_type = str(rng.choice(["CASH", "GUARANTEE"], p=[0.85, 0.15]))

        payment = default_date + pd.Timedelta(days=int(rng.integers(30, 150)))
        observed_total = 0.0
        for weight in weights:
            if payment > cutoff:
                break
            amount = min(target * weight, ead * 0.85 - observed_total)
            if amount > 0:
                observed_total += amount
                rows.append(
                    {
                        "cashflow_id": f"CF-{profile.bank_id}-{sequence:06d}",
                        "exposure_id": exposure_id,
                        "bank_id": profile.bank_id,
                        "payment_date": payment,
                        "recovery_amount": round(amount, 2),
                        "recovery_type": recovery_type,
                        "adjustment_reason": None,
                    }
                )
                sequence += 1
            payment = payment + pd.Timedelta(days=int(rng.integers(90, 150)))
    return pd.DataFrame(rows)


def _write_institutions() -> None:
    frame = pd.DataFrame(
        [
            {
                "bank_id": inst.bank_id,
                "bank_name": inst.bank_name,
                "region": inst.region,
                "peer_group": inst.peer_group,
            }
            for inst in INSTITUTIONS
        ]
    )
    frame.to_csv(INSTITUTIONS_FILE, index=False, encoding="utf-8")


def generate_all(verbose: bool = True) -> dict[str, Any]:
    snapshot_dates = snapshots()
    cutoff = pd.Timestamp(DEMO_CUTOFF_DATE)
    first_snapshot = snapshot_dates[0]
    LANDING_DIR.mkdir(parents=True, exist_ok=True)
    MASTER_DIR.mkdir(parents=True, exist_ok=True)
    _write_institutions()

    manifests: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    db_frames: dict[str, pd.DataFrame] = {}
    db_mappings: dict[str, Any] = {}
    total_files: list[str] = []

    for bank_number, (bank_id, profile) in enumerate(PROFILES.items()):
        rng = np.random.default_rng(SEED + bank_number * 1009)
        master = _generate_master(profile, rng, first_snapshot, cutoff)
        exposures, rating_history = _simulate_exposures(profile, master, snapshot_dates, rng)
        collateral = _generate_collateral(profile, master, exposures, cutoff, rng)
        recoveries = _generate_recoveries(profile, exposures, collateral, cutoff, rng)

        clean = {
            "exposures": exposures,
            "rating_history": rating_history,
            "collateral": collateral,
            "recovery_cashflows": recoveries,
        }
        for dataset_type, frame in clean.items():
            frame.to_parquet(MASTER_DIR / f"{bank_id}_{dataset_type}_clean.parquet", index=False)

        corrupted, bank_issues = inject_quality_issues(bank_id, exposures, rating_history, collateral, recoveries, rng)
        issues.extend(bank_issues)

        for dataset_type, frame in corrupted.items():
            mapping = mapping_for(bank_id, dataset_type)
            if mapping.source.adapter == "duckdb":
                db_frames[dataset_type] = frame
                db_mappings[dataset_type] = mapping
            else:
                path = write_file(mapping, frame)
                total_files.append(str(path))

        manifests.append(
            {
                "bank_id": bank_id,
                "bank_name": next(inst.bank_name for inst in INSTITUTIONS if inst.bank_id == bank_id),
                "source_system": "FICTIONAL_DEMO_" + bank_id,
                "exposures": int(len(exposures)),
                "rating_history": int(len(rating_history)),
                "collateral": int(len(collateral)),
                "recovery_cashflows": int(len(recoveries)),
                "defaulted_exposures": int(exposures.loc[exposures["default_flag"], "exposure_id"].nunique()),
                "snapshots": len(snapshot_dates),
                "data_quality_defects_injected": len(bank_issues),
            }
        )
        if verbose:
            print(
                f"  {bank_id}: {len(exposures):>6,} exposure snapshots | "
                f"{exposures.loc[exposures['default_flag'], 'exposure_id'].nunique():>3} defaults | "
                f"{len(collateral):>5,} collateral valuations | {len(recoveries):>4,} recovery cashflows"
            )

    db_path = write_database_sources(db_frames, db_mappings)
    if db_path:
        total_files.append(str(db_path))

    manifest = {
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat() + "Z",
        "seed": SEED,
        "snapshot_dates": [date.isoformat() for date in snapshot_dates],
        "institutions": manifests,
        "injected_quality_defects": issues,
        "source_files": sorted(set(total_files)),
        "notes": [
            "All institutions, exposures, collateral and cashflows are synthetic.",
            "Clean canonical simulation files are stored in data/synthetic/master for verification.",
            "Landing-zone files contain controlled defects for data-quality demonstration.",
            "SSK005 supplies prepared tables in an isolated source DuckDB file.",
        ],
    }
    (MASTER_DIR / "generation_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (MASTER_DIR / "README.txt").write_text(
        DISCLAIMER
        + "\n\nThis directory contains generated synthetic demonstration data only.\n"
        + "Do not interpret any value as real banking, customer or regulatory information.\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reproducible synthetic Sparkassen risk data")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()
    print("Generating synthetic multi-institution risk portfolio...")
    manifest = generate_all(verbose=not args.quiet)
    print("\nGeneration complete.")
    print(f"  institutions       : {len(manifest['institutions'])}")
    print(f"  snapshot dates     : {len(manifest['snapshot_dates'])}")
    print(f"  injected DQ defects: {len(manifest['injected_quality_defects'])}")
    print(f"  landing zone       : {LANDING_DIR}")
    print(f"  manifest           : {MASTER_DIR / 'generation_manifest.json'}")
    print(f"\n{DISCLAIMER}")


if __name__ == "__main__":
    main()
