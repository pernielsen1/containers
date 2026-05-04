# BISTA — Monthly Balance Sheet Statistics (Monatliche Bilanzstatistik)

You are working on a task related to the Deutsche Bundesbank's **BISTA** reporting framework.
Use the specification knowledge below to assist accurately.

---

## What BISTA is

BISTA is the Deutsche Bundesbank's **Monthly Balance Sheet Statistics** research dataset.
It captures the assets and liabilities of all German banks (Monetary Financial Institutions — MFIs)
at end-of-month, from January 1999 to present.

- Collected monthly via Electronic submission (ExtraNet), XML format
- Legal basis: ECB Regulation ECB/2021/2, Guideline ECB/2021/11
- Bank identifier: `BAID_DOM` (renamed from `BAID` in April 2020)
- Data accessible via RDSC (research proposal + confidentiality agreement required)
- Public aggregates available via Bundesbank SDMX API

---

## Reporting Forms

### Main forms (mandatory for all MFIs)

| Form  | Content |
|-------|---------|
| HV11  | Main form Sheet 1 — Assets |
| HV12  | Main form Sheet 2 — Supplementary data on assets |
| HV21  | Main form Sheet 3 — Liabilities |
| HV22  | Main form Sheet 4 — Supplementary data on liabilities |

### Annexes (conditional, based on business activity)

| Annex | Content |
|-------|---------|
| A1–A3 | Loans/liabilities to/from banks (MFIs), transferable liabilities |
| B1, B3 | Loans to non-banks; euro-area breakdown |
| B4–B7 | Loans by type, collateral, maturity, revolving/overdraft |
| C1–C5 | Liabilities to non-banks; euro-area breakdown; transferable liabilities |
| D1–D2 | Saving deposits |
| E1–E5 | Securities (Treasury bills, shares, euro-area, bearer debt) |
| F1–F2 | Bearer debt securities issued |
| H1–H2 | Liabilities / own debt; minimum reserve calculation |
| I1–I2 | Derivative financial instruments (trading portfolio) |
| L1–L2 | Irrevocable lending commitments; ledger-level supplement |

---

## Key BISTA Item Codes

Item numbers in the guidelines (e.g. Item 010, Item 061) map directly to BISTA codes (HV11_010, HV11_061). HV12 codes are supplementary/sub-items of HV11 main lines; HV22 codes are supplementary/sub-items of HV21 main lines. Order matches `bista_items.csv` (ascending by item code).

### HV11 — Assets (main balance sheet lines)

