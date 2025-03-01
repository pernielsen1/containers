#----------------------------------------------------------------------------------------------
# https://dev.mysql.com/doc/connector-python/en/connector-python-example-cursor-select.html
#---------------------------------------------------------------------------------------------
import mysql.connector
num_recs = 1000

def drop_table(cnx, table_name):
    cursor=cnx.cursor()
    # drop the old tables if they exist
    try:
        cursor.execute("drop table test_db." + table_name)
    except mysql.connector.Error as err:
        print(err.msg)
    else:
        print("table:" + table_name + " dropped")

def create_tables(cnx):
    drop_table(cnx, "today")
    drop_table(cnx, "yesterday")
    drop_table(cnx, "delta")
    drop_table(cnx, "new_today")

    cursor = cnx.cursor()
    fields =  "(account varchar(20), bal_dt  char(10), amount decimal(11, 2), currency char(3))"
    cursor.execute("create table test_db.today " + fields)
    cursor.execute("create table test_db.yesterday " + fields)
    cursor.execute("create table test_db.delta " + fields)
    cursor.execute("create table test_db.new_today " + fields)
           
def fill_db(cnx):
    cursor=cnx.cursor()
    fields =  ( "(account, bal_dt, amount, currency) "
                "VALUES (%(account)s, %(bal_dt)s, %(amount)s, %(currency)s)"
            )
   
    add_yesterday =  "INSERT INTO yesterday " + fields
    add_today = "INSERT INTO today " + fields
   
    for x in range (0, num_recs):
        data_row = {
            'account': 'acc' + str(x + 1),
            'bal_dt': '2024-12-24',
            'amount': x + 1,
            'currency': 'SEK',
        }
        cursor.execute(add_yesterday, data_row)
            if ((x+1) % 100 != 0):
            data_row['bal_dt'] = '2024-12-25'
            cursor.execute(add_today, data_row)
    cnx.commit()
    return


#--------------------------------------------------------------------------------------
# here we go
#---------------------------------------------------------------------------------------
cnx = mysql.connector.connect(user='root', password='password',
                              host='127.0.0.1',
                              database='test_db')

create_tables(cnx)
fill_db(cnx)

cursor = cnx.cursor()
# query = ("SELECT account, amount, currency FROM today")
#
# cursor.execute(query)
#
# for (account, amount, currency) in cursor:
#  print("account:" + account + " amount:", str(amount) + " cur:" + currency)
  
cursor.close()
cnx.close()
