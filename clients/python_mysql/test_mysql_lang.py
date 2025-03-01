#----------------------------------------------------------------------------------------------
# https://dev.mysql.com/doc/connector-python/en/connector-python-example-cursor-select.html
#---------------------------------------------------------------------------------------------
import mysql.connector
import os
import pwd
#------------------------------------------------------------------------------
# create table in db - insert values and list the inserted values
#------------------------------------------------------------------------------
def do_it():

  db_host = '127.0.0.1'
  db_host = 'localhost'
  db_name= 'test_db'
  db_port = 12345
  db_user = "root"
  db_pwd = "password"
  tbl_name = "test_c_and_l"
  cnx = mysql.connector.connect(user=db_user, port=db_port, password=db_pwd, host=db_host, database=db_name)
  cursor = cnx.cursor()

# delete table if existing  
  try:
    cursor.execute("drop table test_db." + tbl_name)
  except mysql.connector.Error as err:
     print(err.msg)
  else:
    print("table:" + tbl_name + " dropped")

  cursor.execute("create table " + tbl_name + "  (id integer, c char(2), l char(2))")
    
  cursor.execute( "INSERT INTO " + tbl_name + " (id, c, l) VALUES(" +  "1," + "'SE'," + "'SE')")
  cursor.execute( "INSERT INTO " + tbl_name + " (id, c, l) VALUES(" + "52," + "'SE'," + "'SE')")
  cursor.execute( "INSERT INTO " + tbl_name + " (id, c, l) VALUES(" +  "1," + "'SE'," + "'EN')")
  cursor.execute( "INSERT INTO " + tbl_name + " (id, c, l) VALUES(" +  "52," + "'SE'," + "'EN')")

  cursor.execute( "INSERT INTO " + tbl_name + " (id, c, l) VALUES(" + "51," + "'NO'," + "'NO')")

  cursor.execute( "INSERT INTO " + tbl_name + " (id, c, l) VALUES(" + "41," + "'AT'," + "'DE')")
  cursor.execute( "INSERT INTO " + tbl_name + " (id, c, l) VALUES(" + "41," + "'AT'," + "'EN')")
  cursor.execute( "INSERT INTO " + tbl_name + " (id, c, l) VALUES(" + "41," + "'DE'," + "'DE')")
  cursor.execute( "INSERT INTO " + tbl_name + " (id, c, l) VALUES(" + "41," + "'DE'," + "'EN')")


  print("Listing full table:")
  cursor.execute("SELECT id, c, l from test_c_and_l")
  for (id, c, l) in cursor:
    print("id:" + str(id) + " c:", c + " l:" + l)

  print("Listing l per c")
  query = ("select a.c, a.id, b.l from " +  
      "(select distinct c, case when c = 'SE' then 52 when c='NO' then 51 else 41 end as id from test_c_and_l) a " + 
      "inner join test_c_and_l b on a.id = b.id and a.c = b.c " + 
      "order by a.id desc")

  cursor.execute(query)
  for (c, id, l) in cursor:
    print(" c:" + c + " id:" + str(id) + " l:" + l)

  cursor.close()
  cnx.commit()
  cnx.close()


#----------------------------------
# here  we go
#----------------------------------
user = pwd.getpwuid(os.getuid())[0]
print(user)
do_it()
