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

# build requirements.txt and remove the local_packages line and make them available in the local packages dir to be used in Dockerfile 
source app/bin/activate
app/bin/python -m pip freeze > requirements.txt
sed -i "/@ file:/d" requirements.txt
mkdir local_packages
cp ../common/dist/* local_packages
deactivate
# build it and start it
docker compose build $NO_CACHE
docker compose up

