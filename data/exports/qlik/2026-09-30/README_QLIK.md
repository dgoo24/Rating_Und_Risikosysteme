# Qlik-fähiger Export

SYNTHETISCHE DEMONSTRATIONSDATEN - KEINE REGULATORISCHE BERICHTSERSTATTUNG UND KEINE ECHTEN SPARKASSEN- ODER KUNDENDATEN

Dieser Ordner enthält ein Flat-File-Sternschema für einen lokalen Qlik-Sense-Ladelauf. Es handelt sich nicht um eine bereitgestellte Qlik-Anwendung, und es wird keine externe Qlik-Verbindung beansprucht.

## Dateien

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

## Laden

1. Öffnen Sie den Qlik-Skripteditor.
2. Ersetzen Sie `vDataPath` in `load_script.qvs`, falls die CSV-Dateien nicht im Datenordner der App liegen.
3. Führen Sie das Skript aus und prüfen Sie den Disclaimer zu den synthetischen Daten.

## Granularität

- `fact_exposure_snapshot`: eine Position je Quartalsstichtag.
- `fact_rating_history`: eine Position je Ratingbeobachtung.
- `fact_collateral`: eine Sicherheitsbewertung.
- `fact_recovery_cashflow`: ein Verwertungs-Zahlungsstrom.
- Die übrigen Faktentabellen sind nach Institut und/oder Risikodimension voraggregiert.

Benchmark-Werte nutzen eine Zähler/Nenner-Aggregation und schließen das Institut aus seiner eigenen Vergleichsgruppe aus.
