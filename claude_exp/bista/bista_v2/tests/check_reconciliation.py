#!/usr/bin/env python3
"""
check_reconciliation.py  —  validates key BISTA reconciliation rules in an output XML.

Usage:  python3 check_reconciliation.py <xml_file>
Exit 0 if all checks pass, exit 1 if any fail.
"""

import sys
import xml.etree.ElementTree as ET

NS = "http://www.bundesbank.de/xmw/2003-01-01"


def get_field(root, pos):
    """Return integer value of a <FELD pos=...> element, or None if absent."""
    for feld in root.iter(f"{{{NS}}}FELD"):
        if feld.attrib.get("pos") == pos:
            return int(feld.text or 0)
    return None


def check(label, a, b, relation="eq"):
    if a is None or b is None:
        print(f"  SKIP  {label}  (position not found in XML)")
        return True
    ok = (a == b) if relation == "eq" else True
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {label}  ({a} {'==' if relation == 'eq' else '?'} {b})")
    return ok


def main():
    if len(sys.argv) < 2:
        print("Usage: check_reconciliation.py <xml_file>")
        sys.exit(1)

    tree = ET.parse(sys.argv[1])
    root = tree.getroot()

    results = []

    # Rule 1: Total assets = Total liabilities
    # HV11/180 → pos Z180S11;  HV21/330 → pos Z330S21
    assets = get_field(root, "Z180S11")
    liabs  = get_field(root, "Z330S21")
    results.append(check("HV11/180 (total assets) == HV21/330 (total liabilities)", assets, liabs))

    # Rule 2: L1 total should equal HV21/390 irrevocable commitments
    # HV21/390 → pos Z390S21
    # L1 total = sum of all FELD elements inside FORMULAR name="L1"
    commitments_hv = get_field(root, "Z390S21")
    l1_total = None
    for formular in root.iter(f"{{{NS}}}FORMULAR"):
        if formular.attrib.get("name") == "L1":
            l1_total = sum(int(f.text or 0) for f in formular.iter(f"{{{NS}}}FELD"))
    results.append(check("HV21/390 (commitments) == L1 sum", commitments_hv, l1_total))

    passed = all(results)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
