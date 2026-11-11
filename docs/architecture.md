# Architecture

Automated Risk Portfolio Reporting Pipeline — local prototype for a fictional
Sparkassen reporting community. Everything runs offline on this machine:
synthetic data, file-based ingestion, DuckDB storage, analytical modules,
report generation and a Streamlit dashboard. **No real bank, customer or
regulatory data is processed** (see the disclaimer in every artefact).

## Design principles

1. **Reproducible without external services.** Python + DuckDB + local files.
   No mail server, no Qlik server, no cloud. Anything that would require a
   paid or corporate service in production is either simulated
   (report distribution) or exported as a hand-off artefact (Qlik CSV bundle).
2. **Shared infrastructure first, risk modules second.** Everything that is
   not rating/loss logic (ingestion, quality, storage, reporting, dashboard)
   lives in shared packages and serves both modules identically.
3. **Deterministic and testable.** Synthetic data is seeded; all 162 tests
   assert hand-computed expected values, not re-implementations of module
   logic.
4. **Fail loudly, never silently overwrite.** Records that violate ERROR-severity
   quality rules are quarantined, not dropped or repaired. Curated snapshots
   are never overwritten (idempotent re-runs).

## Package layout

```
Rating_Und_Risikosysteme/
├── app.py                     # Streamlit entry point (st.navigation over 7 pages)
├── config/                    # Single source of truth for ALL assumptions
│   ├── settings.py            #   paths, rating scale, thresholds, disclaimer
│   ├── institutions.py        #   5 fictional banks + regions + peer groups
│   ├── peer_groups.py         #   PG_URBAN / PG_REGIONAL membership
│   ├── rating_pd_mapping.py   #   grade -> 12M PD
│   ├── collateral_haircuts.py #   collateral type -> haircut
│   ├── source_catalog.py      #   landing-zone file inventory (format per bank)
│   └── models.py              #   dataclasses for batch/finding records
├── synthetic_data/            # Seeded generator for the fictional portfolio
│   ├── generate_data.py       #   CLI: python -m synthetic_data.generate_data
│   ├── profiles.py            #   per-bank portfolio profiles
│   ├── exporters.py           #   CSV / Excel / DuckDB writers, German formats
│   └── quality_injection.py   #   deliberate defects to exercise the DQ engine
├── ingestion/                 # Landing zone -> staging (shared infrastructure)
│   ├── adapters.py           #   adapter_for() factory
│   ├── csv_adapter.py         #   comma + semicolon dialects, de/en numbers
│   ├── excel_adapter.py       #   configured sheet per workbook
│   ├── database_adapter.py    #   source DuckDB tables
│   ├── source_mapping.py      #   source column names -> canonical names
│   └── ingestion_manager.py   #   batch IDs, file hashing, raw archive, staging
├── etl/                       # Orchestration
│   ├── transformations.py    #   standardise_frame, parse_number/flag, record IDs
│   ├── pipeline.py            #   CLI: python -m etl.pipeline [--reset-db]
│   └── pipeline_logger.py     #   run-level logging into pipeline_runs
├── quality/                   # Data quality engine (shared infrastructure)
│   ├── rules.py               #   63-rule catalogue (single source of truth)
│   ├── completeness_checks.py ├── consistency_checks.py
│   ├── plausibility_checks.py ├── uniqueness_checks.py
│   ├── context.py             #   ValidationContext (plain dataclass, no I/O)
│   ├── findings.py            #   finding row construction
│   ├── validation_engine.py   #   evaluate_findings -> load outcome
│   └── quality_report.py      #   scores, by-rule/by-bank/by-category rollups
├── database/                  # DuckDB access layer
│   ├── schema.sql             #   staging + curated + audit tables
│   └── connection.py          #   connect/insert_dataframe/query_df, utc_now
├── modules/                   # THE two risk modules (Module A / Module B)
│   ├── rating_scoring/        #   Module A: PD, rating distribution, defaults,
│   │                          #   migration (pd_calculations, rating_distribution,
│   │                          #   default_rates, rating_migration, calculations,
│   │                          #   reporting -> RatingModuleResult)
│   └── loss_estimation/       #   Module B: collateral haircuts, secured EAD,
│                              #   default cohort, recovery/loss rates, cashflows
│                              #   (collateral_analysis, recovery_rates, loss_rates,
│                              #   recovery_cashflows, calculations,
│                              #   reporting -> LossModuleResult)
├── benchmarking/              # Peer comparison across both modules
│   ├── aggregation.py         #   15-metric catalogue, peer math, flags, ranks
│   └── benchmark_engine.py    #   build_benchmark_result / historical / selectors
├── reporting/                 # Artefact generation + audit
│   ├── data_access.py         #   read curated data for a reporting date
│   ├── context.py             #   ReportContext (rating+loss+benchmark+quality)
│   ├── charts.py              #   matplotlib (Agg) PNG charts
│   ├── pdf_report.py          #   ReportLab PDF (community + per-institution)
│   ├── excel_export.py        #   14-sheet openpyxl workbook
│   ├── csv_export.py          #   flat CSVs + zipped bundle
│   ├── qlik_export.py         #   Qlik-ready star schema + load script
│   ├── distribution.py        #   SIMULATED distribution (file manifest, no mail)
│   ├── report_service.py      #   generate_reports() orchestration
│   ├── audit.py               #   report_log / distribution_log audit tables
│   └── cli.py                 #   CLI: python -m reporting.cli
├── dashboard/                 # Streamlit UI (7 pages)
│   ├── common.py              #   cached curated data access + page bootstrap
│   ├── pages/_shell.py        #   shared page frame (filters, disclaimer)
│   └── pages/*.py             #   overview, rating, loss, benchmarking, data
│                              #   quality, ingestion, reporting pages
├── qlik/load_script.qvs       # Repository template of the Qlik load script
├── tests/                     # 162 pytest tests (hand-computed expectations)
├── data/synthetic/landing/    # generated source files (input of the pipeline)
├── data/processed/risk_portfolio.duckdb   # curated database
├── reports/<date>/…           # generated PDFs, summaries
├── data/exports/<date>/…      # Excel, CSV bundles, Qlik CSVs
└── logs/                      # pipeline run logs
```

