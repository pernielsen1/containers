#!/bin/bash
set -e

# Start MySQL
service mysql start

# Wait for MySQL to be ready
echo "Waiting for MySQL to start..."
until mysqladmin ping --silent 2>/dev/null; do
    sleep 1
done
echo "MySQL is ready."

# Create MySQL user from environment variables
MYSQL_USER="${PN_MYSQL_USER:-appuser}"
MYSQL_PASSWORD="${PN_MYSQL_PASSWORD:-apppassword}"

mysql -u root <<-EOSQL
    CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'localhost' IDENTIFIED BY '${MYSQL_PASSWORD}';
    GRANT ALL PRIVILEGES ON *.* TO '${MYSQL_USER}'@'localhost' WITH GRANT OPTION;
    FLUSH PRIVILEGES;
EOSQL

echo "MySQL user '${MYSQL_USER}' configured."

# Keep container running (exec bash for interactive use)
exec bash
