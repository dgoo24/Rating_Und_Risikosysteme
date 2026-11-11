"""Configurable peer groups for benchmarking.

Peer groups can be maintained explicitly by institution IDs and/or derived from
region characteristics. The benchmark engine always uses weighted aggregate
numerators and denominators and excludes the institution from its own peer
reference where appropriate.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PeerGroupDefinition:
    peer_group: str
    description: str
    members: tuple[str, ...]
    regions: tuple[str, ...] = ()


PEER_GROUPS: dict[str, PeerGroupDefinition] = {
    "PG_URBAN": PeerGroupDefinition(
        peer_group="PG_URBAN",
        description="Fiktionale Institute im städtischen Markt (Demonstrations-Vergleichsgruppe)",
        members=("SSK001", "SSK003", "SSK005"),
        regions=("NORTH", "WEST", "EAST"),
    ),
    "PG_REGIONAL": PeerGroupDefinition(
        peer_group="PG_REGIONAL",
        description="Fiktionale Institute im Regionalmarkt (Demonstrations-Vergleichsgruppe)",
        members=("SSK002", "SSK004"),
        regions=("SOUTH", "CENTRAL"),
    ),
}


def peer_group_for_bank(bank_id: str) -> str | None:
    for group in PEER_GROUPS.values():
        if bank_id in group.members:
            return group.peer_group
    return None


def peer_members(peer_group: str, exclude_bank_id: str | None = None) -> list[str]:
    group = PEER_GROUPS.get(peer_group)
    if group is None:
        return []
    members = list(group.members)
    if exclude_bank_id is not None:
        members = [member for member in members if member != exclude_bank_id]
    return members


def resolve_peer_group(bank_id: str, region: str | None = None) -> str | None:
    """Resolve a configured peer group, falling back to a region mapping.

    This extension point allows future peer definitions based on institution
    characteristics without changing the benchmarking engine.
    """
    configured = peer_group_for_bank(bank_id)
    if configured:
        return configured
    if region:
        for group in PEER_GROUPS.values():
            if region in group.regions:
                return group.peer_group
    return None
