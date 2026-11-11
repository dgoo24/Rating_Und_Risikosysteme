"""PDF report generation with ReportLab.

The report is intentionally explicit about the synthetic nature of the data and
about methodology choices. It is a demonstration artefact, not a regulatory
submission or a validated model report.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from config.collateral_haircuts import COLLATERAL_HAIRCUTS
from config.peer_groups import PEER_GROUPS
from config.rating_pd_mapping import RATING_PD_DESCRIPTION, RATING_PD_MAPPING
from config.settings import DISCLAIMER, REPORT_SETTINGS
from reporting.charts import (
    benchmark_chart,
    cashflow_trend_chart,
    collateral_coverage_chart,
    loss_by_bank_chart,
    migration_heatmap,
    pd_vs_default_chart,
    quality_by_bank_chart,
    rating_distribution_chart,
    recovery_curve_chart,
    recovery_distribution_chart,
)
from reporting.context import ReportContext

NAVY = colors.HexColor("#17324d")
TEAL = colors.HexColor("#2a9d8f")
AMBER = colors.HexColor("#e9c46a")
CORAL = colors.HexColor("#e76f51")
LIGHT = colors.HexColor("#eef2f5")
MID = colors.HexColor("#d7e0e6")
MUTED = colors.HexColor("#5c6b73")
RED = colors.HexColor("#7f1d1d")
WHITE = colors.white

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 16 * mm
RIGHT_MARGIN = 16 * mm
TOP_MARGIN = 20 * mm
BOTTOM_MARGIN = 17 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=24, leading=29, textColor=NAVY, alignment=TA_LEFT, spaceAfter=8),
        "subtitle": ParagraphStyle("ReportSubtitle", parent=base["Normal"], fontName="Helvetica", fontSize=13, leading=17, textColor=MUTED, spaceAfter=6),
        "eyebrow": ParagraphStyle("Eyebrow", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=TEAL, spaceAfter=4),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=NAVY, spaceBefore=6, spaceAfter=7),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=NAVY, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName="Helvetica", fontSize=8.8, leading=12.2, textColor=NAVY, spaceAfter=5),
        "small": ParagraphStyle("Small", parent=base["BodyText"], fontName="Helvetica", fontSize=7.3, leading=9.6, textColor=MUTED, spaceAfter=3),
        "cell": ParagraphStyle("Cell", parent=base["BodyText"], fontName="Helvetica", fontSize=6.8, leading=8.4, textColor=NAVY),
        "cell_bold": ParagraphStyle("CellBold", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=6.8, leading=8.4, textColor=NAVY),
        "cell_white": ParagraphStyle("CellWhite", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=6.8, leading=8.4, textColor=WHITE),
        "disclaimer": ParagraphStyle("Disclaimer", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=9.2, textColor=RED, backColor=colors.HexColor("#fef2f2"), borderColor=colors.HexColor("#fecaca"), borderWidth=0.6, borderPadding=5, spaceBefore=5, spaceAfter=7),
    }


def _fmt_pct(value: object, digits: int = 2) -> str:
    try:
        if value is None or pd.isna(value):
            return "n/a"
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_amount(value: object, digits: int = 0) -> str:
    try:
        if value is None or pd.isna(value):
            return "n/a"
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_int(value: object) -> str:
    try:
        if value is None or pd.isna(value):
            return "n/a"
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_date(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError):
        return str(value)


def _p(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _image(path: str, max_width: float = CONTENT_WIDTH, max_height: float = 245) -> Image:
    with PILImage.open(path) as image:
        width, height = image.size
    ratio = height / width if width else 0.4
    draw_width = max_width
    draw_height = draw_width * ratio
    if draw_height > max_height:
        draw_height = max_height
        draw_width = draw_height / ratio
    return Image(path, width=draw_width, height=draw_height)


def _table(
    frame: pd.DataFrame,
    columns: list[tuple[str, str, str, str]] | None = None,
    max_rows: int | None = None,
    widths: list[float] | None = None,
    font_size: float = 6.8,
    header_color: colors.Color = NAVY,
) -> Table:
    """Build a compact report table.

    columns: list of (source_column, heading, kind, width_weight)
    kind: text | int | amount | pct | date
    """
    if frame is None or frame.empty:
        return Paragraph("No data available for this view.", _styles()["small"])
    if columns is None:
        columns = [(str(column), str(column), "text", "1") for column in frame.columns]
    if max_rows:
        frame = frame.head(max_rows)
    data = [[_p(heading, _styles()["cell_white"]) for _, heading, _, _ in columns]]
    for _, row in frame.iterrows():
        cells: list[Paragraph] = []
        for source, _, kind, _ in columns:
            value = row.get(source)
            if kind == "pct":
                text = _fmt_pct(value)
            elif kind == "amount":
                text = _fmt_amount(value)
            elif kind == "int":
                text = _fmt_int(value)
            elif kind == "date":
                text = _fmt_date(value)
            else:
                text = str(value) if value is not None and not pd.isna(value) else ""
            cells.append(_p(text, _styles()["cell"]))
        data.append(cells)
    if widths is None:
        weights = [float(column[3]) for column in columns]
        total = sum(weights) or 1
        widths = [CONTENT_WIDTH * weight / total for weight in weights]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, MID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, colors.HexColor("#f7f9fb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.2),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
    ]
    table.setStyle(TableStyle(style))
    return table


def _kpi_table(items: list[tuple[str, str, str]]) -> Table:
    rows = [[_p(label, _styles()["cell_bold"]), _p(value, _styles()["cell_bold"]), _p(note, _styles()["small"])] for label, value, note in items]
    table = Table(rows, colWidths=[CONTENT_WIDTH * 0.24, CONTENT_WIDTH * 0.18, CONTENT_WIDTH * 0.58], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9fb")),
                ("BOX", (0, 0), (-1, -1), 0.4, MID),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, MID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _section_heading(title: str, subtitle: str | None = None) -> list[object]:
    result: list[object] = [Paragraph(escape(title), _styles()["h1"])]
    if subtitle:
        result.append(Paragraph(escape(subtitle), _styles()["small"]))
    result.append(HRFlowable(width="100%", thickness=0.8, color=TEAL, spaceBefore=1, spaceAfter=6))
    return result


def _on_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(MID)
    canvas.setLineWidth(0.5)
    canvas.line(LEFT_MARGIN, PAGE_HEIGHT - 12 * mm, PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(LEFT_MARGIN, PAGE_HEIGHT - 10 * mm, REPORT_SETTINGS.title + " | Synthetic demonstration")
    canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 10 * mm, f"Reporting date {doc._reporting_date}")
    canvas.line(LEFT_MARGIN, 13 * mm, PAGE_WIDTH - RIGHT_MARGIN, 13 * mm)
    canvas.setFont("Helvetica-Bold", 6.2)
    canvas.setFillColor(RED)
    canvas.drawString(LEFT_MARGIN, 9.6 * mm, DISCLAIMER)
    canvas.setFont("Helvetica", 6.8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 5.8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _cover(context: ReportContext, styles: dict[str, ParagraphStyle]) -> list[object]:
    banner = Table(
        [[_p("RISK PORTFOLIO REPORTING", styles["cell_white"])]],
        colWidths=[CONTENT_WIDTH],
        hAlign="LEFT",
    )
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return [
        Spacer(1, 18 * mm),
        banner,
        Spacer(1, 10 * mm),
        Paragraph("Automated risk portfolio reporting", styles["title"]),
        Paragraph(f"{context.bank_name}", styles["subtitle"]),
        Paragraph(f"Reporting date {context.reporting_date.date().isoformat()} | Peer group {context.peer_group or 'COMMUNITY'}", styles["body"]),
        Spacer(1, 10 * mm),
        Paragraph("Synthetic demonstration report", styles["eyebrow"]),
        Paragraph(
            "This report combines a shared ingestion and data-quality platform with two analytical modules: "
            "Rating & Scoring and Loss Estimation. It is a runnable prototype built exclusively on fictional "
            "Sparkassen, portfolios and cashflows.",
            styles["body"],
        ),
        Spacer(1, 6 * mm),
        _kpi_table(
            [
                ("Institution scope", context.bank_name, "Community view or single fictional institution."),
                ("Current EAD", f"{_fmt_amount(context.rating.kpis.get('total_ead'))} EUR", "Positive exposure at default in the reporting snapshot."),
                ("Exposure-weighted PD 12M", _fmt_pct(context.rating.kpis.get("portfolio_pd")), "Configured demonstration PD mapping, not a validated model."),
                ("Observed 12M default rate", _fmt_pct(context.rating.kpis.get("default_rate_12m")), "Backward-looking 12-month cohort."),
                ("Observed 12M recovery rate", _fmt_pct(context.loss.kpis.get("recovery_rate")), "Realised recovery cashflows through the reporting date."),
                ("Observed 12M loss rate", _fmt_pct(context.loss.kpis.get("loss_rate")), "EAD at default minus realised recoveries."),
                ("Data quality score", f"{context.quality.overall_score:.2f}%", "Valid records / received records across completed batches."),
                ("Data version", str((context.data_version.get("pipeline_run") or {}).get("pipeline_run_id", "n/a")), "Latest pipeline run identifier."),
            ]
        ),
        Spacer(1, 8 * mm),
        Paragraph(DISCLAIMER, styles["disclaimer"]),
        Paragraph(
            "No real Sparkasse, customer, employee or portfolio is represented. Values are generated with a fixed seed and "
            "controlled data-quality defects for demonstration. The report is not regulatory reporting and must not be used "
            "for supervisory, accounting or customer decisions.",
            styles["small"],
        ),
        PageBreak(),
    ]


def _executive(context: ReportContext, chart_paths: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[object]:
    rating_kpis = context.rating.kpis
    loss_kpis = context.loss.kpis
    story: list[object] = []
    story.extend(_section_heading("1. Executive overview", "One reporting date, two analytical modules and a shared data foundation."))
    story.append(
        Paragraph(
            f"At {context.reporting_date.date().isoformat()}, the selected scope contains "
            f"{_fmt_int(rating_kpis.get('exposure_count'))} exposures with total EAD of EUR {_fmt_amount(rating_kpis.get('total_ead'))}. "
            f"The exposure-weighted configured PD 12M is {_fmt_pct(rating_kpis.get('portfolio_pd'))}. "
            f"The observed 12-month default rate for the backward cohort is {_fmt_pct(rating_kpis.get('default_rate_12m'))} "
            f"({_fmt_int(rating_kpis.get('default_count_12m'))} defaults on a base of {_fmt_int(rating_kpis.get('base_exposures_12m'))} performing exposures). "
            f"Observed recovery through the reporting date is {_fmt_pct(loss_kpis.get('recovery_rate'))}, giving an observed "
            f"loss rate of {_fmt_pct(loss_kpis.get('loss_rate'))} on EAD at default of EUR {_fmt_amount(loss_kpis.get('ead_at_default'))}. "
            f"Collateral coverage of current EAD is {_fmt_pct(loss_kpis.get('collateral_coverage'))}; "
            f"the secured EAD share is {_fmt_pct(loss_kpis.get('secured_ead_share'))}.",
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            f"Data quality is {context.quality.overall_score:.2f}% record pass rate across {context.quality.batches_completed} completed batches. "
            f"{context.quality.error_count:,} error findings and {context.quality.warning_count:,} warning findings were recorded; "
            f"{context.quality.quarantined_records:,} records are retained in quarantine and were not loaded to curated tables. "
            "Warnings remain in curated data with their rule evidence, rather than being silently deleted.",
            styles["body"],
        )
    )
    story.append(
        _kpi_table(
            [
                ("Portfolio PD 12M", _fmt_pct(rating_kpis.get("portfolio_pd")), "Exposure-weighted configured PD."),
                ("Observed 12M default rate", _fmt_pct(rating_kpis.get("default_rate_12m")), "Count-based backward cohort."),
                ("Investment-grade share", _fmt_pct(rating_kpis.get("investment_grade_share")), "EAD rated A or B."),
                ("Upgrade / downgrade rate", f"{_fmt_pct(rating_kpis.get('upgrade_rate'))} / {_fmt_pct(rating_kpis.get('downgrade_rate'))}", "Matched 12-month migration."),
                ("Recovery rate", _fmt_pct(loss_kpis.get("recovery_rate")), "Recoveries / EAD at default."),
                ("Loss rate", _fmt_pct(loss_kpis.get("loss_rate")), "Loss / EAD at default."),
                ("Collateral coverage", _fmt_pct(loss_kpis.get("collateral_coverage")), "Haircut-adjusted collateral / current EAD."),
                ("Quality score", f"{context.quality.overall_score:.2f}%", "Valid / received records."),
            ]
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(_image(chart_paths["rating"], max_width=CONTENT_WIDTH * 0.58, max_height=190))
    story.append(_image(chart_paths["loss"], max_width=CONTENT_WIDTH * 0.58, max_height=190))
    story.append(PageBreak())
    return story


def _rating_section(context: ReportContext, chart_paths: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[object]:
    result = context.rating
    story: list[object] = []
    story.extend(_section_heading("2. Rating & Scoring", "Distribution, configured PD 12M, observed default rates and rating migration."))
    story.append(Paragraph("2.1 Rating distribution", styles["h2"]))
    story.append(
        _table(
            result.distribution,
            [
                ("rating_grade", "Rating", "text", "0.8"),
                ("exposure_count", "Exposures", "int", "1.0"),
                ("ead", "EAD (EUR)", "amount", "1.5"),
                ("share_count", "Share count", "pct", "1.0"),
                ("share_ead", "Share EAD", "pct", "1.0"),
                ("pd_rate", "PD 12M", "pct", "0.9"),
                ("expected_default_ead", "Expected default EAD", "amount", "1.4"),
            ],
        )
    )
    story.append(Spacer(1, 2.5 * mm))
    story.append(_image(chart_paths["pd_default"], max_width=CONTENT_WIDTH * 0.62, max_height=195))
    story.append(Paragraph("2.2 Observed default rates", styles["h2"]))
    story.append(
        Paragraph(
            "The observed default rate uses a 12-month backward cohort. The denominator is the set of performing exposures "
            "in the latest quarter snapshot on or before reporting date minus 12 months. A default is counted once per exposure "
            "when the first observed default date lies after that observation start and on or before the reporting date. "
            "The configured PD is shown separately and is not calibrated to the observed rate in this prototype.",
            styles["body"],
        )
    )
    story.append(
        _table(
            result.default_by_rating,
            [
                ("rating_grade", "Rating", "text", "0.8"),
                ("base_exposures", "Base exposures", "int", "1.1"),
                ("base_ead", "Base EAD", "amount", "1.5"),
                ("default_count", "Defaults", "int", "0.9"),
                ("default_ead", "Default EAD", "amount", "1.3"),
                ("observed_default_rate", "Observed rate", "pct", "1.0"),
                ("observed_default_rate_ead", "Observed rate (EAD)", "pct", "1.1"),
                ("model_pd_weighted", "Configured PD", "pct", "1.0"),
            ],
        )
    )
    story.append(Spacer(1, 2.5 * mm))
    story.append(
        _table(
            result.default_by_bank,
            [
                ("bank_id", "Bank", "text", "0.8"),
                ("base_exposures", "Base exposures", "int", "1.1"),
                ("default_count", "Defaults", "int", "0.9"),
                ("observed_default_rate", "Observed rate", "pct", "1.0"),
                ("observed_default_rate_ead", "Observed EAD rate", "pct", "1.1"),
                ("model_pd_weighted", "Configured PD", "pct", "1.0"),
            ],
        )
    )
    story.append(Paragraph("2.3 Rating migration", styles["h2"]))
    summary = result.migration.summary
    story.append(
        Paragraph(
            f"Migration compares {_fmt_date(summary.get('start_date'))} with {_fmt_date(summary.get('end_date'))}. "
            f"{_fmt_int(summary.get('matched_count'))} exposures are matched. "
            f"{_fmt_int(summary.get('entries'))} entries and {_fmt_int(summary.get('exits'))} exits are reported separately. "
            f"Upgrade rate is {_fmt_pct(summary.get('upgrade_rate'))}; downgrade rate is {_fmt_pct(summary.get('downgrade_rate'))}.",
            styles["body"],
        )
    )
    story.append(_image(chart_paths["migration"], max_width=CONTENT_WIDTH * 0.50, max_height=220))
    matrix = result.migration.matrix_pct.reset_index().rename(columns={"index": "base_rating"})
    matrix_columns = [("base_rating", "From / to", "text", "1.0")] + [
        (rating, rating, "pct", "0.9") for rating in result.migration.matrix_pct.columns
    ]
    story.append(_table(matrix, matrix_columns))
    story.append(PageBreak())
    return story


def _loss_section(context: ReportContext, chart_paths: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[object]:
    result = context.loss
    story: list[object] = []
    story.extend(_section_heading("3. Loss estimation", "Observed recovery, loss severity, collateral coverage and cashflow timing."))
    story.append(
        Paragraph(
            f"The observed default cohort covers {_fmt_int(result.kpis.get('default_count'))} defaults with EAD at default of "
            f"EUR {_fmt_amount(result.kpis.get('ead_at_default'))}. The observed loss amount is EUR {_fmt_amount(result.kpis.get('loss_amount'))}. "
            "Collateral is used only for coverage analysis and is not subtracted again from loss, preventing double counting. "
            f"Observed recovery rate is {_fmt_pct(result.kpis.get('recovery_rate'))}; observed loss rate is {_fmt_pct(result.kpis.get('loss_rate'))}. "
            f"{_fmt_pct(result.kpis.get('zero_recovery_share'))} of defaults have no observed recovery by the reporting date.",
            styles["body"],
        )
    )
    story.append(_image(chart_paths["loss"], max_width=CONTENT_WIDTH * 0.62, max_height=195))
    story.append(Paragraph("3.1 Recovery and loss by institution", styles["h2"]))
    story.append(
        _table(
            result.by_bank,
            [
                ("bank_id", "Bank", "text", "0.8"),
                ("default_count", "Defaults", "int", "0.9"),
                ("ead_at_default", "EAD at default", "amount", "1.4"),
                ("total_recoveries", "Recoveries", "amount", "1.3"),
                ("recovery_rate", "Recovery rate", "pct", "1.0"),
                ("loss_amount", "Loss", "amount", "1.3"),
                ("loss_rate", "Loss rate", "pct", "1.0"),
            ],
        )
    )
    story.append(Paragraph("3.2 Recovery rate by rating at default", styles["h2"]))
    story.append(
        _table(
            result.by_rating,
            [
                ("rating_at_default", "Rating", "text", "0.8"),
                ("default_count", "Defaults", "int", "0.9"),
                ("ead_at_default", "EAD at default", "amount", "1.4"),
                ("total_recoveries", "Recoveries", "amount", "1.3"),
                ("recovery_rate", "Recovery rate", "pct", "1.0"),
                ("loss_rate", "Loss rate", "pct", "1.0"),
            ],
        )
    )
    story.append(Spacer(1, 2.2 * mm))
    story.append(_image(chart_paths["recovery_distribution"], max_width=CONTENT_WIDTH * 0.55, max_height=180))
    story.append(PageBreak())
    return story


def _collateral_section(context: ReportContext, chart_paths: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[object]:
    result = context.loss
    story: list[object] = []
    story.extend(_section_heading("4. Collateral and recovery cashflows", "Latest valuations, haircuts, coverage, cashflow timing and cumulative recovery."))
    story.append(
        Paragraph(
            f"Collateral coverage is based on the latest valuation on or before the reporting date. "
            f"Configured haircuts are 20% for real estate, 5% for financial collateral and 40% for other collateral. "
            f"Total adjusted collateral is EUR {_fmt_amount(result.collateral_summary.get('total_adjusted_collateral'))}; "
            f"the unsecured EAD amount is EUR {_fmt_amount(result.collateral_summary.get('unsecured_ead'))}. "
            f"{_fmt_int(result.collateral_summary.get('stale_items'))} latest collateral items exceed the 3-year valuation age warning threshold.",
            styles["body"],
        )
    )
    story.append(_image(chart_paths["collateral"], max_width=CONTENT_WIDTH * 0.60, max_height=190))
    story.append(Paragraph("4.1 Collateral by institution", styles["h2"]))
    story.append(
        _table(
            result.collateral_by_bank,
            [
                ("bank_id", "Bank", "text", "0.8"),
                ("exposure_count", "Exposures", "int", "0.9"),
                ("ead", "Current EAD", "amount", "1.4"),
                ("total_collateral_value", "Collateral value", "amount", "1.4"),
                ("adjusted_collateral_value", "Adjusted value", "amount", "1.4"),
                ("secured_ead_share", "Secured EAD share", "pct", "1.1"),
                ("coverage_ratio", "Coverage", "pct", "1.0"),
            ],
        )
    )
    story.append(Paragraph("4.2 Collateral type mix", styles["h2"]))
    story.append(
        _table(
            result.collateral_type_mix,
            [
                ("collateral_type", "Type", "text", "1.1"),
                ("collateral_items", "Items", "int", "0.8"),
                ("collateral_value", "Value", "amount", "1.4"),
                ("adjusted_collateral_value", "Adjusted", "amount", "1.4"),
                ("haircut_reduction", "Haircut reduction", "amount", "1.4"),
                ("share_adjusted_value", "Share adjusted", "pct", "1.0"),
            ],
        )
    )
    story.append(Paragraph("4.3 Recovery cashflow timing", styles["h2"]))
    story.append(
        _table(
            result.cashflow_by_quarter.tail(8),
            [
                ("payment_period", "Payment period", "text", "1.0"),
                ("cashflow_count", "Cashflows", "int", "0.9"),
                ("recovered_amount", "Recovered", "amount", "1.4"),
                ("share_amount", "Share", "pct", "0.9"),
                ("cumulative_share", "Cumulative share", "pct", "1.1"),
            ],
        )
    )
    story.append(Spacer(1, 2.5 * mm))
    story.append(_image(chart_paths["recovery_curve"], max_width=CONTENT_WIDTH * 0.55, max_height=180))
    story.append(_image(chart_paths["cashflow"], max_width=CONTENT_WIDTH * 0.55, max_height=180))
    story.append(PageBreak())
    return story


def _benchmark_section(context: ReportContext, chart_paths: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[object]:
    detail = context.benchmark_detail
    story: list[object] = []
    story.extend(_section_heading("5. Peer benchmarking", "Numerator/denominator peer aggregation, excluding the institution from its own peer reference."))
    if detail.empty:
        story.append(Paragraph("No benchmark data available for this scope.", styles["body"]))
        story.append(PageBreak())
        return story
    key_metrics = ["PD_12M_WEIGHTED", "DEFAULT_RATE_12M", "RECOVERY_RATE_12M", "LOSS_RATE_12M", "COLLATERAL_COVERAGE"]
    story.append(
        Paragraph(
            "Peer values are calculated from summed numerators and denominators, not by averaging bank-level ratios. "
            "The bank under review is excluded from its own peer group. Relative differences above 10% are labelled "
            "BETTER or WORSE when the metric has an unambiguous direction; neutral rating-share metrics are informational.",
            styles["body"],
        )
    )
    if context.bank_id is not None:
        selected = detail[detail["metric_id"].isin(key_metrics)]
        story.append(
            _table(
                selected,
                [
                    ("metric_name", "Metric", "text", "1.9"),
                    ("bank_value", "Bank", "pct", "0.9"),
                    ("peer_value", "Peer aggregate", "pct", "1.0"),
                    ("gap", "Gap", "pct", "0.9"),
                    ("rank_in_peer_group", "Rank", "int", "0.7"),
                    ("performance_flag", "Flag", "text", "0.9"),
                ],
            )
        )
    else:
        pivot = detail[detail["metric_id"].isin(key_metrics)].pivot_table(
            index=["bank_id", "bank_name"], columns="metric_id", values="bank_value", aggfunc="first"
        ).reset_index()
        columns = [
            ("bank_id", "Bank", "text", "0.8"),
            ("PD_12M_WEIGHTED", "PD 12M", "pct", "0.9"),
            ("DEFAULT_RATE_12M", "Default rate", "pct", "0.9"),
            ("RECOVERY_RATE_12M", "Recovery rate", "pct", "0.9"),
            ("LOSS_RATE_12M", "Loss rate", "pct", "0.9"),
            ("COLLATERAL_COVERAGE", "Coverage", "pct", "0.9"),
        ]
        story.append(_table(pivot, columns))
        story.append(Spacer(1, 3 * mm))
        flags = detail[detail["metric_id"].isin(key_metrics)].pivot_table(
            index=["bank_id", "bank_name"], columns="metric_id", values="performance_flag", aggfunc="first"
        ).reset_index()
        story.append(Paragraph("Directional benchmark flags", styles["h2"]))
        story.append(
            _table(
                flags,
                [
                    ("bank_id", "Bank", "text", "0.8"),
                    ("PD_12M_WEIGHTED", "PD 12M", "text", "1.0"),
                    ("DEFAULT_RATE_12M", "Default", "text", "1.0"),
                    ("RECOVERY_RATE_12M", "Recovery", "text", "1.0"),
                    ("LOSS_RATE_12M", "Loss", "text", "1.0"),
                    ("COLLATERAL_COVERAGE", "Coverage", "text", "1.0"),
                ],
            )
        )
    story.append(Spacer(1, 3 * mm))
    story.append(_image(chart_paths["benchmark_pd"], max_width=CONTENT_WIDTH * 0.55, max_height=180))
    story.append(_image(chart_paths["benchmark_loss"], max_width=CONTENT_WIDTH * 0.55, max_height=180))
    story.append(PageBreak())
    return story


def _quality_section(context: ReportContext, chart_paths: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[object]:
    quality = context.quality
    story: list[object] = []
    story.extend(_section_heading("6. Data quality and lineage", "Validated records, error quarantine, warnings and pipeline traceability."))
    story.append(
        Paragraph(
            f"The data quality score is {quality.overall_score:.2f}% (valid records / received records). "
            f"{quality.batches_completed} batches completed and {quality.batches_skipped} duplicate batches were skipped. "
            f"{quality.error_count:,} error findings and {quality.warning_count:,} warning findings are available in the audit tables. "
            f"Quarantine holds {quality.quarantined_records:,} records; these were not loaded into curated analytical tables. "
            "Warnings are retained in curated data with their rule evidence.",
            styles["body"],
        )
    )
    story.append(_image(chart_paths["quality"], max_width=CONTENT_WIDTH * 0.56, max_height=190))
    story.append(Paragraph("6.1 Quality by institution", styles["h2"]))
    story.append(
        _table(
            quality.by_bank,
            [
                ("bank_id", "Bank", "text", "0.8"),
                ("batches", "Batches", "int", "0.8"),
                ("rows_received", "Received", "int", "1.1"),
                ("rows_valid", "Valid", "int", "1.1"),
                ("rows_rejected", "Rejected", "int", "1.0"),
                ("quality_score", "Score", "pct", "0.9"),
                ("error_findings", "Errors", "int", "0.8"),
                ("warning_findings", "Warnings", "int", "0.9"),
            ],
        )
    )
    story.append(Paragraph("6.2 Top data-quality rules", styles["h2"]))
    story.append(
        _table(
            quality.by_rule.head(12),
            [
                ("rule_id", "Rule", "text", "1.0"),
                ("rule_name", "Name", "text", "2.3"),
                ("severity", "Severity", "text", "0.8"),
                ("findings", "Findings", "int", "0.8"),
                ("affected_records", "Records", "int", "0.9"),
            ],
        )
    )
    story.append(Paragraph("6.3 Data lineage and batch audit", styles["h2"]))
    if not context.batches.empty:
        lineage = (
            context.batches.groupby(["bank_id", "dataset_type"], as_index=False)
            .agg(
                batches=("batch_id", "nunique"),
                rows_received=("rows_received", "sum"),
                rows_valid=("rows_valid", "sum"),
                rows_rejected=("rows_rejected", "sum"),
                latest_import=("import_timestamp", "max"),
            )
            .sort_values(["bank_id", "dataset_type"])
        )
        story.append(
            _table(
                lineage,
                [
                    ("bank_id", "Bank", "text", "0.8"),
                    ("dataset_type", "Dataset", "text", "1.1"),
                    ("batches", "Batches", "int", "0.8"),
                    ("rows_received", "Received", "int", "1.0"),
                    ("rows_valid", "Valid", "int", "1.0"),
                    ("rows_rejected", "Rejected", "int", "0.9"),
                    ("latest_import", "Latest import", "date", "1.0"),
                ],
            )
        )
    story.append(PageBreak())
    return story


def _methodology(context: ReportContext, styles: dict[str, ParagraphStyle]) -> list[object]:
    story: list[object] = []
    story.extend(_section_heading("7. Methodology and assumptions", "Definitions that are deliberately explicit because the prototype is a demonstration."))
    story.append(Paragraph("7.1 Shared data platform", styles["h2"]))
    story.append(
        Paragraph(
            "Heterogeneous CSV, Excel and source-database files are mapped into canonical staging entities. "
            "Completeness, uniqueness, consistency and plausibility rules run before curated loading. "
            "Error records are quarantined with their rule IDs and raw JSON; warnings are retained in curated data. "
            "Every batch, quality finding and pipeline run is traceable to a source file hash and import timestamp.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.2 Rating & Scoring", styles["h2"]))
    story.append(
        Paragraph(
            f"Rating distribution and expected default are based on the configured, explicitly fictional rating-to-PD mapping: "
            + ", ".join(f"{grade} {value:.1%}" for grade, value in RATING_PD_MAPPING.items())
            + f". {RATING_PD_DESCRIPTION} Observed default rates use a separate 12-month backward cohort and are not used to calibrate the configured PD in this prototype. "
            "Migration compares two snapshots, reports entries and exits separately and uses matched exposures for the transition matrix.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.3 Loss Estimation", styles["h2"]))
    story.append(
        Paragraph(
            "EAD at default is the latest available exposure snapshot on or before the observed default date. "
            "Recoveries are cashflows paid after default and on or before the reporting date. Loss is EAD at default minus realised recoveries. "
            "No discounting, indirect workout costs or collateral double counting are applied. "
            "Collateral coverage uses the latest valuation on or before the reporting date and configured haircuts "
            + ", ".join(f"{collateral_type} {value:.0%}" for collateral_type, value in COLLATERAL_HAIRCUTS.items())
            + ". Coverage is shown for context, not subtracted again from loss.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.4 Benchmarking", styles["h2"]))
    story.append(
        Paragraph(
            "Benchmark values are calculated from summed numerators and denominators across peer institutions. "
            "The institution under review is excluded from its own peer reference. "
            f"Configured peer groups: "
            + "; ".join(f"{group.peer_group} = {', '.join(group.members)}" for group in PEER_GROUPS.values())
            + ". A small peer group means the peer reference is illustrative rather than statistically robust.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.5 Data quality score", styles["h2"]))
    story.append(
        Paragraph(
            "The quality score is the record pass rate: 100 x valid records / received records across completed batches. "
            "It is not a measure of model accuracy, calibration or regulatory fitness. "
            "The score is computed per batch and aggregated by totals, not by averaging batch percentages.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.6 Limitations", styles["h2"]))
    story.append(
        Paragraph(
            "This is a local DuckDB prototype with synthetic data. It has no real external integrations, no production identity management, "
            "no regulatory sign-off and no validated credit-risk models. Peer groups are tiny and illustrative. "
            "The configured PDs, haircuts and loss assumptions are demonstration parameters only. "
            "A production implementation would require model validation, data-lineage controls, access management, "
            "reconciliation, backtesting, audit sign-off and an enterprise database/BI deployment.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.7 Reproducibility", styles["h2"]))
    story.append(
        Paragraph(
            "Synthetic data is generated with a fixed seed and a generation manifest. "
            "The pipeline can be rerun with python synthetic_data/generate_data.py followed by "
            "python -m etl.pipeline --reset-db. Reports are logged in the report_log table and distribution is simulated locally.",
            styles["body"],
        )
    )
    story.append(PageBreak())
    return story


def _appendix(context: ReportContext, styles: dict[str, ParagraphStyle]) -> list[object]:
    story: list[object] = []
    story.extend(_section_heading("Appendix A. Report audit", "Generated artefact metadata and disclaimer."))
    report_meta = pd.DataFrame(
        [
            {"item": "Report title", "value": f"{REPORT_SETTINGS.title} - {context.reporting_date.date()}"},
            {"item": "Organisation label", "value": REPORT_SETTINGS.organisation_label},
            {"item": "Scope", "value": context.bank_name},
            {"item": "Peer group", "value": context.peer_group or "COMMUNITY"},
            {"item": "Generated at", "value": str(context.generated_at)},
            {"item": "Pipeline run", "value": str((context.data_version.get("pipeline_run") or {}).get("pipeline_run_id", "n/a"))},
            {"item": "Batches completed", "value": context.data_version.get("batch_count", 0)},
            {"item": "Rows received", "value": context.data_version.get("rows_received", 0)},
            {"item": "Rows valid", "value": context.data_version.get("rows_valid", 0)},
            {"item": "Rows rejected", "value": context.data_version.get("rows_rejected", 0)},
            {"item": "Disclaimer", "value": DISCLAIMER},
        ]
    )
    story.append(_table(report_meta, [("item", "Item", "text", "0.9"), ("value", "Value", "text", "2.4")], font_size=7.2))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(DISCLAIMER, styles["disclaimer"]))
    story.append(
        Paragraph(
            "The report is generated from synthetic demonstration data. It must not be represented as a real Sparkasse report, "
            "a regulatory submission, a validated model output or a customer communication.",
            styles["small"],
        )
    )
    return story


def build_pdf_report(context: ReportContext, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    with tempfile.TemporaryDirectory(prefix="risk_report_charts_") as chart_dir:
        chart_root = Path(chart_dir)
        chart_paths = {
            "rating": rating_distribution_chart(context.rating, chart_root / "rating.png"),
            "pd_default": pd_vs_default_chart(context.rating, chart_root / "pd_default.png"),
            "migration": migration_heatmap(context.rating, chart_root / "migration.png"),
            "loss": loss_by_bank_chart(context.loss, chart_root / "loss.png"),
            "recovery_distribution": recovery_distribution_chart(context.loss, chart_root / "recovery_dist.png"),
            "collateral": collateral_coverage_chart(context.loss, chart_root / "collateral.png"),
            "recovery_curve": recovery_curve_chart(context.loss, chart_root / "recovery_curve.png"),
            "cashflow": cashflow_trend_chart(context.loss, chart_root / "cashflow.png"),
            "quality": quality_by_bank_chart(context.quality, chart_root / "quality.png"),
            "benchmark_pd": benchmark_chart(context.benchmark_detail, "PD_12M_WEIGHTED", chart_root / "benchmark_pd.png"),
            "benchmark_loss": benchmark_chart(context.benchmark_detail, "LOSS_RATE_12M", chart_root / "benchmark_loss.png"),
        }
        doc = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            leftMargin=LEFT_MARGIN,
            rightMargin=RIGHT_MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOTTOM_MARGIN,
            title=f"Risk Portfolio Report {context.reporting_date.date()} - {context.bank_name}",
            author="Automated Risk Portfolio Reporting Pipeline",
            subject="Synthetic demonstration risk report",
            creator="ReportLab",
        )
        doc._reporting_date = context.reporting_date.date().isoformat()
        story: list[object] = []
        story.extend(_cover(context, styles))
        story.extend(_executive(context, chart_paths, styles))
        story.extend(_rating_section(context, chart_paths, styles))
        story.extend(_loss_section(context, chart_paths, styles))
        story.extend(_collateral_section(context, chart_paths, styles))
        story.extend(_benchmark_section(context, chart_paths, styles))
        story.extend(_quality_section(context, chart_paths, styles))
        story.extend(_methodology(context, styles))
        story.extend(_appendix(context, styles))
        doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return path
