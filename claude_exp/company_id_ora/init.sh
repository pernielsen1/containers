#!/bin/bash
# Select the active database: oracle or mysql.
# Writes the choice to db.conf which up/down/test scripts read.
case "${1:-}" in
    oracle|mysql)
        echo "DB_TYPE=$1" > "$(dirname "$0")/db.conf"
        echo "Active database set to: $1"
        ;;
    *)
        echo "Usage: $0 oracle|mysql"
        exit 1
        ;;
esac
