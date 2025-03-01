#----------------------------------------------------------------------------------------------
# https://dev.mysql.com/doc/connector-python/en/connector-python-example-cursor-select.html
#---------------------------------------------------------------------------------------------
from datetime import datetime, timedelta
def get_bal_dt(cnx):
    bal_dt_str = (datetime.today() - timedelta(days=1)).strftime('%Y-%m-%d')  # if nothing found in today then default to the day before current
    cursor=cnx.cursor()
    cursor.execute("select bal_dt from today")
    for (bal_dt) in cursor:  
      bal_dt_str = "{}".format(bal_dt) 
      bal_dt_str=str(bal_dt).replace("(", "").replace(")", "").replace("'", "").replace(",", "")
      break   # just needs to read first row
    cursor.reset()  # needed in mysql because we only read the first row.
    cursor.close()
    return bal_dt_str

def build_delta(cnx):
    cur_bal_dt = get_bal_dt(cnx)
    cursor=cnx.cursor()
    cursor.execute("delete from delta")
    query = ("insert into delta (account, bal_dt, amount, currency) " +
            "select yesterday.account, " 
            +  "'" + cur_bal_dt  + "'" +
            ", 0, " +
            " yesterday.currency " +
            "from yesterday left join today " +
            "on yesterday.account = today.account " +
            "where today.account is null"
          )
    cursor.execute(query)
    # build new today
    cursor.execute("delete from new_today")
    cursor.execute("insert into new_today select * from today")
    cursor.execute("insert into new_today select * from delta")
    # store today as yesterday - this is a critical moment but we believe in the DB- commit
    # OBS we don't want our new_today as yesterday since it just has a few "zero balancing items"
#    cursor.execute("delete from yesterday")
#    cursor.execute("insert into yesterday select * from today")

    cnx.commit()
    cursor.close()
#-------------------------------------------------------------------------
# here we go
#-------------------------------------------------------------------------
import mysql.connector
cnx = mysql.connector.connect(user='root', password='password',
                              host='127.0.0.1',
                              database='test_db')
build_delta(cnx)
cursor = cnx.cursor()

query = ("SELECT account, bal_dt, amount, currency FROM delta")

cursor.execute(query)
print("listing the delta")
for (account, bal_dt, amount, currency) in cursor:
  print("account:" + account + "bal_dt" + bal_dt + " amount:", str(amount) + " cur:" + currency)
  
cursor.close()
cnx.close()