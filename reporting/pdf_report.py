"""PDF-Berichterstellung mit ReportLab.

Der Bericht weist ausdrücklich auf den synthetischen Charakter der Daten und auf
Methodenentscheidungen hin. Er ist ein Demonstrationsartefakt, keine regulatorische
Einreichung und kein validierter Modellbericht. Alle Texte, Zahlen und Daten folgen
der deutschen Konvention; die Farbwelt orientiert sich am Sparkassenrot.
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

SPARKASSE_RED = colors.HexColor("#E6001E")
SPARKASSE_DEEP = colors.HexColor("#8C0011")
DARK = colors.HexColor("#1F2328")
GRAPHITE = colors.HexColor("#454957")
LIGHT = colors.HexColor("#F4F4F6")
MID = colors.HexColor("#E3E5E8")
MUTED = colors.HexColor("#6B6B6B")
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
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=24, leading=29, textColor=DARK, alignment=TA_LEFT, spaceAfter=8),
        "subtitle": ParagraphStyle("ReportSubtitle", parent=base["Normal"], fontName="Helvetica", fontSize=13, leading=17, textColor=MUTED, spaceAfter=6),
        "eyebrow": ParagraphStyle("Eyebrow", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=SPARKASSE_RED, spaceAfter=4),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=SPARKASSE_DEEP, spaceBefore=6, spaceAfter=7),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=DARK, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName="Helvetica", fontSize=8.8, leading=12.2, textColor=GRAPHITE, spaceAfter=5),
        "small": ParagraphStyle("Small", parent=base["BodyText"], fontName="Helvetica", fontSize=7.3, leading=9.6, textColor=MUTED, spaceAfter=3),
        "cell": ParagraphStyle("Cell", parent=base["BodyText"], fontName="Helvetica", fontSize=6.8, leading=8.4, textColor=GRAPHITE),
        "cell_bold": ParagraphStyle("CellBold", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=6.8, leading=8.4, textColor=DARK),
        "cell_white": ParagraphStyle("CellWhite", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=6.8, leading=8.4, textColor=WHITE),
        "disclaimer": ParagraphStyle("Disclaimer", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=9.2, textColor=SPARKASSE_DEEP, backColor=colors.HexColor("#FFF5F6"), borderColor=colors.HexColor("#F1C9CE"), borderWidth=0.6, borderPadding=5, spaceBefore=5, spaceAfter=7),
    }


def _de_num(value: object, digits: int = 2) -> str:
    """Formatiert eine Zahl deutsch (Punkt als Tausender-, Komma als Dezimaltrenner)."""
    try:
        if value is None or pd.isna(value):
            return "k. A."
        text = f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "k. A."
    return text.replace(",", "\u00A7").replace(".", ",").replace("\u00A7", ".")


def _fmt_pct(value: object, digits: int = 2) -> str:
    """Formatiert eine Ratio (0-1) als deutsche Prozentangabe."""
    try:
        if value is None or pd.isna(value):
            return "k. A."
        return _de_num(float(value) * 100, digits) + " %"
    except (TypeError, ValueError):
        return "k. A."


def _fmt_pct_raw(value: object, digits: int = 2) -> str:
    """Formatiert einen bereits in Prozent vorliegenden Wert deutsch."""
    try:
        if value is None or pd.isna(value):
            return "k. A."
        return _de_num(float(value), digits) + " %"
    except (TypeError, ValueError):
        return "k. A."


def _fmt_amount(value: object, digits: int = 0) -> str:
    return _de_num(value, digits)


def _fmt_int(value: object) -> str:
    try:
        if value is None or pd.isna(value):
            return "k. A."
        return _de_num(int(value), 0)
    except (TypeError, ValueError):
        return "k. A."


def _fmt_date(value: object) -> str:
    if value is None or pd.isna(value):
        return "k. A."
    try:
        return pd.Timestamp(value).strftime("%d.%m.%Y")
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
    header_color: colors.Color = SPARKASSE_RED,
) -> Table:
    """Baut eine kompakte Berichtstabelle.

    columns: Liste von (Quellspalte, Überschrift, Art, Breitengewicht)
    Art: text | int | amount | pct | date
    """
    if frame is None or frame.empty:
        return Paragraph("Für diese Ansicht liegen keine Daten vor.", _styles()["small"])
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
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
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
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
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
    result.append(HRFlowable(width="100%", thickness=0.8, color=SPARKASSE_RED, spaceBefore=1, spaceAfter=6))
    return result


def _on_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(MID)
    canvas.setLineWidth(0.5)
    canvas.line(LEFT_MARGIN, PAGE_HEIGHT - 12 * mm, PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 12 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(LEFT_MARGIN, PAGE_HEIGHT - 10 * mm, REPORT_SETTINGS.title + " | Synthetische Demonstration")
    canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 10 * mm, f"Berichtsstichtag {doc._reporting_date}")
    canvas.line(LEFT_MARGIN, 13 * mm, PAGE_WIDTH - RIGHT_MARGIN, 13 * mm)
    canvas.setFont("Helvetica-Bold", 6.2)
    canvas.setFillColor(SPARKASSE_DEEP)
    canvas.drawString(LEFT_MARGIN, 9.6 * mm, DISCLAIMER)
    canvas.setFont("Helvetica", 6.8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 5.8 * mm, f"Seite {doc.page}")
    canvas.restoreState()


def _cover(context: ReportContext, styles: dict[str, ParagraphStyle]) -> list[object]:
    banner = Table(
        [[_p("RISIKOPORTFOLIO-BERICHTSWESEN", styles["cell_white"])]],
        colWidths=[CONTENT_WIDTH],
        hAlign="LEFT",
    )
    banner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SPARKASSE_RED), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return [
        Spacer(1, 18 * mm),
        banner,
        Spacer(1, 10 * mm),
        Paragraph("Automatisiertes Risikoportfolio-Berichtswesen", styles["title"]),
        Paragraph(f"{context.bank_name}", styles["subtitle"]),
        Paragraph(f"Berichtsstichtag {_fmt_date(context.reporting_date)} | Vergleichsgruppe {context.peer_group or 'BERICHTSGEMEINSCHAFT'}", styles["body"]),
        Spacer(1, 10 * mm),
        Paragraph("Synthetischer Demonstrationsbericht", styles["eyebrow"]),
        Paragraph(
            "Dieser Bericht verbindet eine gemeinsam genutzte Plattform für Datenübernahme und "
            "Datenqualität mit zwei Fachmodulen: Rating & Scoring sowie Verlustschätzung. Es handelt "
            "sich um einen lauffähigen Prototyp, der ausschließlich auf fiktiven Sparkassen, "
            "Portfolios und Zahlungsströmen beruht.",
            styles["body"],
        ),
        Spacer(1, 6 * mm),
        _kpi_table(
            [
                ("Institutsumfang", context.bank_name, "Gesamtansicht der Berichtsgemeinschaft oder einzelnes fiktives Institut."),
                ("Aktuelles EAD", f"{_fmt_amount(context.rating.kpis.get('total_ead'))} EUR", "Positives Haftungsvolumen im Berichtsstichtagsbestand."),
                ("PD 12M (EAD-gewichtet)", _fmt_pct(context.rating.kpis.get("portfolio_pd")), "Konfigurierte Demonstrations-PD-Zuordnung, kein validiertes Modell."),
                ("Beobachtete Ausfallquote 12M", _fmt_pct(context.rating.kpis.get("default_rate_12m")), "Rückblickende 12-Monats-Kohorte."),
                ("Beobachtete Verwertungsquote 12M", _fmt_pct(context.loss.kpis.get("recovery_rate")), "Realisierte Verwertungszahlungen bis zum Berichtsstichtag."),
                ("Beobachtete Verlustquote 12M", _fmt_pct(context.loss.kpis.get("loss_rate")), "EAD im Ausfall abzüglich realisierter Verwertungen."),
                ("Datenqualitäts-Score", _fmt_pct_raw(context.quality.overall_score), "Gültige Datensätze / empfangene Datensätze über alle abgeschlossenen Batches."),
                ("Datenversion", str((context.data_version.get("pipeline_run") or {}).get("pipeline_run_id", "k. A.")), "Kennung des aktuellsten Pipeline-Laufs."),
            ]
        ),
        Spacer(1, 8 * mm),
        Paragraph(DISCLAIMER, styles["disclaimer"]),
        Paragraph(
            "Es wird keine reale Sparkasse, kein Kunde, kein Mitarbeiter und kein Portfolio abgebildet. "
            "Die Werte werden mit festem Seed und gesteuerten Datenqualitätsmängeln zu Demonstrationszwecken "
            "erzeugt. Der Bericht ist keine regulatorische Berichterstattung und darf nicht für "
            "Aufsichts-, Buchhaltungs- oder Kundenentscheidungen verwendet werden.",
            styles["small"],
        ),
        PageBreak(),
    ]


def _executive(context: ReportContext, chart_paths: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[object]:
    rating_kpis = context.rating.kpis
    loss_kpis = context.loss.kpis
    story: list[object] = []
    story.extend(_section_heading("1. Management-Zusammenfassung", "Ein Berichtsstichtag, zwei Fachmodule und eine gemeinsame Datenbasis."))
    story.append(
        Paragraph(
            f"Zum Stichtag {_fmt_date(context.reporting_date)} umfasst der ausgewählte Umfang "
            f"{_fmt_int(rating_kpis.get('exposure_count'))} Positionen mit einem Gesamthafungsvolumen (EAD) von {_fmt_amount(rating_kpis.get('total_ead'))} EUR. "
            f"Die EAD-gewichtete konfigurierte PD 12M beträgt {_fmt_pct(rating_kpis.get('portfolio_pd'))}. "
            f"Die beobachtete Ausfallquote der rückblickenden 12-Monats-Kohorte liegt bei {_fmt_pct(rating_kpis.get('default_rate_12m'))} "
            f"({_fmt_int(rating_kpis.get('default_count_12m'))} Ausfälle auf einer Basis von {_fmt_int(rating_kpis.get('base_exposures_12m'))} performenden Positionen). "
            f"Die bis zum Berichtsstichtag beobachtete Verwertung beträgt {_fmt_pct(loss_kpis.get('recovery_rate'))}; dies ergibt eine beobachtete "
            f"Verlustquote von {_fmt_pct(loss_kpis.get('loss_rate'))} auf ein EAD im Ausfall von {_fmt_amount(loss_kpis.get('ead_at_default'))} EUR. "
            f"Die Besicherungsquote des aktuellen EAD beträgt {_fmt_pct(loss_kpis.get('collateral_coverage'))}; "
            f"der besicherte EAD-Anteil liegt bei {_fmt_pct(loss_kpis.get('secured_ead_share'))}.",
            styles["body"],
        )
    )
    story.append(
        Paragraph(
            f"Die Datenqualität entspricht einer Bestehensquote von {_fmt_pct_raw(context.quality.overall_score)} über {context.quality.batches_completed} abgeschlossene Batches. "
            f"Es wurden {_fmt_int(context.quality.error_count)} Fehlerbefunde und {_fmt_int(context.quality.warning_count)} Warnbefunde erfasst; "
            f"{_fmt_int(context.quality.quarantined_records)} Datensätze verbleiben in Quarantäne und wurden nicht in die kuratierten Tabellen geladen. "
            "Warnungen verbleiben mit ihrem Regelbeleg in den kuratierten Daten, statt stillschweigend gelöscht zu werden.",
            styles["body"],
        )
    )
    story.append(
        _kpi_table(
            [
                ("Portfolio-PD 12M", _fmt_pct(rating_kpis.get("portfolio_pd")), "EAD-gewichtete konfigurierte PD."),
                ("Beobachtete Ausfallquote 12M", _fmt_pct(rating_kpis.get("default_rate_12m")), "Anzahlbasierte rückblickende Kohorte."),
                ("Investment-Grade-Anteil", _fmt_pct(rating_kpis.get("investment_grade_share")), "EAD mit Rating A oder B."),
                ("Hochstufungs- / Herabstufungsquote", f"{_fmt_pct(rating_kpis.get('upgrade_rate'))} / {_fmt_pct(rating_kpis.get('downgrade_rate'))}", "Übereinstimmende 12-Monats-Migration."),
                ("Verwertungsquote", _fmt_pct(loss_kpis.get("recovery_rate")), "Verwertungen / EAD im Ausfall."),
                ("Verlustquote", _fmt_pct(loss_kpis.get("loss_rate")), "Verlust / EAD im Ausfall."),
                ("Besicherungsquote", _fmt_pct(loss_kpis.get("collateral_coverage")), "Sicherheiten nach Haircuts / aktuelles EAD."),
                ("Qualitäts-Score", _fmt_pct_raw(context.quality.overall_score), "Gültige / empfangene Datensätze."),
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
    story.extend(_section_heading("2. Rating & Scoring", "Verteilung, konfigurierte PD 12M, beobachtete Ausfallquoten und Ratingmigration."))
    story.append(Paragraph("2.1 Ratingverteilung", styles["h2"]))
    story.append(
        _table(
            result.distribution,
            [
                ("rating_grade", "Rating", "text", "0.8"),
                ("exposure_count", "Positionen", "int", "1.0"),
                ("ead", "EAD (EUR)", "amount", "1.5"),
                ("share_count", "Anteil (Anzahl)", "pct", "1.0"),
                ("share_ead", "Anteil EAD", "pct", "1.0"),
                ("pd_rate", "PD 12M", "pct", "0.9"),
                ("expected_default_ead", "Erwartetes Ausfall-EAD", "amount", "1.4"),
            ],
        )
    )
    story.append(Spacer(1, 2.5 * mm))
    story.append(_image(chart_paths["pd_default"], max_width=CONTENT_WIDTH * 0.62, max_height=195))
    story.append(Paragraph("2.2 Beobachtete Ausfallquoten", styles["h2"]))
    story.append(
        Paragraph(
            "Die beobachtete Ausfallquote nutzt eine rückblickende 12-Monats-Kohorte. Der Nenner ist die Menge der performenden "
            "Positionen im letzten Quartalsstichtagsbestand am oder vor dem Berichtsstichtag minus zwölf Monaten. Ein Ausfall wird "
            "pro Position genau einmal gezählt, wenn das erste beobachtete Ausfalldatum nach diesem Beobachtungsbeginn und am oder "
            "vor dem Berichtsstichtag liegt. Die konfigurierte PD wird getrennt ausgewiesen und ist in diesem Prototyp nicht auf "
            "die beobachtete Quote kalibriert.",
            styles["body"],
        )
    )
    story.append(
        _table(
            result.default_by_rating,
            [
                ("rating_grade", "Rating", "text", "0.8"),
                ("base_exposures", "Basispositionen", "int", "1.1"),
                ("base_ead", "Basis-EAD", "amount", "1.5"),
                ("default_count", "Ausfälle", "int", "0.9"),
                ("default_ead", "Ausfall-EAD", "amount", "1.3"),
                ("observed_default_rate", "Beobachtete Quote", "pct", "1.0"),
                ("observed_default_rate_ead", "Quote (EAD)", "pct", "1.1"),
                ("model_pd_weighted", "Konfigurierte PD", "pct", "1.0"),
            ],
        )
    )
    story.append(Spacer(1, 2.5 * mm))
    story.append(
        _table(
            result.default_by_bank,
            [
                ("bank_id", "Institut", "text", "0.8"),
                ("base_exposures", "Basispositionen", "int", "1.1"),
                ("default_count", "Ausfälle", "int", "0.9"),
                ("observed_default_rate", "Beobachtete Quote", "pct", "1.0"),
                ("observed_default_rate_ead", "Quote (EAD)", "pct", "1.1"),
                ("model_pd_weighted", "Konfigurierte PD", "pct", "1.0"),
            ],
        )
    )
    story.append(Paragraph("2.3 Ratingmigration", styles["h2"]))
    summary = result.migration.summary
    story.append(
        Paragraph(
            f"Die Migration vergleicht {_fmt_date(summary.get('start_date'))} mit {_fmt_date(summary.get('end_date'))}. "
            f"{_fmt_int(summary.get('matched_count'))} Positionen sind übereinstimmend. "
            f"{_fmt_int(summary.get('entries'))} Zugänge und {_fmt_int(summary.get('exits'))} Abgänge werden gesondert ausgewiesen. "
            f"Die Hochstufungsquote beträgt {_fmt_pct(summary.get('upgrade_rate'))}; die Herabstufungsquote {_fmt_pct(summary.get('downgrade_rate'))}.",
            styles["body"],
        )
    )
    story.append(_image(chart_paths["migration"], max_width=CONTENT_WIDTH * 0.50, max_height=220))
    matrix = result.migration.matrix_pct.reset_index().rename(columns={"index": "base_rating"})
    matrix_columns = [("base_rating", "Von / nach", "text", "1.0")] + [
        (rating, rating, "pct", "0.9") for rating in result.migration.matrix_pct.columns
    ]
    story.append(_table(matrix, matrix_columns))
    story.append(PageBreak())
    return story


def _loss_section(context: ReportContext, chart_paths: dict[str, str], styles: dict[str, ParagraphStyle]) -> list[object]:
    result = context.loss
    story: list[object] = []
    story.extend(_section_heading("3. Verlustschätzung", "Beobachtete Verwertung, Verlustschwere, Besicherung und Zeitpunkt der Zahlungsströme."))
    story.append(
        Paragraph(
            f"Die beobachtete Ausfallkohorte umfasst {_fmt_int(result.kpis.get('default_count'))} Ausfälle mit einem EAD im Ausfall von "
            f"{_fmt_amount(result.kpis.get('ead_at_default'))} EUR. Der beobachtete Verlustbetrag beträgt {_fmt_amount(result.kpis.get('loss_amount'))} EUR. "
            "Sicherheiten fließen ausschließlich in die Besicherungsanalyse ein und werden nicht erneut vom Verlust abgezogen; "
            "eine Doppelzählung wird so vermieden. "
            f"Die beobachtete Verwertungsquote beträgt {_fmt_pct(result.kpis.get('recovery_rate'))}; die beobachtete Verlustquote {_fmt_pct(result.kpis.get('loss_rate'))}. "
            f"{_fmt_pct(result.kpis.get('zero_recovery_share'))} der Ausfälle weisen bis zum Berichtsstichtag keine beobachtete Verwertung auf.",
            styles["body"],
        )
    )
    story.append(_image(chart_paths["loss"], max_width=CONTENT_WIDTH * 0.62, max_height=195))
    story.append(Paragraph("3.1 Verwertung und Verlust nach Institut", styles["h2"]))
    story.append(
        _table(
            result.by_bank,
            [
                ("bank_id", "Institut", "text", "0.8"),
                ("default_count", "Ausfälle", "int", "0.9"),
                ("ead_at_default", "EAD im Ausfall", "amount", "1.4"),
                ("total_recoveries", "Verwertungen", "amount", "1.3"),
                ("recovery_rate", "Verwertungsquote", "pct", "1.0"),
                ("loss_amount", "Verlust", "amount", "1.3"),
                ("loss_rate", "Verlustquote", "pct", "1.0"),
            ],
        )
    )
    story.append(Paragraph("3.2 Verwertungsquote nach Rating bei Ausfall", styles["h2"]))
    story.append(
        _table(
            result.by_rating,
            [
                ("rating_at_default", "Rating", "text", "0.8"),
                ("default_count", "Ausfälle", "int", "0.9"),
                ("ead_at_default", "EAD im Ausfall", "amount", "1.4"),
                ("total_recoveries", "Verwertungen", "amount", "1.3"),
                ("recovery_rate", "Verwertungsquote", "pct", "1.0"),
                ("loss_rate", "Verlustquote", "pct", "1.0"),
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
    story.extend(_section_heading("4. Sicherheiten und Verwertungszahlungen", "Aktuelle Bewertungen, Haircuts, Besicherung, Zahlungstermine und kumulierte Verwertung."))
    story.append(
        Paragraph(
            f"Die Besicherungsquote beruht auf der letzten Bewertung am oder vor dem Berichtsstichtag. "
            f"Die konfigurierten Haircuts betragen 20 % für Immobilien, 5 % für Finanzsicherheiten und 40 % für übrige Sicherheiten. "
            f"Der adjustierte Sicherheitenwert beträgt {_fmt_amount(result.collateral_summary.get('total_adjusted_collateral'))} EUR; "
            f"der unbesicherte EAD-Betrag {_fmt_amount(result.collateral_summary.get('unsecured_ead'))} EUR. "
            f"{_fmt_int(result.collateral_summary.get('stale_items'))} aktuelle Sicherheitspositionen überschreiten die Alterswarnschwelle von drei Jahren für die Bewertung.",
            styles["body"],
        )
    )
    story.append(_image(chart_paths["collateral"], max_width=CONTENT_WIDTH * 0.60, max_height=190))
    story.append(Paragraph("4.1 Sicherheiten nach Institut", styles["h2"]))
    story.append(
        _table(
            result.collateral_by_bank,
            [
                ("bank_id", "Institut", "text", "0.8"),
                ("exposure_count", "Positionen", "int", "0.9"),
                ("ead", "Aktuelles EAD", "amount", "1.4"),
                ("total_collateral_value", "Sicherheitenwert", "amount", "1.4"),
                ("adjusted_collateral_value", "Adjustierter Wert", "amount", "1.4"),
                ("secured_ead_share", "Besicherter EAD-Anteil", "pct", "1.1"),
                ("coverage_ratio", "Besicherungsquote", "pct", "1.0"),
            ],
        )
    )
    story.append(Paragraph("4.2 Sicherheitenmix nach Art", styles["h2"]))
    story.append(
        _table(
            result.collateral_type_mix,
            [
                ("collateral_type", "Art", "text", "1.1"),
                ("collateral_items", "Positionen", "int", "0.8"),
                ("collateral_value", "Wert", "amount", "1.4"),
                ("adjusted_collateral_value", "Adjustiert", "amount", "1.4"),
                ("haircut_reduction", "Haircut-Abschlag", "amount", "1.4"),
                ("share_adjusted_value", "Anteil (adjustiert)", "pct", "1.0"),
            ],
        )
    )
    story.append(Paragraph("4.3 Zeitliche Struktur der Verwertungszahlungen", styles["h2"]))
    story.append(
        _table(
            result.cashflow_by_quarter.tail(8),
            [
                ("payment_period", "Zahlungsquartal", "text", "1.0"),
                ("cashflow_count", "Zahlungsströme", "int", "0.9"),
                ("recovered_amount", "Verwertet", "amount", "1.4"),
                ("share_amount", "Anteil", "pct", "0.9"),
                ("cumulative_share", "Kumulierter Anteil", "pct", "1.1"),
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
    story.extend(_section_heading("5. Vergleichsgruppen-Benchmarking", "Gewichtete Aggregation aus Zählern und Nennern, unter Ausschluss des Instituts aus seiner eigenen Vergleichsreferenz."))
    if detail.empty:
        story.append(Paragraph("Für diesen Umfang liegen keine Benchmark-Daten vor.", styles["body"]))
        story.append(PageBreak())
        return story
    key_metrics = ["PD_12M_WEIGHTED", "DEFAULT_RATE_12M", "RECOVERY_RATE_12M", "LOSS_RATE_12M", "COLLATERAL_COVERAGE"]
    story.append(
        Paragraph(
            "Vergleichsgruppenwerte werden aus summierten Zählern und Nennern berechnet, nicht als Durchschnitt der "
            "Institutsquoten. Das betrachtete Institut wird aus seiner eigenen Vergleichsgruppe ausgeschlossen. Relative "
            "Abstände über 10 % werden als BETTER oder WORSE gekennzeichnet, wenn die Kennzahl eine eindeutige Richtung "
            "besitzt; neutrale Anteilskennzahlen sind informativ.",
            styles["body"],
        )
    )
    if context.bank_id is not None:
        selected = detail[detail["metric_id"].isin(key_metrics)]
        story.append(
            _table(
                selected,
                [
                    ("metric_name", "Kennzahl", "text", "1.9"),
                    ("bank_value", "Institut", "pct", "0.9"),
                    ("peer_value", "VGrp.-Aggregat", "pct", "1.0"),
                    ("gap", "Abstand", "pct", "0.9"),
                    ("rank_in_peer_group", "Rang", "int", "0.7"),
                    ("performance_flag", "Flag", "text", "0.9"),
                ],
            )
        )
    else:
        pivot = detail[detail["metric_id"].isin(key_metrics)].pivot_table(
            index=["bank_id", "bank_name"], columns="metric_id", values="bank_value", aggfunc="first"
        ).reset_index()
        columns = [
            ("bank_id", "Institut", "text", "0.8"),
            ("PD_12M_WEIGHTED", "PD 12M", "pct", "0.9"),
            ("DEFAULT_RATE_12M", "Ausfallquote", "pct", "0.9"),
            ("RECOVERY_RATE_12M", "Verwertungsquote", "pct", "0.9"),
            ("LOSS_RATE_12M", "Verlustquote", "pct", "0.9"),
            ("COLLATERAL_COVERAGE", "Besicherung", "pct", "0.9"),
        ]
        story.append(_table(pivot, columns))
        story.append(Spacer(1, 3 * mm))
        flags = detail[detail["metric_id"].isin(key_metrics)].pivot_table(
            index=["bank_id", "bank_name"], columns="metric_id", values="performance_flag", aggfunc="first"
        ).reset_index()
        story.append(Paragraph("Richtungsabhängige Benchmark-Flags", styles["h2"]))
        story.append(
            _table(
                flags,
                [
                    ("bank_id", "Institut", "text", "0.8"),
                    ("PD_12M_WEIGHTED", "PD 12M", "text", "1.0"),
                    ("DEFAULT_RATE_12M", "Ausfall", "text", "1.0"),
                    ("RECOVERY_RATE_12M", "Verwertung", "text", "1.0"),
                    ("LOSS_RATE_12M", "Verlust", "text", "1.0"),
                    ("COLLATERAL_COVERAGE", "Besicherung", "text", "1.0"),
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
    story.extend(_section_heading("6. Datenqualität und Datenherkunft", "Validierte Datensätze, Fehlerquarantäne, Warnungen und Rückverfolgbarkeit der Pipeline."))
    story.append(
        Paragraph(
            f"Der Datenqualitäts-Score beträgt {_fmt_pct_raw(quality.overall_score)} (gültige / empfangene Datensätze). "
            f"{quality.batches_completed} Batches wurden abgeschlossen und {quality.batches_skipped} Duplikat-Batches übersprungen. "
            f"{_fmt_int(quality.error_count)} Fehlerbefunde und {_fmt_int(quality.warning_count)} Warnbefunde liegen in den Prüftabellen vor. "
            f"Die Quarantäne umfasst {_fmt_int(quality.quarantined_records)} Datensätze; diese wurden nicht in die kuratierten Analysetabellen geladen. "
            "Warnungen verbleiben mit ihrem Regelbeleg in den kuratierten Daten.",
            styles["body"],
        )
    )
    story.append(_image(chart_paths["quality"], max_width=CONTENT_WIDTH * 0.56, max_height=190))
    story.append(Paragraph("6.1 Qualität nach Institut", styles["h2"]))
    story.append(
        _table(
            quality.by_bank,
            [
                ("bank_id", "Institut", "text", "0.8"),
                ("batches", "Batches", "int", "0.8"),
                ("rows_received", "Empfangen", "int", "1.1"),
                ("rows_valid", "Gültig", "int", "1.1"),
                ("rows_rejected", "Abgelehnt", "int", "1.0"),
                ("quality_score", "Score", "pct", "0.9"),
                ("error_findings", "Fehler", "int", "0.8"),
                ("warning_findings", "Warnungen", "int", "0.9"),
            ],
        )
    )
    story.append(Paragraph("6.2 Wichtigste Datenqualitätsregeln", styles["h2"]))
    story.append(
        _table(
            quality.by_rule.head(12),
            [
                ("rule_id", "Regel", "text", "1.0"),
                ("rule_name", "Name", "text", "2.3"),
                ("severity", "Schweregrad", "text", "0.8"),
                ("findings", "Befunde", "int", "0.8"),
                ("affected_records", "Datensätze", "int", "0.9"),
            ],
        )
    )
    story.append(Paragraph("6.3 Datenherkunft und Batch-Prüfung", styles["h2"]))
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
                    ("bank_id", "Institut", "text", "0.8"),
                    ("dataset_type", "Datensatz", "text", "1.1"),
                    ("batches", "Batches", "int", "0.8"),
                    ("rows_received", "Empfangen", "int", "1.0"),
                    ("rows_valid", "Gültig", "int", "1.0"),
                    ("rows_rejected", "Abgelehnt", "int", "0.9"),
                    ("latest_import", "Letzter Import", "date", "1.0"),
                ],
            )
        )
    story.append(PageBreak())
    return story


def _methodology(context: ReportContext, styles: dict[str, ParagraphStyle]) -> list[object]:
    story: list[object] = []
    story.extend(_section_heading("7. Methodik und Annahmen", "Definitionen, die bewusst explizit sind, weil es sich um einen Demonstrationsprototyp handelt."))
    story.append(Paragraph("7.1 Gemeinsame Datenplattform", styles["h2"]))
    story.append(
        Paragraph(
            "Heterogene CSV-, Excel- und Quelldatenbankdateien werden auf kanonische Staging-Entitäten abgebildet. "
            "Vollständigkeits-, Eindeutigkeits-, Konsistenz- und Plausibilitätsregeln laufen vor dem kuratierten Laden. "
            "Fehlerdatensätze werden mit ihren Regel-IDs und dem Roh-JSON in Quarantäne gestellt; Warnungen verbleiben in "
            "den kuratierten Daten. Jeder Batch, jeder Qualitätsbefund und jeder Pipeline-Lauf ist über Datei-Hash und "
            "Importzeitstempel zur Quelle rückverfolgbar.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.2 Rating & Scoring", styles["h2"]))
    story.append(
        Paragraph(
            "Ratingverteilung und erwarteter Ausfall beruhen auf der konfigurierten, ausdrücklich fiktiven Rating-zu-PD-Zuordnung: "
            + ", ".join(f"{grade} {_fmt_pct(value, 1)}" for grade, value in RATING_PD_MAPPING.items())
            + f". {RATING_PD_DESCRIPTION} Beobachtete Ausfallquoten nutzen eine separate rückblickende 12-Monats-Kohorte und werden in diesem Prototyp nicht zur Kalibrierung der konfigurierten PD herangezogen. "
            "Die Migration vergleicht zwei Stichtagsbestände, weist Zugänge und Abgänge gesondert aus und verwendet übereinstimmende Positionen für die Übergangsmatrix.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.3 Verlustschätzung", styles["h2"]))
    story.append(
        Paragraph(
            "Das EAD im Ausfall ist der letzte verfügbare Positionsbestand am oder vor dem beobachteten Ausfalldatum. "
            "Verwertungen sind Zahlungsströme nach Ausfall und am oder vor dem Berichtsstichtag. Der Verlust ist das EAD im Ausfall abzüglich der realisierten Verwertungen. "
            "Es erfolgt keine Diskontierung, keine Berücksichtigung indirekter Bearbeitungskosten und keine Doppelzählung von Sicherheiten. "
            "Die Besicherungsquote nutzt die letzte Bewertung am oder vor dem Berichtsstichtag und die konfigurierten Haircuts "
            + ", ".join(f"{collateral_type} {_fmt_pct(value, 0)}" for collateral_type, value in COLLATERAL_HAIRCUTS.items())
            + ". Die Besicherung wird zur Einordnung ausgewiesen, nicht erneut vom Verlust abgezogen.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.4 Benchmarking", styles["h2"]))
    story.append(
        Paragraph(
            "Benchmark-Werte werden aus summierten Zählern und Nennern über die Institutes der Vergleichsgruppe berechnet. "
            "Das betrachtete Institut wird aus seiner eigenen Vergleichsreferenz ausgeschlossen. "
            "Konfigurierte Vergleichsgruppen: "
            + "; ".join(f"{group.peer_group} = {', '.join(group.members)}" for group in PEER_GROUPS.values())
            + ". Eine kleine Vergleichsgruppe bedeutet, dass die Vergleichsreferenz illustrativ und nicht statistisch belastbar ist.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.5 Datenqualitäts-Score", styles["h2"]))
    story.append(
        Paragraph(
            "Der Qualitäts-Score ist die Bestehensquote der Datensätze: 100 x gültige Datensätze / empfangene Datensätze über alle "
            "abgeschlossenen Batches. Er ist keine Aussage über Modellgüte, Kalibrierung oder regulatorische Eignung. "
            "Der Score wird je Batch berechnet und über Summen aggregiert, nicht durch Mittelung von Batch-Prozentwerten.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.6 Einschränkungen", styles["h2"]))
    story.append(
        Paragraph(
            "Dies ist ein lokaler DuckDB-Prototyp mit synthetischen Daten. Er hat keine echten externen Integrationen, kein "
            "Produktions-Identitätsmanagement, keine regulatorische Freigabe und keine validierten Kreditrisikomodelle. "
            "Die Vergleichsgruppen sind klein und illustrativ. "
            "Die konfigurierten PDs, Haircuts und Verlustannahmen sind ausschließlich Demonstrationsparameter. "
            "Eine Produktivumsetzung würde Modellvalidierung, Datenherkunftskontrollen, Zugriffsmanagement, Abstimmung, "
            "Backtesting, Prüfungsfreigabe sowie eine Enterprise-Datenbank-/BI-Landschaft erfordern.",
            styles["body"],
        )
    )
    story.append(Paragraph("7.7 Reproduzierbarkeit", styles["h2"]))
    story.append(
        Paragraph(
            "Synthetische Daten werden mit festem Seed und einem Generierungsmanifest erzeugt. "
            "Die Pipeline kann mit python synthetic_data/generate_data.py und anschließend "
            "python -m etl.pipeline --reset-db erneut ausgeführt werden. Berichte werden in der Tabelle report_log "
            "protokolliert und die Verteilung lokal simuliert.",
            styles["body"],
        )
    )
    story.append(PageBreak())
    return story


def _appendix(context: ReportContext, styles: dict[str, ParagraphStyle]) -> list[object]:
    story: list[object] = []
    story.extend(_section_heading("Anhang A. Berichtsprüfung", "Metadaten der erzeugten Artefakte und Disclaimer."))
    report_meta = pd.DataFrame(
        [
            {"item": "Berichtstitel", "value": f"{REPORT_SETTINGS.title} - {_fmt_date(context.reporting_date)}"},
            {"item": "Organisationsbezeichnung", "value": REPORT_SETTINGS.organisation_label},
            {"item": "Umfang", "value": context.bank_name},
            {"item": "Vergleichsgruppe", "value": context.peer_group or "BERICHTSGEMEINSCHAFT"},
            {"item": "Erstellt am", "value": str(context.generated_at)},
            {"item": "Pipeline-Lauf", "value": str((context.data_version.get("pipeline_run") or {}).get("pipeline_run_id", "k. A."))},
            {"item": "Abgeschlossene Batches", "value": _fmt_int(context.data_version.get("batch_count", 0))},
            {"item": "Empfangene Zeilen", "value": _fmt_int(context.data_version.get("rows_received", 0))},
            {"item": "Gültige Zeilen", "value": _fmt_int(context.data_version.get("rows_valid", 0))},
            {"item": "Abgelehnte Zeilen", "value": _fmt_int(context.data_version.get("rows_rejected", 0))},
            {"item": "Disclaimer", "value": DISCLAIMER},
        ]
    )
    story.append(_table(report_meta, [("item", "Angabe", "text", "0.9"), ("value", "Wert", "text", "2.4")], font_size=7.2))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(DISCLAIMER, styles["disclaimer"]))
    story.append(
        Paragraph(
            "Der Bericht wird aus synthetischen Demonstrationsdaten erzeugt. Er darf nicht als echter Sparkassen-Bericht, "
            "als regulatorische Einreichung, als validierte Modellausgabe oder als Kundenkommunikation dargestellt werden.",
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
            title=f"Risikoportfolio-Bericht {_fmt_date(context.reporting_date)} - {context.bank_name}",
            author="Automatisierte Risikoportfolio-Berichtspipeline",
            subject="Synthetischer Demonstrations-Risikobericht",
            creator="ReportLab",
        )
        doc._reporting_date = context.reporting_date.strftime("%d.%m.%Y")
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
