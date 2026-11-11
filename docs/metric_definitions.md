# Metric definitions

Formulas as implemented, with the module that owns each calculation.
Reporting date R is the latest curated quarterly snapshot; the 12M window
starts 12 months before R. All money values are EUR; all rates are ratios.

`sum(EAD)` always means the sum of `exposure_at_default` over the selected
scope (community, one bank via `bank_ids`, or a sector via `sectors`).

## Module A — Rating & Scoring (`modules/rating_scoring`)

| Metric | Formula | Notes |
|---|---|---|
| Exposure-weighted PD 12M (`weighted_pd`) | `sum(EAD_i x PD(rating_i)) / sum(EAD_i)` | PD per grade from `config/rating_pd_mapping.py` (A 0.001 … F 0.12). Exposures without a valid rating are excluded from numerator and denominator. |
| PD by rating grade | `sum(EAD x PD) / sum(EAD)` grouped by `rating_grade` | Expected default EAD per grade |
| PD by bank | as above, grouped by `bank_id` | |
| Rating distribution | count and EAD per grade; shares = EAD share of total | Basis for the distribution charts |
| Investment-grade share | `sum(EAD rated A or B) / sum(EAD)` | A–B is investment grade |
| Observed 12M default rate (count) | `defaults in window / performing exposures at window start` | Cohort = exposures performing at the window start (12 months before R) |
| Observed 12M default rate (EAD) | `EAD of those defaults / EAD of the cohort` | |
| Model PD vs observed default rate | per bank: model PD of the cohort vs realised rate | Calibration view |
| Rating upgrades / downgrades | matched observations between migration start and R: `upgrades / matched`, `downgrades / matched` | Migration matrix A–F x A–F with row percentages, entries and exits |

## Module B — Loss Estimation (`modules/loss_estimation`)

| Metric | Formula | Notes |
|---|---|---|
| Collateral value | `sum(collateral_value)` at latest valuation per collateral | Latest valuation wins; orphan collateral (unknown exposure) is excluded from exposure joins but reported |
| Haircut | per type: REAL_ESTATE 20%, FINANCIAL_COLLATERAL 5%, OTHER 40% | `adjusted = value x (1 - haircut)` |
| Adjusted collateral coverage | `sum(adjusted collateral) / sum(EAD)` | Community/bank scope, current snapshot |
| Secured EAD (capped) | `sum(min(adjusted collateral, EAD)) / sum(EAD)` | Collateral never covers more than the exposure |
| Stale collateral items | valuations older than 3 years (WARNING) | Flagged per item |
| Primary collateral type | the collateral type with the largest adjusted value per exposure | Ties broken deterministically |
| 12M default cohort | exposures that defaulted inside the window with EAD at default | Basis for recovery/loss rates |
| Recovery rate 12M (EAD-weighted) | `sum(recovery cashflows) / sum(EAD at default)` | Cashflows after default date, up to the reporting date; pre-default and future payments excluded |
| Loss rate 12M | `1 - recovery rate` per cohort, aggregated EAD-weighted | `loss = EAD - recoveries` |
| Recovery distribution | buckets <25%, 25–50%, 50–75%, >75% per defaulted exposure | Severity bands: LOW <25%, MODERATE 25–50%, SEVERE 50–75%, VERY_SEVERE >75% |
| Recovery by rating vs collateral | realised recovery rate by rating at default versus average coverage | Collateral double-counting is avoided: secured EAD caps at exposure EAD |
| Recovery cashflow timing | days between default date and payment date; volume-weighted average and max | Quarterly cashflow trend |

## Benchmarking — the 15 peer metrics (`benchmarking/aggregation.py`)

Rating module (11): `PD_12M_WEIGHTED`, `SHARE_IG_A_B`, `SHARE_RATING_A` …
`SHARE_RATING_F`, `DEFAULT_RATE_12M`, `RATING_UPGRADE_RATE`,
`RATING_DOWNGRADE_RATE`.

Loss module (4): `RECOVERY_RATE_12M`, `LOSS_RATE_12M`, `COLLATERAL_COVERAGE`,
`SECURED_EAD_SHARE`.

Each metric is produced as a numerator/denominator pair per bank and
reporting date — never as a pre-computed ratio — so that every aggregation
level re-derives the correct weighted result:

- **bank value** = `numerator / denominator`
- **peer value** = `sum(peer numerators) / sum(peer denominators)`, peers =
  the configured peer group minus the bank itself (exposure-weighted, never
  the mean of ratios)
- **portfolio value** = aggregate over all banks present for the metric
- **gap** = `bank - peer`; **relative gap** = `gap / peer`
- **performance flag** = BETTER/WORSE if `|relative gap| > 10%` in the metric's
  direction (`higher_is_better`), IN_LINE within ±10%, INFORMATION when the
  metric has no direction, NO_BENCHMARK when no peers have data
- **rank** = 1 + number of peers strictly better (ties share a rank);
  **percentile** = share of reference banks strictly better

Metric directions: PD and default/downgrade/loss rates are
`higher_is_better=False`; IG share, upgrade rate, recovery rate, coverage and
secured share are `True`; per-grade rating shares are INFORMATION
(directionless). The catalogue (id, name, module, unit, direction,
description) is served to dashboards, Excel and the Qlik `dim_metric` table
from a single tuple in `benchmarking/aggregation.py`.

## Worked example (fixture portfolio, R = 2026-06-30)

The test suite (`tests/test_benchmarking.py`, `tests/test_rating_scoring.py`,
`tests/test_loss_estimation.py`) derives every number by hand; e.g. for the
community scope: 8 exposures, EAD 1900, expected default EAD 13.9 → weighted
PD 0.73%; cohort of 6 performing exposures at 2025-06-30, 2 defaults → count
default rate 1/3; adjusted collateral 1320.5 → coverage 1320.5/1900;
recoveries 85 on EAD-at-default 200 → recovery rate 0.425, loss rate 0.575.
