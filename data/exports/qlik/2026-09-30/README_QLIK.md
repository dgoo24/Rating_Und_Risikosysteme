# Qlik-ready export

SYNTHETIC DEMONSTRATION DATA - NOT REGULATORY REPORTING AND NOT REAL SPARKASSEN OR CUSTOMER INFORMATION

This folder contains a flat-file star schema for a local Qlik Sense load. It is not a deployed Qlik application and no external Qlik connection is claimed.

## Files

- `dim_institution.csv`
- `dim_rating.csv`
- `dim_collateral_type.csv`
- `dim_date.csv`
- `dim_metric.csv`
- `fact_exposure_snapshot.csv`
- `fact_rating_history.csv`
- `fact_collateral.csv`
- `fact_recovery_cashflow.csv`
- `fact_rating_distribution.csv`
- `fact_default_rate.csv`
- `fact_loss_recovery.csv`
- `fact_collateral_coverage.csv`
- `fact_recovery_curve.csv`
- `fact_benchmark.csv`
- `fact_quality_batch.csv`
- `fact_quality_finding.csv`
- `assumptions.csv`
- `load_script.qvs`

## Load

1. Open the Qlik load script editor.
2. Replace `vDataPath` in `load_script.qvs` if the CSV files are not in the app's data folder.
3. Run the script and review the synthetic data disclaimer.

## Grain

- `fact_exposure_snapshot`: one exposure per quarter snapshot.
- `fact_rating_history`: one exposure per rating observation.
- `fact_collateral`: one collateral valuation.
- `fact_recovery_cashflow`: one recovery cashflow.
- Other fact tables are pre-aggregated by bank and/or risk dimension.

Benchmarks use numerator/denominator aggregation and exclude the bank from its own peer group.
