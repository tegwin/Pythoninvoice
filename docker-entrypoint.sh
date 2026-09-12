#!/bin/sh
# Writes data/db_config.json from environment variables, waits for the
# database, loads the schema, then starts the app.
set -e

CONFIG_DIR=/app/data
CONFIG_FILE="$CONFIG_DIR/db_config.json"

mkdir -p "$CONFIG_DIR" /app/static/uploads

# database.py reads its settings from this file, not from the environment,
# so translate the env vars into the file it expects on every boot.
cat > "$CONFIG_FILE" <<EOF
{
  "type": "mysql",
  "mysql_host": "${MYSQL_HOST:-db}",
  "mysql_port": ${MYSQL_PORT:-3306},
  "mysql_user": "${MYSQL_USER:-invoice}",
  "mysql_password": "${MYSQL_PASSWORD:-invoice}",
  "mysql_database": "${MYSQL_DATABASE:-invoice_manager}",
  "mysql_ssl": ${MYSQL_SSL:-false}
}
EOF

echo "Waiting for MySQL at ${MYSQL_HOST:-db}:${MYSQL_PORT:-3306} ..."
for i in $(seq 1 60); do
    if python -c "
import sys, mysql.connector
try:
    mysql.connector.connect(
        host='${MYSQL_HOST:-db}', port=${MYSQL_PORT:-3306},
        user='${MYSQL_USER:-invoice}', password='${MYSQL_PASSWORD:-invoice}',
        database='${MYSQL_DATABASE:-invoice_manager}', connection_timeout=3).close()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        echo "Database is up."
        break
    fi
    [ "$i" = "60" ] && { echo "ERROR: database never became reachable."; exit 1; }
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
    host=os.environ.get('MYSQL_HOST', 'db'),
    port=int(os.environ.get('MYSQL_PORT', 3306)),
    user=os.environ.get('MYSQL_USER', 'invoice'),
    password=os.environ.get('MYSQL_PASSWORD', 'invoice'),
    database=os.environ.get('MYSQL_DATABASE', 'invoice_manager'),
)
cur = conn.cursor()
for stmt in statements:
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
