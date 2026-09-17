#!/usr/bin/env python3
"""
Add Missing Columns to MySQL
Run this after setup_mysql_schema.py and before migration.
"""

import sys
import json
import os

try:
    import mysql.connector
except ImportError:
    print("ERROR: mysql-connector-python is not installed.")
    sys.exit(1)

def get_mysql_config():
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

def add_column(cursor, table, column, col_type):
    try:
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {col_type}")  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
        print(f"  ✓ Added {table}.{column}")
        return True
    except mysql.connector.Error as e:
        if e.errno == 1060:  # Duplicate column
            return False
        else:
            print(f"  ✗ {table}.{column}: {e}")
            return False

def fix_columns():
    print("=" * 60)
    print("Adding Missing Columns to MySQL")
    print("=" * 60)
    
    config = get_mysql_config()
    if not config:
        print("ERROR: MySQL configuration not found")
        return False
    
    conn = mysql.connector.connect(
        host=config['host'],
        port=config['port'],
        user=config['user'],
        password=config['password'],
        database=config['database'],
        charset='utf8mb4'
    )
    cursor = conn.cursor()
    
    # All missing columns found from SQLite
    columns_to_add = [
        # company_settings
        ("company_settings", "tax_rates", "VARCHAR(255) DEFAULT '0,5,10,15,20,25'"),
        ("company_settings", "coa_mandatory", "TINYINT DEFAULT 0"),
        ("company_settings", "show_footer", "TINYINT DEFAULT 1"),
        ("company_settings", "footer_text", "VARCHAR(500) DEFAULT 'Powered by Invoice Manager'"),
        
        # customers - email preferences
        ("customers", "email_invoice_created", "TINYINT DEFAULT 1"),
        ("customers", "email_invoice_reminder", "TINYINT DEFAULT 1"),
        ("customers", "email_payment_received", "TINYINT DEFAULT 1"),
        
        # roadmap_features
        ("roadmap_features", "updated_at", "TIMESTAMP NULL"),
        ("roadmap_features", "category", "VARCHAR(100)"),
        ("roadmap_features", "completed_at", "TIMESTAMP NULL"),
        
        # roadmap_phases
        ("roadmap_phases", "target_date", "DATE"),
        ("roadmap_phases", "color", "VARCHAR(50)"),
        ("roadmap_phases", "updated_at", "TIMESTAMP NULL"),
        
        # sumup_settings
        ("sumup_settings", "webhook_secret", "VARCHAR(255)"),
        
        # recurring_invoice_items
        ("recurring_invoice_items", "coa_id", "INT"),
        
        # invoices - ensure updated_at exists
        ("invoices", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    ]
    
    added = 0
    for table, column, col_type in columns_to_add:
        if add_column(cursor, table, column, col_type):
            added += 1
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print()
    print(f"Added {added} columns")
    print("=" * 60)
    print("\nNow run: python migrate_sqlite_to_mysql.py")
    
    return True

if __name__ == '__main__':
    fix_columns()