## Data flow

```
synthetic_data.generate_data          (seeded; 5 banks x 4 datasets x 9 quarters)
        |
        v
data/synthetic/landing/               CSV (3 dialects) | Excel | source DuckDB
        |
        v
ingestion.ingestion_manager          adapter_for() -> raw archive + staging
        |                             (file hash, batch IDs, column mapping)
        v
etl.transformations                   standardise: dates, numbers (de/en),
        |                             flags, canonical column names
        v
quality.validation_engine             63 rules -> findings; ERROR rows quarantined
        |                             (never repaired, never dropped silently)
        v
database (DuckDB)                    curated tables: exposures, rating_history,
        |                             collateral, recovery_cashflows
        |                             audit tables: ingestion_batches,
        |                             quality_results, quarantine_records,
        |                             pipeline_runs, report_log, distribution_log
        v
modules.rating_scoring | modules.loss_estimation        (Module A | Module B)
        |                             RatingModuleResult | LossModuleResult
        v
benchmarking.benchmark_engine         peer-group comparison (15 metrics)
        v
reporting.report_service.generate_reports
        |--> reports/<date>/…                PDF + generation_summary.json
        |--> data/exports/<date>/excel/…     XLSX (14 sheets)
        |--> data/exports/<date>/csv/…       CSV bundle (zip)
        |--> data/exports/qlik/<date>/…     Qlik-ready star schema + load script
        |--> report_log / distribution_log   full audit trail
        v
dashboard (Streamlit, app.py)         live local views over the same curated DB
```

## Module boundaries

**Shared infrastructure** (`ingestion`, `quality`, `database`, `etl`,
`benchmarking`, `reporting`, `dashboard`, `config`) knows nothing about PD
formulas or loss mechanics; it moves, validates, stores and presents rows.

**Module A — Rating & Scoring** (`modules/rating_scoring`) computes
exposure-weighted PD, rating distributions, observed 12M default rates and
12M rating migration from curated exposures + rating history.

**Module B — Loss Estimation** (`modules/loss_estimation`) computes
haircut-adjusted collateral coverage, secured/unsecured EAD, the 12M default
cohort, recovery rates, loss rates and recovery cashflow timing.

Both modules expose the same shape: a `*ModuleResult` dataclass with KPIs and
typed view frames, built by `build_*_result(exposures, …, reporting_date,
bank_ids, sectors)` — so the reporting layer, benchmarking engine and
dashboard consume them uniformly. The benchmarking engine derives its
numerator/denominator pairs from both modules' results.

## Key design decisions

- **Quality gate semantics:** ERROR findings quarantine the offending record;
  WARNING findings keep the record and flag it. A batch outcome is ACCEPTED /
  ACCEPTED_WITH_WARNINGS / QUARANTINED; quarantined batches load nothing.
- **Idempotency:** identical files (same hash) are skipped; curated primary
  keys (exposure_id+snapshot_date, …) prevent double-loading. `--reset-db`
  rebuilds from scratch for demos.
- **Benchmarking math:** peer values are aggregates of numerators and
  denominators (exposure-weighted), never averages of ratios. The bank under
  review is excluded from its own peer reference. A ±10% relative gap is
  BETTER/WORSE, otherwise IN_LINE; metrics without a `higher_is_better`
  direction are INFORMATION-only.
- **Reporting date:** all analytics select the latest curated quarter-end
  snapshot (`DEMO_CUTOFF_DATE = 2026-09-30`); 12M observation windows start
  twelve months earlier.
- **Qlik vs. Streamlit:** the Streamlit app is the *live local* dashboard;
  Qlik Sense is an *export target only* — the pipeline writes Qlik-ready CSVs
  and a sample load script but does not claim a deployed or connected Qlik
  application (see `docs/qlik_integration.md`).

## Verification

- `python -m pytest tests/` — 162 tests, all expected values hand-computed.
- Dashboard smoke tests use Streamlit `AppTest` for all seven pages.
- End-to-end integration test seeds a temporary DuckDB and asserts the full
  artefact inventory plus `report_log` audit rows.