| Item | Description (EN) | German |
|------|-----------------|--------|
| HV11_010 | Cash in hand | Kassenbestand |
| HV11_011 | Cash reserves (cash + central bank balances) | Barreserve |
| HV11_020 | Balances with central banks | Guthaben bei Zentralnotenbanken |
| HV11_040 | Treasury bills eligible for refinancing | Schatzwechsel und ähnliche refinanzierbare Schuldtitel |
| HV11_050 | Bills eligible for refinancing | Wechsel refinanzierbar |
| HV11_060 | Loans and advances to banks (MFIs) — total | Forderungen an Banken (MFIs) |
| HV11_061 | Loans and advances to banks (MFIs) — book claims | Forderungen an Kreditinstitute |
| HV11_062 | Bills received from banks (other than item 050) | Wechsel von Banken (soweit nicht Position 050) |
| HV11_070 | Loans and advances to non-banks (non-MFIs) — total | Forderungen an Nichtbanken (Nicht-MFIs) |
| HV11_071 | Loans and advances to non-banks (non-MFIs) — book claims | Forderungen an Kunden |
| HV11_072 | Bills received from non-banks (other than item 050) | Wechsel von Nichtbanken (soweit nicht Position 050) |
| HV11_080 | Debt instruments (bonds, fixed income) | Schuldverschreibungen und andere festverzinsliche Wertpapiere |
| HV11_081 | Money market paper | Geldmarktpapiere (soweit nicht Position 040) |
| HV11_082 | Bonds and notes | Anleihen und Schuldverschreibungen |
| HV11_090 | Shares and other variable-yield securities | Aktien und andere nicht festverzinsliche Wertpapiere |
| HV11_100 | Participations | Beteiligungen |
| HV11_110 | Shares in affiliated enterprises | Anteile an verbundenen Unternehmen |
| HV11_120 | Trust assets | Treuhandvermoegen |
| HV11_121 | Fiduciary loans | Treuhandkredite |
| HV11_122 | Securities managed on a fiduciary basis | Treuhänderisch gehaltene Wertpapiere |
| HV11_123 | Other fiduciary assets | Sonstiges Treuhandvermögen |
| HV11_130 | Equalisation claims against public authorities | Ausgleichsforderungen gegen oeffentliche Hand |
| HV11_131 | Debt securities from conversion of equalisation claims | Schuldverschreibungen aus Umtausch von Ausgleichsforderungen |
| HV11_140 | Intangible assets / Tangible assets | Immaterielle Anlagewerte / Sachanlagen |
| HV11_150 | Unpaid contributions to subscribed capital | Ausstehende Einlagen auf gezeichnetes Kapital |
| HV11_160 | Own shares | Eigene Aktien oder Anteile |
| HV11_161 | Nominal value of own shares | Nennbetrag der eigenen Aktien oder Anteile |
| HV11_170 | Other assets | Sonstige Vermoegensgegenstände |
| HV11_171 | Cheques and items received for collection | Schecks fällige Schuldverschreibungen Einzugspapiere |
| HV11_172 | Assets leased | Leasinggegenstände |
| HV11_173 | Prepayments for savings bonds and similar discount papers | Rechnungsabgrenzung Sparbriefe und Abzinsungspapiere |
| HV11_174 | Credit balance on items in process of settlement | Aktivsaldo der schwebenden Verrechnungen |
| HV11_175 | Tax receivables / Credit balance on income and expenditure accounts | Steuererstattungsansprueche / Aktivsaldo Aufwands-/Ertragskonten |
| HV11_176 | Prepaid expenses and accrued income / Others | Rechnungsabgrenzungsposten Aktiva / Übrige Aktiva |
| HV11_180 | Total assets | Summe der Aktiva |

### HV12 — Supplementary asset data (sub-items and memo items)

| Item | Description (EN) | German |
|------|-----------------|--------|
| HV12_011 | Domestic legal tender | Inländische gesetzliche Zahlungsmittel |
| HV12_041 | Treasury bills eligible for refinancing with Deutsche Bundesbank | Schatzwechsel refinanzierbar bei der Deutschen Bundesbank |
| HV12_042 | Treasury bills eligible for refinancing with other establishment-country central banks | Schatzwechsel refinanzierbar andere Niederlassungsländer |
| HV12_048 | Legal tender denominated in Deutsche Mark | Auf D-Mark lautende Zahlungsmittel |
| HV12_052 | Bills eligible for refinancing with other establishment-country central banks | Wechsel refinanzierbar andere Niederlassungsländer |
| HV12_079 | ECB debt securities | Schuldverschreibungen der EZB |
| HV12_083 | Own debt securities (repurchased) | Eigene Schuldverschreibungen |
| HV12_084 | Floating rate notes | Variabel verzinsliche Anleihen |
| HV12_085 | Zero coupon bonds | Null-Kupon-Anleihen |
| HV12_086 | Foreign currency bonds | Fremdwährungsanleihen |
| HV12_101 | Nominal value of participating interests in domestic banks (MFIs) | Nennbetrag Beteiligungen inländische Banken (MFIs) |
| HV12_141 | Real estate holdings | darunter Immobilienbestände |
| HV12_177 | Options and futures market position payments (assets) | Optionspreise und Terminmarktpositionen Aktiva |
| HV12_178 | Interest accrued on loans | Aufgelaufene Zinsen auf Kredite |
| HV12_179 | Claims underlying traditional securitisations — removal, originator and servicer | Verbriefungsforderungen mit Bilanzabgang Originator und Servicer |
| HV12_181 | Claims underlying traditional securitisations — servicer only, not originator | Verbriefungsforderungen kein Originator nur Servicer |
| HV12_182 | Claims underlying traditional securitisations — no removal, originator | Verbriefungsforderungen ohne Bilanzabgang Originator |
| HV12_183 | Interest accrued on securities (assets side) | Aufgelaufene Zinsen auf Wertpapiere Aktiva |
| HV12_184 | Prepaid expenses | Rechnungsabgrenzungsposten (soweit nicht unter HV11/173) |
| HV12_185 | Tax refund claims | Steuererstattungsansprüche HV12 |
| HV12_186 | Derivative financial instruments in trading portfolio (positive value) | Derivative Finanzinstrumente Handelsbestand positiv |
| HV12_187 | Currency adjustment item (assets) | Währungsausgleichsposten Aktiva |
| HV12_188 | Working capital at foreign branches | Betriebskapital in ausländischen Zweigstellen |
| HV12_189 | Negative interest accrued on loans | Aufgelaufene negative Zinsen auf Kredite |
| HV12_190 | Negative interest accrued on securities (assets) | Aufgelaufene negative Zinsen auf Wertpapier Aktiva |
| HV12_192_195 | Bills protested and cheques unpaid during reporting month | Protestwechsel und nicht eingelöste Schecks |
| HV12_196 | Trading portfolio memo (assets) | Handelsbestand Aktiva nachrichtlich |
| HV12_197 | Derivative financial instruments excluded from trading portfolio (assets) | Derivate nicht Handelsbestand Aktiva |
| HV12_198 | Interest accrued on trading portfolio derivatives (assets) | Zinsen auf Derivate Handelsbestand Aktiva |
| HV12_213 | Servicing loans — sold with removal as originator | Servicing-Kredite mit Bilanzabgang Originator |
| HV12_214 | Servicing loans — sold without removal as originator | Servicing-Kredite ohne Bilanzabgang Originator |
| HV12_215 | Servicing loans — servicer only, not originator | Servicing-Kredite nur Servicer kein Originator |
| HV12_700_704 | Trading portfolio — breakdown by asset class | Handelsbestand nach Assetklassen |
| HV12_760 | Ledger level before value adjustments — loans to banks | Buchungsstand vor Abzug EWB Bankforderungen |
| HV12_770 | Ledger level before value adjustments — loans to non-banks | Buchungsstand vor Abzug EWB Kundenforderungen |

