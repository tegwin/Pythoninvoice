"""
Add Microsoft Graph email columns to existing database.
Run this once to enable Microsoft Graph email integration.
"""

import sys
sys.path.insert(0, '.')

from database import get_db

def add_graph_columns():
    """Add Microsoft Graph email columns."""
    
    alterations = [
        ("company_settings", "email_provider", "VARCHAR(50) DEFAULT 'smtp'"),
        ("company_settings", "graph_tenant_id", "VARCHAR(255)"),
        ("company_settings", "graph_client_id", "VARCHAR(255)"),
        ("company_settings", "graph_client_secret", "VARCHAR(500)"),
        ("company_settings", "graph_sender_email", "VARCHAR(255)"),
    ]
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        for table, column, col_type in alterations:
            try:
                cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {col_type}")  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                print(f"✅ Added {table}.{column}")
            except Exception as e:
                if 'Duplicate column' in str(e) or '1060' in str(e):
                    print(f"✓ {table}.{column} already exists")
                else:
                    print(f"❌ {table}.{column}: {e}")
        
        conn.commit()
    
    print("\n✅ Microsoft Graph email columns added!")
    print("\nYou can now configure Microsoft Graph in Settings > Email Settings")
    return True

if __name__ == '__main__':
    add_graph_columns()
