"""Peer aggregation and bank-vs-peer benchmark calculations.

Benchmarks are calculated from numerators and denominators, not by averaging
bank-level ratios. The institution under review is excluded from its own peer
reference. When a peer group has only two members, the remaining member is a
single-peer reference and the peer median equals that member's value.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import pandas as pd

from config.peer_groups import PEER_GROUPS, peer_members, resolve_peer_group


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    metric_name: str
    module: str
    unit: str
    higher_is_better: bool | None
    description: str


METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition("PD_12M_WEIGHTED", "Exposure-weighted PD 12M", "rating", "ratio", False, "Sum(EAD x configured PD) / Sum(EAD)."),
    MetricDefinition("SHARE_IG_A_B", "Investment-grade share (A-B, EAD)", "rating", "ratio", True, "EAD rated A or B / total rated EAD."),
    MetricDefinition("SHARE_RATING_A", "Rating A share (EAD)", "rating", "ratio", None, "EAD rated A / total rated EAD."),
    MetricDefinition("SHARE_RATING_B", "Rating B share (EAD)", "rating", "ratio", None, "EAD rated B / total rated EAD."),
    MetricDefinition("SHARE_RATING_C", "Rating C share (EAD)", "rating", "ratio", None, "EAD rated C / total rated EAD."),
    MetricDefinition("SHARE_RATING_D", "Rating D share (EAD)", "rating", "ratio", None, "EAD rated D / total rated EAD."),
    MetricDefinition("SHARE_RATING_E", "Rating E share (EAD)", "rating", "ratio", None, "EAD rated E / total rated EAD."),
    MetricDefinition("SHARE_RATING_F", "Rating F share (EAD)", "rating", "ratio", None, "EAD rated F / total rated EAD."),
    MetricDefinition("DEFAULT_RATE_12M", "Observed 12M default rate (count)", "rating", "ratio", False, "Defaults in the 12M cohort / performing exposures at observation start."),
    MetricDefinition("RATING_UPGRADE_RATE", "Rating upgrade rate", "rating", "ratio", True, "Upgrades / matched rating observations."),
    MetricDefinition("RATING_DOWNGRADE_RATE", "Rating downgrade rate", "rating", "ratio", False, "Downgrades / matched rating observations."),
    MetricDefinition("RECOVERY_RATE_12M", "Observed 12M recovery rate (EAD-weighted)", "loss", "ratio", True, "Recovery cashflows / EAD at default for the 12M cohort."),
    MetricDefinition("LOSS_RATE_12M", "Observed 12M loss rate (EAD-weighted)", "loss", "ratio", False, "Loss amount / EAD at default for the 12M cohort."),
    MetricDefinition("COLLATERAL_COVERAGE", "Adjusted collateral coverage", "loss", "ratio", True, "Haircut-adjusted collateral value / current EAD."),
    MetricDefinition("SECURED_EAD_SHARE", "Secured EAD share (capped)", "loss", "ratio", True, "Secured EAD (capped at exposure EAD) / current EAD."),
)

METRIC_BY_ID = {metric.metric_id: metric for metric in METRICS}

METRIC_COLUMNS = [
    "bank_id", "reporting_date", "unit", "metric_id", "metric_name",
    "higher_is_better", "numerator", "denominator",
]

DETAIL_COLUMNS = [
    "bank_id", "bank_name", "peer_group", "reporting_date", "metric_id", "metric_name",
    "module", "unit", "higher_is_better", "numerator", "denominator", "bank_value",
    "peer_numerator", "peer_denominator", "peer_value", "peer_median", "peer_min",
    "peer_max", "peer_count", "gap", "relative_gap", "rank_in_peer_group", "percentile",
    "performance_flag", "portfolio_value", "portfolio_gap", "portfolio_relative_gap",
    "portfolio_rank", "portfolio_percentile", "portfolio_performance_flag",
]


def metric_catalog_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "metric_id": metric.metric_id,
                "metric_name": metric.metric_name,
                "module": metric.module,
                "unit": metric.unit,
                "higher_is_better": metric.higher_is_better,
                "description": metric.description,
            }
            for metric in METRICS
        ]
    )


def normalize_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    if metrics.empty:
        return pd.DataFrame(columns=METRIC_COLUMNS)
    frame = metrics.copy()
    # Optional metadata columns are filled from the catalogue before typing,
    # so callers may pass minimal frames (bank_id, metric_id, values, ...).
    if "higher_is_better" not in frame.columns:
        frame["higher_is_better"] = frame["metric_id"].map(
            {metric.metric_id: metric.higher_is_better for metric in METRICS}
        )
    if "unit" not in frame.columns:
        frame["unit"] = "ratio"
    if "metric_name" not in frame.columns:
        frame["metric_name"] = frame["metric_id"].map(
            {metric.metric_id: metric.metric_name for metric in METRICS}
        )
    for column in ("bank_id", "metric_id", "metric_name"):
        frame[column] = frame[column].astype("string")
    frame["numerator"] = pd.to_numeric(frame["numerator"], errors="coerce")
    frame["denominator"] = pd.to_numeric(frame["denominator"], errors="coerce")
    frame["reporting_date"] = pd.to_datetime(frame["reporting_date"], errors="coerce").dt.normalize()
    frame = frame[frame["denominator"].fillna(0) > 0].copy()
    frame["higher_is_better"] = frame["higher_is_better"].map(
        lambda value: None if pd.isna(value) else bool(value)
    )
    return frame[METRIC_COLUMNS].reset_index(drop=True)


def combine_metrics(*frames: pd.DataFrame) -> pd.DataFrame:
    available = [frame for frame in frames if frame is not None and not frame.empty]
    if not available:
        return pd.DataFrame(columns=METRIC_COLUMNS)
    combined = pd.concat([normalize_metrics(frame) for frame in available], ignore_index=True)
    return combined.drop_duplicates(["bank_id", "reporting_date", "metric_id"], keep="first").reset_index(drop=True)


def _bank_values(metrics: pd.DataFrame) -> pd.DataFrame:
    values = metrics.copy()
    values["bank_value"] = values["numerator"] / values["denominator"].where(values["denominator"] > 0)
    return values


def _peer_ids(bank_id: str, peer_group: str | None, institutions: pd.DataFrame) -> list[str]:
    if peer_group is None:
        return []
    configured = peer_members(peer_group, exclude_bank_id=bank_id)
    if configured:
        return configured
    if institutions.empty:
        return []
    same_group = institutions[
        (institutions["peer_group"] == peer_group) & (institutions["bank_id"] != bank_id)
    ]
    return same_group["bank_id"].astype(str).tolist()


def _performance_flag(bank_value: float | None, peer_value: float | None, higher_is_better: bool | None) -> str:
    if bank_value is None or peer_value is None or pd.isna(bank_value) or pd.isna(peer_value):
        return "NO_BENCHMARK"
    if higher_is_better is None:
        return "INFORMATION"
    relative = (bank_value - peer_value) / peer_value if peer_value else None
    if relative is None:
        return "INFORMATION"
    threshold = 0.10
    if relative > threshold:
        return "BETTER" if higher_is_better else "WORSE"
    if relative < -threshold:
        return "WORSE" if higher_is_better else "BETTER"
    return "IN_LINE"


def _rank_and_percentile(
    bank_value: float | None,
    reference_values: pd.Series,
    higher_is_better: bool | None,
    include_self: bool,
) -> tuple[int | None, float | None]:
    """Rank a bank against a reference population (1 = best).

    Percentiles are the share of reference banks that are strictly better and
    therefore lie in ``[0, 1]``. Ties share the same rank.
    """
    if higher_is_better is None or bank_value is None or reference_values.empty:
        return None, None
    if higher_is_better:
        better_count = int((reference_values < bank_value).sum())
    else:
        better_count = int((reference_values > bank_value).sum())
    denominator = reference_values.size if not include_self else max(reference_values.size - 1, 0)
    if denominator <= 0:
        return 1, None
    return 1 + better_count, better_count / denominator


def _override_group(
    bank_id: str,
    peer_group_override: str | Mapping[str, str] | None,
) -> str | None:
    if peer_group_override is None:
        return None
    if isinstance(peer_group_override, str):
        return peer_group_override
    return peer_group_override.get(bank_id)


def build_benchmark_detail(
    metrics: pd.DataFrame,
    institutions: pd.DataFrame,
    peer_group_override: str | Mapping[str, str] | None = None,
    peer_ids_override: Mapping[str, Iterable[str]] | None = None,
) -> pd.DataFrame:
    """Compare each bank metric with its peer group and the overall portfolio.

    Parameters
    ----------
    metrics:
        Long-form metric frame with numerator/denominator columns.
    institutions:
        Institution master used to resolve peer-group membership and names.
    peer_group_override:
        Optionally replace the peer group label for one bank (mapping of
        ``bank_id -> peer_group``) or for every bank (a single group name).
        Peer membership always comes from the configured peer group, excluding
        the bank itself.
    peer_ids_override:
        Explicit peer bank IDs by bank ID. This takes precedence over the
        configured peer groups and is primarily useful for what-if analyses.

    Portfolio comparisons use the aggregate of all banks present for the
    metric (weighted numerator / weighted denominator), while peer comparisons
    exclude the bank itself.
    """
    normalized = normalize_metrics(metrics)
    if normalized.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    institution_frame = institutions.copy()
    if institution_frame.empty:
        institution_frame = pd.DataFrame(columns=["bank_id", "bank_name", "peer_group"])
    institution_frame["bank_id"] = institution_frame["bank_id"].astype(str)
    bank_names = institution_frame.set_index("bank_id")["bank_name"].to_dict() if "bank_name" in institution_frame.columns else {}
    bank_regions = institution_frame.set_index("bank_id")["region"].to_dict() if "region" in institution_frame.columns else {}

    enriched = normalized.copy()
    enriched["bank_name"] = enriched["bank_id"].map(bank_names).fillna(enriched["bank_id"])
    enriched["peer_group"] = enriched["bank_id"].map(
        lambda bank_id: resolve_peer_group(str(bank_id), bank_regions.get(str(bank_id)))
    )
    enriched["peer_group"] = [
        _override_group(str(bank_id), peer_group_override) or peer_group
        for bank_id, peer_group in zip(enriched["bank_id"], enriched["peer_group"])
    ]
    values = _bank_values(enriched)
    available_ids = set(values["bank_id"].astype(str))

    portfolio = (
        values.groupby("metric_id", as_index=False)
        .agg(
            portfolio_numerator=("numerator", "sum"),
            portfolio_denominator=("denominator", "sum"),
        )
    )
    portfolio["portfolio_value"] = (
        portfolio["portfolio_numerator"] / portfolio["portfolio_denominator"].where(
            portfolio["portfolio_denominator"] > 0
        )
    )
    portfolio_by_metric = portfolio.set_index("metric_id")

    rows: list[dict[str, object]] = []
    for _, row in values.iterrows():
        bank_id = str(row["bank_id"])
        peer_group = row["peer_group"] if pd.notna(row["peer_group"]) else None
        if peer_ids_override is not None and bank_id in peer_ids_override:
            peers = [str(peer) for peer in peer_ids_override[bank_id] if str(peer) != bank_id]
        else:
            peers = _peer_ids(bank_id, peer_group, institution_frame)
        peers = [peer for peer in peers if peer in available_ids]
        peer_rows = values[
            (values["metric_id"] == row["metric_id"])
            & (values["bank_id"].astype(str).isin(peers))
        ]
        peer_numerator = float(peer_rows["numerator"].sum()) if not peer_rows.empty else None
        peer_denominator = float(peer_rows["denominator"].sum()) if not peer_rows.empty else None
        peer_value = (
            peer_numerator / peer_denominator
            if peer_numerator is not None and peer_denominator not in (None, 0)
            else None
        )
        peer_values = peer_rows["bank_value"].dropna() if not peer_rows.empty else pd.Series(dtype=float)
        peer_median = float(peer_values.median()) if not peer_values.empty else None
        peer_min = float(peer_values.min()) if not peer_values.empty else None
        peer_max = float(peer_values.max()) if not peer_values.empty else None
        peer_count = int(peer_values.size)

        bank_value = float(row["bank_value"]) if pd.notna(row["bank_value"]) else None
        gap = bank_value - peer_value if bank_value is not None and peer_value is not None else None
        relative_gap = gap / peer_value if gap is not None and peer_value not in (None, 0) else None

        higher_is_better = row["higher_is_better"]
        rank, percentile = _rank_and_percentile(bank_value, peer_values, higher_is_better, include_self=False)
        performance = _performance_flag(bank_value, peer_value, higher_is_better)

        portfolio_row = portfolio_by_metric.loc[row["metric_id"]] if row["metric_id"] in portfolio_by_metric.index else None
        portfolio_value = (
            float(portfolio_row["portfolio_value"])
            if portfolio_row is not None and pd.notna(portfolio_row["portfolio_value"])
            else None
        )
        portfolio_gap = (
            bank_value - portfolio_value
            if bank_value is not None and portfolio_value is not None
            else None
        )
        portfolio_relative_gap = (
            portfolio_gap / portfolio_value
            if portfolio_gap is not None and portfolio_value not in (None, 0)
            else None
        )
        portfolio_values = values.loc[values["metric_id"] == row["metric_id"], "bank_value"].dropna()
        portfolio_rank, portfolio_percentile = _rank_and_percentile(
            bank_value, portfolio_values, higher_is_better, include_self=True
        )
        portfolio_performance = _performance_flag(bank_value, portfolio_value, higher_is_better)

        rows.append(
            {
                "bank_id": bank_id,
                "bank_name": row["bank_name"],
                "peer_group": peer_group,
                "reporting_date": row["reporting_date"],
                "metric_id": row["metric_id"],
                "metric_name": row["metric_name"],
                "module": METRIC_BY_ID.get(str(row["metric_id"]), MetricDefinition(
                    str(row["metric_id"]), str(row["metric_name"]), "other", "ratio", None, ""
                )).module,
                "unit": row["unit"],
                "higher_is_better": higher_is_better,
                "numerator": float(row["numerator"]),
                "denominator": float(row["denominator"]),
                "bank_value": bank_value,
                "peer_numerator": peer_numerator,
                "peer_denominator": peer_denominator,
                "peer_value": peer_value,
                "peer_median": peer_median,
                "peer_min": peer_min,
                "peer_max": peer_max,
                "peer_count": peer_count,
                "gap": gap,
                "relative_gap": relative_gap,
                "rank_in_peer_group": rank,
                "percentile": percentile,
                "performance_flag": performance,
                "portfolio_value": portfolio_value,
                "portfolio_gap": portfolio_gap,
                "portfolio_relative_gap": portfolio_relative_gap,
                "portfolio_rank": portfolio_rank,
                "portfolio_percentile": portfolio_percentile,
                "portfolio_performance_flag": portfolio_performance,
            }
        )
    detail = pd.DataFrame(rows)
    for column in DETAIL_COLUMNS:
        if column not in detail.columns:
            detail[column] = None
    return detail[DETAIL_COLUMNS].sort_values(["metric_id", "bank_id"]).reset_index(drop=True)


def peer_group_summary(metrics: pd.DataFrame, institutions: pd.DataFrame) -> pd.DataFrame:
    """Aggregate each peer group from members' numerators and denominators."""
    normalized = normalize_metrics(metrics)
    if normalized.empty or institutions.empty:
        return pd.DataFrame(
            columns=["peer_group", "metric_id", "metric_name", "bank_count", "numerator", "denominator", "peer_value"]
        )
    peer_map = institutions.set_index("bank_id")["peer_group"].astype(str).to_dict()
    frame = normalized.copy()
    frame["peer_group"] = frame["bank_id"].astype(str).map(peer_map)
    frame = frame[frame["peer_group"].notna() & (frame["peer_group"] != "nan")]
    if frame.empty:
        return pd.DataFrame(
            columns=["peer_group", "metric_id", "metric_name", "bank_count", "numerator", "denominator", "peer_value"]
        )
    grouped = (
        frame.groupby(["peer_group", "metric_id"], as_index=False)
        .agg(
            metric_name=("metric_name", "first"),
            bank_count=("bank_id", "nunique"),
            numerator=("numerator", "sum"),
            denominator=("denominator", "sum"),
        )
    )
    grouped["peer_value"] = grouped["numerator"] / grouped["denominator"].where(grouped["denominator"] > 0)
    return grouped.sort_values(["peer_group", "metric_id"]).reset_index(drop=True)