### HV21 — Liabilities (main balance sheet lines)

| Item | Description (EN) | German |
|------|-----------------|--------|
| HV21_210 | Liabilities to banks (MFIs) | Verbindlichkeiten gegenueber Kreditinstituten |
| HV21_211 | Syndicated loans raised (sub of HV21/210) | Aufgenommene Konsortialkredite (HV21/210) |
| HV21_220 | Other liabilities to non-banks (non-MFIs) | Andere Verbindlichkeiten gegenueber Kunden (Nicht-MFI) |
| HV21_221 | Savings deposits | Spareinlagen |
| HV21_222 | Savings deposits / Other liabilities to non-banks ¹ | Spareinlagen / Andere Verbindlichkeiten Nichtbanken |
| HV21_223 | Syndicated loans raised (sub of HV21/220) | Aufgenommene Konsortialkredite (HV21/220) |
| HV21_224 | Syndicated loans raised (sub of HV21/280) | Aufgenommene Konsortialkredite (HV21/280) |
| HV21_225 | Syndicated loans raised (sub of HV21/330) | Aufgenommene Konsortialkredite (HV21/330) |
| HV21_230 | Securitised liabilities | Verbriefte Verbindlichkeiten |
| HV21_231 | Debt securities in issue | Begebene Schuldverschreibungen |
| HV21_232 | Money market paper in issue | Begebene Geldmarktpapiere |
| HV21_233 | Own acceptances and promissory notes outstanding | Eigene Akzepte und Solawechsel im Umlauf |
| HV21_234 | Other securitised liabilities | Sonstige verbriefte Verbindlichkeiten |
| HV21_240 | Trust liabilities | Treuhandverbindlichkeiten |
| HV21_241 | Fiduciary loans (liabilities) | Treuhandkredite Passiva |
| HV21_242 | Securities issued on a fiduciary basis | Treuhänderisch begebene Wertpapiere |
| HV21_243 | Other fiduciary liabilities | Sonstige Treuhandverbindlichkeiten |
| HV21_250 | Other liabilities / Value adjustments ¹ | Sonstige Verbindlichkeiten / Wertberichtigungen |
| HV21_260 | Deferred income / Provisions for liabilities and charges ¹ | Rechnungsabgrenzungsposten Passiva / Rueckstellungen |
| HV21_280 | Tax liabilities / Subordinated liabilities ¹ | Steuerverbindlichkeiten / Nachrangige Verbindlichkeiten |
| HV21_281 | Subordinated negotiable debt securities | Nachrangig begebene börsenfähige Schuldverschreibungen |
| HV21_282 | Subordinated non-negotiable debt securities | Nachrangig begebene nicht börsenfähige Schuldverschreibungen |
| HV21_290 | Capital represented by participation rights | Genussrechtskapital |
| HV21_300 | Subordinated liabilities / Fund for general banking risks ¹ | Nachrangige Verbindlichkeiten / Fonds f. allg. Bankrisiken |
| HV21_301 | Fund — Section 340e(4) HGB amounts | Beträge gemäß § 340e Abs. 4 HGB |
| HV21_302 | Fund — other earmarked amounts | Sonstige zweckgebundene Beträge |
| HV21_310 | Participation rights capital / Capital and reserves ¹ | Genussrechtskapital / Eigenkapital |
| HV21_311 | Subscribed capital | Gezeichnetes Kapital |
| HV21_312 | Reserves | Rücklagen |
| HV21_313 | Net loss / loss brought forward | Nettofehlbetrag und Verlustvortrag |
| HV21_320 | Fund for general banking risks / Other liabilities ¹ | Fonds f. allg. Bankrisiken / Sonstige Passiva |
| HV21_321 | Interest accrued on zero coupon bonds | Aufgelaufene Zinsen auf Null-Kupon Anleihen |
| HV21_322 | Liability from refinancing of lease receivables | Passivposition Refinanzierung von Leasingforderungen |
| HV21_323 | Liabilities from transactions in goods and trade credits | Verpflichtungen aus Warengeschäften und Warenkrediten |
| HV21_324 | Debit balance on items in process of settlement | Passivsaldo der schwebenden Verrechnungen |
| HV21_325 | Capital and reserves / Debit balance on income and expenditure accounts ¹ | Eigenkapital / Passivsaldo Aufwands-/Ertragskonten |
| HV21_326 | Other liabilities — residual | Übrige Passiva |
| HV21_327 | Subordinated registered debt securities | Nachrangig begebene Namensschuldverschreibungen |
| HV21_329 | Amounts loaded on prepaid cards | Geldkarten-Aufladungsgegenwerte |
| HV21_330 | Total liabilities | Summe der Passiva |
| HV21_339 | Undisclosed contingency reserves | Stille Vorsorgereserven |
| HV21_340 | Contingent liabilities | Eventualverbindlichkeiten |
| HV21_341 | Contingent liabilities — endorsement of rediscounted bills | Eventualvbk. aus weitergegebenen abgerechneten Wechseln |
| HV21_342 | Sureties and guarantee agreements | Verbindlichkeiten aus Bürgschaften und Gewährleistungen |
| HV21_343 | Assets pledged as collateral on behalf of third parties | Haftung aus Sicherheiten für fremde Verbindlichkeiten |
| HV21_350 | Bills sent for collection before maturity | Wechsel vor Verfall zum Einzug versandt |
| HV21_360 | Volume of business | Geschäftsvolumen |
| HV21_370 | Commitments from sales with option to repurchase | Rücknahmeverpflichtungen aus unechten Pensionsgeschäften |
| HV21_380 | Placing and underwriting commitments | Platzierungs- und Übernahmeverpflichtungen |
| HV21_390 | Irrevocable lending commitments | Unwiderrufliche Kreditzusagen |
| HV21_400 | Funds raised against collateral | Verbindlichkeiten gegen Sicherheitsleistung |
| HV21_410 | Interest and currency swaps | Zins- und Währungsswaps |
| HV21_420 | Administered loans | Verwaltungskredite |

