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
        CNTRY  CHAR(2),
        ID_TYPE CHAR(3),
        ID     CHAR(50)
    )
""")

# Load CSV into table
with open(CSV_FILE, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter=";")
    rows = [(row["CNTRY"], row["ID_TYPE"], row["ID"]) for row in reader]

cursor.executemany(
    "INSERT INTO company_ids (CNTRY, ID_TYPE, ID) VALUES (%s, %s, %s)", rows
)
print(f"Loaded {len(rows)} rows into company_ids.")

# Create stored procedure
cursor.execute("DROP PROCEDURE IF EXISTS validate_company_id")
cursor.execute("""
    CREATE PROCEDURE validate_company_id(
        IN p_CNTRY   CHAR(2),
        IN p_ID_TYPE CHAR(3),
        IN p_ID      CHAR(50),
        OUT p_result TINYINT
    )
    BEGIN
        IF p_CNTRY IN ('NO', 'SE') THEN
            SET p_result = 1;
        ELSE
            SET p_result = 0;
        END IF;
    END
""")
print("Stored procedure validate_company_id created.")

# Select all rows and call the procedure for each
cursor.execute("SELECT CNTRY, ID_TYPE, ID FROM company_ids")
rows = cursor.fetchall()

print(f"\n{'CNTRY':<6} {'ID_TYPE':<8} {'ID':<52} {'validation_result'}")
print("-" * 80)

for cntry, id_type, id_val in rows:
    cursor.execute("CALL validate_company_id(%s, %s, %s, @res)", (cntry, id_type, id_val))
    cursor.execute("SELECT @res")
    (result,) = cursor.fetchone()
    print(f"{cntry or '':<6} {id_type or '':<8} {id_val or '':<52} {result}")

cursor.close()
conn.close()
