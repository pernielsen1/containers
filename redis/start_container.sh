#!/bin/bash
# https://geshan.com.np/blog/2022/01/redis-docker/
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
mkdir ../../container_data/redis
mkdir ../../container_data/redis/cache

if [ "$BUILD" = true ] ; then
    echo "building"
    docker compose pull
fi
echo "starting redis_container in detached mode log into the container to see what's going on"
docker compose up --remove-orphans  -d
