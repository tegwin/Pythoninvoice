#!/bin/sh
# Writes data/db_config.json from environment variables, waits for the
# database, loads the schema, then starts the app.
set -e

# Railway's MySQL service exports MYSQLHOST/MYSQLPORT/... (no underscore).
# Accept those as fallbacks so the same image runs under compose and Railway.
DB_HOST="${MYSQL_HOST:-${MYSQLHOST:-db}}"
DB_PORT="${MYSQL_PORT:-${MYSQLPORT:-3306}}"
DB_USER="${MYSQL_USER:-${MYSQLUSER:-invoice}}"
DB_PASS="${MYSQL_PASSWORD:-${MYSQLPASSWORD:-}}"
DB_NAME="${MYSQL_DATABASE:-${MYSQLDATABASE:-invoice_manager}}"

export DB_HOST DB_PORT DB_USER DB_PASS DB_NAME

CONFIG_DIR=/app/data
CONFIG_FILE="$CONFIG_DIR/db_config.json"

if [ -z "$DB_PASS" ]; then
    echo "ERROR: set MYSQL_PASSWORD (or MYSQLPASSWORD). No default is provided."
    exit 1
fi

mkdir -p "$CONFIG_DIR" /app/static/uploads

# database.py reads its settings from this file, not from the environment,
# so translate the env vars into the file it expects on every boot.
cat > "$CONFIG_FILE" <<EOF
{
  "type": "mysql",
  "mysql_host": "${DB_HOST}",
  "mysql_port": ${DB_PORT},
  "mysql_user": "${DB_USER}",
  "mysql_password": "${DB_PASS}",
  "mysql_database": "${DB_NAME}",
  "mysql_ssl": ${MYSQL_SSL:-false}
}
EOF

echo "Waiting for MySQL at ${DB_HOST}:${DB_PORT} ..."
for i in $(seq 1 60); do
    if python -c "
import os, sys, mysql.connector
try:
    mysql.connector.connect(
        host=os.environ['DB_HOST'], port=int(os.environ['DB_PORT']),
        user=os.environ['DB_USER'], password=os.environ['DB_PASS'],
        database=os.environ['DB_NAME'],
        connection_timeout=3, use_pure=True).close()
except Exception as e:
    print(e, file=sys.stderr)
    sys.exit(1)
" 2>/tmp/dbwait.err; then
        echo "Database is up."
        break
    fi
    if [ "$i" = "60" ]; then
        echo "ERROR: database never became reachable."
        cat /tmp/dbwait.err
        exit 1
    fi
    sleep 2
done

# Load the schema. Every statement is IF NOT EXISTS, so this is safe on
# each restart and on an already-populated database.
if [ -f /app/schema.sql ]; then
    echo "Applying schema..."
    python - <<'PY'
import os, re, mysql.connector

sql = open('/app/schema.sql').read()
# Strip comments, then split on ';' - no stored routines here, so this is safe.
sql = re.sub(r'^\s*--.*$', '', sql, flags=re.M)
statements = [s.strip() for s in sql.split(';') if s.strip()]

conn = mysql.connector.connect(
    host=os.environ['DB_HOST'], port=int(os.environ['DB_PORT']),
    user=os.environ['DB_USER'], password=os.environ['DB_PASS'],
    database=os.environ['DB_NAME'], use_pure=True,
)
cur = conn.cursor()
for stmt in statements:
    # Never let the file switch database - the configured name may differ.
    if re.match(r'^(CREATE\s+DATABASE|USE)\b', stmt, re.IGNORECASE):
        continue
    try:
        cur.execute(stmt)
    except mysql.connector.Error as e:
        # 1050 table exists, 1061 duplicate index - both fine on a re-run.
        if e.errno not in (1050, 1061):
            print(f"  skipped: {e}")
conn.commit()
cur.close()
conn.close()
print("Schema applied.")
PY
fi

exec "$@"
