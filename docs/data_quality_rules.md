# Data quality rules

The rule catalogue lives in `quality/rules.py` (63 rules) and is seeded into
the `dq_rule_catalog` table on every pipeline run. The catalogue is the single
source of truth: rule IDs, names, dataset types, categories, severities and
descriptions are defined once and reused by the check functions, the report
context, the Excel `Data_Quality` sheet, the dashboard quality page and the
Qlik `fact_quality_finding` table.

## Severity semantics

| Severity | Effect on the record | Effect on the batch |
|---|---|---|
| `ERROR` | Record is **quarantined** (stored in `quarantine_records` with its JSON payload and reasons; not loaded into curated data) | Batch outcome `QUARANTINED` (nothing from the batch loads) |
| `WARNING` | Record is loaded and flagged in `quality_results` | Batch outcome `ACCEPTED_WITH_WARNINGS` |
| `INFO` | Record is loaded and flagged | no effect on the outcome |

Batch outcome `ACCEPTED` means zero findings. Quarantined rows are never
repaired or silently dropped — the full record is retained for review, and
re-running the corrected source loads cleanly because curated primary keys
prevent overwrites.

## Categories

- **Completeness (23)** — required vs. recommended fields.
- **Consistency (16)** — references against the institution master, the
  curated exposures and configured scales/currencies.
- **Plausibility (15)** — logical and temporal sanity.
- **Uniqueness (9)** — duplicates within a batch and against curated data.

Counts by severity: 54 ERROR, 9 WARNING. By dataset: exposures 22,
rating_history 11, collateral 15, recovery_cashflows 15.

## Exposures (22 rules)

| Rule | Category | Severity | Description |
|---|---|---|---|
| COMP-EXP-001 | Completeness | ERROR | Exposure ID is required |
| COMP-EXP-002 | Completeness | ERROR | Bank ID is required |
| COMP-EXP-003 | Completeness | ERROR | Reporting snapshot date is required |
| COMP-EXP-004 | Completeness | ERROR | Exposure at default (EAD) is required |
| COMP-EXP-005 | Completeness | ERROR | Rating grade is required |
| COMP-EXP-006 | Completeness | WARNING | Outstanding balance is recommended |
| COMP-EXP-007 | Completeness | WARNING | Customer ID is recommended |
| UNIQ-EXP-001 | Uniqueness | ERROR | Exposure is unique within the import batch |
| UNIQ-EXP-002 | Uniqueness | ERROR | Exposure is unique across curated data |
| CONS-EXP-001 | Consistency | ERROR | Bank exists in the institution master |
| CONS-EXP-002 | Consistency | ERROR | Rating grade is on the configured scale |
| CONS-EXP-003 | Consistency | ERROR | Currency is supported (EUR) |
| CONS-EXP-004 | Consistency | WARNING | Reporting date is a quarter end |
| CONS-EXP-005 | Consistency | WARNING | Default flag is interpretable |
| PLAUS-EXP-001 | Plausibility | ERROR | EAD is non-negative |
| PLAUS-EXP-002 | Plausibility | WARNING | Outstanding balance is non-negative |
| PLAUS-EXP-003 | Plausibility | ERROR | Maturity follows origination |
| PLAUS-EXP-004 | Plausibility | ERROR | Origination does not follow snapshot |
| PLAUS-EXP-005 | Plausibility | ERROR | Default date follows origination |
| PLAUS-EXP-006 | Plausibility | ERROR | Reporting date is not in the future |
| PLAUS-EXP-007 | Plausibility | ERROR | Default flag has a default date |
| PLAUS-EXP-008 | Plausibility | WARNING | Default date accompanies the default flag |

## Rating history (11 rules)

