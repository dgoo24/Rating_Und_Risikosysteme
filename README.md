# Automated Risk Portfolio Reporting Pipeline

A fully local prototype of an automated risk-reporting pipeline for a
fictional Sparkassen reporting community: synthetic multi-format source data,
a governed ingestion and data-quality layer, a curated DuckDB warehouse, two
independent risk modules (rating & scoring, loss estimation), cross-institution
benchmarking, automated PDF/Excel/CSV/Qlik-ready report generation with a
complete audit trail, and a live Streamlit dashboard.

> **DISCLAIMER — SYNTHETIC DEMONSTRATION DATA.** All institutions
> (SSK001–SSK005, "Muster-Sparkasse …"), customers, exposures, ratings,
> collateral and cashflows are invented. This is not regulatory reporting and
> contains no real Sparkassen, customer or portfolio information. Report
> distribution is simulated; there is no Qlik server — only Qlik-ready file
> exports.

## 1. Scope

- **Module A — Rating & Scoring:** exposure-weighted PD, rating
  distributions, observed 12M default rates, rating migration.
- **Module B — Loss Estimation:** haircut-adjusted collateral coverage,
  secured/unsecured EAD, 12M default cohort, recovery and loss rates,
  recovery cashflow timing.
- **Shared infrastructure:** source catalogue and adapters (CSV/Excel/DuckDB
  in three dialects), a 63-rule data-quality engine with quarantine,
  curated DuckDB storage, peer benchmarking (15 metrics), report generation
  (PDF, Excel, CSV, Qlik CSV star schema), simulated distribution, audit
  logging, and a 7-page Streamlit dashboard.

## 2. Design principles

1. Runs entirely offline — Python, DuckDB, local files; no external or paid
   services, no fabricated integrations.
2. Shared infrastructure first; the two risk modules plug into it
   uniformly.
3. Deterministic seeded data; 162 tests with hand-computed expectations.
4. Errors are quarantined, never silently repaired or dropped; curated data
   is never overwritten (idempotent ingestion).

## 3. Prerequisites

- Python 3.12 (3.10+ should work), Windows/macOS/Linux
- ~200 MB free disk space

```powershell
python -m pip install -r requirements.txt
```

(pandas, numpy, duckdb, openpyxl, XlsxWriter, streamlit, plotly, reportlab,
matplotlib, pytest)

## 4. Quick start (the full pipeline)

```powershell
# 1. Generate the synthetic landing zone (5 banks x 4 datasets x 9 quarters)
python -m synthetic_data.generate_data

# 2. Ingest, validate and load into the curated DuckDB
python -m etl.pipeline --reset-db

# 3. Generate all report artefacts (PDF, Excel, CSV, Qlik CSVs)
python -m reporting.cli

# 4. Start the live dashboard
streamlit run app.py
```

Then open <http://localhost:8501>. Re-running steps 1–3 is safe:
`--reset-db` rebuilds the warehouse; without it, identical files are
skipped.

## 5. Artefact locations

| Artefact | Path |
|---|---|
| Synthetic landing zone | `data/synthetic/landing/` |
| Generation manifest | `data/synthetic/master/generation_manifest.json` |
| Curated DuckDB | `data/processed/risk_portfolio.duckdb` |
| Community/institution PDFs | `reports/<date>/community/`, `reports/<date>/institutions/` |
| Generation summary | `reports/<date>/generation_summary.json` |
| Excel workbooks (14 sheets) | `data/exports/<date>/excel/` |
| CSV bundle (zip) | `data/exports/<date>/csv/` |
| Qlik star schema + load script | `data/exports/qlik/<date>/` |
| Pipeline logs | `logs/` |

`<date>` is the reporting date, e.g. `2026-09-30`.

## 6. CLI reference

```powershell
python -m synthetic_data.generate_data                       # regenerate sources
python -m etl.pipeline [--reset-db] [--bank SSK001] [--dataset exposures]
python -m reporting.cli [--reporting-date 2026-09-30] [--bank SSK001] [--sector RETAIL]
                        [--formats pdf excel csv qlik]
                        [--no-community|--no-institutions|--no-distribution]
streamlit run app.py                                        # dashboard
python -m pytest tests/ -q                                  # 163 tests
```

## 7. Dashboard (Streamlit — the live view)

`app.py` navigates seven pages through a top navigation bar (no sidebar), all
reading the same curated DuckDB through cached access
(`dashboard/common.py`). The dashboard UI is German, including German number
formatting (comma decimal separator, dot thousands separator) and German
date formatting (`TT.MM.JJJJ`); scope filters live in the main dashboard
area:

