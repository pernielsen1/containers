import os
import sys
import csv
import json
import re
import oracledb

ORA_USER     = os.environ["PN_MYSQL_USER"]
ORA_PASSWORD = os.environ["PN_MYSQL_PASSWORD"]
DSN          = "localhost:1521/XEPDB1"

_DIR       = os.path.dirname(__file__)
_SQL_DIR   = os.path.join(_DIR, '..', 'company_id_sql')
CSV_FILE   = os.path.join(_SQL_DIR, 'company_ids.csv')
XJUSTIZ_JSON = os.path.join(_SQL_DIR, 'snippets_copy', 'XJustiz.json')

_arg = sys.argv[1].upper() if len(sys.argv) > 1 else None
if _arg not in (None, 'CID', 'VAT', 'XJUSTIZ'):
    print(f"Usage: python3 test_company_id.py [CID|VAT|XJUSTIZ]", file=sys.stderr)
    sys.exit(1)
RUN_CID     = _arg in (None, 'CID')
RUN_VAT     = _arg in (None, 'VAT')
RUN_XJUSTIZ = _arg == 'XJUSTIZ'

conn   = oracledb.connect(user=ORA_USER, password=ORA_PASSWORD, dsn=DSN)
cursor = conn.cursor()


def load_sql_file(cursor, sql_file, label):
    """Load an Oracle SQL file, executing each block separated by a '/' line."""
    with open(sql_file, encoding='utf-8') as f:
        content = f.read()

    # Split on lines that contain only '/' (Oracle PL/SQL block terminator)
    blocks = re.split(r'(?m)^\s*/\s*$', content)
    executed = 0
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        code_lines = [l for l in block.splitlines()
                      if l.strip() and not l.strip().startswith('--')]
        if not code_lines:
            continue
        cursor.execute(block)
        executed += 1

    conn.commit()
    print(f"Loaded {label} from {os.path.basename(sql_file)} ({executed} blocks).")


def run_pass(cursor, rows, pkg_proc, label):
    """Run a single test pass and print PASS/FAIL results."""
    print(f"\n=== Pass: {label} ({pkg_proc}) ===")
    print(f"{'CNTRY':<6} {'ID':<36} {'EXP':<5} {'GOT':<5} {'RESULT'}")
    print("-" * 62)
    passed = 0
    failed = 0
    result_var = cursor.var(oracledb.NUMBER)
    for cntry, id_val, expected in rows:
        cursor.callproc(pkg_proc, [cntry, id_val, result_var])
        got = int(result_var.getvalue() or 0)
        ok  = "PASS" if got == expected else "FAIL"
        if got == expected:
            passed += 1
        else:
            failed += 1
        print(f"{cntry or '':<6} {(id_val or ''):<36} {expected:<5} {got:<5} {ok}")
    print("-" * 62)
    print(f"Total: {passed + failed}  PASS: {passed}  FAIL: {failed}")


# Load and split test data (kept in Python, no Oracle table needed)
with open(CSV_FILE, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter=';')
    all_rows = [(row['CNTRY'], row['ID_TYPE'], row['ID'], int(row['EXPECTED'])) for row in reader]

print(f"Loaded {len(all_rows)} rows from {os.path.basename(CSV_FILE)}.")

cid_rows = [(r[0], r[2], r[3]) for r in all_rows if r[1] == 'CID']
vat_rows = [(r[0], r[2], r[3]) for r in all_rows if r[1] == 'VAT']
de_rows  = [(r[0], r[2])       for r in all_rows if r[0] == 'DE' and r[1] == 'CID']

# Create courts table and load XJustiz court data
load_sql_file(cursor, os.path.join(_DIR, 'xjustiz.sql'), 'xjustiz')

_clean_table = str.maketrans('.-()','    ')
def _clean_key(s):
    return s.translate(_clean_table).replace(' ', '')

with open(XJUSTIZ_JSON, encoding='utf-8') as f:
    xjustiz_data = json.load(f)

cursor.executemany(
    "INSERT INTO courts (court_key, court_code, court_name) VALUES (:1, :2, :3)",
    [(_clean_key(k), v, k) for k, v in xjustiz_data.items()],
)
conn.commit()
print(f"Loaded {len(xjustiz_data)} XJustiz court entries.")

# COMPANY_ID_PKG is always loaded; VAT_ID_PKG depends on it
load_sql_file(cursor, os.path.join(_DIR, 'validate_company_id.sql'), 'COMPANY_ID_PKG')
if RUN_VAT:
    load_sql_file(cursor, os.path.join(_DIR, 'validate_vat_id.sql'), 'VAT_ID_PKG')

# Pass 1: CID rows → COMPANY_ID_PKG.VALIDATE_COMPANY_ID
if RUN_CID:
    run_pass(cursor, cid_rows, 'COMPANY_ID_PKG.VALIDATE_COMPANY_ID', 'CID')

# Pass 2: VAT rows → VAT_ID_PKG.VALIDATE_VAT_ID
if RUN_VAT:
    run_pass(cursor, vat_rows, 'VAT_ID_PKG.VALIDATE_VAT_ID', 'VAT')

# Pass 3: DE CID rows → COMPANY_ID_PKG.GET_XJUSTIZ_CODE
if RUN_XJUSTIZ:
    print(f"\n=== XJustiz codes for DE company IDs ===")
    print(f"{'CNTRY':<6} {'CID':<36} {'XJUSTIZ'}")
    print("-" * 56)
    code_var = cursor.var(oracledb.STRING)
    for cntry, id_val in de_rows:
        cursor.callproc('COMPANY_ID_PKG.GET_XJUSTIZ_CODE', [cntry, id_val, code_var])
        code = code_var.getvalue() or ''
        print(f"{cntry or '':<6} {(id_val or ''):<36} {code}")
    print("-" * 56)
    print(f"Total: {len(de_rows)}")

cursor.close()
conn.close()
