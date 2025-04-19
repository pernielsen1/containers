
import json
import mysql.connector
from sqlalchemy import create_engine
from sqlalchemy import text
# from sqlalchemy.orm import Session
# engine = create_engine("sqlite+pysqlite:///:memory:", echo=True)
# uses mysql  pip install mysql-connector-python
# pip install SQLAlchemy
# mysql connection input 
# htps://planetscale.com/blog/using-mysql-with-sql-alchemy-hands-on-examples
# mysql+<drivername>://<username>:<password>@<server>:<port>/dbname
# https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html
           

PN_CRYPTO_KEYS = "pn_crypto_keys"
PN_CRYPTO_DATABASE = "pn_crypto_key_store"

import pn_utilities.logger.PnLogger as PnLogger
log = PnLogger.PnLogger()
#------------------------------------------
# PnCryptKey - the key object
#------------------------------------------
class PnCryptKey():
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
    def __init__(self, id="", description="", value="", type=""):
        self.key = {}
        self.key['id'] = id
        self.key['description'] = description
        self.key['value'] = value
        self.key['type'] = type

    def get_id(self):
        return str(self.key['id'])
    def get_description(self):
        return str(self.key['description'])
    def get_uri(self):
        return '/v1/keys/' + self.get_id()
    def get_value(self):
        return self.key['value']
    def get_type(self):
        return self.key['type']
    def get_key(self):
        return self.key
#---------------------------------------------------------
# PnCryptKeys - load the keys from the data store to 
#---------------------------------------------------------
class PnCryptoKeys:
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, config):
        self.keys = {}
        self.config = config
        self.has_db = False
        self.load_keys()

    def load_keys(self):
        data_store_type = self.config['PnCrypto']['dataStoreType']
        log.info("Loading keys from:" + data_store_type)

        if ( data_store_type == 'json'): 
            key_store_file = self.config['PnCrypto']['keyStoreFile']
            log.info("Loading keys store from:" + key_store_file)
            with open(key_store_file, 'r') as file:
                dict = json.loads(file.read())
                input_keys = dict['crypto_keys']
                for k in input_keys:
                    self.keys[k] = PnCryptKey(k, "desc for " + k, input_keys[k], "a type")
        elif ( data_store_type == 'mysql'):
            self.has_db = True
            user = self.config['PnCrypto']['mysql']['user']
            port = self.config['PnCrypto']['mysql']['port']
            host = self.config['PnCrypto']['mysql']['host']
            password = self.config['PnCrypto']['mysql']['password']
            database = PN_CRYPTO_DATABASE
            log.info("opening mysql with user:" + user + " host:port "
                        + host + ":" + str(port) + " database:" + database)
            if (self.config['PnCrypto']['mysql'].get("log_sql", "False").upper() == "TRUE"): 
                log_sql = True
            else:
                log_sql = False
            mysql_conn_str=('mysql+mysqlconnector://' + 
                            user + ':' + password + '@' + host + ':' + str(port)+ '/' + database )
#            log.info("creating engine with connstr:" + mysql_conn_str)   
            self.sqlalchemy_engine = create_engine(mysql_conn_str, echo=log_sql)
            self.datastore_sqlalchemy_conn = self.sqlalchemy_engine.connect()

            self.sync_keys_db()
        else:
            log.error("unsupported ID for dataStoreType" + data_store_type)

    def sync_keys_db(self):
        self.keys = {}
        query = ("SELECT id, description, value, type from " + PN_CRYPTO_KEYS)
        r1 = self.datastore_sqlalchemy_conn.execute(text(query))
        result = r1.fetchall()
        for row in result:
            self.keys[row.id] = PnCryptKey(row.id, row.description, row.value, row.type)

    def get_keys(self):
        return self.keys

    def get_key(self, id):
        return self.keys.get(id, None)

    def get_key_json(self, id):
        x = self.keys[id].get_key()
        return json.dumps(x)
     
    def get_keys_json(self):
        r_dict = {}
        for k in self.keys:
            entry = {}
            entry['description'] = self.keys[k].get_description()
            entry['uri'] = self.keys[k].get_uri()
            r_dict[k] = entry

        return json.dumps(r_dict)

    def delete_key(self, id):
        PLING = "'"
        delete_sql = ( "delete from " + PN_CRYPTO_KEYS + " where id=" + PLING + id + PLING )
        self.datastore_sqlalchemy_conn.execute(text(delete_sql))
    
        self.datastore_sqlalchemy_conn.commit()
        self.sync_keys_db()

    def update_key(self, id, description, value, type):
        if (self.get_key(id) == None):
            return False   # oops it does not exist then you can't update
        
        self.datastore_sqlalchemy_conn.execute(
            text(
                "UPDATE " + PN_CRYPTO_KEYS + 
                " set description=:description, value=:value, type=:type" +
                " where id=:id"
            ),
             {"description": description, "value": value, "type": type, "id": id}
        )
        self.datastore_sqlalchemy_conn.commit()

        self.sync_keys_db()
        return True
    
    def import_key(self, id, description, value, type):
        if (self.get_key(id) != None):
            return False   # oops it already exists
        # still here all good
        pling = "'"
        self.keys[id] = PnCryptKey(id, description, value, type)
        insert_sql = ( "insert into " + PN_CRYPTO_KEYS + 
                      " (id, description, value, type) " +
                      "values(" + 
                      pling + id + pling + ", " + 
                      pling + description + pling + ", " +
                      pling + value +  pling + ", " + 
                      pling + type + pling + 
                      ")" ) 
        self.datastore_sqlalchemy_conn.execute(text(insert_sql))
        self.datastore_sqlalchemy_conn.commit()
        # and updata our in memory copy - do a full reload..  - in prod we would need to reload all servers !
        self.sync_keys_db()

        return True

    def import_ephemeral_key(self, value, type):
        key_no = len(self.keys) + 1
        key_id= "eph_" + str(key_no)
        self.keys[key_id] = PnCryptKey(key_id, "ephemeral no:" + str(key_no), value, type)
        return self.keys[key_id]

    def get_key(self, key_id):
        return self.keys.get(key_id, None)
        
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)