¹ Code appears in both the legacy mapping file (original name) and the guidelines (guidelines name) — review for consolidation.

### HV22 — Supplementary liability data (sub-items and memo items)

| Item | Description (EN) | German |
|------|-----------------|--------|
| HV22_219 | Registered debt securities to banks | Namensschuldverschreibungen an Banken |
| HV22_229 | Registered debt securities to non-banks | Namensschuldverschreibungen an Nichtbanken |
| HV22_239 | Memo — own acceptances and promissory notes held in portfolio | nachrichtlich Eigener Bestand an Akzepten und Solawechseln |
| HV22_284 | Subordinated non-negotiable debt securities denominated in euro | Nachrangige nicht börsenfähige SV auf Euro lautend |
| HV22_285 | Subordinated registered debt securities denominated in euro | Nachrangige Namensschuldverschreibungen auf Euro lautend |
| HV22_295 | Additional regulatory tier 1 instruments | Instrumente des zusätzlichen aufsichtsrechtlichen Kernkapitals |
| HV22_335 | Option prices received and margin payments (liabilities) | Erhaltene Optionspreise und Marginzahlungen |
| HV22_336 | Interest accrued on liabilities | Aufgelaufene Zinsen auf Verbindlichkeiten |
| HV22_337 | Interest accrued on securities (liabilities side) | Aufgelaufene Zinsen auf Wertpapiere Passiva |
| HV22_338 | Deferred income | Rechnungsabgrenzungsposten Passiva HV22 |
| HV22_345 | Interest accrued on trading portfolio derivatives (liabilities) | Zinsen auf Derivate Handelsbestand Passiva |
| HV22_431 | Retirement provisions per Altersvermögensgesetz | Altersvorsorgervermögen nach dem AVmG |
| HV22_432 | Subordinated debt securities maturity ≤ 2 years | Nachrangige SV Laufzeit bis zwei Jahre einschließlich |
| HV22_441 | Subordinated non-securitised liabilities to non-banks — maturity ≤ 2 years | Unverbriefte nachrangige Vbk. Nichtbanken Laufzeit bis 2 Jahre |
| HV22_442 | — of which: domestic non-banks and euro-area non-banks | davon Nichtbanken Inland und Euroraum |
| HV22_443 | — of which: non-MFI credit institutions subject to minimum reserve | davon mindestreservepfl. Nicht-MFI-Kreditinstitute |
| HV22_472 | Number of employees (full-time equivalents) | Anzahl der Beschäftigten nach Vollzeitbeschäftigten |
| HV22_473 | Number of employees (headcount) | Anzahl der Beschäftigten nach Köpfen |
| HV22_480 | Trading portfolio (liabilities memo) | Handelsbestand Passiva nachrichtlich |
| HV22_501 | Amounts loaded on prepaid cards denominated in euro | Geldkarten-Aufladungsgegenwerte auf Euro lautend |
| HV22_502 | Loaded network money amounts | Netzgeld-Aufladungsgegenwerte |
| HV22_505 | Derivative financial instruments in trading portfolio (negative value) | Derivative Finanzinstrumente Handelsbestand negativ |
| HV22_506 | Currency adjustment item (liabilities) | Währungsausgleichsposten Passiva |
| HV22_507 | Negative interest accrued on liabilities | Aufgelaufene negative Zinsen auf Verbindlichkeiten |
| HV22_508 | Negative interest accrued on securities (liabilities) | Aufgelaufene negative Zinsen auf Wertpapier Passiva |
| HV22_509 | Advance allocation to reserves from generated profits | Vorwegzuführung zu den Rücklagen aus Überschüssen |
| HV22_510 | Net profit / profit brought forward | Nettoüberschuss und Gewinnvortrag |
| HV22_511 | Derivatives excluded from trading portfolio (liabilities) | Derivate nicht Handelsbestand Passiva |
| HV22_512 | Covered bonds eligible for own use (Article 138 bonds) | Gedeckte SV für Eigengebrauch gemäß Artikel 138 EZB |
| HV22_515 | Reserves — share attributable to revenue reserves | Rücklagen Anteil auf Gewinnrücklage |
| HV22_521 | Reserves — share attributable to capital reserves and other components | Rücklagen Anteil auf Kapitalrücklage und sonstige Anteile |
| HV22_523 | Notional cash pooling | Fiktives Cash-Pooling FCP |
| HV22_524_526 | Trading portfolio — liabilities breakdown | Handelsbestand Passiva Aufgliederung |
| HV22_624_625 | Trading portfolio valued at settlement day | Handelsbestand bewertet zum Erfüllungsbetrag |

