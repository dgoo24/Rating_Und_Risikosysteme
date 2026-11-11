"""Command-line interface for report generation.

Examples:
    python -m reporting.cli --formats pdf excel csv qlik
    python -m reporting.cli --reporting-date 2026-09-30 --bank SSK001 --formats pdf excel
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reporting.report_service import generate_reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate risk portfolio PDF, Excel, CSV and Qlik-ready outputs")
    parser.add_argument("--reporting-date", help="Quarter-end reporting date, e.g. 2026-09-30")
    parser.add_argument("--bank", action="append", help="Optional bank filter (repeatable)")
    parser.add_argument("--sector", action="append", help="Optional industry-sector filter (repeatable)")
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["pdf", "excel", "csv", "qlik"],
        choices=["pdf", "excel", "csv", "qlik"],
        help="Output formats to generate",
    )
    parser.add_argument("--no-community", action="store_true", help="Skip the community-wide report")
    parser.add_argument("--no-institutions", action="store_true", help="Skip per-institution reports")
    parser.add_argument("--no-distribution", action="store_true", help="Skip simulated distribution logging")
    args = parser.parse_args()

    summary = generate_reports(
        reporting_date=args.reporting_date,
        bank_ids=args.bank,
        sectors=args.sector,
        output_formats=args.formats,
        include_community=not args.no_community,
        include_institutions=not args.no_institutions,
        simulate_dist=not args.no_distribution,
    )
    print("\nReport generation summary")
    print(f"  Reporting date : {summary['reporting_date']}")
    print(f"  Data version   : {summary['data_version']}")
    print(f"  Formats        : {', '.join(summary['output_formats'])}")
    print(f"  Artefacts      : {len(summary['generated'])} generated, {len(summary['failures'])} failed")
    for item in summary["generated"]:
        print(f"    + {item['file_format']:<10} {item['path']}")
    for failure in summary["failures"]:
        print(f"    ! {failure['artefact']}: {failure['error']}")
    if summary.get("distribution_manifest"):
        print(f"  Distribution   : SIMULATED - manifest {summary['distribution_manifest']}")
    else:
        print("  Distribution   : not simulated")
    print(f"  Summary        : {summary.get('community_pdf') or summary.get('community_excel') or ''}")
    if summary["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
