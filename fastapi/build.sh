#!/bin/bash
# https://www.datacamp.com/tutorial/set-up-and-configure-mysql-in-docker
# https://fastapi.tiangolo.com/tutorial/first-steps/
# source app/bin/activate
# https://fastapi.tiangolo.com/deployment/docker/#one-process-per-container
# https://docs.docker.com/compose/gettingstarted/
# script assumes we are in the build_fastapi_venv.sh homedir i.e. app just below us...
NO_CACHE=""
if [ $# -eq 0 ]
    then
        echo "No arguments supplied"
    else
        echo "Argument" $1 " supplied"
        if [ "$1" = "REBUILD" ]
            then
                NO_CACHE="--no-cache"
            else
                echo "illegal argument " $1 " supplied - valid is REBUILD or no argument - exiting"
        fi
fi
echo "NO_CACHE is:" $NO_CACHE

echo "build requirements.txt"
app/bin/python -m pip freeze > requirements.txt
# docker compose up
docker compose build $NO_CACHEdoc
docker compose up
docker ps