---

## Classification Rules

**Maturity bands** (based on originally agreed maturity, not residual):
- Short-term: on demand or ≤ 1 year
- Medium-term: > 1 year and ≤ 5 years (unsecuritised lending only from Jan 1999)
- Long-term: > 5 years

**Sector classification** follows ESA 2010 (from December 2014):
- Banks (MFIs) / Non-banks: Enterprises · Households · Non-profit institutions · General government
- Foreign: banks abroad, non-financial corporations abroad, foreign governments

**Currency**: All amounts in EUR. Foreign currency items converted at ECB reference rate on reporting date.

**Reporting date**: Last working day of the month (section 192 BGB).

---

## Project Implementation (v2)

The v2 annex-level toolchain lives in `/home/perni/containers/claude_exp/bista/bista_v2/`:

| File / Dir | Purpose |
|------------|---------|
| `annex_bista.py` | Main script — annex-level CSV → XMW XML, with calculation engine |
| `bista_fields.csv` | Field catalogue: form, field_id, description, method (input/calculate/sub/nil), relevant_charge_card |
| `bista_calcs.csv` | Calculation rules: form, field_id, formula (e.g. `061 + 062`) — engine derives totals automatically |
| `config/melder.json` | Reporting institution config (BLZ, name, address, contact, RZLZ) |
| `input/` | Input CSV files |
| `output/` | Generated XML files |
| `tests/run_tests.sh` | Smoke test suite (29 tests) — run with `bash tests/run_tests.sh` |
| `tests/test_catalogue.py` | pytest: catalogue loading and calculation engine unit tests |
| `tests/test_validation.py` | pytest: period/stufe validation, form warnings, reconciliation |
| `tests/test_xml.py` | pytest: XML structure and encoding tests |
| `tests/fixtures/` | Test fixtures: minimal_input.csv, full_cc_example.csv, balance_mismatch.csv |

