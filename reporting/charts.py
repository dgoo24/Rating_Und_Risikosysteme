"""Matplotlib-Diagrammhilfen für den PDF-Bericht.

Das Dashboard nutzt Altair direkt; diese statischen Diagramme dienen ausschließlich
der PDF-Ausgabe. Farbwelt und Beschriftungen folgen dem Sparkasse-inspirierten
Design (Sparkassenrot, Dunkelgrau, Weiß) und der deutschen Zahlenkonvention.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# Sparkassenrot als Signaturfarbe, ergänzt um die Neutraltöne des Designs.
SPARKASSE_RED = "#E6001E"
SPARKASSE_DARK = "#454957"
SPARKASSE_DEEP = "#8C0011"
AMBER = "#F5A623"
SLATE = "#6E7B8B"
GREEN = "#13795B"
MUTED = "#8A8F98"
LIGHT = "#F4F4F6"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.edgecolor": "#D5D7DB",
        "axes.labelcolor": SPARKASSE_DARK,
        "xtick.color": SPARKASSE_DARK,
        "ytick.color": SPARKASSE_DARK,
        "text.color": "#262626",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.grid": True,
        "grid.color": "#E3E5E8",
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def _de(value: float, digits: int = 1) -> str:
    """Formatiert eine Zahl mit deutscher Konvention (Komma als Dezimaltrenner)."""
    return f"{value:.{digits}f}".replace(".", ",")


def _pct_axis(axis) -> None:
    """Beschriftet eine Achse mit Prozentwerten in deutscher Schreibweise."""
    axis.yaxis.set_major_formatter(mticker.FuncFormatter(lambda value, _: f"{value:g}".replace(".", ",") + " %"))


def _finish(fig: plt.Figure, path: Path) -> str:
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def _empty_chart(title: str, path: Path, message: str = "Für diese Ansicht liegen keine Daten vor.") -> str:
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.axis("off")
    ax.set_title(title, loc="left", color="#262626", fontsize=11, fontweight="bold")
    ax.text(0.5, 0.5, message, ha="center", va="center", color=MUTED, fontsize=10)
    return _finish(fig, path)


def rating_distribution_chart(rating, path: Path) -> str:
    data = rating.distribution.copy()
    data = data[data["exposure_count"] > 0]
    if data.empty:
        return _empty_chart("Ratingverteilung (EAD-Anteil)", path)
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    colors = [SPARKASSE_DARK if grade in ("A", "B") else AMBER if grade in ("C", "D") else SPARKASSE_RED for grade in data["rating_grade"]]
    bars = ax.bar(data["rating_grade"], data["share_ead"] * 100, color=colors, width=0.62)
    ax.set_title("Ratingverteilung nach EAD-Anteil", loc="left")
    ax.set_ylabel("Anteil des EAD")
    ax.set_xlabel("Ratingstufe")
    ax.set_ylim(0, max(5, (data["share_ead"].max() * 100) * 1.22))
    for bar, share in zip(bars, data["share_ead"]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.6, _de(share * 100) + " %", ha="center", fontsize=8)
    _pct_axis(ax)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def pd_vs_default_chart(rating, path: Path) -> str:
    data = rating.default_by_rating.copy()
    if data.empty:
        return _empty_chart("Konfigurierte PD vs. beobachtete Ausfallquote", path)
    x = np.arange(len(data))
    width = 0.36
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.bar(x - width / 2, data["model_pd_weighted"] * 100, width, label="Konfigurierte PD (gewichtet)", color=SPARKASSE_DARK)
    ax.bar(x + width / 2, data["observed_default_rate"] * 100, width, label="Beobachtete Ausfallquote 12M", color=SPARKASSE_RED)
    ax.set_xticks(x)
    ax.set_xticklabels(data["rating_grade"])
    ax.set_ylabel("Quote")
    ax.set_xlabel("Ratingstufe")
    ax.set_title("Konfigurierte PD versus beobachtete Ausfallquote 12M", loc="left")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    _pct_axis(ax)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def loss_by_bank_chart(loss, path: Path) -> str:
    data = loss.by_bank.copy()
    if data.empty:
        return _empty_chart("Verwertungs- und Verlustquote nach Institut", path)
    x = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.bar(x, data["recovery_rate"] * 100, color=SPARKASSE_DARK, width=0.55, label="Verwertungsquote")
    ax.bar(x, data["loss_rate"] * 100, bottom=data["recovery_rate"] * 100, color=SPARKASSE_RED, width=0.55, label="Verlustquote")
    ax.set_xticks(x)
    ax.set_xticklabels(data["bank_id"])
    ax.set_ylabel("Anteil des EAD im Ausfall")
    ax.set_title("Beobachtete Verwertungs- und Verlustquote nach Institut (12M-Kohorte)", loc="left")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.set_ylim(0, 112)
    _pct_axis(ax)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def collateral_coverage_chart(loss, path: Path) -> str:
    data = loss.collateral_by_bank.copy()
    if data.empty:
        return _empty_chart("Besicherungsquote nach Institut", path)
    x = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.bar(x, data["secured_ead_share"] * 100, color=SPARKASSE_DARK, width=0.55, label="Besicherter EAD-Anteil")
    ax.bar(x, (1 - data["secured_ead_share"]) * 100, bottom=data["secured_ead_share"] * 100, color=SPARKASSE_RED, width=0.55, label="Unbesicherter EAD-Anteil")
    ax.set_xticks(x)
    ax.set_xticklabels(data["bank_id"])
    ax.set_ylabel("Anteil des aktuellen EAD")
    ax.set_ylim(0, 100)
    ax.set_title("Besicherung des aktuellen EAD (nach Haircuts, gedeckelt)", loc="left")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    _pct_axis(ax)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def recovery_curve_chart(loss, path: Path) -> str:
    data = loss.recovery_curve.copy()
    if data.empty:
        return _empty_chart("Kumulierte Verwertungskurve", path)
    fig, ax = plt.subplots(figsize=(7.2, 3.1))
    ax.plot(data["months_since_default"], data["cumulative_recovery_rate"] * 100, color=SPARKASSE_RED, linewidth=2.2)
    ax.fill_between(data["months_since_default"], data["cumulative_recovery_rate"] * 100, color=SPARKASSE_RED, alpha=0.10)
    ax.set_xlabel("Monate seit Ausfall")
    ax.set_ylabel("Anteil des Kohorten-EAD")
    ax.set_title("Kumulierte beobachtete Verwertungskurve", loc="left")
    ax.set_xlim(0, max(1, int(data["months_since_default"].max())))
    ax.set_ylim(0, max(5, data["cumulative_recovery_rate"].max() * 110))
    _pct_axis(ax)
    return _finish(fig, path)


def recovery_distribution_chart(loss, path: Path) -> str:
    data = loss.recovery_distribution.copy()
    if data.empty or data["default_count"].sum() == 0:
        return _empty_chart("Verteilung der Verwertungsquoten", path)
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.bar(data["recovery_bucket"].astype(str), data["default_count"], color=SPARKASSE_DARK, width=0.6)
    ax.set_ylabel("Ausfälle")
    ax.set_xlabel("Verwertungsquoten-Segment")
    ax.set_title("Verteilung der Verwertungsquoten auf Positionsebene", loc="left")
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def cashflow_trend_chart(loss, path: Path) -> str:
    data = loss.cashflow_by_quarter.copy()
    if data.empty:
        return _empty_chart("Verlauf der Verwertungszahlungen", path)
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.bar(data["payment_period"], data["recovered_amount"] / 1_000_000, color=SPARKASSE_RED, width=0.6)
    ax.set_ylabel("Verwertungen (Mio. EUR)")
    ax.set_xlabel("Zahlungsquartal")
    ax.set_title("Beobachtete Verwertungszahlungen nach Zahlungsquartal", loc="left")
    ax.tick_params(axis="x", rotation=35)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda value, _: f"{value:g}".replace(".", ",")))
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def quality_by_bank_chart(quality, path: Path) -> str:
    data = quality.by_bank.copy()
    if data.empty:
        return _empty_chart("Datenqualitäts-Score nach Institut", path)
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    colors = [GREEN if value >= 97 else AMBER if value >= 90 else SPARKASSE_RED for value in data["quality_score"]]
    bars = ax.bar(data["bank_id"], data["quality_score"], color=colors, width=0.55)
    ax.set_ylim(0, 104)
    ax.set_ylabel("Bestehensquote der Datensätze (%)")
    ax.set_title("Datenqualitäts-Score nach Institut", loc="left")
    for bar, value in zip(bars, data["quality_score"]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.2, _de(value) + " %", ha="center", fontsize=8)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)


def migration_heatmap(rating, path: Path) -> str:
    matrix = rating.migration.matrix_pct
    if matrix.empty or matrix.to_numpy().sum() == 0:
        return _empty_chart("Ratingmigrationsmatrix", path)
    fig, ax = plt.subplots(figsize=(4.8, 4.0))
    data = matrix.to_numpy(dtype=float) * 100
    image = ax.imshow(data, cmap="Reds", vmin=0, vmax=max(1, data.max()))
    ax.set_xticks(range(matrix.shape[1]))
    ax.set_xticklabels(matrix.columns)
    ax.set_yticks(range(matrix.shape[0]))
    ax.set_yticklabels(matrix.index)
    ax.set_xlabel("Rating am Ende")
    ax.set_ylabel("Rating zu Beginn")
    ax.set_title("Ratingmigration 12M (% der Zeile)", loc="left")
    for row in range(data.shape[0]):
        for column in range(data.shape[1]):
            value = data[row, column]
            if value >= 0.5:
                ax.text(column, row, _de(value, 0), ha="center", va="center", fontsize=7, color="white" if value > 45 else SPARKASSE_DARK)
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    ax.grid(False)
    return _finish(fig, path)


def benchmark_chart(benchmark_detail: pd.DataFrame, metric_id: str, path: Path) -> str:
    # Ein fehlendes Benchmark-Ergebnis ergibt einen spaltenlosen leeren DataFrame.
    if benchmark_detail is None or benchmark_detail.empty or "metric_id" not in benchmark_detail.columns:
        return _empty_chart("Vergleichsgruppen-Benchmark", path)
    data = benchmark_detail[benchmark_detail["metric_id"] == metric_id].copy()
    if data.empty:
        return _empty_chart("Vergleichsgruppen-Benchmark", path)
    data = data.sort_values("bank_value", ascending=False)
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    x = np.arange(len(data))
    ax.bar(x, data["bank_value"] * 100, color=SPARKASSE_RED, width=0.5, label="Institut")
    ax.scatter(x, data["peer_value"] * 100, color=SPARKASSE_DARK, zorder=3, label="Vergleichsgruppen-Aggregat", marker="D", s=38)
    ax.set_xticks(x)
    ax.set_xticklabels(data["bank_id"])
    ax.set_ylabel("Quote")
    ax.set_title(f"Vergleichsgruppen-Benchmark: {data.iloc[0]['metric_name']}", loc="left")
    ax.legend(frameon=False, fontsize=8)
    _pct_axis(ax)
    ax.grid(axis="x", visible=False)
    return _finish(fig, path)
