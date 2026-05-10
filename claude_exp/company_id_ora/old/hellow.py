import oracledb
import getpass
# docker run -p 1521:1521 -i -t container-registry.oracle.com/database/express:latest
un = "SYS"
cs = "localhost/orclpdb"
cs = "localhost:1521/XEPDB1"
pw = "oracle"
pw = "password"
print("X")
with oracledb.connect(user=un, password=pw, dsn=cs) as connection:
    with connection.cursor() as cursor:
        sql = "select sysdate from dual"
        for r in cursor.execute(sql):
            print(r)
