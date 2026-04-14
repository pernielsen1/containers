import os
import csv
import pymysql

MYSQL_USER = os.environ["PN_MYSQL_USER"]
MYSQL_PASSWORD = os.environ["PN_MYSQL_PASSWORD"]
CSV_FILE = os.path.join(os.path.dirname(__file__), "company_ids.csv")

conn = pymysql.connect(
    host="localhost",
    user=MYSQL_USER,
    password=MYSQL_PASSWORD,
    autocommit=True,
)
cursor = conn.cursor()

# Create database
cursor.execute("CREATE DATABASE IF NOT EXISTS db")
cursor.execute("USE db")

# Create table
cursor.execute("DROP TABLE IF EXISTS company_ids")
cursor.execute("""
    CREATE TABLE company_ids (
        CNTRY    CHAR(2),
        ID_TYPE  CHAR(3),
        ID       VARCHAR(100),
        EXPECTED TINYINT
    )
""")

# Load CSV into table
with open(CSV_FILE, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter=";")
    rows = [(row["CNTRY"], row["ID_TYPE"], row["ID"], int(row["EXPECTED"])) for row in reader]

cursor.executemany(
    "INSERT INTO company_ids (CNTRY, ID_TYPE, ID, EXPECTED) VALUES (%s, %s, %s, %s)", rows
)
print(f"Loaded {len(rows)} rows into company_ids.")

def load_sql_file(cursor, sql_file, label):
    """Parse and execute a SQL file that may use DELIMITER directives."""
    with open(sql_file, encoding="utf-8") as f:
        sql_text = f.read()

    delimiter = ";"
    statements = []
    current = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER"):
            delimiter = stripped.split()[-1]
            continue
        current.append(line)
        if stripped.endswith(delimiter) and delimiter != ";":
            stmt = "\n".join(current).rstrip()
            if stmt.endswith(delimiter):
                stmt = stmt[: -len(delimiter)].rstrip()
            if stmt.strip():
                statements.append(stmt)
            current = []
        elif delimiter == ";" and stripped.endswith(";"):
            stmt = "\n".join(current).rstrip().rstrip(";")
            if stmt.strip():
                statements.append(stmt)
            current = []

    for stmt in statements:
        if stmt.strip():
            cursor.execute(stmt)
    print(f"Stored procedure {label} created (from {os.path.basename(sql_file)}).")


def run_pass(cursor, rows, procedure, label):
    """Run a single test pass and print PASS/FAIL results."""
    print(f"\n=== Pass: {label} ({procedure}) ===")
    print(f"{'CNTRY':<6} {'ID':<36} {'EXP':<5} {'GOT':<5} {'RESULT'}")
    print("-" * 62)
    passed = 0
    failed = 0
    for cntry, id_val, expected in rows:
        cursor.execute(f"CALL {procedure}(%s, %s, @res)", (cntry, id_val))
        cursor.execute("SELECT @res")
        (got,) = cursor.fetchone()
        ok = "PASS" if got == expected else "FAIL"
        if got == expected:
            passed += 1
        else:
            failed += 1
        print(f"{cntry or '':<6} {(id_val or ''):<36} {expected:<5} {got:<5} {ok}")
    print("-" * 62)
    print(f"Total: {passed + failed}  PASS: {passed}  FAIL: {failed}")


# Load stored procedures
load_sql_file(cursor, os.path.join(os.path.dirname(__file__), "validate_company_id.sql"), "validate_company_id")
load_sql_file(cursor, os.path.join(os.path.dirname(__file__), "validate_vat_id.sql"), "validate_vat_id")

# Pass 1 — CID rows → validate_company_id
cursor.execute("SELECT CNTRY, ID, EXPECTED FROM company_ids WHERE ID_TYPE = 'CID'")
cid_rows = cursor.fetchall()
run_pass(cursor, cid_rows, "validate_company_id", "CID")

# Pass 2 — VAT rows → validate_vat_id
cursor.execute("SELECT CNTRY, ID, EXPECTED FROM company_ids WHERE ID_TYPE = 'VAT'")
vat_rows = cursor.fetchall()
run_pass(cursor, vat_rows, "validate_vat_id", "VAT")

cursor.close()
conn.close()
