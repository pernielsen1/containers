#!/bin/bash
# https://www.datacamp.com/tutorial/set-up-and-configure-mysql-in-docker
CONTAINER=test-mysql
docker start $CONTAINER
docker exec  test-mysql bash -c /recipies/wait_mysql.sh

