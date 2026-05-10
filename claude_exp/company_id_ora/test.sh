#!/bin/bash
# Run company-ID validation tests against the selected database.
# Optional args (CID, VAT, XJUSTIZ) are forwarded to the test script.
DIR="$(dirname "$0")"
source "$DIR/db.conf" 2>/dev/null || { echo "Run ./init.sh oracle|mysql first"; exit 1; }

case "$DB_TYPE" in
    oracle)
        python3 "$DIR/test_company_id.py" "$@"
        ;;
    mysql)
        export MYSQL_USER="$PN_MYSQL_USER"
        export MYSQL_PASSWORD="$PN_MYSQL_PASSWORD"
        python3 "$DIR/../company_id_sql/test_company_id.py" "$@"
        ;;
esac
