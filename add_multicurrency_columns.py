"""
Add multi-currency and tax authority columns to existing database.
Run this once to enable multi-currency support and tax authority integration.
"""

import sys
sys.path.insert(0, '.')

from database import get_db

def add_columns():
    """Add new columns for multi-currency and tax authority."""
    
    alterations = [
        # Tax authority settings
        ("company_settings", "tax_authority", "VARCHAR(100)"),
        ("company_settings", "tax_authority_api_key", "VARCHAR(500)"),
        ("company_settings", "tax_authority_email", "VARCHAR(255)"),
        # Accountant settings
        ("company_settings", "accountant_name", "VARCHAR(255)"),
        ("company_settings", "accountant_email", "VARCHAR(255)"),
        ("company_settings", "accountant_phone", "VARCHAR(100)"),
        # Invoice exchange rate fields
        ("invoices", "exchange_rate", "DECIMAL(15,6) DEFAULT 1"),
        ("invoices", "base_currency", "VARCHAR(10)"),
        ("invoices", "base_total", "DECIMAL(15,2)"),
        # Bill exchange rate fields
        ("bills", "exchange_rate", "DECIMAL(15,6) DEFAULT 1"),
        ("bills", "base_currency", "VARCHAR(10)"),
        ("bills", "base_total", "DECIMAL(15,2)"),
    ]
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Add columns to existing tables
        for table, column, col_type in alterations:
            try:
                cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {col_type}")  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                print(f"✅ Added {table}.{column}")
            except Exception as e:
                if 'Duplicate column' in str(e) or '1060' in str(e):
                    print(f"✓ {table}.{column} already exists")
                else:
                    print(f"❌ {table}.{column}: {e}")
        
        # Create VAT submissions table
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS vat_submissions (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    period_start DATE NOT NULL,
                    period_end DATE NOT NULL,
                    output_vat DECIMAL(15,2) DEFAULT 0,
                    input_vat DECIMAL(15,2) DEFAULT 0,
                    net_vat DECIMAL(15,2) DEFAULT 0,
                    total_sales DECIMAL(15,2) DEFAULT 0,
                    total_purchases DECIMAL(15,2) DEFAULT 0,
                    checklist_sales_verified TINYINT DEFAULT 0,
                    checklist_vat_numbers TINYINT DEFAULT 0,
                    checklist_credit_notes TINYINT DEFAULT 0,
                    checklist_expenses_receipts TINYINT DEFAULT 0,
                    checklist_partial_exemption TINYINT DEFAULT 0,
                    checklist_reverse_charge TINYINT DEFAULT 0,
                    checklist_eu_supply TINYINT DEFAULT 0,
                    checklist_accountant_reviewed TINYINT DEFAULT 0,
                    submitted_to_authority TINYINT DEFAULT 0,
                    submitted_to_authority_at TIMESTAMP NULL,
                    submitted_to_accountant TINYINT DEFAULT 0,
                    submitted_to_accountant_at TIMESTAMP NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_vat_period (user_id, period_start, period_end)
                )
            ''')
            print("✅ Created vat_submissions table")
        except Exception as e:
            if 'already exists' in str(e).lower() or '1050' in str(e):
                print("✓ vat_submissions table already exists")
            else:
                print(f"❌ vat_submissions table: {e}")
        
        conn.commit()
    
    print("\n✅ Multi-currency and tax authority columns added!")
    return True

if __name__ == '__main__':
    add_columns()
