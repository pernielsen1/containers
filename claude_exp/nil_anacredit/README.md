# Belgium ANACREDIT Nil Report Generator

This workspace contains a simple Python tool to generate a Belgian ANACREDIT nil XML report for a reporting period when no instruments were issued to any counterparties.

## Files

- `belgium_nil.py` - script that reads reporter metadata from `reporter.json` and writes a nil ANACREDIT XML report.
- `reporter.json` - sample fixed reporter information for the entity.
- `nil_anacredit_be.md` - user note describing the use case and requirements.

## Usage

1. Update `reporter.json` with your entity data.
2. Run the generator:

```bash
python3 belgium_nil.py --reporter reporter.json --period 2026-06
```

3. The script writes `belgium_nil_report.xml` by default.

## Options

- `--reporter` - path to `reporter.json`.
- `--period` - reporting period in `YYYY-MM` format.
- `--output` - optional output XML filename.

## Example

```bash
python3 belgium_nil.py --reporter reporter.json --period 2026-06 --output be_nil_2026-06.xml
```

## Notes

- This generator creates a minimal nil report structure.
- Review the XML output and adapt the tags if your Belgium ANACREDIT schema requires more specific elements.