1. **Überblick** — community KPIs and snapshot navigation
2. **Rating & Scoring** — Module A views (PD, distribution, defaults, migration)
3. **Verlustschätzung** — Module B views (collateral, recovery, loss, cashflows)
4. **Benchmarking** — peer comparison incl. interactive what-if overrides
5. **Datenqualität** — scores, findings, quarantine browser
6. **Datenübernahme** — batch history and load outcomes
7. **Reporting** — artefact registry and regeneration from the UI

Streamlit is the prototype's live local dashboard; it is **not** the
enterprise BI tool. Qlik Sense is the export target (see §10).

## 8. Data model in brief

Curated tables (business keys in bold): **exposures** (`exposure_id`,
`snapshot_date`), **rating_history** (`exposure_id`, `observation_date`),
**collateral** (`collateral_id`, `valuation_date`), **recovery_cashflows**
(`cashflow_id`) — plus staging mirrors, `institutions` master, the rule
catalogue, quality results, quarantine records and audit logs. Full column
documentation: `docs/data_dictionary.md`.

## 9. Data quality engine

63 rules in four categories (completeness, consistency, plausibility,
uniqueness) across the four datasets; 54 ERROR / 9 WARNING. ERROR findings
quarantine the record (full JSON payload retained); WARNING findings flag
and load. Batch outcomes: ACCEPTED / ACCEPTED_WITH_WARNINGS / QUARANTINED.
Full catalogue: `docs/data_quality_rules.md`.

## 10. Qlik integration (export target, not a live connection)

`python -m reporting.cli --formats qlik` writes 18 CSV tables in a star
schema (dimensions: institution, rating, collateral type, date, metric) plus
a sample `load_script.qvs` into `data/exports/qlik/<date>/`. A Qlik developer
loads these files locally. **No Qlik server, connector or deployed
application is claimed** — the CSV hand-off is the honest boundary for a
local prototype. Details: `docs/qlik_integration.md`.

## 11. Metric definitions

All KPIs and the 15 benchmark metrics with formulas, directions and
aggregation semantics (numerator/denominator aggregates, never means of
ratios; peers exclude the bank itself; ±10% relative-gap thresholds):
`docs/metric_definitions.md`.

## 12. Configuration

All assumptions live in `config/` — one place to change anything:
`settings.py` (paths via environment variables `RISK_DB_PATH`,
`RISK_REPORT_DIR`, `RISK_EXPORT_DIR`, `RISK_SYNTHETIC_DIR`; rating scale,
thresholds, disclaimer), `institutions.py` / `peer_groups.py` (banks and peer
groups), `rating_pd_mapping.py` (grade → 12M PD), `collateral_haircuts.py`
(type → haircut), `source_catalog.py` (landing-zone inventory and formats).

## 13. Testing

```powershell
python -m pytest tests/ -q          # 162 passed in ~1 minute
```

- `test_transformations.py` — number/flag parsing, mappings, record IDs
- `test_ingestion.py` — adapters (CSV dialects, Excel, DuckDB), manager,
  idempotency
- `test_data_quality.py` — every rule, load outcomes, quarantine
- `test_rating_scoring.py` / `test_loss_estimation.py` — module math against
  hand-computed fixture values
- `test_benchmarking.py` — peer aggregation, flags, ranks, overrides
- `test_reporting.py` — context, exports, end-to-end generation against a
  temporary database, audit log, CLI
- `test_dashboard.py` — Streamlit `AppTest` render checks for all pages

Expected values are derived by hand in the test docstrings — the tests never
re-implement module logic.

## 14. Documentation and demo

| Document | Content |
|---|---|
| `docs/architecture.md` | layers, data flow, design decisions |
| `docs/data_dictionary.md` | landing zone, curated schema, audit tables, reference values |
| `docs/metric_definitions.md` | Module A/B KPIs and benchmark metric formulas |
| `docs/data_quality_rules.md` | the 63-rule catalogue and severity semantics |
| `docs/qlik_integration.md` | star schema, load script, integration boundary |
| `docs/deployment.md` | hosting the dashboard for free on Streamlit Community Cloud |
| `docs/interview_demo.md` | 10-step, 5–10 minute guided demo |

`docs/interview_demo.md` is the scripted walkthrough for a live
presentation — use it to demo the pipeline end to end.
