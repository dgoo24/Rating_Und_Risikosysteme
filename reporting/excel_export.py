"""Excel-Arbeitsmappen-Export mit reproduzierbarer Formatierung.

Tabellenblätter, Titel, Hinweise und Spaltenüberschriften sind deutsch; die
Spaltenüberschriften werden über ``COLUMN_LABELS`` aus den technischen
(englischen) Spaltennamen abgeleitet. Zahlenformate folgen der im Excel des
Betrachters eingestellten Landeseinstellung.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.collateral_haircuts import COLLATERAL_HAIRCUTS
from config.rating_pd_mapping import RATING_PD_DESCRIPTION, RATING_PD_MAPPING
from config.settings import DISCLAIMER
from reporting.context import ReportContext


def _is_percent_column(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("rate", "share", "pct", "percent", "coverage", "pd_", "ratio", "haircut"))


def _is_amount_column(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("ead", "amount", "value", "recover", "loss", "numerator", "denominator"))


def _is_count_column(column: str) -> bool:
    lowered = column.lower()
    return any(token in lowered for token in ("count", "exposures", "items", "batches", "records", "findings", "days", "rank", "peer_count"))


# Deutsche Anzeigename für die technischen (englischen) Spaltennamen der
# Analyserahmen. Nicht aufgeführte Spalten behalten ihren Rohnamen.
COLUMN_LABELS: dict[str, str] = {
    # Allgemeine Hilfsspalten
    "item": "Angabe",
    "value": "Wert",
    "note": "Erläuterung",
    "assumption": "Annahme",
    "status": "Status",
    "reason": "Begründung",
    # Identifikatoren und Dimensionen
    "bank_id": "Institut",
    "bank_name": "Institutsname",
    "peer_group": "Vergleichsgruppe",
    "industry_sector": "Wirtschaftssektor",
    "product_type": "Produktart",
    "collateral_type": "Sicherheitenart",
    "primary_collateral_type": "Primäre Sicherheitsart",
    "recovery_type": "Verwertungsart",
    "dataset_type": "Datensatz",
    "rating_grade": "Rating",
    "rating_at_default": "Rating bei Ausfall",
    "base_rating": "Basisrating",
    "severity": "Schweregrad",
    "category": "Kategorie",
    # Datumsangaben
    "reporting_date": "Berichtsstichtag",
    "snapshot_date": "Stichtag",
    "observation_start": "Beobachtungsbeginn",
    "observation_end": "Beobachtungsende",
    "window_start": "Fensterbeginn",
    "window_end": "Fensterende",
    "window_months": "Fenster (Monate)",
    "start_date": "Beginn",
    "end_date": "Ende",
    "valuation_date": "Bewertungsdatum",
    "valuation_age_years": "Bewertungsalter (Jahre)",
    "payment_period": "Zahlungsquartal",
    "default_quarter": "Ausfallquartal",
    "first_payment_date": "Erste Zahlung",
    "last_payment_date": "Letzte Zahlung",
    "generated_at": "Erstellt am",
    "import_timestamp": "Importzeitpunkt",
    "execution_timestamp": "Prüfzeitpunkt",
    "quarantined_at": "In Quarantäne seit",
    # Ratingverteilung und PD
    "exposure_count": "Positionen",
    "ead": "EAD",
    "share_count": "Anteil (Anzahl)",
    "share_ead": "Anteil EAD",
    "pd_rate": "PD 12M",
    "expected_default_ead": "Erwartetes Ausfall-EAD",
    "weighted_pd": "Gewichtete PD",
    # Ausfallquoten
    "base_exposures": "Basispositionen",
    "base_ead": "Basis-EAD",
    "default_count": "Ausfälle",
    "default_ead": "Ausfall-EAD",
    "observed_default_rate": "Beobachtete Ausfallquote",
    "observed_default_rate_ead": "Beobachtete Ausfallquote (EAD)",
    "model_pd_weighted": "Konfigurierte PD (gewichtet)",
    "model_pd_12m": "Modell-PD 12M",
    # Ratingmigration
    "matched_count": "Übereinstimmend",
    "entries": "Zugänge",
    "exits": "Abgänge",
    "upgrades": "Hochstufungen",
    "downgrades": "Herabstufungen",
    "unchanged": "Unverändert",
    "upgrade_rate": "Hochstufungsquote",
    "downgrade_rate": "Herabstufungsquote",
    "base_count": "Beobachtungen zu Beginn",
    "target_count": "Beobachtungen am Ende",
    # Verlust und Verwertung
    "ead_at_default": "EAD im Ausfall",
    "total_recoveries": "Verwertungen",
    "recoveries": "Verwertungen",
    "recovered_amount": "Verwerteter Betrag",
    "recovery_count": "Zahlungsströme",
    "cashflow_count": "Zahlungsströme",
    "recovery_rate": "Verwertungsquote",
    "loss_amount": "Verlustbetrag",
    "loss_rate": "Verlustquote",
    "average_recovery_rate": "Ø Verwertungsquote",
    "recovery_bucket": "Verwertungsquoten-Segment",
    "loss_bucket": "Verlustquoten-Segment",
    "zero_recovery_share": "Anteil ohne Verwertung",
    "months_since_default": "Monate seit Ausfall",
    "cumulative_recoveries": "Kumulierte Verwertungen",
    "cumulative_recovery_rate": "Kumulierte Verwertungsquote",
    "cumulative_share": "Kumulierter Anteil",
    "share_amount": "Betragsanteil",
    "average_amount": "Ø Betrag",
    "average_days": "Ø Tage",
    "average_days_to_payment": "Ø Tage bis Zahlung",
    "weighted_average_days": "Gewichteter Ø Verzug (Tage)",
    "time_to_recovery_bucket": "Zeit bis zur ersten Verwertung",
    "share": "Anteil",
    "count": "Anzahl",
    # Sicherheiten
    "collateral_items": "Sicherheitenpositionen",
    "collateral_value": "Sicherheitenwert",
    "total_collateral_value": "Sicherheitenwert gesamt",
    "adjusted_collateral_value": "Adjustierter Wert",
    "haircut_reduction": "Haircut-Abschlag",
    "haircut": "Haircut",
    "average_haircut": "Ø Haircut",
    "share_value": "Wertanteil",
    "share_adjusted_value": "Anteil (adjustiert)",
    "secured_ead": "Besichertes EAD",
    "secured_ead_share": "Besicherter EAD-Anteil",
    "coverage_ratio": "Besicherungsquote",
    "unsecured_ead": "Unbesichertes EAD",
    "total_adjusted_collateral": "Adjustierter Sicherheitenwert gesamt",
    "stale_items": "Veraltete Bewertungen",
    # Benchmarking
    "metric_id": "Kennzahl-ID",
    "metric_name": "Kennzahl",
    "module": "Modul",
    "unit": "Einheit",
    "higher_is_better": "Höher ist besser",
    "description": "Definition",
    "bank_value": "Institutswert",
    "peer_value": "Vergleichsgruppenwert",
    "peer_median": "Median der Vergleichsgruppe",
    "portfolio_value": "Community-Wert",
    "gap": "Abstand",
    "relative_gap": "Relativer Abstand",
    "rank_in_peer_group": "Rang in der Vergleichsgruppe",
    "portfolio_rank": "Rang (Community)",
    "performance_flag": "Vergleichsgruppen-Flag",
    "portfolio_performance_flag": "Community-Flag",
    "peer_count": "Mitgliederzahl",
    # Datenqualität
    "rule_id": "Regel",
    "rule_name": "Regelname",
    "findings": "Befunde",
    "affected_records": "Betroffene Datensätze",
    "batches": "Batches",
    "rows_received": "Empfangene Zeilen",
    "rows_valid": "Gültige Zeilen",
    "rows_rejected": "Abgelehnte Zeilen",
    "quality_score": "Qualitäts-Score",
    "error_findings": "Fehlerbefunde",
    "warning_findings": "Warnbefunde",
    "quarantined_records": "Quarantäne-Datensätze",
    # Prüffelder
    "field_name": "Feld",
    "failed_value": "Fehlerhafter Wert",
    "record_id": "Datensatz-ID",
    "batch_id": "Batch",
}


def _de_num(value: object, digits: int = 0) -> str:
    """Formatiert eine Zahl deutsch (Punkt als Tausender-, Komma als Dezimaltrenner)."""
    try:
        if value is None or pd.isna(value):
            return "k. A."
        text = f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "k. A."
    return text.replace(",", "\u00A7").replace(".", ",").replace("\u00A7", ".")


def _de_pct(value: object, digits: int = 2) -> str:
    try:
        if value is None or pd.isna(value):
            return "k. A."
        return _de_num(float(value) * 100, digits) + " %"
    except (TypeError, ValueError):
        return "k. A."


def _de_date(value: object) -> str:
    if value is None or pd.isna(value):
        return "k. A."
    try:
        return pd.Timestamp(value).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return str(value)


class ExcelWorkbook:
    def __init__(self, path: Path, context: ReportContext):
        self.path = path
        self.context = context
        self.writer = pd.ExcelWriter(path, engine="xlsxwriter", datetime_format="dd.mm.yyyy hh:mm", date_format="dd.mm.yyyy")
        self.workbook = self.writer.book
        self.formats = self._build_formats()
        self.workbook.set_properties(
            {
                "title": f"Risikoportfolio-Bericht {context.reporting_date.date()}",
                "subject": "Synthetisches Demonstrations-Risikoreporting",
                "author": "Automatisierte Risikoportfolio-Berichtspipeline",
                "company": "Fiktionale Sparkassen-Berichtsgemeinschaft",
                "comments": DISCLAIMER,
            }
        )

    def _build_formats(self) -> dict[str, object]:
        base = {"font_name": "Calibri", "font_size": 10, "valign": "top"}
        return {
            "title": self.workbook.add_format({**base, "bold": True, "font_size": 15, "font_color": "#1F2328"}),
            "subtitle": self.workbook.add_format({**base, "italic": True, "font_size": 9, "font_color": "#6B6B6B"}),
            "section": self.workbook.add_format({**base, "bold": True, "font_size": 11, "font_color": "#8C0011", "bg_color": "#FFF5F6"}),
            "header": self.workbook.add_format(
                {**base, "bold": True, "font_color": "white", "bg_color": "#E6001E", "border": 1, "border_color": "#E6001E", "text_wrap": True}
            ),
            "text": self.workbook.add_format({**base, "border": 1, "border_color": "#E3E5E8"}),
            "integer": self.workbook.add_format({**base, "num_format": "#,##0", "border": 1, "border_color": "#E3E5E8"}),
            "amount": self.workbook.add_format({**base, "num_format": "#,##0.00", "border": 1, "border_color": "#E3E5E8"}),
            "percent": self.workbook.add_format({**base, "num_format": "0.00%", "border": 1, "border_color": "#E3E5E8"}),
            "date": self.workbook.add_format({**base, "num_format": "dd.mm.yyyy", "border": 1, "border_color": "#E3E5E8"}),
            "note": self.workbook.add_format({**base, "italic": True, "font_color": "#6B6B6B", "text_wrap": True}),
            "disclaimer": self.workbook.add_format(
                {**base, "bold": True, "font_color": "#8C0011", "bg_color": "#FFF5F6", "border": 1, "border_color": "#F1C9CE", "text_wrap": True}
            ),
            "kpi_label": self.workbook.add_format({**base, "bold": True, "bg_color": "#F4F4F6", "border": 1, "border_color": "#E3E5E8"}),
            "kpi_value": self.workbook.add_format({**base, "border": 1, "border_color": "#E3E5E8"}),
        }

    def _sheet(self, name: str) -> None:
        self.writer.sheets[name] = self.workbook.add_worksheet(name)

    def _write_frame(self, sheet_name: str, title: str, frame: pd.DataFrame, note: str | None = None, start_row: int = 0) -> int:
        worksheet = self.writer.sheets.get(sheet_name)
        if worksheet is None:
            worksheet = self.workbook.add_worksheet(sheet_name)
            self.writer.sheets[sheet_name] = worksheet
        worksheet.write(start_row, 0, title, self.formats["title"])
        row = start_row + 1
        if note:
            worksheet.merge_range(row, 0, row, max(1, len(frame.columns) - 1), note, self.formats["note"])
            worksheet.set_row(row, 30)
            row += 1
        row += 1
        if frame is None or frame.empty:
            worksheet.write(row, 0, "Für diese Ansicht liegen keine Daten vor.", self.formats["note"])
            return row + 1
        display = frame.copy()
        headers = [COLUMN_LABELS.get(str(column), str(column)) for column in display.columns]
        for column_index, header in enumerate(headers):
            worksheet.write(row, column_index, header, self.formats["header"])
        for row_index, (_, values) in enumerate(display.iterrows(), start=row + 1):
            for column_index, column in enumerate(display.columns):
                value = values[column]
                if isinstance(value, (list, dict, tuple)):
                    value = str(value)
                if pd.isna(value):
                    worksheet.write_blank(row_index, column_index, None, self.formats["text"])
                elif isinstance(value, (pd.Timestamp,)) or pd.api.types.is_datetime64_any_dtype(display[column]):
                    worksheet.write_datetime(row_index, column_index, pd.Timestamp(value).to_pydatetime(), self.formats["date"])
                elif _is_percent_column(column) and isinstance(value, (int, float)):
                    worksheet.write_number(row_index, column_index, float(value), self.formats["percent"])
                elif _is_amount_column(column) and isinstance(value, (int, float)):
                    worksheet.write_number(row_index, column_index, float(value), self.formats["amount"])
                elif _is_count_column(column) and isinstance(value, (int, float)):
                    worksheet.write_number(row_index, column_index, float(value), self.formats["integer"])
                elif isinstance(value, (int, float, bool)):
                    worksheet.write(row_index, column_index, value, self.formats["text"])
                else:
                    worksheet.write(row_index, column_index, str(value), self.formats["text"])
        worksheet.freeze_panes(row + 1, 0)
        if len(display.columns) > 0:
            worksheet.autofilter(row, 0, row + len(display), len(display.columns) - 1)
        for column_index, (column, header) in enumerate(zip(display.columns, headers)):
            width = min(42, max(11, len(str(header)) + 2))
            if not display.empty:
                sample = display[column].astype(str).head(100)
                width = min(46, max(width, int(sample.str.len().max()) + 2))
            worksheet.set_column(column_index, column_index, width)
        return row + len(display) + 2

    def _write_kpis(self, sheet_name: str, title: str) -> None:
        worksheet = self.writer.sheets.get(sheet_name)
        if worksheet is None:
            worksheet = self.workbook.add_worksheet(sheet_name)
            self.writer.sheets[sheet_name] = worksheet
        worksheet.write(0, 0, title, self.formats["title"])
        worksheet.write(1, 0, DISCLAIMER, self.formats["disclaimer"])
        worksheet.merge_range(1, 0, 1, 4, DISCLAIMER, self.formats["disclaimer"])
        row = 3
        worksheet.write(row, 0, "Kennzahl", self.formats["header"])
        worksheet.write(row, 1, "Wert", self.formats["header"])
        worksheet.write(row, 2, "Auslegung / Definition", self.formats["header"])
        row += 1
        context = self.context
        rows = [
            ("Berichtsstichtag", _de_date(context.reporting_date), "Ausgewählter quartalsweiser Berichtsstichtag."),
            ("Institutsumfang", context.bank_name, "Gesamtansicht der Berichtsgemeinschaft oder einzelnes fiktives Institut."),
            ("Vergleichsgruppe", context.peer_group or "BERICHTSGEMEINSCHAFT", "Konfigurierte Demonstrations-Vergleichsgruppe."),
            ("Positionen im Bestand", _de_num(context.rating.kpis.get("exposure_count", 0)), "Positionen im aktuellen Quartalsstichtagsbestand."),
            ("Aktuelles EAD", f"{_de_num(context.rating.kpis.get('total_ead', 0))} EUR", "Summe der positiven Haftungsvolumina im aktuellen Bestand."),
            ("PD 12M (EAD-gewichtet)", _de_pct(context.rating.kpis.get("portfolio_pd", 0)), "Summe(EAD x konfigurierte PD) / Summe(EAD). Demonstrations-PD-Zuordnung."),
            ("Beobachtete Ausfallquote 12M", _de_pct(context.rating.kpis.get("default_rate_12m") or 0), "Ausfälle / performende Positionen zu Beobachtungsbeginn der 12M-Kohorte."),
            ("Investment-Grade-Anteil", _de_pct(context.rating.kpis.get("investment_grade_share") or 0), "EAD mit Rating A oder B / gültiges geratetes EAD gesamt."),
            ("Hochstufungsquote", _de_pct(context.rating.kpis.get("upgrade_rate") or 0), "Hochstufungen / übereinstimmende Ratingbeobachtungen zwischen den Migrationsdaten."),
            ("Herabstufungsquote", _de_pct(context.rating.kpis.get("downgrade_rate") or 0), "Herabstufungen / übereinstimmende Ratingbeobachtungen zwischen den Migrationsdaten."),
            ("Beobachtete Verwertungsquote 12M", _de_pct(context.loss.kpis.get("recovery_rate") or 0), "Verwertungszahlungen / EAD im Ausfall der 12M-Kohorte."),
            ("Beobachtete Verlustquote 12M", _de_pct(context.loss.kpis.get("loss_rate") or 0), "Verlustbetrag / EAD im Ausfall der 12M-Kohorte."),
            ("Besicherungsquote", _de_pct(context.loss.kpis.get("collateral_coverage") or 0), "Sicherheitenwert nach Haircuts / aktuelles EAD."),
            ("Besicherter EAD-Anteil", _de_pct(context.loss.kpis.get("secured_ead_share") or 0), "Besichertes EAD (auf Positionsebene gedeckelt) / aktuelles EAD."),
            ("Datenqualitäts-Score", f"{_de_num(context.quality.overall_score, 2)} %", "Gültige Datensätze / empfangene Datensätze über alle abgeschlossenen Batches."),
            ("Quarantäne-Datensätze", _de_num(context.quality.quarantined_records), "Durch Fehlerregeln abgelehnte und zur Prüfung vorgehaltene Datensätze."),
            ("Datenversion", str((context.data_version.get("pipeline_run") or {}).get("pipeline_run_id", "k. A.")), "Kennung des aktuellsten Pipeline-Laufs."),
        ]
        for label, value, definition in rows:
            worksheet.write(row, 0, label, self.formats["kpi_label"])
            worksheet.write(row, 1, value, self.formats["kpi_value"])
            worksheet.write(row, 2, definition, self.formats["text"])
            worksheet.merge_range(row, 2, row, 4, definition, self.formats["text"])
            row += 1
        worksheet.set_column(0, 0, 30)
        worksheet.set_column(1, 1, 24)
        worksheet.set_column(2, 4, 52)

    def build(self) -> Path:
        context = self.context
        self._write_kpis("Übersicht", f"Risikoportfolio-Überblick - {_de_date(context.reporting_date)}")

        assumptions = pd.DataFrame(
            [
                {"assumption": "Ratingskala", "value": "A, B, C, D, E, F", "note": "Fiktionale Demonstrationsskala."},
                *[
                    {"assumption": f"PD 12M - Rating {grade}", "value": value, "note": RATING_PD_DESCRIPTION}
                    for grade, value in RATING_PD_MAPPING.items()
                ],
                *[
                    {"assumption": f"Haircut - {collateral_type}", "value": value, "note": "Wird auf den letzten Sicherheitenwert vor der Besicherungsanalyse angewendet."}
                    for collateral_type, value in COLLATERAL_HAIRCUTS.items()
                ],
                {"assumption": "Ausfallkohorte", "value": "12 Monate", "note": "Ausfälle nach dem Beobachtungsbeginn-Stichtag bis zum Berichtsstichtag."},
                {"assumption": "Verwertungsbeobachtung", "value": "bis Berichtsstichtag", "note": "Es zählen nur Zahlungen am oder vor dem Berichtsstichtag."},
                {"assumption": "Verlustdefinition", "value": "EAD - Verwertungen", "note": "Nicht diskontierter beobachteter Verlust; keine indirekten Kosten."},
                {"assumption": "Qualitäts-Score", "value": "gültig / empfangen", "note": "Bestehensquote auf Datensatzebene, keine Maßzahl für Modellqualität."},
            ]
        )
        self._write_frame("Annahmen", "Konfigurierbare Demonstrationsannahmen", assumptions, "Alle Werte sind synthetisch und konfigurierbar; es handelt sich nicht um regulatorische Parameter.")

        self._write_frame(
            "Berichtsmetadaten",
            "Berichtsmetadaten und Datenversion",
            pd.DataFrame(
                [
                    {"item": "Erstellt am", "value": str(context.generated_at)},
                    {"item": "Berichtsstichtag", "value": _de_date(context.reporting_date)},
                    {"item": "Umfang", "value": context.bank_name},
                    {"item": "Vergleichsgruppe", "value": context.peer_group or "BERICHTSGEMEINSCHAFT"},
                    {"item": "Pipeline-Lauf", "value": str((context.data_version.get("pipeline_run") or {}).get("pipeline_run_id", "k. A."))},
                    {"item": "Abgeschlossene Batches", "value": context.data_version.get("batch_count", 0)},
                    {"item": "Empfangene Zeilen", "value": context.data_version.get("rows_received", 0)},
                    {"item": "Gültige Zeilen", "value": context.data_version.get("rows_valid", 0)},
                    {"item": "Abgelehnte Zeilen", "value": context.data_version.get("rows_rejected", 0)},
                    {"item": "Disclaimer", "value": DISCLAIMER},
                ]
            ),
            "Rückverfolgbarkeitsangaben aus den Aufnahme- und Pipeline-Prüftabellen.",
        )

        self._write_frame("Ratingverteilung", "Ratingverteilung und konfigurierter erwarteter Ausfall", context.rating.distribution)
        self._write_frame(
            "Ausfallquoten",
            "Beobachtete Ausfallquoten 12M",
            context.rating.default_summary,
            "Der Kohorten-Nenner ist die Menge der performenden Positionen im letzten Quartalsstichtag am oder vor dem Berichtsstichtag minus zwölf Monate.",
        )
        row = 0
        for title, frame in (
            ("Ausfallquote nach Rating", context.rating.default_by_rating),
            ("Ausfallquote nach Institut", context.rating.default_by_bank),
            ("Ausfallquote nach Sektor", context.rating.default_by_sector),
            ("Ausfallquoten-Verlauf", context.rating.default_trend),
        ):
            row = self._write_frame("Ausfallquoten", title, frame, start_row=row + 1)
        self._write_frame("PD-Details", "Details zur konfigurierten PD", context.rating.pd_by_rating)
        row = 0
        for title, frame in (
            ("PD nach Institut", context.rating.pd_by_bank),
            ("PD nach Sektor", context.rating.pd_by_sector),
            ("PD-Verlauf", context.rating.pd_trend),
        ):
            row = self._write_frame("PD-Details", title, frame, start_row=row + 1)

        migration_summary = pd.DataFrame([context.rating.migration.summary])
        self._write_frame(
            "Ratingmigration",
            "Zusammenfassung der Ratingmigration",
            migration_summary,
            "Zugänge und Abgänge werden gesondert ausgewiesen; die übereinstimmenden Zahlen bestimmen die Migrationsmatrix.",
        )
        row = self._write_frame(
            "Ratingmigration",
            "Migrationsmatrix - Anzahlen",
            context.rating.migration.matrix_counts.reset_index().rename(columns={"index": "base_rating"}),
            start_row=8,
        )
        row = self._write_frame(
            "Ratingmigration",
            "Migrationsmatrix - Zeilenprozente",
            context.rating.migration.matrix_pct.reset_index().rename(columns={"index": "base_rating"}),
            start_row=row + 1,
        )
        self._write_frame("Ratingmigration", "Migration nach Institut", context.rating.migration.by_bank, start_row=row + 1)

        loss_summary_frame = pd.DataFrame([context.loss.summary])
        self._write_frame(
            "Verlustübersicht",
            "Beobachtete Verlust- und Verwertungsübersicht",
            loss_summary_frame,
            "Verlust = EAD im Ausfall - beobachtete Verwertungen. Sicherheiten dienen der Besicherungsanalyse und werden nicht erneut abgezogen.",
        )
        row = self._write_frame("Verlustübersicht", "Verlust und Verwertung nach Institut", context.loss.by_bank, start_row=row + 1)
        self._write_frame("Verlustübersicht", "Verlustschwere-Bänder", context.loss.loss_severity, start_row=row + 1)
        self._write_frame("Verlustübersicht", "Verlustverteilung", context.loss.loss_distribution, start_row=row + 12)

        self._write_frame("Verwertungsquoten", "Verwertungsquote nach Rating bei Ausfall", context.loss.by_rating)
        row = 0
        for title, frame in (
            ("Verwertungsquote nach Produkt", context.loss.by_product),
            ("Verwertungsquote nach Sektor", context.loss.by_sector),
            ("Verwertungsquote nach Sicherheitsart", context.loss.by_collateral_type),
            ("Verwertungsquote nach Ausfallquartal", context.loss.recovery_by_default_quarter),
            ("Verteilung der Verwertungsquoten", context.loss.recovery_distribution),
        ):
            row = self._write_frame("Verwertungsquoten", title, frame, start_row=row + 1)

        self._write_frame("Sicherheiten", "Besicherungsquote nach Institut", context.loss.collateral_by_bank)
        row = 0
        for title, frame in (
            ("Besicherungsquote nach Rating", context.loss.collateral_by_rating),
            ("Besicherungsquote nach Produkt", context.loss.collateral_by_product),
            ("Besicherungsquote nach primärer Sicherheitsart", context.loss.collateral_by_primary_type),
            ("Sicherheitenmix und Haircut-Wirkung", context.loss.collateral_type_mix),
            ("Haircut-Vergleich", context.loss.haircut_comparison),
            ("Veraltete Sicherheitsbewertungen", context.loss.stale_collateral),
        ):
            row = self._write_frame("Sicherheiten", title, frame, start_row=row + 1)

        self._write_frame("Verwertungszahlungen", "Zusammenfassung der Verwertungszahlungen", pd.DataFrame([context.loss.cashflow_summary]))
        row = 0
        for title, frame in (
            ("Zahlungsströme nach Zahlungsquartal", context.loss.cashflow_by_quarter),
            ("Verwertungsart-Mix", context.loss.recovery_type_mix),
            ("Zeit bis zur ersten Verwertung", context.loss.time_to_recovery),
            ("Kumulierte Verwertungskurve", context.loss.recovery_curve),
            ("Verwertungsverzug nach Institut", context.loss.recovery_lag_by_bank),
        ):
            row = self._write_frame("Verwertungszahlungen", title, frame, start_row=row + 1)

        benchmark_context_note = (
            "Vergleichsgruppenwerte nutzen eine Zähler/Nenner-Aggregation über die Institutes der "
            "Vergleichsgruppe und schließen das Institut selbst aus. Die Schwelle für BETTER/WORSE-Flags "
            "liegt bei einem relativen Abstand von 10 %."
        )
        self._write_frame("Benchmarking", "Detailvergleich Institut vs. Vergleichsgruppe", context.benchmark_detail, benchmark_context_note)
        self._write_frame("Kennzahlendefinitionen", "Definitionen der Kennzahlen", self._metric_definitions(), start_row=0)

        self._write_frame("Datenqualität", "Datenqualität nach Institut", context.quality.by_bank)
        row = 0
        for title, frame in (
            ("Befunde nach Kategorie", context.quality.by_category),
            ("Befunde nach Regel", context.quality.by_rule),
            ("Quarantäne-Übersicht", context.quality.quarantine),
            ("Regelwerk", context.quality.catalog),
        ):
            row = self._write_frame("Datenqualität", title, frame, start_row=row + 1)

        self.writer.close()
        return self.path

    def _metric_definitions(self) -> pd.DataFrame:
        from benchmarking.aggregation import metric_catalog_frame

        return metric_catalog_frame()


def export_excel(context: ReportContext, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return ExcelWorkbook(path, context).build()