### Pipeline

```bash
# Activate venv first
source /home/perni/containers/claude_exp/bin/activate

# Generate XML (Test mode — safe default)
python3 annex_bista.py --input input/my_data.csv --period 2026-03

# Live submission
python3 annex_bista.py --input input/my_data.csv --period 2026-03 --stufe Produktion

# Custom output path / melder config
python3 annex_bista.py --input input/my_data.csv --period 2026-03 \
    --output output/submission.xml --melder config/melder.json

# Skip catalogue (no auto-derivation)
python3 annex_bista.py --input input/my_data.csv --period 2026-03 --no-catalogue

# Run full test suite
bash tests/run_tests.sh
```

### Input CSV format

Semicolon-free, comma-separated. Lines starting with `#` and blank lines are ignored.

```csv
form,line,column,description,value_eur,comments
# Main form items — column 00
HV11,020,00,Balances with Deutsche Bundesbank,2000000,
HV11,071,00,Card receivables — book claims on non-banks,120000000,
HV21,210,00,Liabilities to banks — interbank funding,80000000,
HV21,311,00,Subscribed capital,60000000,
# Annex items — column = breakdown dimension (maturity / counterparty / product type)
A1,111,01,Other domestic banks — overnight,15000000,
A1,111,02,Other domestic banks — short-term ≤1yr,20000000,
B7,122,02,Domestic employed households — convenience credit card,50000000,
L1,220,01,Domestic households — unused card limits,110000000,
```

**Column conventions by annex:**
- A1/A2: 01=overnight 02=≤1yr 03=>1yr≤5yr 04=>5yr 05=total(calc) 09=central bank
- A2: 01=overnight 02=≤1yr 03=>1yr≤2yr 04=>2yr 05=total(calc)
- B1/B3/C1: 01=short-term(≤1yr) 02=medium-term(>1yr≤5yr) 03=long-term(>5yr) 04=total(calc)
- B7: 01=revolving+overdrafts 02=convenience(charge card) 03=extended(revolving)
- L1: 01=total commitments

