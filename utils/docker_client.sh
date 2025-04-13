#!/bin/bash
echo "passed:"  $1
docker exec -it $1 sh
