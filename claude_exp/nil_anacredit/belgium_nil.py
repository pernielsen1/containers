#!/usr/bin/env python3
"""Generate a Belgium ANACREDIT nil XML report from fixed reporter data."""

import argparse
import datetime
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def indent(elem, level=0):
    """Pretty-print XML by indenting elements."""
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def load_reporter(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def build_nil_report(reporter: dict, period: str) -> ET.Element:
    root = ET.Element("AnaCreditReport")
    header = ET.SubElement(root, "Header")

    reporting_entity = ET.SubElement(header, "ReportingEntity")
    ET.SubElement(reporting_entity, "EntityId").text = str(reporter.get("entity_id", ""))
    ET.SubElement(reporting_entity, "EntityName").text = reporter.get("entity_name", "")
    ET.SubElement(reporting_entity, "LegalCountry").text = reporter.get("legal_country", "BE")
    ET.SubElement(reporting_entity, "ReporterBIC").text = reporter.get("reporter_bic", "")
    ET.SubElement(reporting_entity, "ReportingCenter").text = reporter.get("reporting_center", "")

    report_info = ET.SubElement(header, "ReportInformation")
    ET.SubElement(report_info, "ReportPeriod").text = period
    ET.SubElement(report_info, "ReportType").text = "NIL"
    ET.SubElement(report_info, "CreationDateTime").text = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    if reporter.get("contact_name") or reporter.get("contact_email"):
        contact = ET.SubElement(report_info, "ContactDetails")
        if reporter.get("contact_name"):
            ET.SubElement(contact, "ContactName").text = reporter["contact_name"]
        if reporter.get("contact_email"):
            ET.SubElement(contact, "ContactEmail").text = reporter["contact_email"]

    nil_payload = ET.SubElement(root, "NilReport")
    ET.SubElement(nil_payload, "NilIndicator").text = "true"
    ET.SubElement(nil_payload, "NumberOfRecords").text = "0"
    ET.SubElement(nil_payload, "Comment").text = reporter.get(
        "nil_comment", "No instruments issued to any counterparties for this reporting period."
    )

    return root


def validate_reporter(reporter: dict) -> None:
    required = ["entity_id", "entity_name"]
    missing = [field for field in required if not reporter.get(field)]
    if missing:
        raise ValueError(f"Missing required reporter field(s): {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a Belgian ANACREDIT nil report XML file from reporter.json."
    )
    parser.add_argument(
        "--reporter",
        required=True,
        help="Path to reporter.json containing fixed entity information.",
    )
    parser.add_argument(
        "--period",
        required=True,
        help="Reporting period in YYYY-MM format (e.g. 2026-06).",
    )
    parser.add_argument(
        "--output",
        default="belgium_nil_report.xml",
        help="Output XML filename.",
    )

    args = parser.parse_args()
    reporter_path = Path(args.reporter)
    output_path = Path(args.output)

    if not reporter_path.exists():
        print(f"Reporter file not found: {reporter_path}", file=sys.stderr)
        return 1

    reporter = load_reporter(reporter_path)
    try:
        validate_reporter(reporter)
    except ValueError as exc:
        print(f"Invalid reporter.json: {exc}", file=sys.stderr)
        return 1

    root = build_nil_report(reporter, args.period)
    indent(root)
    tree = ET.ElementTree(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    print(f"Created nil report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
