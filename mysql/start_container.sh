#!/bin/bash
# when the data directory is empty on startup i.e. container_data/mysql then 
# the Mysql image will run scripts found in start_up of this directory
# this creates the necessary tables in the database.
# access the container online:  docker exec -it mysql_container bash
# go into into the database is 
# mysql -u root -p PerN_db
#
# https://stackoverflow.com/questions/43322033/create-database-on-docker-compose-startup
NO_CACHE=""
BUILD=false
if [ $# -eq 0 ]
    then
        echo "No arguments supplied"
    else
        echo "Argument" $1 " supplied"
        if [ "$1" = "REBUILD" ]; then
            NO_CACHE="--no-cache"
            BUILD=true
        elif [ "$1" = "BUILD" ]; then
            BUILD=true
        else
           echo "illegal argument " $1 " supplied - valid is REBUILD  BUILD or no argument - exiting"
        fi
fi
mkdir ../../container_data/mysql
mkdir ../../container_data/mysql/pn_crypto_key_store_db

if [ "$BUILD" = true ] ; then
#    docker rmi mysql:latest -f  
    echo "building"
#    docker compose build $NO_CACHE # build it
    docker compose pull
fi
docker compose up --remove-orphans 
