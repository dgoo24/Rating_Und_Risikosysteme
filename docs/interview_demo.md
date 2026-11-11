# Interview demo guide (5–10 minutes)

A scripted walkthrough of the prototype. Every step runs locally; nothing
external is contacted. Prepare once with `pip install -r requirements.txt`.

**Pre-demo setup (not part of the 10 steps):** run steps 1 and 2 once before
the interview so the dashboard starts instantly; keep two terminal windows
and a file explorer open.

## The 10 steps

### 1. Synthetic sources (~30 s)

```powershell
python -m synthetic_data.generate_data
```

Point at `data/synthetic/landing/`: five fictional Sparkassen
(SSK001–SSK005) export exposures, rating history, collateral and recovery
cashflows for nine quarterly snapshots (2024-09-30 → 2026-09-30) —
deliberately as CSV (three dialects), Excel and a source DuckDB, with German
column names and number formats. Mention the injected quality defects and
`data/synthetic/master/generation_manifest.json`. **Everything is
synthetic — no real bank or customer data.**

### 2. Ingestion + quality gate + curated DB (~1 min)

```powershell
python -m etl.pipeline --reset-db
```

Show the console: each source is hashed, archived, mapped to canonical
columns, staged and validated against the 63-rule catalogue. ERROR rows are
quarantined — not repaired, not dropped — and the batch outcome
(ACCEPTED / ACCEPTED_WITH_WARNINGS / QUARANTINED) decides what reaches the
curated DuckDB at `data/processed/risk_portfolio.duckdb`. Re-run without
`--reset-db` to show idempotency: identical files are skipped, curated keys
prevent double-loading.

### 3. The quality rules (~45 s)

Open `docs/data_quality_rules.md` or the *Datenqualität* dashboard page (see
step 7): completeness / consistency / plausibility / uniqueness across the
four datasets; severity semantics table (ERROR = quarantine, WARNING = flag).
One concrete example: the generator injects an exposure with an invalid
rating grade → CONS-EXP-002 quarantines it; find it in `quarantine_records`
with its full JSON payload.

### 4. Module A — Rating & Scoring (~1 min)

Open the *Rating & Scoring* dashboard page. Walk through: exposure-weighted
PD by grade (fictional PD map A 0.1% … F 12%), rating distribution, observed
12M default rate (count and EAD) versus model PD, and the 12M migration
matrix with upgrade/downgrade rates. Emphasise the module boundary: pure
rating analytics, no loss numbers.

### 5. Module B — Loss Estimation (~1 min)

Open the *Verlustschätzung* page: haircut-adjusted collateral coverage
(REAL_ESTATE 20%, FINANCIAL 5%, OTHER 40%), capped secured EAD, stale
valuations (>3 years), the 12M default cohort, realised recovery rate
(EAD-weighted), loss rate and recovery cashflow timing. One sentence on
avoiding collateral double-counting (secured EAD caps at exposure EAD).

### 6. Benchmarking (~1 min)

Open the *Benchmarking* page: each bank against its configured peer group
(PG_URBAN = SSK001/SSK003/SSK005, PG_REGIONAL = SSK002/SSK004) across the 15
shared metrics — always as numerator/denominator aggregates
(exposure-weighted), never the mean of ratios; the bank is excluded from its
own peer reference; BETTER/WORSE at ±10% relative gap, IN_LINE inside.
Show the what-if: override a peer group or peer IDs and watch the flags
recompute (NO_BENCHMARK when no peers have data).

### 7. Dashboard architecture (~30 s)

One sentence: `app.py` uses `st.navigation` over seven pages
(overview, rating, loss, benchmarking, data quality, ingestion, reporting)
backed by `dashboard/common.py` cached access to the same curated DuckDB —
the dashboard is the live view, not a separate data copy.

### 8. Report generation (~1 min)

```powershell
python -m reporting.cli
```

Show the console summary and then the artefacts:
`reports/2026-09-30/community/risk_report_community_2026-09-30.pdf`
(cover, KPIs, module sections, benchmarking, data quality, methodology,
synthetic-data disclaimer), the 14-sheet Excel workbook under
`data/exports/2026-09-30/excel/`, the CSV bundle (zip) and
`reports/2026-09-30/generation_summary.json`. Mention the audit trail:
`report_log` has one GENERATED row per artefact with data version and
contributing batch IDs; distribution is simulated into `distribution_log`
(no emails are sent — stated honestly).

### 9. Qlik hand-off (~45 s)

Open `data/exports/qlik/2026-09-30/`: 18 CSV tables in a star schema
(dimensions: institution, rating, collateral type, date, metric) plus
`load_script.qvs` and `README_QLIK.md`. Explain the boundary: **the pipeline
exports Qlik-ready files and a sample load script; it does not claim a Qlik
server or live connection.** Streamlit is the live dashboard; Qlik Sense is
the enterprise BI target this export is shaped for.

### 10. Tests (~45 s)

```powershell
python -m pytest tests/ -q
```

163 tests pass in about a minute. Every expected value is hand-computed
(documented in the test docstrings) — weighted PD 13.9/1900, recovery rate
85/200 = 0.425, peer aggregate 130/500 = 0.26, … — not re-implementations of
module logic. The suite covers transformations, ingestion adapters, all 63
quality rules, both modules, benchmarking, reporting (including an
end-to-end run against a temporary DuckDB) and all seven dashboard pages via
Streamlit `AppTest`.

## Backup answers

- **"Why DuckDB?"** Local, zero-configuration, columnar, SQL-typed; the
  schema in `database/schema.sql` is written portably so a PostgreSQL
  deployment would only replace the thin access layer.
- **"Where are real emails / a real Qlik server?"** Out of scope by design —
  no paid service or customer data is used; distribution is a simulated,
  audited manifest and the Qlik export is a documented CSV hand-off.
- **"How do I trust the numbers?"** Config-driven assumptions (PD map,
  haircuts, peer groups) in one `config/` package, an `assumptions` table in
  every export, and 162 hand-computed tests.
- **"What breaks first in production?"** The landing-zone contract: the
  source catalogue and column mappings would move to metadata tables; the
  quality catalogue already is data, so new rules are rows, not code changes.

## Timing budget

Steps 1–3 ≈ 3 min, 4–6 ≈ 3 min, 7–10 ≈ 3 min. If time is short, skip step 1
(pre-generated) and shorten step 3 — steps 4, 5, 6 and 10 carry the story.
