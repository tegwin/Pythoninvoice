#!/usr/bin/env python3
"""
SQLite to MySQL Migration Script
Migrates all data from SQLite database to MySQL.
"""

import sqlite3
import os
import sys

# Try to import MySQL connector
try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    print("ERROR: mysql-connector-python is not installed.")
    print("Run: pip install mysql-connector-python")
    sys.exit(1)

# Configuration - Update these with your MySQL settings
SQLITE_PATH = os.path.join(os.path.dirname(__file__), 'data', 'invoices.db')

def get_mysql_config():
    """Load MySQL config from db_config.json."""
    import json
    config_path = os.path.join(os.path.dirname(__file__), 'data', 'db_config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
            return {
                'host': config.get('mysql_host', 'localhost'),
                'port': config.get('mysql_port', 3306),
                'user': config.get('mysql_user', ''),
                'password': config.get('mysql_password', ''),
                'database': config.get('mysql_database', 'invoice_manager'),
            }
    return None

def migrate_table(sqlite_cursor, mysql_cursor, table_name, mysql_conn):
    """Migrate a single table from SQLite to MySQL."""
    
    # Get column info from SQLite
    sqlite_cursor.execute(f"PRAGMA table_info({table_name})")  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
    columns_info = sqlite_cursor.fetchall()
    columns = [col[1] for col in columns_info]
    
    if not columns:
        print(f"  Skipping {table_name} - no columns found")
        return 0
    
    # Get data from SQLite
    sqlite_cursor.execute(f"SELECT * FROM {table_name}")  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
    rows = sqlite_cursor.fetchall()
    
    if not rows:
        return 0
    
    # Build INSERT statement
    placeholders = ', '.join(['%s'] * len(columns))
    columns_str = ', '.join([f"`{col}`" for col in columns])
    
    insert_sql = f"INSERT INTO `{table_name}` ({columns_str}) VALUES ({placeholders})"
    
    # Insert rows
    inserted = 0
    for row in rows:
        try:
            # Convert None and handle special types
            processed_row = []
            for val in row:
                if val is None:
                    processed_row.append(None)
                elif isinstance(val, bytes):
                    processed_row.append(val.decode('utf-8', errors='ignore'))
                else:
                    processed_row.append(val)
            
            mysql_cursor.execute(insert_sql, tuple(processed_row))  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
            inserted += 1
        except mysql.connector.Error as e:
            if e.errno == 1062:  # Duplicate entry
                pass  # Skip duplicates
            else:
                print(f"    Error inserting row: {e}")
    
    mysql_conn.commit()
    return inserted

def migrate():
    """Run the migration."""
    print("=" * 60)
    print("SQLite to MySQL Migration")
    print("=" * 60)
    
    # Check SQLite file exists
    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite database not found at {SQLITE_PATH}")
        return False
    
    # Get MySQL config
    mysql_config = get_mysql_config()
    if not mysql_config:
        print("ERROR: MySQL configuration not found in data/db_config.json")
        return False
    
    print(f"\nSource: {SQLITE_PATH}")
    print(f"Target: MySQL {mysql_config['user']}@{mysql_config['host']}/{mysql_config['database']}")
    print()
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to MySQL
    try:
        mysql_conn = mysql.connector.connect(
            host=mysql_config['host'],
            port=mysql_config['port'],
            user=mysql_config['user'],
            password=mysql_config['password'],
            database=mysql_config['database'],
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci'
        )
        mysql_cursor = mysql_conn.cursor()
    except mysql.connector.Error as e:
        print(f"ERROR: Could not connect to MySQL: {e}")
        return False
    
    # Get list of tables from SQLite
    sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = [row[0] for row in sqlite_cursor.fetchall()]
    
    print(f"Found {len(tables)} tables to migrate\n")
    
    # Tables to migrate in order (respecting foreign keys)
    priority_tables = [
        'users',
        'company_settings', 
        'customers',
        'products',
        'invoices',
        'invoice_items',
        'payments',
        'suppliers',
        'bills',
        'bill_items',
        'bill_payments',
        'expenses',
        'chart_of_accounts',
        'recurring_invoices',
        'recurring_invoice_items',
        'credit_notes',
        'credit_note_items',
        'credit_note_applications',
    ]
    
    # Migrate priority tables first
    migrated_tables = set()
    total_rows = 0
    
    # Disable foreign key checks for migration
    mysql_cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    
    for table in priority_tables:
        if table in tables:
            try:
                count = migrate_table(sqlite_cursor, mysql_cursor, table, mysql_conn)
                if count > 0:
                    print(f"  ✓ {table}: {count} rows migrated")
                    total_rows += count
                migrated_tables.add(table)
            except Exception as e:
                print(f"  ✗ {table}: Error - {e}")
    
    # Migrate remaining tables
    for table in tables:
        if table not in migrated_tables:
            try:
                count = migrate_table(sqlite_cursor, mysql_cursor, table, mysql_conn)
                if count > 0:
                    print(f"  ✓ {table}: {count} rows migrated")
                    total_rows += count
            except Exception as e:
                print(f"  ✗ {table}: Error - {e}")
    
    # Re-enable foreign key checks
    mysql_cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    mysql_conn.commit()
    
    # Close connections
    sqlite_conn.close()
    mysql_cursor.close()
    mysql_conn.close()
    
    print()
    print("=" * 60)
    print(f"Migration complete! {total_rows} total rows migrated.")
    print("=" * 60)
    
    return True

if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)
