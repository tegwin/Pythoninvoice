#!/bin/sh
# Resolve DB config, wait for the server and apply the schema, then run the app.
set -e
python /app/bootstrap_db.py
exec "$@"