def benchmark_kpis(detail: pd.DataFrame) -> dict[str, object]:
    if detail.empty:
        return {"banks": 0, "metrics": 0, "better": 0, "worse": 0, "in_line": 0, "benchmarked": 0}
    flags = detail["performance_flag"].value_counts()
    return {
        "banks": int(detail["bank_id"].nunique()),
        "metrics": int(detail["metric_id"].nunique()),
        "better": int(flags.get("BETTER", 0)),
        "worse": int(flags.get("WORSE", 0)),
        "in_line": int(flags.get("IN_LINE", 0)),
        "benchmarked": int(detail["peer_value"].notna().sum()),
    }


def benchmark_metric_summary(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(
            columns=["metric_id", "metric_name", "module", "banks", "better", "worse", "in_line", "peer_value"]
        )
    grouped = (
        detail.groupby(["metric_id", "metric_name", "module"], as_index=False)
        .agg(
            banks=("bank_id", "nunique"),
            better=("performance_flag", lambda values: int((values == "BETTER").sum())),
            worse=("performance_flag", lambda values: int((values == "WORSE").sum())),
            in_line=("performance_flag", lambda values: int((values == "IN_LINE").sum())),
        )
    )
    peer_values = detail.groupby("metric_id", as_index=False)["peer_value"].mean().rename(
        columns={"peer_value": "average_peer_value"}
    )
    return grouped.merge(peer_values, on="metric_id", how="left").sort_values(["module", "metric_id"]).reset_index(drop=True)


def top_gaps(detail: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if detail.empty:
        return detail.copy()
    frame = detail[detail["relative_gap"].notna()].copy()
    frame["_abs_gap"] = frame["relative_gap"].abs()
    columns = [
        "bank_id", "bank_name", "peer_group", "metric_id", "metric_name", "bank_value",
        "peer_value", "gap", "relative_gap", "performance_flag", "rank_in_peer_group",
    ]
    return frame.sort_values("_abs_gap", ascending=False)[columns].head(limit).reset_index(drop=True)


def metric_values_table(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return detail.copy()
    return detail.pivot_table(
        index=["bank_id", "bank_name", "peer_group"],
        columns="metric_id",
        values="bank_value",
        aggfunc="first",
    ).reset_index()
