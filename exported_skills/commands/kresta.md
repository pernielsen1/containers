# KreStA — Quarterly Borrower Statistics (Kreditnehmerstatistik)

You are working on a task related to the Deutsche Bundesbank's **KreStA** reporting framework.
Use the specification knowledge below to assist accurately.

---

## What KreStA Is

KreStA (VJKRE — Vierteljährliche Kreditnehmerstatistik) is the Deutsche Bundesbank's **Quarterly Borrower Statistics**.
It captures outstanding loans to domestic enterprises and households at end-of-quarter, broken down by borrower category, loan type, and maturity.

- Collected quarterly (end of each calendar quarter)
- Deadline: 10th business day after quarter end
- Submission format: XMW XML (same namespace as BISTA)
- Submission channel: ExtraNet → NExt (transition expected Q3 2026)
- Legal basis: Mitteilung Nr. 8003/2004 (21 July 2004, Bundesanzeiger Nr. 144/2004)
- Guidelines: Statistische Sonderveröffentlichung 1, Januar 2026 (section 4)
- All MFIs required to report; no size threshold

**Reconciliation constraint**: V1/Z400 + V3/Z400 (across all columns) must equal BISTA Annex B1/Z100 (total loans to domestic enterprises and households).

---

## Reporting Forms

| Form | Content | Effective |
|------|---------|-----------|
| V1 | Short and medium-term loans ≤5yr — main matrix | 01.01.2026 |
| V2 | Supplementary data for V1 (sector sub-items) | 01.01.2026 |
| V3 | Long-term loans >5yr — main matrix | 01.01.2026 |
| V4 | Supplementary data for V3 (sector sub-items) | 01.01.2026 |
| VA | Service sector short/medium-term (sub of V1/row 180) | 01.07.2008 |
| VB | Service sector long-term (sub of V3/row 180) | 01.07.2008 |
| V1B | Value adjustments (Bewertungskorrekturen) for V1 | — |
| V2B | Value adjustments for V2 | — |
| V3B | Value adjustments for V3 | — |
| V4B | Value adjustments for V4 | — |
| VAB | Value adjustments for VA | — |
| VBB | Value adjustments for VB | — |

B-variants capture write-downs/ups (negative = write-down) in the reporting period. Nil report not required if no adjustments occurred.

---

## Column Definitions

### V1, V2, VA, V1B, V2B, VAB, VBB (short/medium-term, ≤5yr)

| Col | Description |
|-----|-------------|
| S01 | Forderungen ≤ 1 Jahr (claims due within 1 year) |
| S02 | Forderungen > 1 Jahr ≤ 5 Jahre |
| S03 | Wechseldiskontkredite (bills discounted — by Einreicher) |
| S04 | Wechsel im Bestand (bills held — by Bezogener) |

### V3, V4, VB, V3B, V4B, VBB (long-term, >5yr)

| Col | Description |
|-----|-------------|
| S05 | Forderungen > 5 Jahre (ohne Hypothekarkredite) |
| S06 | Treuhandkredite — **deprecated since 2021, always nil** |
| S07 | Hypothekarkredite insgesamt (total mortgage loans) |
| S08 | darunter: Hypothekarkredite auf Wohngrundstücke (residential mortgage sub-item) |

---

## Row Definitions — Main Forms (V1 and V3)

| Row | Description | Method |
|-----|-------------|--------|
| 100 | Unternehmen u. selbst. Privatpersonen — total (= 110+120+130+140+150+160+170+180) | **calculate** |
| 110 | Land- und Forstwirtschaft, Fischerei und Aquakultur | input |
| 120 | Energie- und Wasserversorgung; Entsorgung; Bergbau | input |
| 130 | Verarbeitendes Gewerbe | input |
| 140 | Baugewerbe | input |
| 150 | Handel | input |
| 160 | Verkehr und Lagerei; Nachrichtenübermittlung | input |
| 170 | Finanzierungsinstitutionen (ohne MFIs) u. Versicherungen | input |
| 180 | Dienstleistungen (einschl. freier Berufe) | input |
| 200 | Wirtschaftlich unselbständige u. sonstige Privatpersonen (= 210+220+230) | **calculate** |
| 210 | Ratenkredite (ohne Wohnungsbaukredite) — instalment credit | input |
| 220 | Nichtratenkredite (ohne Wohnungsbaukredite) — non-instalment (incl. charge card) | input |
| 230 | Kredite für den Wohnungsbau — housing credit | input |
| 300 | Organisationen ohne Erwerbszweck (non-profit organisations) | input |
| 400 | Summe inländische Unternehmen und Privatpersonen (= 100+200+300) | **calculate** |

