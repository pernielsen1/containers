# Plan: BISTA CSV → XML Converter

## Context

The `bista_mapper.py` script produces a CSV (`bista_report.csv`) with columns:
`form, bista_item, bista_description, side, amount_eur`

Deutsche Bundesbank requires BISTA submissions via ExtraNet as XML files conforming to the XMW
(XML-basiertes elektronisches Meldewesen) format. This plan creates `bista_to_xml.py` and a
`melder.json` template, plus downloads the guide PDF to docs/.

Source: *XMW Electronic Reporting System in XML format — Banking statistics* (Dec 2014 guide).

---

## XML Structure (from the guide)

Four-level hierarchy:

```
LIEFERUNG-BISTA            ← root (level 1)
  ABSENDER                 ← delivery institution (adresse type)
  MELDUNG                  ← report for one MFI (level 2)
    MELDER                 ← reporting MFI (adresse type)
    MELDETERMIN            ← YYYY-MM  (reporting period)
    FORMULAR name="HV"     ← form element (level 3); all HV11/12/21/22 in one FORMULAR
      FELD pos="Z010S11"   ← field element (level 4); value in EUR thousands
      FELD pos="Z186S12"
      FELD pos="Z210S21"
      FELD pos="Z510S22"
```

### Item code → XML position derivation

`HV{NN}_{LINE}` maps to `pos="Z{LINE}S{NN}"`:

| bista_item  | FORMULAR name | pos       |
|-------------|---------------|-----------|
| HV11_010    | HV            | Z010S11   |
| HV12_186    | HV            | Z186S12   |
| HV21_210    | HV            | Z210S21   |
| HV22_510    | HV            | Z510S22   |

Rule: split on `_`, subform digits = column (`S{NN}`), item digits = line (`Z{LINE}`).
The FORMULAR `name` for all HV sub-forms is just `HV`.

### Amounts

- Unit: `Tsd` (thousands of EUR) — standard for balance sheet positions
- mapper output is full EUR → divide by 1000, round to integer
- Zero amounts: omit FELD element (keeps file small; omission = 0 per spec)

---

## Files to create

### 1. `/home/perni/clexp/experiments/bista/melder.json`

Template with all Melder (reporting org) and Absender (sender/delivery org) fields:

```json
{
  "absender": {
    "rzlz": "R12345678",
    "name": "Rechenzentrum Musterbank"
  },
  "melder": {
    "blz": "500005005",
    "name": "Musterbank AG",
    "strasse": "Bankstrasse 12",
    "plz": "60431",
    "ort": "Frankfurt am Main",
    "land": "DE",
    "kontakt": {
      "vorname": "Max",
      "zuname": "Mustermann",
      "abteilung": "Meldewesen",
      "telefon": "069/1234-567",
      "email": "meldewesen@musterbank.de"
    }
  }
}
```

Fields are the `adresse` datatype from the spec. `blz` is mandatory; others optional but
recommended for subject-related queries.

### 2. `/home/perni/clexp/experiments/bista/bista_to_xml.py`

CLI script. Usage:

```bash
python bista_to_xml.py --csv bista_report.csv --melder melder.json --period 2024-12
python bista_to_xml.py --csv bista_report.csv --melder melder.json --period 2024-12 \
    --output bista2412.xml --stufe Produktion
```

**Arguments:**

| Arg         | Required | Default                        | Notes                          |
|-------------|----------|--------------------------------|--------------------------------|
| `--csv`     | no       | `bista_report.csv`             | Output of bista_mapper.py      |
| `--melder`  | no       | `melder.json`                  | Reporting org JSON             |
| `--period`  | yes      | —                              | `YYYY-MM` reporting month      |
| `--output`  | no       | `bista{YYMM}.xml`              | Auto-derived from period       |
| `--stufe`   | no       | `Test`                         | `Test` or `Produktion`         |

**Key implementation steps:**

1. Load CSV with pandas; load melder JSON with stdlib `json`
2. Parse `bista_item` → `(formular_name, pos)`:
   - regex: `^(HV)(11|12|21|22)_(\d{3})$`
   - formular_name = `"HV"`
   - pos = `f"Z{line}S{subform}"` e.g. `Z010S11`
3. Convert `amount_eur` → `round(amount_eur / 1000)` (integer, Tsd)
4. Skip rows where rounded amount == 0
5. Build XML using `xml.etree.ElementTree` (stdlib — no extra deps)
6. Group all FELD elements under a single `<FORMULAR name="HV">`
7. Sort FELD by pos for deterministic output
8. Write with `<?xml version="1.0" encoding="UTF-8"?>` declaration

**Root element attributes** (all required):
```xml
<LIEFERUNG-BISTA
    xmlns="http://www.bundesbank.de/xmw/2003-01-01"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:noNamespaceSchemaLocation="BbkXmwBsm.xsd"
    erstellzeit="2024-12-31T12:00:00"
    version="1.0"
    stufe="Test"
    bereich="Statistik">
```

**Note on `erstellzeit`**: set to current datetime at script run time.

**MELDUNG attributes:**
```xml
<MELDUNG erstellzeit="2024-12-31T12:00:00">
```

**MELDETERMIN:** `<MELDETERMIN>2024-12</MELDETERMIN>`

**File naming:** default output = `bista{YY}{MM}.xml` derived from `--period`.

---

## Files to download

`/home/perni/clexp/docs/xmw-bsm-guide-dec2014.pdf`
Source: https://www.bundesbank.de/resource/blob/612316/4271d94656d562627c49d6ad672d6d02/472B63F073F071307366337C94F8C870/engl-guide-xmw-bsm-12-2014-data.pdf
(Download with `curl -L -o`)

---

## Critical files

| File | Action |
|------|--------|
| `/home/perni/clexp/experiments/bista/bista_to_xml.py` | Create (new) |
| `/home/perni/clexp/experiments/bista/melder.json` | Create (new template) |
| `/home/perni/clexp/docs/xmw-bsm-guide-dec2014.pdf` | Download |

No existing files are modified.

---

## Verification

```bash
cd /home/perni/clexp/experiments/bista

# 1. Generate a BISTA CSV from the sample GL
python bista_mapper.py --standard hgb --gl sample_gl.csv --output bista_report.csv

# 2. Convert to XML (test mode, period = 2024-12)
python bista_to_xml.py --period 2024-12

# 3. Inspect output
cat bista2412.xml   # check structure manually

# 4. Validate against schema (optional, if BbkXmwBsm.xsd is available)
# xmllint --schema BbkXmwBsm.xsd bista2412.xml
```

Expected output structure:
- Root `LIEFERUNG-BISTA` with correct namespace and attributes
- One `MELDUNG` with MELDER populated from `melder.json`
- `MELDETERMIN` = `2024-12`
- One `FORMULAR name="HV"` containing one `FELD` per non-zero BISTA item
- FELD `pos` values in `Z{LINE}S{NN}` format
- FELD values as integers (EUR thousands)
