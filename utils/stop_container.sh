#!/bin/bash
mytask=$1
echo "stopping " $mytask
docker stop $mytask
echo "waiting for " $mytask " to stop"
docker wait $mytask
echo "the " $mytask " is stopped"
