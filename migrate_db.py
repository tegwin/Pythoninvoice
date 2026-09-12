"""
Database Migration Script
Run this to add new columns to existing databases.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'invoices.db')

def migrate():
    """Add missing columns to existing database."""
    if not os.path.exists(DB_PATH):
        print("No database found. A new one will be created when you run the app.")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    migrations = [
        # Users table - add role and parent_user_id columns
        ("users", "role", "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'owner'"),
        ("users", "parent_user_id", "ALTER TABLE users ADD COLUMN parent_user_id INTEGER"),
        ("users", "active", "ALTER TABLE users ADD COLUMN active INTEGER DEFAULT 1"),
        ("users", "display_name", "ALTER TABLE users ADD COLUMN display_name TEXT"),
        ("users", "phone", "ALTER TABLE users ADD COLUMN phone TEXT"),
        ("users", "timezone", "ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'Europe/London'"),
        ("users", "bio", "ALTER TABLE users ADD COLUMN bio TEXT"),
        ("users", "avatar_path", "ALTER TABLE users ADD COLUMN avatar_path TEXT"),
        ("users", "totp_secret", "ALTER TABLE users ADD COLUMN totp_secret TEXT"),
        ("users", "totp_enabled", "ALTER TABLE users ADD COLUMN totp_enabled INTEGER DEFAULT 0"),
        ("users", "backup_codes", "ALTER TABLE users ADD COLUMN backup_codes TEXT"),
        ("users", "login_count", "ALTER TABLE users ADD COLUMN login_count INTEGER DEFAULT 0"),
        
        # Company settings - SMTP and reminder columns
        ("company_settings", "smtp_host", "ALTER TABLE company_settings ADD COLUMN smtp_host TEXT"),
        ("company_settings", "smtp_port", "ALTER TABLE company_settings ADD COLUMN smtp_port INTEGER DEFAULT 587"),
        ("company_settings", "smtp_username", "ALTER TABLE company_settings ADD COLUMN smtp_username TEXT"),
        ("company_settings", "smtp_password", "ALTER TABLE company_settings ADD COLUMN smtp_password TEXT"),
        ("company_settings", "smtp_use_tls", "ALTER TABLE company_settings ADD COLUMN smtp_use_tls INTEGER DEFAULT 1"),
        ("company_settings", "smtp_from_email", "ALTER TABLE company_settings ADD COLUMN smtp_from_email TEXT"),
        ("company_settings", "reminders_enabled", "ALTER TABLE company_settings ADD COLUMN reminders_enabled INTEGER DEFAULT 0"),
        ("company_settings", "reminder_1_days", "ALTER TABLE company_settings ADD COLUMN reminder_1_days INTEGER DEFAULT 7"),
        ("company_settings", "reminder_2_days", "ALTER TABLE company_settings ADD COLUMN reminder_2_days INTEGER DEFAULT 0"),
        ("company_settings", "reminder_3_days", "ALTER TABLE company_settings ADD COLUMN reminder_3_days INTEGER DEFAULT -7"),
        ("company_settings", "max_reminders", "ALTER TABLE company_settings ADD COLUMN max_reminders INTEGER DEFAULT 3"),
        ("company_settings", "send_payment_thanks", "ALTER TABLE company_settings ADD COLUMN send_payment_thanks INTEGER DEFAULT 0"),
        
        # Branding columns
        ("company_settings", "brand_name", "ALTER TABLE company_settings ADD COLUMN brand_name TEXT"),
        ("company_settings", "brand_logo_path", "ALTER TABLE company_settings ADD COLUMN brand_logo_path TEXT"),
        ("company_settings", "show_brand_name", "ALTER TABLE company_settings ADD COLUMN show_brand_name INTEGER DEFAULT 1"),
        ("company_settings", "show_brand_logo", "ALTER TABLE company_settings ADD COLUMN show_brand_logo INTEGER DEFAULT 0"),
        ("company_settings", "show_powered_by", "ALTER TABLE company_settings ADD COLUMN show_powered_by INTEGER DEFAULT 0"),
        ("company_settings", "tax_rates", "ALTER TABLE company_settings ADD COLUMN tax_rates TEXT DEFAULT '0,5,10,15,20,25'"),
        ("company_settings", "show_footer", "ALTER TABLE company_settings ADD COLUMN show_footer INTEGER DEFAULT 1"),
        ("company_settings", "footer_text", "ALTER TABLE company_settings ADD COLUMN footer_text TEXT DEFAULT 'Powered by Invoice Manager'"),
        # Currency API integration
        ("company_settings", "currency_api_key", "ALTER TABLE company_settings ADD COLUMN currency_api_key TEXT"),
        ("company_settings", "currency_api_provider", "ALTER TABLE company_settings ADD COLUMN currency_api_provider TEXT DEFAULT 'currencyapi'"),
        ("company_settings", "auto_update_rates", "ALTER TABLE company_settings ADD COLUMN auto_update_rates INTEGER DEFAULT 0"),
        ("company_settings", "rates_last_updated", "ALTER TABLE company_settings ADD COLUMN rates_last_updated TIMESTAMP"),
        
        # Products - billing term for services and COA
        ("products", "billing_term", "ALTER TABLE products ADD COLUMN billing_term TEXT"),
        ("products", "coa_id", "ALTER TABLE products ADD COLUMN coa_id INTEGER"),
        
        # Customer email preferences
        ("customers", "email_invoice_created", "ALTER TABLE customers ADD COLUMN email_invoice_created INTEGER DEFAULT 1"),
        ("customers", "email_invoice_reminder", "ALTER TABLE customers ADD COLUMN email_invoice_reminder INTEGER DEFAULT 1"),
        ("customers", "email_payment_received", "ALTER TABLE customers ADD COLUMN email_payment_received INTEGER DEFAULT 1"),
        
        # Invoice items COA
        ("invoice_items", "coa_id", "ALTER TABLE invoice_items ADD COLUMN coa_id INTEGER"),
        
        # Recurring invoice items COA
        ("recurring_invoice_items", "coa_id", "ALTER TABLE recurring_invoice_items ADD COLUMN coa_id INTEGER"),
        
        # Company settings - COA mandatory
        ("company_settings", "coa_mandatory", "ALTER TABLE company_settings ADD COLUMN coa_mandatory INTEGER DEFAULT 0"),
    ]
    
    # Check which columns exist
    def column_exists(table, column):
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cursor.fetchall()]
        return column in columns
    
    print("Running database migrations...")
    
    for table, column, sql in migrations:
        if not column_exists(table, column):
            try:
                cursor.execute(sql)
                print(f"  ✅ Added {table}.{column}")
            except sqlite3.OperationalError as e:
                print(f"  ⚠️ Could not add {table}.{column}: {e}")
        else:
            print(f"  ✓ {table}.{column} already exists")
    
    # Create new tables if they don't exist
    new_tables = [
        ("team_members", '''
            CREATE TABLE IF NOT EXISTS team_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                member_user_id INTEGER NOT NULL,
                role TEXT DEFAULT 'viewer',
                permissions TEXT DEFAULT '[]',
                invited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                accepted_at TIMESTAMP,
                active INTEGER DEFAULT 1,
                FOREIGN KEY (owner_user_id) REFERENCES users (id),
                FOREIGN KEY (member_user_id) REFERENCES users (id),
                UNIQUE(owner_user_id, member_user_id)
            )
        '''),
        ("email_templates", '''
            CREATE TABLE IF NOT EXISTS email_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                template_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(user_id, template_type)
            )
        '''),
        ("email_log", '''
            CREATE TABLE IF NOT EXISTS email_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                invoice_id INTEGER,
                customer_id INTEGER,
                email_type TEXT NOT NULL,
                to_email TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                error_message TEXT,
                sent_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (invoice_id) REFERENCES invoices (id),
                FOREIGN KEY (customer_id) REFERENCES customers (id)
            )
        '''),
        ("invoice_reminders", '''
            CREATE TABLE IF NOT EXISTS invoice_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                reminder_number INTEGER DEFAULT 1,
                days_before_due INTEGER DEFAULT 7,
                scheduled_date DATE,
                sent_at TIMESTAMP,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE CASCADE
            )
        '''),
        ("user_preferences", '''
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                preference_key TEXT NOT NULL,
                preference_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(user_id, preference_key)
            )
        '''),
        ("currency_rates", '''
            CREATE TABLE IF NOT EXISTS currency_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                base_currency TEXT NOT NULL,
                target_currency TEXT NOT NULL,
                rate REAL NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(user_id, base_currency, target_currency)
            )
        '''),
        ("enabled_currencies", '''
            CREATE TABLE IF NOT EXISTS enabled_currencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                currency_code TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(user_id, currency_code)
            )
        '''),
        ("chart_of_accounts", '''
            CREATE TABLE IF NOT EXISTS chart_of_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                account_type TEXT NOT NULL,
                description TEXT,
                parent_id INTEGER,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (parent_id) REFERENCES chart_of_accounts (id),
                UNIQUE(user_id, code)
            )
        '''),
        ("recurring_invoices", '''
            CREATE TABLE IF NOT EXISTS recurring_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                frequency TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE,
                next_invoice_date DATE NOT NULL,
                last_invoice_date DATE,
                currency TEXT DEFAULT 'GBP',
                tax_rate REAL DEFAULT 0,
                notes TEXT,
                payment_terms TEXT,
                auto_send INTEGER DEFAULT 0,
                send_days_before INTEGER DEFAULT 0,
                invoice_prefix TEXT DEFAULT 'REC-',
                invoices_generated INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (customer_id) REFERENCES customers (id)
            )
        '''),
        ("recurring_invoice_items", '''
            CREATE TABLE IF NOT EXISTS recurring_invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recurring_invoice_id INTEGER NOT NULL,
                product_id INTEGER,
                description TEXT NOT NULL,
                quantity REAL DEFAULT 1,
                unit_price REAL DEFAULT 0,
                tax_rate REAL DEFAULT 0,
                line_total REAL DEFAULT 0,
                is_recurring_item INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (recurring_invoice_id) REFERENCES recurring_invoices (id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        '''),
        ("incoming_webhooks", '''
            CREATE TABLE IF NOT EXISTS incoming_webhooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                endpoint_key TEXT NOT NULL UNIQUE,
                secret_key TEXT,
                provider TEXT DEFAULT 'generic',
                active INTEGER DEFAULT 1,
                last_received_at TIMESTAMP,
                receive_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        '''),
        ("incoming_webhook_logs", '''
            CREATE TABLE IF NOT EXISTS incoming_webhook_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                webhook_id INTEGER NOT NULL,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                payload TEXT,
                headers TEXT,
                status TEXT DEFAULT 'received',
                response TEXT,
                invoice_id INTEGER,
                FOREIGN KEY (webhook_id) REFERENCES incoming_webhooks (id) ON DELETE CASCADE,
                FOREIGN KEY (invoice_id) REFERENCES invoices (id)
            )
        '''),
        ("stripe_settings", '''
            CREATE TABLE IF NOT EXISTS stripe_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                enabled INTEGER DEFAULT 0,
                live_mode INTEGER DEFAULT 0,
                test_publishable_key TEXT,
                test_secret_key TEXT,
                live_publishable_key TEXT,
                live_secret_key TEXT,
                webhook_secret TEXT,
                include_in_invoice_pdf INTEGER DEFAULT 1,
                include_in_email INTEGER DEFAULT 1,
                payment_button_text TEXT DEFAULT 'Pay Now with Card',
                success_url TEXT,
                cancel_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        '''),
        ("stripe_payment_sessions", '''
            CREATE TABLE IF NOT EXISTS stripe_payment_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                invoice_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                payment_intent_id TEXT,
                payment_url TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (invoice_id) REFERENCES invoices (id)
            )
        '''),
        ("stripe_webhook_logs", '''
            CREATE TABLE IF NOT EXISTS stripe_webhook_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_type TEXT,
                event_id TEXT,
                invoice_id INTEGER,
                status TEXT,
                message TEXT,
                payload TEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (invoice_id) REFERENCES invoices (id)
            )
        '''),
        ("credit_notes", '''
            CREATE TABLE IF NOT EXISTS credit_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                credit_note_number TEXT NOT NULL,
                customer_id INTEGER,
                invoice_id INTEGER,
                status TEXT DEFAULT 'draft',
                issue_date DATE DEFAULT CURRENT_DATE,
                currency TEXT DEFAULT 'GBP',
                tax_rate REAL DEFAULT 0,
                subtotal REAL DEFAULT 0,
                tax_amount REAL DEFAULT 0,
                total REAL DEFAULT 0,
                amount_used REAL DEFAULT 0,
                reason TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (customer_id) REFERENCES customers (id),
                FOREIGN KEY (invoice_id) REFERENCES invoices (id)
            )
        '''),
        ("credit_note_items", '''
            CREATE TABLE IF NOT EXISTS credit_note_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                credit_note_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                quantity REAL DEFAULT 1,
                unit_price REAL DEFAULT 0,
                tax_rate REAL DEFAULT 0,
                line_total REAL DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (credit_note_id) REFERENCES credit_notes (id) ON DELETE CASCADE
            )
        '''),
        ("credit_note_applications", '''
            CREATE TABLE IF NOT EXISTS credit_note_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                credit_note_id INTEGER NOT NULL,
                invoice_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                FOREIGN KEY (credit_note_id) REFERENCES credit_notes (id),
                FOREIGN KEY (invoice_id) REFERENCES invoices (id)
            )
        '''),
        ("suppliers", '''
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                contact_name TEXT,
                email TEXT,
                phone TEXT,
                address_line1 TEXT,
                address_line2 TEXT,
                city TEXT,
                state TEXT,
                postal_code TEXT,
                country TEXT DEFAULT 'United Kingdom',
                tax_id TEXT,
                payment_terms INTEGER DEFAULT 30,
                default_coa_id INTEGER,
                notes TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        '''),
        ("bills", '''
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                supplier_id INTEGER,
                bill_number TEXT NOT NULL,
                reference TEXT,
                bill_date DATE NOT NULL,
                due_date DATE,
                currency TEXT DEFAULT 'GBP',
                tax_rate REAL DEFAULT 0,
                subtotal REAL DEFAULT 0,
                tax_amount REAL DEFAULT 0,
                total REAL DEFAULT 0,
                amount_paid REAL DEFAULT 0,
                status TEXT DEFAULT 'draft',
                notes TEXT,
                attachment_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
            )
        '''),
        ("bill_items", '''
            CREATE TABLE IF NOT EXISTS bill_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER NOT NULL,
                description TEXT,
                quantity REAL DEFAULT 1,
                unit_price REAL DEFAULT 0,
                total REAL DEFAULT 0,
                coa_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (bill_id) REFERENCES bills (id) ON DELETE CASCADE,
                FOREIGN KEY (coa_id) REFERENCES chart_of_accounts (id)
            )
        '''),
        ("bill_payments", '''
            CREATE TABLE IF NOT EXISTS bill_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                payment_date DATE NOT NULL,
                payment_method TEXT,
                reference TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (bill_id) REFERENCES bills (id) ON DELETE CASCADE
            )
        '''),
        ("expenses", '''
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                supplier_id INTEGER,
                coa_id INTEGER,
                expense_date DATE NOT NULL,
                description TEXT,
                category TEXT,
                amount REAL NOT NULL,
                tax_rate REAL DEFAULT 0,
                tax_amount REAL DEFAULT 0,
                net_amount REAL DEFAULT 0,
                currency TEXT DEFAULT 'GBP',
                payment_method TEXT,
                reference TEXT,
                receipt_path TEXT,
                is_billable INTEGER DEFAULT 0,
                is_reimbursable INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
                FOREIGN KEY (coa_id) REFERENCES chart_of_accounts (id)
            )
        '''),
    ]
    
    for table_name, sql in new_tables:
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if not cursor.fetchone():
            cursor.execute(sql)
            print(f"  ✅ Created table {table_name}")
        else:
            print(f"  ✓ Table {table_name} already exists")
    
    conn.commit()
    conn.close()
    
    print("\n✅ Migration complete!")

if __name__ == '__main__':
    migrate()
