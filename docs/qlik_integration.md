# Qlik integration

## What this pipeline does — and does not — claim

**Does:** export a Qlik-ready star schema as flat CSV files plus a sample
Qlik Sense load script (`load_script.qvs`) that a Qlik developer can paste
into a new app and load locally.

**Does not:** connect to a Qlik server, deploy a Qlik application, schedule
Qlik reloads, or claim any live Qlik integration. There is no Qlik licence,
server or client in this prototype. The dashboard in this repository is a
Streamlit application — Qlik Sense is an *export target*, not the tool the
prototype runs on.

## Export location and invocation

```
python -m reporting.cli                          # all formats, incl. Qlik
python -m reporting.cli --formats qlik           # Qlik bundle only
```

Files land in `data/exports/qlik/<reporting-date>/`:

- 18 CSV tables (see below) — only non-empty tables are written
- `load_script.qvs` — the sample load script (also maintained as a template
  at `qlik/load_script.qvs` in the repository root)
- `README_QLIK.md` — load instructions and the synthetic-data disclaimer

## Star schema

**Dimensions**

| Table | Grain | Content |
|---|---|---|
| `dim_institution` | bank | bank_id, bank_name, region, peer_group (5 fictional banks) |
| `dim_rating` | grade | rating_grade, rating_rank, pd_rate, investment/sub-investment band |
| `dim_collateral_type` | type | collateral_type, haircut |
| `dim_date` | day | date_key, year, quarter, year_quarter, month, month_name — generated daily across all observed dates |
| `dim_metric` | metric | the 15 benchmark metric definitions |

**Facts**

| Table | Grain | Content |
|---|---|---|
| `fact_exposure_snapshot` | exposure x quarter | full curated exposures; `default_flag` as 0/1; `year_quarter` column |
| `fact_rating_history` | exposure x observation date | curated rating observations |
| `fact_collateral` | collateral x valuation date | curated collateral valuations |
| `fact_recovery_cashflow` | cashflow | curated recovery payments |
| `fact_rating_distribution` | bank x grade (plus `ALL` community rows) | exposure count and EAD per grade for the reporting date |
| `fact_default_rate` | dimension_type x dimension_value | default-rate facts by bank, rating and sector |
| `fact_loss_recovery` | dimension_type x dimension_value | loss/recovery facts by bank, rating, product, collateral type |
| `fact_collateral_coverage` | bank | collateral value, adjusted value, secured/unsecured EAD |
| `fact_recovery_curve` | days after default | recovery cashflow timing curve |
| `fact_benchmark` | bank x metric | the full benchmark detail (bank value, peer aggregate, gaps, flags, ranks) |
| `fact_quality_batch` | batch | ingestion batch outcomes and quality scores |
| `fact_quality_finding` | finding | data quality findings for the reporting date |
| `assumptions` | key | PD mapping, haircuts, reporting date, disclaimer — every number in the export is traceable to a documented assumption |

All dates are ISO `YYYY-MM-DD` strings; timestamps are
`YYYY-MM-DD hh:mm:ss`. Encoding is UTF-8, delimiter `,`, decimal `.` —
matching the `SET` statements at the top of the load script.

## Loading in Qlik Sense

1. Create a new Qlik Sense app.
2. Copy the CSV files and `load_script.qvs` into the app's data folder, or
   edit `vDataPath` in the script header to point at the export directory.
3. Paste the script into the load script editor and run it.
4. Suggested associations (also commented in the script):
   - `fact_exposure_snapshot.bank_id` → `dim_institution.bank_id`
   - `fact_exposure_snapshot.rating_grade` → `dim_rating.rating_grade`
   - `fact_collateral.collateral_type` → `dim_collateral_type.collateral_type`
   - `fact_benchmark.metric_id` → `dim_metric.metric_id`
   - Date fields are ISO strings; add a Qlik master calendar if needed.

## Why CSV hand-off instead of a connector

A real deployment would use a Qlik connector or the Qlik REST/analytic
engine API against a governed database. For a local, licence-free prototype
the CSV bundle achieves the same hand-off contract — stable file names, a
documented grain, a star schema and a load script — without pretending to
integrate with a server that does not exist here. The boundary is honest:
everything up to and including the export is fully automated and tested; the
Qlik load itself is the one manual, documented step.
