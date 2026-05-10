import os
import oracledb

user = os.environ["PN_MYSQL_USER"]
password = os.environ["PN_MYSQL_PASSWORD"]
dsn = "localhost:1521/XEPDB1"

with oracledb.connect(user=user, password=password, dsn=dsn) as conn:
    with conn.cursor() as cur:
        for row in cur.execute("SELECT sysdate FROM dual"):
            print(row)
