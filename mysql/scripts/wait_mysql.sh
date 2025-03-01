#!/bin/bash
# https://github.com/docker-library/mysql/issues/547
set -e
echo "Check DB!"
while ! mysqladmin -u $MYSQL_USER -p$MYSQL_PASSWORD ping -h localhost; do
    echo "Wait ..."
    sleep 1
done
echo "DB is listening "
while ! mysql -u $MYSQL_USER -p$MYSQL_PASSWORD -e "SELECT @@global.read_only"; do
    echo "Waiting again..."
    sleep 1
done
timeout 5 mysql -u $MYSQL_USER -p$MYSQL_PASSWORD -e "SELECT @@global.read_only"
echo "DB is ready"
