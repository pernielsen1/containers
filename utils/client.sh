#!/bin/bash
if [ $# -eq 0 ]; then
  echo "no container name passed - listing active containers"
  docker ps --format '{{.Names}}'	
else
  echo "passed:"  $1
  docker exec -it $1 sh
fi

