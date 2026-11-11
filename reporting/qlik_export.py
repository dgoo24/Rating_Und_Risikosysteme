"""Qlik-ready CSV star schema and sample load script.

The export is a set of flat CSV files. It deliberately does not claim a live Qlik
connection or a deployed Qlik application. The sample script is a starting point
for a local Qlik Sense load.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.collateral_haircuts import COLLATERAL_HAIRCUTS
from config.rating_pd_mapping import RATING_PD_MAPPING, RATING_SCALE
from config.settings import DISCLAIMER
from modules.rating_scoring.rating_distribution import rating_distribution_by_bank
from reporting.context import ReportContext

QLIK_FILES = (
    "dim_institution",
    "dim_rating",
    "dim_collateral_type",
    "dim_date",
    "dim_metric",
    "fact_exposure_snapshot",
    "fact_rating_history",
    "fact_collateral",
    "fact_recovery_cashflow",
    "fact_rating_distribution",
    "fact_default_rate",
    "fact_loss_recovery",
    "fact_collateral_coverage",
    "fact_recovery_curve",
    "fact_benchmark",
    "fact_quality_batch",
    "fact_quality_finding",
    "assumptions",
)


def _write(frame: pd.DataFrame, directory: Path, name: str) -> Path | None:
    if frame is None or frame.empty:
        return None
    path = directory / f"{name}.csv"
    frame.to_csv(path, index=False, encoding="utf-8")
    return path


def _dim_date(*frames: pd.DataFrame) -> pd.DataFrame:
    values: set[pd.Timestamp] = set()
    for frame, columns in frames:
        if frame.empty:
            continue
        for column in columns:
            if column in frame.columns:
                dates = pd.to_datetime(frame[column], errors="coerce").dropna().dt.normalize()
                values.update(pd.Timestamp(value) for value in dates.unique())
    if not values:
        return pd.DataFrame(columns=["date_key", "year", "quarter", "year_quarter", "month", "month_name"])
    date_index = pd.date_range(min(values), max(values), freq="D")
    return pd.DataFrame(
        {
            "date_key": date_index.strftime("%Y-%m-%d"),
            "year": date_index.year,
            "quarter": date_index.quarter,
            "year_quarter": [f"{year}-Q{quarter}" for year, quarter in zip(date_index.year, date_index.quarter)],
            "month": date_index.month,
            "month_name": date_index.strftime("%b"),
        }
    )


def _exposure_fact(exposures: pd.DataFrame) -> pd.DataFrame:
    if exposures.empty:
        return exposures.copy()
    frame = exposures.copy()
    for column in ("snapshot_date", "origination_date", "maturity_date", "default_date"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.strftime("%Y-%m-%d")
    if "snapshot_date" in frame.columns:
        dates = pd.to_datetime(frame["snapshot_date"], errors="coerce")
        frame["year_quarter"] = [f"{value.year}-Q{value.quarter}" if pd.notna(value) else None for value in dates]
    frame["default_flag"] = frame["default_flag"].fillna(False).astype(int)
    return frame


def _add_dimension(frame: pd.DataFrame, dimension_type: str, value_column: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    result.insert(0, "dimension_type", dimension_type)
    result.insert(1, "dimension_value", result[value_column].astype(str))
    return result


def build_qlik_tables(context: ReportContext, data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    exposures = data.get("exposures", pd.DataFrame())
    rating_history = data.get("rating_history", pd.DataFrame())
    collateral = data.get("collateral", pd.DataFrame())
    cashflows = data.get("recovery_cashflows", pd.DataFrame())

    institutions = context.institutions.copy() if not context.institutions.empty else data.get("institutions", pd.DataFrame())
    dim_institution = institutions[["bank_id", "bank_name", "region", "peer_group"]].copy() if not institutions.empty else institutions
    dim_rating = pd.DataFrame(
        [
            {
                "rating_grade": grade,
                "rating_rank": index,
                "pd_rate": RATING_PD_MAPPING[grade],
                "rating_band": "INVESTMENT_GRADE" if grade in ("A", "B") else "SUB_INVESTMENT_GRADE",
            }
            for index, grade in enumerate(RATING_SCALE, start=1)
        ]
    )
    dim_collateral_type = pd.DataFrame(
        [{"collateral_type": collateral_type, "haircut": haircut} for collateral_type, haircut in COLLATERAL_HAIRCUTS.items()]
    )
    dim_date = _dim_date(
        (exposures, ("snapshot_date", "default_date")),
        (rating_history, ("observation_date",)),
        (collateral, ("valuation_date",)),
        (cashflows, ("payment_date",)),
    )
    from benchmarking.aggregation import metric_catalog_frame

    dim_metric = metric_catalog_frame()

    fact_exposure = _exposure_fact(exposures)
    fact_rating = rating_history.copy()
    if "observation_date" in fact_rating.columns:
        fact_rating["observation_date"] = pd.to_datetime(fact_rating["observation_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    fact_collateral = collateral.copy()
    if "valuation_date" in fact_collateral.columns:
        fact_collateral["valuation_date"] = pd.to_datetime(fact_collateral["valuation_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    fact_cashflow = cashflows.copy()
    if "payment_date" in fact_cashflow.columns:
        fact_cashflow["payment_date"] = pd.to_datetime(fact_cashflow["payment_date"], errors="coerce").dt.strftime("%Y-%m-%d")

    distribution = rating_distribution_by_bank(exposures)
    if not distribution.empty:
        distribution = distribution[pd.to_datetime(distribution["snapshot_date"], errors="coerce").dt.normalize() == context.reporting_date]
        distribution["snapshot_date"] = pd.to_datetime(distribution["snapshot_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        community = context.rating.distribution.copy()
        community["bank_id"] = "ALL"
        community["snapshot_date"] = context.reporting_date.strftime("%Y-%m-%d")
        distribution = pd.concat([distribution, community], ignore_index=True)

    default_parts = [
        _add_dimension(context.rating.default_by_bank, "BANK", "bank_id"),
        _add_dimension(context.rating.default_by_rating, "RATING", "rating_grade"),
        _add_dimension(context.rating.default_by_sector, "SECTOR", "industry_sector"),
    ]
    fact_default = pd.concat([part for part in default_parts if not part.empty], ignore_index=True) if any(not part.empty for part in default_parts) else pd.DataFrame()

    loss_parts = [
        _add_dimension(context.loss.by_bank, "BANK", "bank_id"),
        _add_dimension(context.loss.by_rating, "RATING", "rating_at_default"),
        _add_dimension(context.loss.by_product, "PRODUCT", "product_type"),
        _add_dimension(context.loss.by_collateral_type, "COLLATERAL", "primary_collateral_type"),
    ]
    fact_loss = pd.concat([part for part in loss_parts if not part.empty], ignore_index=True) if any(not part.empty for part in loss_parts) else pd.DataFrame()

    fact_collateral_coverage = context.loss.collateral_by_bank.copy()
    fact_curve = context.loss.recovery_curve.copy()
    fact_benchmark = context.benchmark_detail.copy()
    fact_batch = context.batches.copy()
    if not fact_batch.empty:
        for column in ("reporting_date", "import_timestamp"):
            if column in fact_batch.columns:
                fact_batch[column] = pd.to_datetime(fact_batch[column], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    fact_findings = context.quality.findings.copy()
    if not fact_findings.empty:
        for column in ("reporting_date", "execution_timestamp"):
            if column in fact_findings.columns:
                fact_findings[column] = pd.to_datetime(fact_findings[column], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
        keep = [
            "quality_result_id", "batch_id", "dataset_type", "bank_id", "reporting_date", "record_id",
            "rule_id", "rule_name", "category", "severity", "field_name", "failed_value", "reason",
            "execution_timestamp",
        ]
        fact_findings = fact_findings[[column for column in keep if column in fact_findings.columns]]

    assumptions = pd.DataFrame(
        [
            *[
                {"area": "PD mapping", "key": grade, "value": value, "note": "Fictional demonstration PD 12M."}
                for grade, value in RATING_PD_MAPPING.items()
            ],
            *[
                {"area": "Collateral haircut", "key": collateral_type, "value": value, "note": "Demonstration haircut."}
                for collateral_type, value in COLLATERAL_HAIRCUTS.items()
            ],
            {"area": "Reporting", "key": "disclaimer", "value": DISCLAIMER, "note": "Synthetic demonstration data."},
            {"area": "Reporting", "key": "reporting_date", "value": context.reporting_date.date().isoformat(), "note": "Selected reporting date."},
        ]
    )

    return {
        "dim_institution": dim_institution,
        "dim_rating": dim_rating,
        "dim_collateral_type": dim_collateral_type,
        "dim_date": dim_date,
        "dim_metric": dim_metric,
        "fact_exposure_snapshot": fact_exposure,
        "fact_rating_history": fact_rating,
        "fact_collateral": fact_collateral,
        "fact_recovery_cashflow": fact_cashflow,
        "fact_rating_distribution": distribution,
        "fact_default_rate": fact_default,
        "fact_loss_recovery": fact_loss,
        "fact_collateral_coverage": fact_collateral_coverage,
        "fact_recovery_curve": fact_curve,
        "fact_benchmark": fact_benchmark,
        "fact_quality_batch": fact_batch,
        "fact_quality_finding": fact_findings,
        "assumptions": assumptions,
    }


def load_script_text(data_path: str = ".") -> str:
    files = "\n".join(
        f"{name}:\nLOAD * FROM [$(vDataPath)/{name}.csv] (txt, utf8, embedded labels, delimiter is ',', msq);\n"
        for name in QLIK_FILES
    )
    return f"""// Automated Risk Portfolio Reporting Pipeline