### V2 / V4 supplementary rows (sub-items)

| Row | Description |
|-----|-------------|
| 105 | Selbständige und Einzelkaufleute (in rows 110–180) |
| 106/107 | Wohnungsbaukredite — Unternehmen etc. |
| 108 | Handwerk (craft enterprises in rows 110–180) |
| 131–139 | Verarbeitendes Gewerbe sub-sectors (sub of row 130) |
| 171 | Finanzierungsleasing (sub of row 170) |
| 181–186 | Dienstleistungen sub-sectors (sub of row 180) |
| 221 | Debetsalden auf Lohn-/Gehalts-/Renten-/Pensionskonten |
| 309 | Wohnungsbaukredite in rows 200 and 300 |

### VA / VB service sector rows (sub of V1/V3 row 180)

| Row | Description |
|-----|-------------|
| 181 | Wohnungsunternehmen |
| 182 | Beteiligungsgesellschaften |
| 183 | Sonstiges Grundstückswesen |
| 184 | Gastgewerbe |
| 185 | Information und Kommunikation; F&E; Interessenvertretungen |
| 186 | Gesundheits-, Veterinär- und Sozialwesen |

---

## Charge Card Company — What to Report

For a pure charge card company (no revolving credit):

| Form | Relevant? | Rationale |
|------|-----------|-----------|
| V1 | **Yes** | All card receivables ≤1yr → col S01; row 220 (Nichtratenkredite) for households; rows 110–180 for corporate cardholders |
| V2 | **Yes** | Breakdown of V1 row 130 (Verarbeitendes Gewerbe) and row 180 sub-sectors |
| V3 | No | No long-term credit |
| V4 | No | No long-term credit |
| VA | Optional | Only if row 180 (Dienstleistungen) has material sub-sector data |
| VB | No | No long-term service credit |
| V1B | **Yes** | When write-downs on card receivables occur |
| V3B | No | No long-term credit |

Card receivables classification:
- Billing cycle <30 days → all **column S01** (≤1yr)
- Household card spend → row **220** (Nichtratenkredite — non-instalment)
- Corporate card spend → rows **110–180** by borrower sector

---

## Project Implementation

The KreStA toolchain lives in `/home/perni/containers/claude_exp/bista/kresta/`:

| File / Dir | Purpose |
|------------|---------|
| `kresta.py` | Main script — CSV → `LIEFERUNG-VJKRE` XMW XML |
| `kresta_fields.csv` | Field catalogue: form, field_id, description, method (input/calculate) |
| `kresta_calcs.csv` | Derivation rules for totals (rows 100, 200, 400 per column) |
| `config/melder.json` | Reporting institution config (BLZ, RZLZ, name, address, contact) |
| `input/` | Input CSV files |
| `output/` | Generated XML files |
| `tests/run_tests.sh` | Smoke test suite (29 tests) |
| `tests/test_catalogue.py` | pytest: catalogue loading and engine unit tests |
| `tests/test_xml.py` | pytest: XML structure, encoding, and derivation tests |
| `tests/fixtures/` | minimal_input.csv, full_cc_example.csv |

Shared library at `bista/shared/` (used by both BISTA and KreStA):

| File | Purpose |
|------|---------|
| `shared/xmw.py` | XML builder (`build_xml`, `build_formulars`, `encode_pos`, `to_pretty_xml`) |
| `shared/catalogue.py` | `Catalogue` class — loads fields/calcs CSVs |
| `shared/engine.py` | `CalculationEngine` — derives totals from input fields |
| `shared/csv_io.py` | `load_csv`, `rows_to_data`, `data_to_rows` |

### Pipeline

```bash
# Activate venv first
source /home/perni/containers/claude_exp/bin/activate

# Generate XML (Test mode — safe default)
python3 kresta.py --input input/my_data.csv --period 2026-03

# Live submission (Q1 2026)
python3 kresta.py --input input/my_data.csv --period 2026-03 --stufe Produktion

# Custom output and melder
python3 kresta.py --input input/my_data.csv --period 2026-03 \
    --output output/q1_2026.xml --melder config/melder.json

# Skip catalogue (no auto-derivation of totals)
python3 kresta.py --input input/my_data.csv --period 2026-03 --no-catalogue

# Run full test suite
bash tests/run_tests.sh
```

### Period format

Use the **last month of the quarter** in `YYYY-MM` format:

