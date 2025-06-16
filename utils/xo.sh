#!/bin/bash
function govenvx() {
    cwd=$(pwd)
    if [ ! -d "$1" ]; then
        echo "$1 does not exist - we go the guess way."
        cd ~/containers/$1
    else
        echo "$1 does exist - we cd into it"
        cd $1
    fi
    echo "activate and restore orignal working directory"
    source bin/activate
    cd $cwd
}
export -f govenvx
govenvx $1