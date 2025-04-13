#!/bin/bash
mysql -h localhost -u $PN_MYSQL_USER -p$PN_MYSQL_PASSWORD --protocol=TCP  pn_crypto_key_store
