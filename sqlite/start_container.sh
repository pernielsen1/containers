#!/bin/bash
# https://www.hibit.dev/posts/215/setting-up-sqlite-with-docker-compose
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
mkdir ../../container_data/sqlite
if [ "$BUILD" = true ] ; then
    echo "building"
    docker compose build $NO_CACHE # build it
fi
docker compose up --remove-orphans 
