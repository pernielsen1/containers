#!/bin/bash
# adapted from:
# https://www.reddit.com/r/docker/comments/mje7u2/dockercompose_dynamically_static_port_assignments/
NUM_SERVICES=2
echo "services:">docker-compose.yml
for (( i = 1; i <= $NUM_SERVICES; i++ )) 
    do
        export SERVICE_NAME="api${i}"
        export PORT=$((8000 + i))
        echo "$(envsubst < docker-compose.template.yml)">>docker-compose.yml
    done
cat docker-compose-nginx.yml>>docker-compose.yml
# cat docker-compose.yml | more
# make the common package available for install
docker compose up --remove-orphans 
