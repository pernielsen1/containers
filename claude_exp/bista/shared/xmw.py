"""
shared/xmw.py — Bundesbank XMW XML builder, shared by BISTA and KreStA.

Position encoding:
  HV forms (BISTA only): Z{line}S{subform}  e.g. HV11/071 → Z071S11
  All annex forms:       Z{line}S{col}       e.g. B7/122/02 → Z122S02

hv_subforms maps CSV form names to their XML subform suffix, e.g.:
  {"HV11": "11", "HV12": "12", "HV21": "21", "HV22": "22"}
Pass None or {} for submissions that have no merged HV block (KreStA).
"""

import json
import xml.etree.ElementTree as ET
from xml.dom import minidom

XMW_NS = "http://www.bundesbank.de/xmw/2003-01-01"
XMW_VERSION = "1.0"

ET.register_namespace("", XMW_NS)


def _t(name):
    return f"{{{XMW_NS}}}{name}"


def load_melder(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def encode_pos(form, line, col, hv_subforms=None):
    if hv_subforms and form in hv_subforms:
        return f"Z{line}S{hv_subforms[form]}"
    return f"Z{line}S{col}"


def build_formulars(rows, hv_subforms=None, merge_hv_as="HV"):
    """
    Group rows into {formular_name: [(pos, value_tsd), ...]}.
    When hv_subforms is provided, HV11/12/21/22 merge into one FORMULAR named
    merge_hv_as. All other forms get their own FORMULAR.
    Zero values after EUR→Tsd rounding are dropped.
    """
    bucket = {}
    for form, line, col, value_eur in rows:
        value_tsd = round(value_eur / 1000)
        if value_tsd == 0:
            continue
        pos = encode_pos(form, line, col, hv_subforms)
        name = merge_hv_as if (hv_subforms and form in hv_subforms) else form
        bucket.setdefault(name, []).append((pos, value_tsd))

    ordered = {}
    if merge_hv_as in bucket:
        ordered[merge_hv_as] = bucket.pop(merge_hv_as)
    for k in sorted(bucket):
        ordered[k] = bucket[k]
    return ordered


def build_xml(melder, period, stufe, formulars, root_element="LIEFERUNG-BISTA"):
    root = ET.Element(_t(root_element))
    root.set("version", XMW_VERSION)
    root.set("stufe", stufe)
    root.set("bereich", "Statistik")

    ab = ET.SubElement(root, _t("ABSENDER"))
    ET.SubElement(ab, _t("RZLZ")).text = melder["rzlz"]
    ET.SubElement(ab, _t("NAME")).text = melder["absender_name"]

    ml = ET.SubElement(root, _t("MELDUNG"))

    me = ET.SubElement(ml, _t("MELDER"))
    ET.SubElement(me, _t("BLZ")).text = melder["blz"]
    ET.SubElement(me, _t("NAME")).text = melder["melder_name"]
    ET.SubElement(me, _t("STRASSE")).text = melder["strasse"]
    ET.SubElement(me, _t("PLZ")).text = melder["plz"]
    ET.SubElement(me, _t("ORT")).text = melder["ort"]
    ko = ET.SubElement(me, _t("KONTAKT"))
    ET.SubElement(ko, _t("NAME")).text = melder["kontakt"]
    ET.SubElement(ko, _t("TELEFON")).text = melder["telefon"]
    ET.SubElement(ko, _t("EMAIL")).text = melder["email"]

    ET.SubElement(ml, _t("MELDETERMIN")).text = period

    for fname, fields in formulars.items():
        fm = ET.SubElement(ml, _t("FORMULAR"))
        fm.set("name", fname)
        fm.set("modus", "Normal")
        for pos, value_tsd in fields:
            fd = ET.SubElement(fm, _t("FELD"))
            fd.set("pos", pos)
            fd.text = str(value_tsd)

    return root


def to_pretty_xml(root):
    raw = ET.tostring(root, encoding="unicode", xml_declaration=False)
    dom = minidom.parseString(raw)
    return dom.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
