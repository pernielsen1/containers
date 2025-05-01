#!/bin/bash
if [[ -z "${VIRTUAL_ENV}" ]]; then
    echo "Not in virtual environment exiting"
    exit 1
else
    TARGET=$(basename $VIRTUAL_ENV)
    TARGET_FILE=${TARGET}"_requirements.txt"
    echo "Freezing <" $TARGET "> into " $TARGET_FILE
fi
pip freeze>$TARGET_FILE
