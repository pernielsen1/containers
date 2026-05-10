#!/bin/bash
DIR="$(dirname "$0")"
source "$DIR/db.conf" 2>/dev/null || { echo "Run ./init.sh oracle|mysql first"; exit 1; }

case "$DB_TYPE" in
    oracle) docker compose -f "$DIR/compose.yaml"       up -d ;;
    mysql)  docker compose -f "$DIR/compose_mysql.yaml" up -d ;;
esac