**Calculation engine**: Fields marked `calculate` in `bista_fields.csv` are auto-derived from `bista_calcs.csv` formulas. You only need to supply `input` fields. Totals (HV11/180, HV21/330, A1/100, B7/120, etc.) are computed automatically. If you supply a calculated field, the engine warns if it differs from the computed value by >€500.

### Position encoding (XMW XML)

```
HV11/12/21/22 → Z{line}S{subform}    e.g. HV11/071 → Z071S11, HV22/336 → Z336S22
Annexes       → Z{line}S{col}         e.g. B7/122/02 → Z122S02, A1/111/01 → Z111S01
```

All HV11/HV12/HV21/HV22 items merge into a **single** `<FORMULAR name="HV">`. Each annex gets its own formular. Zero values (after EUR→Tsd rounding) are omitted.

```xml
<LIEFERUNG-BISTA xmlns="http://www.bundesbank.de/xmw/2003-01-01" version="1.0" stufe="Test" bereich="Statistik">
  <ABSENDER><RZLZ>R12345678</RZLZ><NAME>...</NAME></ABSENDER>
  <MELDUNG>
    <MELDER><BLZ>500005005</BLZ><NAME>Musterbank AG</NAME>...</MELDER>
    <MELDETERMIN>2026-03</MELDETERMIN>
    <FORMULAR name="HV" modus="Normal">
      <FELD pos="Z020S11">2000</FELD>
      <FELD pos="Z071S11">120000</FELD>
      <FELD pos="Z180S11">168250</FELD>
      ...
    </FORMULAR>
    <FORMULAR name="A1" modus="Normal">
      <FELD pos="Z111S01">15000</FELD>
      ...
    </FORMULAR>
    <FORMULAR name="B7" modus="Normal">
      <FELD pos="Z122S02">50000</FELD>
      ...
    </FORMULAR>
  </MELDUNG>
</LIEFERUNG-BISTA>
```

### Charge card company — relevant annexes

For a pure charge card company (no revolving credit), the relevant annexes are:

| Annex | What it captures | Notes |
|-------|-----------------|-------|
| A1 | Loans to banks — breakdown of HV11/061 | By maturity + counterparty |
| A2 | Liabilities to banks — breakdown of HV21/210 | By maturity + counterparty |
| B1 | Loans to domestic non-banks — breakdown of HV11/071 | Domestic only |
| B3 | Loans to EA non-banks — breakdown of HV11/071 | Euro-area cross-border |
| B4 | Household loans by type | Convenience credit → row 352 |
| B7 | Credit card credit breakdown | col 01=revolving(0), col 02=convenience(≠0) |
| C1 | Liabilities to domestic non-banks | Cardholder overpayment balances |
| C3 | Liabilities to EA non-banks | EA cardholder overpayments |
| H | Minimum reserve calculation | Sheet 2 col 03 = reserve base |
| L1 | Irrevocable lending commitments | Must equal HV21/390 |

---

## Reference Documents

### 1. BISTA Data Report 2026-04 (metadata / research dataset description)
- What it is: Describes the research dataset structure, scope, variables and access conditions
- Metadata Version: BISTA-Doc-v8-0
- DOI: 10.12757/BBk.BISTA.9925.01.01
- URL: https://www.bundesbank.de/resource/blob/992274/6a9219bd214bbcd8122fdd92f70a3372/472B63F073F071307366337C94F8C870/2026-04-bista-data.pdf

### 2. Banking Statistics Guidelines — Monthly Balance Sheet Statistics (January 2026)
- What it is: **Official reporting guidelines** with authoritative item-by-item descriptions for all HV1/HV2 main form items and annexes. Unofficial English translation; only the German version is binding.
- Covers: Guidelines on individual items (HV11/HV12 Assets, HV21/HV22 Liabilities) plus all annexes A–L, supplementary guidelines for building and loan associations, and general reporting rules
- Note: Item numbers in this document (e.g. Item 010, Item 061) correspond directly to BISTA item codes (HV11_010, HV11_061)
- URL: https://www.bundesbank.de/resource/blob/620158/4f3806b49ca5b2bbcdb492e0d728d3a1/472B63F073F071307366337C94F8C870/statso01-03-monatliche-bilanzstatistik-data.pdf

### Contact
- fdsz-data@bundesbank.de · https://www.bundesbank.de/rdsc
