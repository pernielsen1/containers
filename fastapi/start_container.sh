#!/bin/bash
# https://www.datacamp.com/tutorial/set-up-and-configure-mysql-in-docker
# https://fastapi.tiangolo.com/tutorial/first-steps/
# source app/bin/activate
# https://fastapi.tiangolo.com/deployment/docker/#one-process-per-container
# https://docs.docker.com/compose/gettingstarted/
# script assumes we are in the build_fastapi_venv.sh homedir i.e. app just below us...
#v https://docs.docker.com/reference/compose-file/build/
# adapted from:
# https://www.reddit.com/r/docker/comments/mje7u2/dockercompose_dynamically_static_port_assignments/

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
export BUILD_COMMAND="build: ./app"
echo "services:">docker-compose.yml  # top of file
NUM_SERVICES=2
for (( i = 1; i <= $NUM_SERVICES; i++ )) 
    do
        export SERVICE_NAME="api${i}"
        export PORT=$((8000 + i))
        echo "$(envsubst < docker-compose.template.yml)">>docker-compose.yml
        export BUILD_COMMAND=""
    done
cat docker-compose-nginx.yml>>docker-compose.yml

# ...do something interesting...
if [ "$BUILD" = true ] ; then
    # build requirements.txt and remove the local_packages line and make them available in the local packages dir to be used in Dockerfile 
    source app/bin/activate
    app/bin/python -m pip freeze > app/requirements.txt
    sed -i "/@ file:/d" app/requirements.txt
    # the common packages are copied to local packages when venv is built
    pip install app/local_packages/pn_utilities-0.1.tar.gz
    deactivate    build: ./app
    docker compose build $NO_CACHE # build it
fi
# let's start the containers
docker compose up --remove-orphans 
