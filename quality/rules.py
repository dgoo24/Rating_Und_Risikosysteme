"""Single source of truth for data-quality rule definitions."""
from __future__ import annotations

from dataclasses import dataclass

import duckdb

SEVERITIES = ("ERROR", "WARNING", "INFO")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    rule_name: str
    dataset_type: str
    category: str
    severity: str
    description: str


_ERROR = "ERROR"
_WARNING = "WARNING"
_COMP = "Completeness"
_UNIQ = "Uniqueness"
_CONS = "Consistency"
_PLAUS = "Plausibility"

RULES: tuple[Rule, ...] = (
    Rule("COMP-EXP-001", "Exposure ID is required", "exposures", _COMP, _ERROR, "The exposure identifier must not be missing."),
    Rule("COMP-EXP-002", "Bank ID is required", "exposures", _COMP, _ERROR, "Every exposure must be associated with a known reporting institution."),
    Rule("COMP-EXP-003", "Reporting snapshot date is required", "exposures", _COMP, _ERROR, "The exposure snapshot date must not be missing."),
    Rule("COMP-EXP-004", "Exposure at default is required", "exposures", _COMP, _ERROR, "EAD must be reported for every exposure snapshot."),
    Rule("COMP-EXP-005", "Rating grade is required", "exposures", _COMP, _ERROR, "A configured rating grade must be available."),
    Rule("COMP-EXP-006", "Outstanding balance is recommended", "exposures", _COMP, _WARNING, "Missing outstanding balance is flagged but does not block the record."),
    Rule("COMP-EXP-007", "Customer ID is recommended", "exposures", _COMP, _WARNING, "Missing customer identifier is flagged."),
    Rule("UNIQ-EXP-001", "Exposure is unique within the import batch", "exposures", _UNIQ, _ERROR, "Duplicate exposure_id/snapshot_date combinations are quarantined after the first occurrence."),
    Rule("UNIQ-EXP-002", "Exposure is unique across curated data", "exposures", _UNIQ, _ERROR, "Records already present in curated data are not overwritten; they are quarantined."),
    Rule("CONS-EXP-001", "Bank exists in the institution master", "exposures", _CONS, _ERROR, "The bank identifier must exist in the reference institution table."),
    Rule("CONS-EXP-002", "Rating grade is on the configured scale", "exposures", _CONS, _ERROR, "Ratings must belong to the configured A-F scale."),
    Rule("CONS-EXP-003", "Currency is supported", "exposures", _CONS, _ERROR, "Only the configured reporting currency EUR is accepted in the prototype."),
    Rule("CONS-EXP-004", "Reporting date is a quarter end", "exposures", _CONS, _WARNING, "Non-quarter-end snapshots are retained but flagged as period inconsistencies."),
    Rule("CONS-EXP-005", "Default flag is interpretable", "exposures", _CONS, _WARNING, "An unrecognised default flag is flagged and treated as not defaulted only after review."),
    Rule("PLAUS-EXP-001", "EAD is non-negative", "exposures", _PLAUS, _ERROR, "Negative exposure at default is implausible."),
    Rule("PLAUS-EXP-002", "Outstanding balance is non-negative", "exposures", _PLAUS, _WARNING, "Negative outstanding balances are flagged."),
    Rule("PLAUS-EXP-003", "Maturity follows origination", "exposures", _PLAUS, _ERROR, "Maturity date must not be before origination date."),
    Rule("PLAUS-EXP-004", "Origination does not follow snapshot", "exposures", _PLAUS, _ERROR, "An exposure cannot be originated after its reporting snapshot."),
    Rule("PLAUS-EXP-005", "Default date follows origination", "exposures", _PLAUS, _ERROR, "Default date must not be before origination."),
    Rule("PLAUS-EXP-006", "Reporting date is not in the future", "exposures", _PLAUS, _ERROR, "Future snapshot dates are impossible for an observed reporting date."),
    Rule("PLAUS-EXP-007", "Default flag has a default date", "exposures", _PLAUS, _ERROR, "A defaulted record must carry the observed default date."),
    Rule("PLAUS-EXP-008", "Default date accompanies the default flag", "exposures", _PLAUS, _WARNING, "A default date without a default flag is inconsistent and retained with a warning."),

    Rule("COMP-RAT-001", "Rating history exposure ID is required", "rating_history", _COMP, _ERROR, "Rating observations must identify an exposure."),
    Rule("COMP-RAT-002", "Rating history bank ID is required", "rating_history", _COMP, _ERROR, "Rating observations must identify a bank."),
    Rule("COMP-RAT-003", "Rating observation date is required", "rating_history", _COMP, _ERROR, "Rating observations require an observation date."),
    Rule("COMP-RAT-004", "Rating history grade is required", "rating_history", _COMP, _ERROR, "Rating observations require a rating grade."),
    Rule("UNIQ-RAT-001", "Rating observation is unique within batch", "rating_history", _UNIQ, _ERROR, "Duplicate exposure/date rating observations are quarantined after the first occurrence."),
    Rule("UNIQ-RAT-002", "Rating observation is unique across curated data", "rating_history", _UNIQ, _ERROR, "Existing curated rating observations are not overwritten."),
    Rule("CONS-RAT-001", "Rating history bank exists", "rating_history", _CONS, _ERROR, "Bank identifier must exist in the institution master."),
    Rule("CONS-RAT-002", "Rating history grade is valid", "rating_history", _CONS, _ERROR, "Ratings must be on the configured scale."),
    Rule("CONS-RAT-003", "Rating history exposure exists", "rating_history", _CONS, _ERROR, "Rating observations must reference a curated exposure."),
    Rule("CONS-RAT-004", "Rating history bank matches exposure", "rating_history", _CONS, _ERROR, "A rating observation and its exposure must belong to the same bank."),
    Rule("PLAUS-RAT-001", "Rating observation is not in the future", "rating_history", _PLAUS, _ERROR, "Future observation dates are impossible."),

    Rule("COMP-COL-001", "Collateral ID is required", "collateral", _COMP, _ERROR, "Collateral must have a unique identifier."),
    Rule("COMP-COL-002", "Collateral exposure ID is required", "collateral", _COMP, _ERROR, "Collateral must reference an exposure."),
    Rule("COMP-COL-003", "Collateral bank ID is required", "collateral", _COMP, _ERROR, "Collateral must reference a bank."),
    Rule("COMP-COL-004", "Collateral value is required", "collateral", _COMP, _ERROR, "Collateral value must be provided."),
    Rule("COMP-COL-005", "Collateral valuation date is required", "collateral", _COMP, _ERROR, "Collateral requires a valuation date."),
    Rule("COMP-COL-006", "Collateral type is recommended", "collateral", _COMP, _WARNING, "Missing collateral type is flagged."),
    Rule("UNIQ-COL-001", "Collateral valuation is unique within batch", "collateral", _UNIQ, _ERROR, "Duplicate collateral_id/valuation_date combinations are quarantined."),
    Rule("UNIQ-COL-002", "Collateral valuation is unique across curated data", "collateral", _UNIQ, _ERROR, "Existing collateral valuations are not overwritten."),
    Rule("CONS-COL-001", "Collateral bank exists", "collateral", _CONS, _ERROR, "Bank identifier must exist in the institution master."),
    Rule("CONS-COL-002", "Collateral currency is supported", "collateral", _CONS, _ERROR, "Only EUR is accepted in the prototype."),
    Rule("CONS-COL-003", "Collateral exposure exists", "collateral", _CONS, _ERROR, "Collateral must reference a curated exposure."),
    Rule("CONS-COL-004", "Collateral bank matches exposure", "collateral", _CONS, _ERROR, "Collateral and exposure must belong to the same bank."),
    Rule("PLAUS-COL-001", "Collateral value is non-negative", "collateral", _PLAUS, _ERROR, "Negative collateral values are impossible."),
    Rule("PLAUS-COL-002", "Collateral valuation is not in the future", "collateral", _PLAUS, _ERROR, "Future valuation dates are impossible."),
    Rule("PLAUS-COL-003", "Collateral valuation is not stale", "collateral", _PLAUS, _WARNING, "Valuations older than the configured threshold are flagged."),

    Rule("COMP-REC-001", "Recovery cashflow ID is required", "recovery_cashflows", _COMP, _ERROR, "Every recovery cashflow requires an identifier."),
    Rule("COMP-REC-002", "Recovery exposure ID is required", "recovery_cashflows", _COMP, _ERROR, "Every recovery cashflow must reference an exposure."),
    Rule("COMP-REC-003", "Recovery bank ID is required", "recovery_cashflows", _COMP, _ERROR, "Every recovery cashflow must reference a bank."),
    Rule("COMP-REC-004", "Recovery amount is required", "recovery_cashflows", _COMP, _ERROR, "Recovery amount must be provided."),
    Rule("COMP-REC-005", "Recovery payment date is required", "recovery_cashflows", _COMP, _ERROR, "Recovery payment date must be provided."),
    Rule("COMP-REC-006", "Recovery type is recommended", "recovery_cashflows", _COMP, _WARNING, "Missing recovery type is flagged."),
    Rule("UNIQ-REC-001", "Cashflow ID is unique within batch", "recovery_cashflows", _UNIQ, _ERROR, "Duplicate cashflow IDs are quarantined."),
    Rule("UNIQ-REC-002", "Cashflow ID is unique across curated data", "recovery_cashflows", _UNIQ, _ERROR, "Existing cashflow IDs are not overwritten."),
    Rule("UNIQ-REC-003", "Recovery business record is not duplicated", "recovery_cashflows", _UNIQ, _ERROR, "Identical exposure/date/amount/type records are treated as duplicates."),
    Rule("CONS-REC-001", "Recovery bank exists", "recovery_cashflows", _CONS, _ERROR, "Bank identifier must exist in the institution master."),
    Rule("CONS-REC-002", "Recovery exposure exists", "recovery_cashflows", _CONS, _ERROR, "Recovery cashflows must reference a curated exposure."),
    Rule("CONS-REC-003", "Recovery bank matches exposure", "recovery_cashflows", _CONS, _ERROR, "Recovery and exposure must belong to the same bank."),
    Rule("PLAUS-REC-001", "Recovery amount is non-negative", "recovery_cashflows", _PLAUS, _ERROR, "Negative recovery cashflows are impossible."),
    Rule("PLAUS-REC-002", "Recovery payment is not in the future", "recovery_cashflows", _PLAUS, _ERROR, "Future payment dates are impossible for observed cashflows."),
    Rule("PLAUS-REC-003", "Recoveries do not exceed exposure at default", "recovery_cashflows", _PLAUS, _ERROR, "Aggregate recoveries above EAD require a documented adjustment; unexplained overages are quarantined."),
)

RULE_BY_ID: dict[str, Rule] = {rule.rule_id: rule for rule in RULES}


def seed_rule_catalog(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DELETE FROM dq_rule_catalog")
    con.executemany(
        "INSERT INTO dq_rule_catalog (rule_id, rule_name, dataset_type, category, severity, description) VALUES (?, ?, ?, ?, ?, ?)",
        [(rule.rule_id, rule.rule_name, rule.dataset_type, rule.category, rule.severity, rule.description) for rule in RULES],
    )