| Rule | Category | Severity | Description |
|---|---|---|---|
| COMP-RAT-001 | Completeness | ERROR | Rating history exposure ID is required |
| COMP-RAT-002 | Completeness | ERROR | Rating history bank ID is required |
| COMP-RAT-003 | Completeness | ERROR | Rating observation date is required |
| COMP-RAT-004 | Completeness | ERROR | Rating history grade is required |
| UNIQ-RAT-001 | Uniqueness | ERROR | Rating observation is unique within batch |
| UNIQ-RAT-002 | Uniqueness | ERROR | Rating observation is unique across curated data |
| CONS-RAT-001 | Consistency | ERROR | Rating history bank exists |
| CONS-RAT-002 | Consistency | ERROR | Rating history grade is valid |
| CONS-RAT-003 | Consistency | ERROR | Rating history exposure exists |
| CONS-RAT-004 | Consistency | ERROR | Rating history bank matches exposure |
| PLAUS-RAT-001 | Plausibility | ERROR | Rating observation is not in the future |

## Collateral (15 rules)

| Rule | Category | Severity | Description |
|---|---|---|---|
| COMP-COL-001 | Completeness | ERROR | Collateral ID is required |
| COMP-COL-002 | Completeness | ERROR | Collateral exposure ID is required |
| COMP-COL-003 | Completeness | ERROR | Collateral bank ID is required |
| COMP-COL-004 | Completeness | ERROR | Collateral value is required |
| COMP-COL-005 | Completeness | ERROR | Collateral valuation date is required |
| COMP-COL-006 | Completeness | WARNING | Collateral type is recommended |
| UNIQ-COL-001 | Uniqueness | ERROR | Collateral valuation is unique within batch |
| UNIQ-COL-002 | Uniqueness | ERROR | Collateral valuation is unique across curated data |
| CONS-COL-001 | Consistency | ERROR | Collateral bank exists |
| CONS-COL-002 | Consistency | ERROR | Collateral currency is supported |
| CONS-COL-003 | Consistency | ERROR | Collateral exposure exists |
| CONS-COL-004 | Consistency | ERROR | Collateral bank matches exposure |
| PLAUS-COL-001 | Plausibility | ERROR | Collateral value is non-negative |
| PLAUS-COL-002 | Plausibility | ERROR | Collateral valuation is not in the future |
| PLAUS-COL-003 | Plausibility | WARNING | Collateral valuation is not stale (>3 years) |

## Recovery cashflows (15 rules)

| Rule | Category | Severity | Description |
|---|---|---|---|
| COMP-REC-001 | Completeness | ERROR | Recovery cashflow ID is required |
| COMP-REC-002 | Completeness | ERROR | Recovery exposure ID is required |
| COMP-REC-003 | Completeness | ERROR | Recovery bank ID is required |
| COMP-REC-004 | Completeness | ERROR | Recovery amount is required |
| COMP-REC-005 | Completeness | ERROR | Recovery payment date is required |
| COMP-REC-006 | Completeness | WARNING | Recovery type is recommended |
| UNIQ-REC-001 | Uniqueness | ERROR | Cashflow ID is unique within batch |
| UNIQ-REC-002 | Uniqueness | ERROR | Cashflow ID is unique across curated data |
| UNIQ-REC-003 | Uniqueness | ERROR | Recovery business record is not duplicated |
| CONS-REC-001 | Consistency | ERROR | Recovery bank exists |
| CONS-REC-002 | Consistency | ERROR | Recovery exposure exists |
| CONS-REC-003 | Consistency | ERROR | Recovery bank matches exposure |
| PLAUS-REC-001 | Plausibility | ERROR | Recovery amount is non-negative |
| PLAUS-REC-002 | Plausibility | ERROR | Recovery payment is not in the future |
| PLAUS-REC-003 | Plausibility | ERROR | Recoveries do not exceed EAD without a documented adjustment |

## Quality score

`overall_quality_score` per batch = `rows_valid / rows_received x 100`.
Warning thresholds: <97 amber, <90 red (`config/settings.py`). Scores and
rollups (by bank, rule, category) are surfaced in the report context, the
Excel `Data_Quality` sheet and the dashboard quality page.

## Where findings surface

- `quality_results` table — every finding with record ID, field, failed value.
- `quarantine_records` — the rejected records with full JSON payloads.
- Dashboard page *Data Quality* — scorecards, findings, quarantine browser.
- PDF/Excel reports — data quality section with score and top findings.
- Qlik export — `fact_quality_batch` / `fact_quality_finding` tables.