| Quarter | Period |
|---------|--------|
| Q1 (Jan–Mar) | `YYYY-03` |
| Q2 (Apr–Jun) | `YYYY-06` |
| Q3 (Jul–Sep) | `YYYY-09` |
| Q4 (Oct–Dec) | `YYYY-12` |

### Input CSV format

```csv
form,line,column,description,value_eur,comments
# V1 — short/medium-term card receivables
V1,130,01,Verarbeitendes Gewerbe — card receivables,50000000,
V1,220,01,Nichtratenkredite — employed households (charge card),70000000,
# V2 — sub-sector breakdown of V1 row 130
V2,135,01,Maschinenbau; Fahrzeugbau,30000000,
V2,136,01,Elektronik; Datenverarbeitungsgeräte,20000000,
# V1B — write-downs this quarter
V1B,130,01,Value adjustment — Verarbeitendes Gewerbe,-500000,Write-down
```

### Position encoding (XMW XML)

```
Z{line}S{col}    e.g.  V1/row 220/col 01 → Z220S01
                        V3/row 200/col 07 → Z200S07
```

Each form gets its own `<FORMULAR name="V1">` etc. No HV-style merging.

### XMW XML output structure

```xml
<LIEFERUNG-VJKRE xmlns="http://www.bundesbank.de/xmw/2003-01-01" version="1.0" stufe="Test" bereich="Statistik">
  <ABSENDER><RZLZ>R12345678</RZLZ><NAME>...</NAME></ABSENDER>
  <MELDUNG>
    <MELDER><BLZ>500005005</BLZ><NAME>Musterbank AG</NAME>...</MELDER>
    <MELDETERMIN>2026-03</MELDETERMIN>
    <FORMULAR name="V1" modus="Normal">
      <FELD pos="Z130S01">50000</FELD>
      <FELD pos="Z220S01">70000</FELD>
      <FELD pos="Z100S01">50000</FELD>  <!-- derived -->
      <FELD pos="Z200S01">70000</FELD>  <!-- derived -->
      <FELD pos="Z400S01">120000</FELD> <!-- derived -->
    </FORMULAR>
    <FORMULAR name="V2" modus="Normal">
      <FELD pos="Z135S01">30000</FELD>
      <FELD pos="Z136S01">20000</FELD>
      <FELD pos="Z130S01">50000</FELD>  <!-- derived -->
    </FORMULAR>
  </MELDUNG>
</LIEFERUNG-VJKRE>
```

### Calculation engine

Fields marked `calculate` in `kresta_fields.csv` are auto-derived from `kresta_calcs.csv`:

| Derived field | Formula |
|--------------|---------|
| V1/100/S01–S04 | Sum of rows 110–180 per column |
| V1/200/S01–S04 | 210 + 220 + 230 per column |
| V1/400/S01–S04 | 100 + 200 + 300 per column |
| V3/100/S05,S07,S08 | Sum of rows 110–180 per column |
| V3/200/S05,S07,S08 | 210 + 220 + 230 per column |
| V3/400/S05,S07,S08 | 100 + 200 + 300 per column |
| V2/130/S01–S04 | Sum of rows 131–139 per column |
| VA/100/S01–S04 | Sum of rows 181–186 per column |
| VB/100/S05,S07,S08 | Sum of rows 181–186 per column |

Zero values (after EUR→Tsd rounding) are omitted from XML. Amounts in EUR thousands.

---

## Reference Documents

### Guidelines (authoritative)
- **Richtlinien zur Kreditnehmerstatistik** (section 4 of Statistische Sonderveröffentlichung 1, Januar 2026)
- URL: https://www.bundesbank.de/resource/blob/612430/2e93a5650f7c27f215cd92f25564d973/472B63F073F071307366337C94F8C870/statso01-04-kreditnehmerstatistik-data.pdf

### Blank forms (Vordrucke)
- All forms (ZIP, 755 KB, 01.01.2026): https://www.bundesbank.de/resource/blob/612160/b675f3a5c0b78d109ed4f904fcb39f09/472B63F073F071307366337C94F8C870/vjkre-pdf-zip-data.zip
- V1 form: https://www.bundesbank.de/resource/blob/611844/27c8ca76b818ed1366ab131d5d40c9a1/472B63F073F071307366337C94F8C870/v1-data.pdf
- V3 form: https://www.bundesbank.de/resource/blob/611890/ac97aebeb1be41095b6fcd38b1a0d036/472B63F073F071307366337C94F8C870/v3-data.pdf

### Contact
- Statistik-AAMI@bundesbank.de · https://www.bundesbank.de/rdsc
