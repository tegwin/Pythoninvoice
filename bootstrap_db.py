#!/usr/bin/env python3
"""Resolve DB settings, wait for the server, apply schema.sql.

Runs from docker-entrypoint.sh before the app starts. Config comes from
either a connection URL (Railway exposes MYSQL_URL / MYSQL_PRIVATE_URL) or
individual variables (docker compose). A URL is preferred because it avoids
having to match five separate variable names.
"""
import json
import os
import re
import sys
import time
from urllib.parse import urlparse, unquote

import mysql.connector

CONFIG_PATH = '/app/data/db_config.json'
SCHEMA_PATH = '/app/schema.sql'

# Railway's own names have no underscore; compose uses the underscored ones.
URL_VARS = ('MYSQL_URL', 'MYSQL_PRIVATE_URL', 'DATABASE_URL')


def first_env(*names):
    """Return the first env var that is set AND non-empty.

    Railway resolves a reference to a variable that does not exist as an
    empty string rather than leaving it unset, so `or` on '' matters here.
    """
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


# A pasted value often carries the variable name, quotes or a stray newline
# with it. Pull the URL out of whatever surrounds it rather than failing.
URL_RE = re.compile(r'(mysql|mariadb)://\S+')


def clean_url(raw):
    """Return just the connection URL from a value that may have extra text."""
    m = URL_RE.search(raw.strip().strip('"\''))
    return m.group(0).rstrip('",\'') if m else None


def resolve_config():
    raw = first_env(*URL_VARS)
    url = clean_url(raw) if raw else None
    if raw and not url:
        print(f"WARNING: ignoring a connection URL that contains no mysql:// "
              f"address; falling back to individual variables.", file=sys.stderr)
    if url:
        u = urlparse(url)
        if not u.hostname:
            sys.exit(f"ERROR: could not parse a host out of the connection URL in "
                     f"{[n for n in URL_VARS if os.environ.get(n)][0]}")
        return {
            'type': 'mysql',
            'mysql_host': u.hostname,
            'mysql_port': u.port or 3306,
            'mysql_user': unquote(u.username or ''),
            'mysql_password': unquote(u.password or ''),
            'mysql_database': (u.path or '/').lstrip('/') or 'invoice_manager',
            'mysql_ssl': os.environ.get('MYSQL_SSL', 'false').lower() == 'true',
        }

    host = first_env('MYSQL_HOST', 'MYSQLHOST')
    password = first_env('MYSQL_PASSWORD', 'MYSQLPASSWORD')
    if not host or not password:
        sys.exit(
            "ERROR: no database configuration found.\n"
            "  Set one of MYSQL_URL / MYSQL_PRIVATE_URL / DATABASE_URL,\n"
            "  or all of MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE.\n"
            f"  Saw: host={host or '(empty)'} "
            f"password={'(set)' if password else '(empty)'}\n"
            "  On Railway an empty value usually means the ${{Service.VAR}} "
            "reference name does not match the database service."
        )
    return {
        'type': 'mysql',
        'mysql_host': host,
        'mysql_port': int(first_env('MYSQL_PORT', 'MYSQLPORT') or 3306),
        'mysql_user': first_env('MYSQL_USER', 'MYSQLUSER') or 'invoice',
        'mysql_password': password,
        'mysql_database': first_env('MYSQL_DATABASE', 'MYSQLDATABASE') or 'invoice_manager',
        'mysql_ssl': os.environ.get('MYSQL_SSL', 'false').lower() == 'true',
    }


def connect(cfg, timeout=5):
    return mysql.connector.connect(
        host=cfg['mysql_host'], port=cfg['mysql_port'],
        user=cfg['mysql_user'], password=cfg['mysql_password'],
        database=cfg['mysql_database'],
        connection_timeout=timeout,
        # The bundled C extension has no IPv6 support, which is all
        # Railway's private network offers.
        use_pure=True,
    )


def wait_for_db(cfg, attempts=60, delay=2):
    last = None
    for i in range(attempts):
        try:
            connect(cfg).close()
            print("Database is up.")
            return
        except Exception as e:
            last = e
            time.sleep(delay)
    sys.exit(f"ERROR: database never became reachable after "
             f"{attempts * delay}s: {last}")


def apply_schema(cfg):
    if not os.path.exists(SCHEMA_PATH):
        return
    print("Applying schema...")
    sql = re.sub(r'^\s*--.*$', '', open(SCHEMA_PATH).read(), flags=re.M)
    conn = connect(cfg, timeout=30)
    cur = conn.cursor()
    for stmt in (s.strip() for s in sql.split(';')):
        # Never let the file switch database - the configured name may differ.
        if not stmt or re.match(r'^(CREATE\s+DATABASE|USE)\b', stmt, re.I):
            continue
        try:
            cur.execute(stmt)
        except mysql.connector.Error as e:
            # 1050 table exists, 1061 duplicate index - fine on a re-run.
            if e.errno not in (1050, 1061):
                print(f"  skipped: {e}")
    conn.commit()
    cur.close()
    conn.close()
    print("Schema applied.")


def seed_demo_if_empty(cfg):
    """On a demo service, seed sample data when the database is still empty.

    Only ever runs against an empty users table, so it cannot overwrite
    anything. Saves needing the cron service to fire before the demo is
    usable on a freshly created database.
    """
    if os.environ.get('DEMO_MODE', '').lower() not in ('1', 'true', 'yes'):
        return
    conn = connect(cfg, timeout=30)
    cur = conn.cursor()
    try:
        cur.execute('SELECT COUNT(*) FROM users')
        row = cur.fetchone()
        count = row['COUNT(*)'] if isinstance(row, dict) else row[0]
    except Exception:
        return
    finally:
        cur.close()
        conn.close()

    if count:
        return
    print('Demo database is empty - seeding sample data...')
    import reset_demo
    reset_demo.main()


def write_config(cfg):
    """Persist the resolved settings where database.py expects them.

    database.py reads this file rather than the environment, so anything that
    imports app_core needs it on disk first.
    """
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    os.makedirs('/app/static/uploads', exist_ok=True)
    with open(CONFIG_PATH, 'w') as fh:
        json.dump(cfg, fh, indent=2)
    os.chmod(CONFIG_PATH, 0o600)


def main():
    cfg = resolve_config()
    write_config(cfg)

    print(f"Database target: {cfg['mysql_user']}@{cfg['mysql_host']}:"
          f"{cfg['mysql_port']}/{cfg['mysql_database']}")
    wait_for_db(cfg)
    apply_schema(cfg)
    seed_demo_if_empty(cfg)


if __name__ == '__main__':
    main()