// Sample Qlik Sense load script. Generated for the synthetic demonstration only.
// Adjust vDataPath to the folder containing the exported CSV files.

SET ThousandSep=',';
SET DecimalSep='.';
SET MoneyThousandSep=',';
SET MoneyDecimalSep='.';
SET DateFormat='YYYY-MM-DD';
SET TimestampFormat='YYYY-MM-DD hh:mm:ss';
SET vDataPath='{data_path}';

// ---------------------------------------------------------------------------
// Dimensions
// ---------------------------------------------------------------------------
{files}
// ---------------------------------------------------------------------------
// Suggested associations:
//   fact_exposure_snapshot.bank_id -> dim_institution.bank_id
//   fact_exposure_snapshot.rating_grade -> dim_rating.rating_grade
//   fact_collateral.collateral_type -> dim_collateral_type.collateral_type
//   fact_benchmark.metric_id -> dim_metric.metric_id
// The date fields are ISO strings. Add a master calendar in Qlik if needed.
// ---------------------------------------------------------------------------
TRACE Synthetic demonstration data only - not regulatory reporting.
"""


def export_qlik_bundle(
    context: ReportContext,
    data: dict[str, pd.DataFrame],
    output_dir: Path,
    template_path: Path | None = None,
) -> tuple[list[Path], Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tables = build_qlik_tables(context, data)
    written: list[Path] = []
    for name, frame in tables.items():
        path = _write(frame, output_dir, name)
        if path is not None:
            written.append(path)
    script = output_dir / "load_script.qvs"
    script.write_text(load_script_text("."), encoding="utf-8")
    written.append(script)
    readme = output_dir / "README_QLIK.md"
    readme.write_text(
        "# Qlik-ready export\n\n"
        f"{DISCLAIMER}\n\n"
        "This folder contains a flat-file star schema for a local Qlik Sense load. "
        "It is not a deployed Qlik application and no external Qlik connection is claimed.\n\n"
        "## Files\n\n"
        + "\n".join(f"- `{name}.csv`" for name in QLIK_FILES)
        + "\n- `load_script.qvs`\n\n## Load\n\n"
        "1. Open the Qlik load script editor.\n"
        "2. Replace `vDataPath` in `load_script.qvs` if the CSV files are not in the app's data folder.\n"
        "3. Run the script and review the synthetic data disclaimer.\n\n"
        "## Grain\n\n"
        "- `fact_exposure_snapshot`: one exposure per quarter snapshot.\n"
        "- `fact_rating_history`: one exposure per rating observation.\n"
        "- `fact_collateral`: one collateral valuation.\n"
        "- `fact_recovery_cashflow`: one recovery cashflow.\n"
        "- Other fact tables are pre-aggregated by bank and/or risk dimension.\n\n"
        "Benchmarks use numerator/denominator aggregation and exclude the bank from its own peer group.\n",
        encoding="utf-8",
    )
    written.append(readme)
    if template_path is not None and template_path.exists():
        # The repository template is maintained separately; the run-specific script uses '.'.
        pass
    return written, script
