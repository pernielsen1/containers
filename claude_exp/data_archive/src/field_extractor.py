import csv
import json
from pathlib import Path

from .archiver import decompress_from_base64

DEFAULT_ARCHIVE = Path(__file__).parent.parent / 'output' / 'pass1' / 'archive.csv'
DEFAULT_RULES = Path(__file__).parent.parent / 'to_be_extracted.csv'
DEFAULT_OUTPUT = Path(__file__).parent.parent / 'output' / 'pass2' / 'extracted.csv'


def _traverse(data, path):
    try:
        current = data
        for seg in path.split('.'):
            if '[' in seg:
                key, idx = seg.split('[', 1)
                current = current[key][int(idx.rstrip(']'))]
            else:
                current = current[seg]
        return '' if isinstance(current, (dict, list)) else str(current)
    except (KeyError, IndexError, TypeError):
        return ''


def extract_fields(
    archive_csv: Path = DEFAULT_ARCHIVE,
    rules_csv: Path = DEFAULT_RULES,
    output_csv: Path = DEFAULT_OUTPUT,
) -> int:
    with open(rules_csv, encoding='utf-8-sig', newline='') as f:
        rules = list(csv.DictReader(f, delimiter=';'))

    output_cols = list(dict.fromkeys(r['output_col'] for r in rules))
    rule_map: dict[tuple, list] = {}
    for r in rules:
        rule_map.setdefault((r['key'], r['type']), []).append(r)

    rows_written = 0
    with open(archive_csv, encoding='utf-8-sig', newline='') as af, \
         open(output_csv, 'w', encoding='utf-8-sig', newline='') as of:

        writer = csv.DictWriter(of, fieldnames=['run_id', 'key', 'type'] + output_cols, delimiter=';')
        writer.writeheader()

        for row in csv.DictReader(af, delimiter=';'):
            matching = rule_map.get((row['key'], row['type']), [])
            if not matching:
                continue

            data = json.loads(decompress_from_base64(row['base64_json']))
            out_row = {'run_id': row['run_id'], 'key': row['key'], 'type': row['type']}
            out_row.update({col: '' for col in output_cols})
            for rule in matching:
                out_row[rule['output_col']] = _traverse(data, rule['path'])

            writer.writerow(out_row)
            rows_written += 1

    return rows_written
