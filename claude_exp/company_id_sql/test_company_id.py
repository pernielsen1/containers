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

# Load and execute validate_company_id.sql (helper functions + procedure)
SQL_FILE = os.path.join(os.path.dirname(__file__), "validate_company_id.sql")
with open(SQL_FILE, encoding="utf-8") as f:
    sql_text = f.read()

# Split on DELIMITER markers; execute each statement block using // as the delimiter.
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
print("Stored procedure validate_company_id created (from validate_company_id.sql).")

# Call the procedure for each row and show PASS/FAIL vs expected
cursor.execute("SELECT CNTRY, ID_TYPE, ID, EXPECTED FROM company_ids")
rows = cursor.fetchall()

print(f"\n{'CNTRY':<6} {'ID_TYPE':<8} {'ID':<36} {'EXP':<5} {'GOT':<5} {'RESULT'}")
print("-" * 70)

passed = 0
failed = 0
for cntry, id_type, id_val, expected in rows:
    cursor.execute("CALL validate_company_id(%s, %s, @res)", (cntry, id_val))
    cursor.execute("SELECT @res")
    (got,) = cursor.fetchone()
    ok = "PASS" if got == expected else "FAIL"
    if got == expected:
        passed += 1
    else:
        failed += 1
    print(f"{cntry or '':<6} {id_type or '':<8} {(id_val or ''):<36} {expected:<5} {got:<5} {ok}")

print("-" * 70)
print(f"Total: {passed + failed}  PASS: {passed}  FAIL: {failed}")

cursor.close()
conn.close()
