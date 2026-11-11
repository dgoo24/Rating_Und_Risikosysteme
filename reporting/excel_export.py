"""Excel workbook export with reproducible formatting."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.collateral_haircuts import COLLATERAL_HAIRCUTS
from config.institutions import INSTITUTIONS
from config.peer_groups import PEER_GROUPS
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


class ExcelWorkbook:
    def __init__(self, path: Path, context: ReportContext):
        self.path = path
        self.context = context
        self.writer = pd.ExcelWriter(path, engine="xlsxwriter", datetime_format="yyyy-mm-dd", date_format="yyyy-mm-dd")
        self.workbook = self.writer.book
        self.formats = self._build_formats()
        self.workbook.set_properties(
            {
                "title": f"Risk Portfolio Report {context.reporting_date.date()}",
                "subject": "Synthetic demonstration risk reporting",
                "author": "Automated Risk Portfolio Reporting Pipeline",
                "company": "Fictional Sparkassen Reporting Community",
                "comments": DISCLAIMER,
            }
        )

    def _build_formats(self) -> dict[str, object]:
        base = {"font_name": "Calibri", "font_size": 10, "valign": "top"}
        return {
            "title": self.workbook.add_format({**base, "bold": True, "font_size": 15, "font_color": "#17324d"}),
            "subtitle": self.workbook.add_format({**base, "italic": True, "font_size": 9, "font_color": "#5c6b73"}),
            "section": self.workbook.add_format({**base, "bold": True, "font_size": 11, "font_color": "#17324d", "bg_color": "#eef2f5"}),
            "header": self.workbook.add_format(
                {**base, "bold": True, "font_color": "white", "bg_color": "#17324d", "border": 1, "border_color": "#17324d", "text_wrap": True}
            ),
            "text": self.workbook.add_format({**base, "border": 1, "border_color": "#d7e0e6"}),
            "integer": self.workbook.add_format({**base, "num_format": "#,##0", "border": 1, "border_color": "#d7e0e6"}),
            "amount": self.workbook.add_format({**base, "num_format": "#,##0.00", "border": 1, "border_color": "#d7e0e6"}),
            "percent": self.workbook.add_format({**base, "num_format": "0.00%", "border": 1, "border_color": "#d7e0e6"}),
            "date": self.workbook.add_format({**base, "num_format": "yyyy-mm-dd", "border": 1, "border_color": "#d7e0e6"}),
            "note": self.workbook.add_format({**base, "italic": True, "font_color": "#5c6b73", "text_wrap": True}),
            "disclaimer": self.workbook.add_format(
                {**base, "bold": True, "font_color": "#7f1d1d", "bg_color": "#fef2f2", "border": 1, "border_color": "#fecaca", "text_wrap": True}
            ),
            "kpi_label": self.workbook.add_format({**base, "bold": True, "bg_color": "#f7f9fa", "border": 1, "border_color": "#d7e0e6"}),
            "kpi_value": self.workbook.add_format({**base, "border": 1, "border_color": "#d7e0e6"}),
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
            worksheet.write(row, 0, "No data available for this view.", self.formats["note"])
            return row + 1
        display = frame.copy()
        for column_index, column in enumerate(display.columns):
            worksheet.write(row, column_index, str(column), self.formats["header"])
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
        for column_index, column in enumerate(display.columns):
            width = min(42, max(11, len(str(column)) + 2))
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
        worksheet.write(row, 0, "Key indicator", self.formats["header"])
        worksheet.write(row, 1, "Value", self.formats["header"])
        worksheet.write(row, 2, "Interpretation / definition", self.formats["header"])
        row += 1
        context = self.context
        rows = [
            ("Reporting date", context.reporting_date.date().isoformat(), "Selected quarterly reporting date."),
            ("Institution scope", context.bank_name, "Community view or one fictional institution."),
            ("Peer group", context.peer_group or "COMMUNITY", "Configured demonstration peer group."),
            ("Current exposure count", f"{context.rating.kpis.get('exposure_count', 0):,}", "Exposures in the current quarter snapshot."),
            ("Current EAD", f"{context.rating.kpis.get('total_ead', 0):,.0f} EUR", "Sum of positive exposure at default in the current snapshot."),
            ("Exposure-weighted PD 12M", f"{context.rating.kpis.get('portfolio_pd', 0):.2%}", "Sum(EAD x configured PD) / Sum(EAD). Demonstration PD mapping."),
            ("Observed 12M default rate", f"{(context.rating.kpis.get('default_rate_12m') or 0):.2%}", "Defaults / performing exposures at the 12M observation start."),
            ("Investment-grade share", f"{(context.rating.kpis.get('investment_grade_share') or 0):.2%}", "EAD rated A or B / total valid rated EAD."),
            ("Upgrade rate", f"{(context.rating.kpis.get('upgrade_rate') or 0):.2%}", "Upgrades / matched rating observations between migration dates."),
            ("Downgrade rate", f"{(context.rating.kpis.get('downgrade_rate') or 0):.2%}", "Downgrades / matched rating observations between migration dates."),
            ("Observed 12M recovery rate", f"{(context.loss.kpis.get('recovery_rate') or 0):.2%}", "Recovery cashflows / EAD at default for the 12M cohort."),
            ("Observed 12M loss rate", f"{(context.loss.kpis.get('loss_rate') or 0):.2%}", "Loss amount / EAD at default for the 12M cohort."),
            ("Collateral coverage", f"{(context.loss.kpis.get('collateral_coverage') or 0):.2%}", "Haircut-adjusted collateral / current EAD."),
            ("Secured EAD share", f"{(context.loss.kpis.get('secured_ead_share') or 0):.2%}", "Secured EAD capped at exposure level / current EAD."),
            ("Data quality score", f"{context.quality.overall_score:.2f}%", "Valid records / received records across completed batches."),
            ("Quarantined records", f"{context.quality.quarantined_records:,}", "Records rejected by error-severity DQ rules and retained for review."),
            ("Data version", str((context.data_version.get('pipeline_run') or {}).get('pipeline_run_id', 'n/a')), "Latest pipeline run identifier."),
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
        self._write_kpis("Overview", f"Risk Portfolio Overview - {context.reporting_date.date()}")

        assumptions = pd.DataFrame(
            [
                {"assumption": "Rating scale", "value": "A, B, C, D, E, F", "note": "Fictional demonstration scale."},
                *[
                    {"assumption": f"PD 12M - rating {grade}", "value": value, "note": RATING_PD_DESCRIPTION}
                    for grade, value in RATING_PD_MAPPING.items()
                ],
                *[
                    {"assumption": f"Haircut - {collateral_type}", "value": value, "note": "Applied to latest collateral value before coverage analysis."}
                    for collateral_type, value in COLLATERAL_HAIRCUTS.items()
                ],
                {"assumption": "Default cohort", "value": "12 months", "note": "Defaults after the observation start snapshot through the reporting date."},
                {"assumption": "Recovery observation", "value": "through reporting date", "note": "Only cashflows paid on or before the reporting date are counted."},
                {"assumption": "Loss definition", "value": "EAD - recoveries", "note": "Undiscounted observed loss; no indirect costs."},
                {"assumption": "Quality score", "value": "valid / received", "note": "Record-level pass rate, not a model-quality measure."},
            ]
        )
        self._write_frame("Assumptions", "Configurable demonstration assumptions", assumptions, "All values are synthetic and configurable; they are not regulatory parameters.")

        self._write_frame(
            "Report_Metadata",
            "Report metadata and data version",
            pd.DataFrame(
                [
                    {"item": "Generated at", "value": str(context.generated_at)},
                    {"item": "Reporting date", "value": context.reporting_date.date().isoformat()},
                    {"item": "Scope", "value": context.bank_name},
                    {"item": "Peer group", "value": context.peer_group or "COMMUNITY"},
                    {"item": "Pipeline run", "value": str((context.data_version.get("pipeline_run") or {}).get("pipeline_run_id", "n/a"))},
                    {"item": "Batches completed", "value": context.data_version.get("batch_count", 0)},
                    {"item": "Rows received", "value": context.data_version.get("rows_received", 0)},
                    {"item": "Rows valid", "value": context.data_version.get("rows_valid", 0)},
                    {"item": "Rows rejected", "value": context.data_version.get("rows_rejected", 0)},
                    {"item": "Disclaimer", "value": DISCLAIMER},
                ]
            ),
            "Traceability information compiled from ingestion and pipeline audit tables.",
        )

        self._write_frame("Rating_Distribution", "Rating distribution and configured expected default", context.rating.distribution)
        self._write_frame(
            "Default_Rates",
            "Observed 12M default rates",
            context.rating.default_summary,
            "Cohort denominator is the set of performing exposures in the latest quarter snapshot on or before reporting date minus 12 months.",
        )
        row = 0
        for title, frame in (
            ("Default rate by rating", context.rating.default_by_rating),
            ("Default rate by institution", context.rating.default_by_bank),
            ("Default rate by sector", context.rating.default_by_sector),
            ("Default rate trend", context.rating.default_trend),
        ):
            row = self._write_frame("Default_Rates", title, frame, start_row=row + 1)
        self._write_frame("PD_Detail", "Configured PD detail", context.rating.pd_by_rating)
        row = 0
        for title, frame in (
            ("PD by institution", context.rating.pd_by_bank),
            ("PD by sector", context.rating.pd_by_sector),
            ("PD trend", context.rating.pd_trend),
        ):
            row = self._write_frame("PD_Detail", title, frame, start_row=row + 1)

        migration_summary = pd.DataFrame([context.rating.migration.summary])
        self._write_frame(
            "Rating_Migration",
            "Rating migration summary",
            migration_summary,
            "Entries and exits are reported separately; matched counts drive the migration matrix.",
        )
        row = self._write_frame(
            "Rating_Migration",
            "Migration matrix - counts",
            context.rating.migration.matrix_counts.reset_index().rename(columns={"index": "base_rating"}),
            start_row=8,
        )
        row = self._write_frame(
            "Rating_Migration",
            "Migration matrix - row percentages",
            context.rating.migration.matrix_pct.reset_index().rename(columns={"index": "base_rating"}),
            start_row=row + 1,
        )
        self._write_frame("Rating_Migration", "Migration by institution", context.rating.migration.by_bank, start_row=row + 1)

        loss_summary_frame = pd.DataFrame([context.loss.summary])
        self._write_frame(
            "Loss_Summary",
            "Observed loss and recovery summary",
            loss_summary_frame,
            "Loss = EAD at default - observed recoveries. Collateral is used for coverage, not subtracted again.",
        )
        row = self._write_frame("Loss_Summary", "Loss and recovery by institution", context.loss.by_bank, start_row=row + 1)
        self._write_frame("Loss_Summary", "Loss severity bands", context.loss.loss_severity, start_row=row + 1)
        self._write_frame("Loss_Summary", "Loss distribution", context.loss.loss_distribution, start_row=row + 12)

        self._write_frame("Recovery_Rates", "Recovery rate by rating at default", context.loss.by_rating)
        row = 0
        for title, frame in (
            ("Recovery rate by product", context.loss.by_product),
            ("Recovery rate by sector", context.loss.by_sector),
            ("Recovery rate by collateral type", context.loss.by_collateral_type),
            ("Recovery rate by default quarter", context.loss.recovery_by_default_quarter),
            ("Recovery distribution", context.loss.recovery_distribution),
        ):
            row = self._write_frame("Recovery_Rates", title, frame, start_row=row + 1)

        self._write_frame("Collateral", "Collateral coverage by institution", context.loss.collateral_by_bank)
        row = 0
        for title, frame in (
            ("Collateral coverage by rating", context.loss.collateral_by_rating),
            ("Collateral coverage by product", context.loss.collateral_by_product),
            ("Collateral coverage by primary collateral type", context.loss.collateral_by_primary_type),
            ("Collateral type mix and haircut impact", context.loss.collateral_type_mix),
            ("Haircut comparison", context.loss.haircut_comparison),
            ("Stale collateral valuations", context.loss.stale_collateral),
        ):
            row = self._write_frame("Collateral", title, frame, start_row=row + 1)

        self._write_frame("Recovery_Cashflows", "Recovery cashflow summary", pd.DataFrame([context.loss.cashflow_summary]))
        row = 0
        for title, frame in (
            ("Cashflows by payment quarter", context.loss.cashflow_by_quarter),
            ("Recovery type mix", context.loss.recovery_type_mix),
            ("Time to first recovery", context.loss.time_to_recovery),
            ("Cumulative recovery curve", context.loss.recovery_curve),
            ("Recovery lag by institution", context.loss.recovery_lag_by_bank),
        ):
            row = self._write_frame("Recovery_Cashflows", title, frame, start_row=row + 1)

        benchmark_context_note = (
            "Peer values use numerator/denominator aggregation across peer institutions and exclude the bank itself. "
            "Relative gap threshold for BETTER/WORSE flags is 10%."
        )
        self._write_frame("Benchmarking", "Bank versus peer detail", context.benchmark_detail, benchmark_context_note)
        self._write_frame("Metric_Definitions", "Metric definitions", self._metric_definitions(), start_row=0)

        self._write_frame("Data_Quality", "Data quality by institution", context.quality.by_bank)
        row = 0
        for title, frame in (
            ("Findings by category", context.quality.by_category),
            ("Findings by rule", context.quality.by_rule),
            ("Quarantine summary", context.quality.quarantine),
            ("Rule catalog", context.quality.catalog),
        ):
            row = self._write_frame("Data_Quality", title, frame, start_row=row + 1)

        self.writer.close()
        return self.path

    def _metric_definitions(self) -> pd.DataFrame:
        from benchmarking.aggregation import metric_catalog_frame

        return metric_catalog_frame()


def export_excel(context: ReportContext, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return ExcelWorkbook(path, context).build()
