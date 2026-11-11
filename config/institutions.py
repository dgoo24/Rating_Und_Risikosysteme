"""Fictional reference institutions used by the demonstration.

These are invented Sparkassen-like institutions. No real institution, customer,
employee or portfolio is represented.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstitutionDefinition:
    bank_id: str
    bank_name: str
    region: str
    peer_group: str


INSTITUTIONS: tuple[InstitutionDefinition, ...] = (
    InstitutionDefinition("SSK001", "Muster-Sparkasse Nord (fiktiv)", "NORTH", "PG_URBAN"),
    InstitutionDefinition("SSK002", "Muster-Sparkasse Süd (fiktiv)", "SOUTH", "PG_REGIONAL"),
    InstitutionDefinition("SSK003", "Muster-Sparkasse West (fiktiv)", "WEST", "PG_URBAN"),
    InstitutionDefinition("SSK004", "Muster-Sparkasse Mitte (fiktiv)", "CENTRAL", "PG_REGIONAL"),
    InstitutionDefinition("SSK005", "Muster-Sparkasse Ost (fiktiv)", "EAST", "PG_URBAN"),
)

BANK_NAMES: dict[str, str] = {inst.bank_id: inst.bank_name for inst in INSTITUTIONS}
BANK_REGIONS: dict[str, str] = {inst.bank_id: inst.region for inst in INSTITUTIONS}
