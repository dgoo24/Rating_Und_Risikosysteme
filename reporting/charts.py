"""Matplotlib chart helpers used by the PDF report.

The dashboard uses Plotly directly; these static charts are only for PDF output.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

NAVY = "#17324d"
TEAL = "#2a9d8f"
AMBER = "#e9c46a"
CORAL = "#e76f51"
MUTED = "#8d99ae"
LIGHT = "#eef2f5"
RED = "#c1121f"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.edgecolor": "#c8d2da",
        "axes.labelcolor": NAVY,
        "xtick.color": NAVY,
        "ytick.color": NAVY,
        "text.color": NAVY,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.grid": True,
        "grid.color": "#dde5ea",
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def _finish(fig: plt.Figure, path: Path) -> str:
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def _empty_chart(title: str, path: Path, message: str = "No data available for this view") -> str:
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.axis("off")
    ax.set_title(title, loc="left", color=NAVY, fontsize=11, fontweight="bold")
    ax.text(0.5, 0.5, message, ha="center", va="center", color=MUTED, fontsize=10)
    return _finish(fig, path)


def rating_distribution_chart(rating, path: Path) -> str:
    data = rating.distribution.copy()
    data = data[data["exposure_count"] > 0]
    if data.empty:
        return _empty_chart("Rating distribution (EAD share)", path)
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    colors = [TEAL if grade in ("A", "B") else AMBER if grade in ("C", "D") else CORAL for grade in data["rating_grade"]]
    bars = ax.bar(data["rating_grade"], data["share_ead"] * 100, color=colors, width=0.62)
    ax.set_title("Rating distribution by EAD share", loc="left")
    ax.set_ylabel("% of EAD")
    ax.set_xlabel("Rating grade")
    ax.set_ylim(0, max(5, (data["share_ead"].max() * 100) * 1.22))
    for bar, share in zip(bars, data["share_ead"]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.6, f"{share * 100:.1f}%", ha="center", fontsize=8)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def pd_vs_default_chart(rating, path: Path) -> str:
    data = rating.default_by_rating.copy()
    if data.empty:
        return _empty_chart("Configured PD vs observed default rate", path)
    x = np.arange(len(data))
    width = 0.36
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.bar(x - width / 2, data["model_pd_weighted"] * 100, width, label="Configured PD (weighted)", color=NAVY)
    ax.bar(x + width / 2, data["observed_default_rate"] * 100, width, label="Observed 12M default rate", color=CORAL)
    ax.set_xticks(x)
    ax.set_xticklabels(data["rating_grade"])
    ax.set_ylabel("%")
    ax.set_xlabel("Rating grade")
    ax.set_title("Configured PD versus observed 12M default rate", loc="left")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def loss_by_bank_chart(loss, path: Path) -> str:
    data = loss.by_bank.copy()
    if data.empty:
        return _empty_chart("Recovery and loss rate by institution", path)
    x = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.bar(x, data["recovery_rate"] * 100, color=TEAL, width=0.55, label="Recovery rate")
    ax.bar(x, data["loss_rate"] * 100, bottom=data["recovery_rate"] * 100, color=CORAL, width=0.55, label="Loss rate")
    ax.set_xticks(x)
    ax.set_xticklabels(data["bank_id"])
    ax.set_ylabel("% of EAD at default")
    ax.set_title("Observed recovery and loss rate by institution (12M cohort)", loc="left")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.set_ylim(0, 112)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def collateral_coverage_chart(loss, path: Path) -> str:
    data = loss.collateral_by_bank.copy()
    if data.empty:
        return _empty_chart("Collateral coverage by institution", path)
    x = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.bar(x, data["secured_ead_share"] * 100, color=TEAL, width=0.55, label="Secured EAD share")
    ax.bar(x, (1 - data["secured_ead_share"]) * 100, bottom=data["secured_ead_share"] * 100, color=CORAL, width=0.55, label="Unsecured EAD share")
    ax.set_xticks(x)
    ax.set_xticklabels(data["bank_id"])
    ax.set_ylabel("% of current EAD")
    ax.set_ylim(0, 100)
    ax.set_title("Collateral coverage of current EAD (haircut-adjusted, capped)", loc="left")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def recovery_curve_chart(loss, path: Path) -> str:
    data = loss.recovery_curve.copy()
    if data.empty:
        return _empty_chart("Cumulative recovery curve", path)
    fig, ax = plt.subplots(figsize=(7.2, 3.1))
    ax.plot(data["months_since_default"], data["cumulative_recovery_rate"] * 100, color=TEAL, linewidth=2.2)
    ax.fill_between(data["months_since_default"], data["cumulative_recovery_rate"] * 100, color=TEAL, alpha=0.12)
    ax.set_xlabel("Months since default")
    ax.set_ylabel("% of cohort EAD")
    ax.set_title("Cumulative observed recovery curve", loc="left")
    ax.set_xlim(0, max(1, int(data["months_since_default"].max())))
    ax.set_ylim(0, max(5, data["cumulative_recovery_rate"].max() * 110))
    return _finish(fig, path)


def recovery_distribution_chart(loss, path: Path) -> str:
    data = loss.recovery_distribution.copy()
    if data.empty or data["default_count"].sum() == 0:
        return _empty_chart("Recovery rate distribution", path)
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.bar(data["recovery_bucket"].astype(str), data["default_count"], color=TEAL, width=0.6)
    ax.set_ylabel("Defaults")
    ax.set_xlabel("Recovery rate bucket")
    ax.set_title("Exposure-level recovery rate distribution", loc="left")
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def cashflow_trend_chart(loss, path: Path) -> str:
    data = loss.cashflow_by_quarter.copy()
    if data.empty:
        return _empty_chart("Recovery cashflow trend", path)
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.bar(data["payment_period"], data["recovered_amount"] / 1_000_000, color=TEAL, width=0.6)
    ax.set_ylabel("Recoveries (EUR m)")
    ax.set_xlabel("Payment quarter")
    ax.set_title("Observed recovery cashflows by payment quarter", loc="left")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def quality_by_bank_chart(quality, path: Path) -> str:
    data = quality.by_bank.copy()
    if data.empty:
        return _empty_chart("Data quality score by institution", path)
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    colors = [TEAL if value >= 97 else AMBER if value >= 90 else RED for value in data["quality_score"]]
    bars = ax.bar(data["bank_id"], data["quality_score"], color=colors, width=0.55)
    ax.set_ylim(0, 104)
    ax.set_ylabel("Record pass rate (%)")
    ax.set_title("Data quality score by institution", loc="left")
    for bar, value in zip(bars, data["quality_score"]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.2, f"{value:.1f}%", ha="center", fontsize=8)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def migration_heatmap(rating, path: Path) -> str:
    matrix = rating.migration.matrix_pct
    if matrix.empty or matrix.to_numpy().sum() == 0:
        return _empty_chart("Rating migration matrix", path)
    fig, ax = plt.subplots(figsize=(4.8, 4.0))
    data = matrix.to_numpy(dtype=float) * 100
    image = ax.imshow(data, cmap="Blues", vmin=0, vmax=max(1, data.max()))
    ax.set_xticks(range(matrix.shape[1]))
    ax.set_xticklabels(matrix.columns)
    ax.set_yticks(range(matrix.shape[0]))
    ax.set_yticklabels(matrix.index)
    ax.set_xlabel("Rating at end")
    ax.set_ylabel("Rating at start")
    ax.set_title("12M rating migration (% of row)", loc="left")
    for row in range(data.shape[0]):
        for column in range(data.shape[1]):
            value = data[row, column]
            if value >= 0.5:
                ax.text(column, row, f"{value:.0f}", ha="center", va="center", fontsize=7, color="white" if value > 45 else NAVY)
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    ax.grid(False)
    return _finish(fig, path)


def benchmark_chart(benchmark_detail: pd.DataFrame, metric_id: str, path: Path) -> str:
    # An absent benchmark result yields a column-less empty frame.
    if benchmark_detail is None or benchmark_detail.empty or "metric_id" not in benchmark_detail.columns:
        return _empty_chart("Peer benchmark", path)
    data = benchmark_detail[benchmark_detail["metric_id"] == metric_id].copy()
    if data.empty:
        return _empty_chart("Peer benchmark", path)
    data = data.sort_values("bank_value", ascending=False)
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    x = np.arange(len(data))
    ax.bar(x, data["bank_value"] * 100, color=NAVY, width=0.5, label="Institution")
    ax.scatter(x, data["peer_value"] * 100, color=CORAL, zorder=3, label="Peer aggregate", marker="D", s=38)
    ax.set_xticks(x)
    ax.set_xticklabels(data["bank_id"])
    ax.set_ylabel("%")
    ax.set_title(f"Peer benchmark: {data.iloc[0]['metric_name']}", loc="left")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)
