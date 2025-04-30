#!/bin/bash
if [ $# -eq 0 ]
    then
        echo "No arguments supplied exiting"
        exit 1
    else
        TARGET=$1
        TARGET_FILE=${TARGET}"_requirements.txt"
        echo "Freezing <" $TARGET "> into " $TARGET_FILE
fi
pip freeze>$TARGET_FILE
