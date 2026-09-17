"""
Invoice Manager - Core Application Module
Handles database operations, user authentication, and data models.
"""

import os
import re
import json
import sqlite3
import hashlib
import secrets
import uuid as uuid_lib
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple

# Import get_db from database module (supports MySQL and SQLite)
from database import get_db

# Database path (used for SQLite fallback)
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DB_PATH = os.path.join(DATA_DIR, 'invoices.db')

os.makedirs(DATA_DIR, exist_ok=True)


# =============================================================================
# Database Connection Management
# =============================================================================

# get_db is now imported from database.py which handles MySQL/SQLite switching


# Columns added after the original tables shipped. A database created by an
# earlier version still has the old layout, and init_database() skips table
# creation entirely once the tables exist, so these are applied separately on
# every startup.
REQUIRED_COLUMNS = [
    # CustomerManager.create() always inserts a generated uuid.
    ('customers', 'uuid', 'VARCHAR(36)', 'TEXT'),
    ('customers', 'email_invoice_created', 'TINYINT DEFAULT 1', 'INTEGER DEFAULT 1'),
    ('customers', 'email_invoice_reminder', 'TINYINT DEFAULT 1', 'INTEGER DEFAULT 1'),
    ('customers', 'email_payment_received', 'TINYINT DEFAULT 1', 'INTEGER DEFAULT 1'),
    # Multi-currency.
    ('invoices', 'exchange_rate', 'DECIMAL(15,6) DEFAULT 1', 'REAL DEFAULT 1'),
    ('invoices', 'base_currency', 'VARCHAR(10)', 'TEXT'),
    ('invoices', 'base_total', 'DECIMAL(15,2)', 'REAL'),
    ('bills', 'exchange_rate', 'DECIMAL(15,6) DEFAULT 1', 'REAL DEFAULT 1'),
    ('bills', 'base_currency', 'VARCHAR(10)', 'TEXT'),
    ('bills', 'base_total', 'DECIMAL(15,2)', 'REAL'),
    # Chart of Accounts on line items.
    ('products', 'coa_id', 'INT', 'INTEGER'),
    ('invoice_items', 'coa_id', 'INT', 'INTEGER'),
    ('company_settings', 'coa_mandatory', 'TINYINT DEFAULT 0', 'INTEGER DEFAULT 0'),
    # Email provider settings (SMTP vs Microsoft Graph).
    ('company_settings', 'email_provider', "VARCHAR(50) DEFAULT 'smtp'", 'TEXT'),
    ('company_settings', 'email_invoice_created', 'TINYINT DEFAULT 0', 'INTEGER DEFAULT 0'),
    ('company_settings', 'graph_tenant_id', 'VARCHAR(255)', 'TEXT'),
    ('company_settings', 'graph_client_id', 'VARCHAR(255)', 'TEXT'),
    ('company_settings', 'graph_client_secret', 'VARCHAR(500)', 'TEXT'),
    ('company_settings', 'graph_sender_email', 'VARCHAR(255)', 'TEXT'),
    # VAT / tax submission details.
    ('company_settings', 'accountant_name', 'VARCHAR(255)', 'TEXT'),
    ('company_settings', 'accountant_email', 'VARCHAR(255)', 'TEXT'),
    ('company_settings', 'accountant_phone', 'VARCHAR(100)', 'TEXT'),
    ('company_settings', 'tax_authority', 'VARCHAR(100)', 'TEXT'),
    ('company_settings', 'tax_authority_api_key', 'VARCHAR(500)', 'TEXT'),
    ('company_settings', 'tax_authority_email', 'VARCHAR(255)', 'TEXT'),
    # Payment source tracking.
    ('payments', 'created_via', 'VARCHAR(100)', 'TEXT'),
    # Outbound webhook fields used by api_webhooks.py.
    ('webhooks', 'webhook_id', 'VARCHAR(255)', 'TEXT'),
    ('webhooks', 'name', 'VARCHAR(255)', 'TEXT'),
    ('webhooks', 'auth_type', 'VARCHAR(50)', 'TEXT'),
    ('webhooks', 'auth_value', 'VARCHAR(255)', 'TEXT'),
    ('webhooks', 'headers', 'TEXT', 'TEXT'),
    ('webhooks', 'last_status', 'VARCHAR(50)', 'TEXT'),
    ('webhooks', 'last_error', 'TEXT', 'TEXT'),
    ('webhooks', 'trigger_count', 'INT DEFAULT 0', 'INTEGER DEFAULT 0'),
]


SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')


def apply_schema_file(cursor):
    """Create every table from the bundled schema.sql.

    The per-module CREATE TABLE calls below only run when that module is first
    used, so a fresh database is otherwise missing most tables until you happen
    to visit the right page. Applying the full schema up front avoids that.
    Every statement is IF NOT EXISTS, so this is safe on each startup.
    """
    if not os.path.exists(SCHEMA_FILE):
        return False

    with open(SCHEMA_FILE, 'r', encoding='utf-8') as fh:
        sql = fh.read()

    sql = re.sub(r'^\s*--.*$', '', sql, flags=re.M)

    applied = 0
    for statement in sql.split(';'):
        statement = statement.strip()
        if not statement:
            continue
        # The connection is already pointed at the configured database, which
        # may not be called invoice_manager - never let the file switch it.
        if re.match(r'^(CREATE\s+DATABASE|USE)\b', statement, re.IGNORECASE):
            continue
        try:
            cursor.execute(statement)
            applied += 1
        except Exception:
            # Already exists, or a duplicate index - both fine on a re-run.
            pass
    return applied > 0


def ensure_required_columns(cursor, is_mysql):
    """Add any missing columns listed in REQUIRED_COLUMNS. Safe to re-run."""
    for table, column, mysql_type, sqlite_type in REQUIRED_COLUMNS:
        try:
            if is_mysql:
                cursor.execute('''
                    SELECT COUNT(*) AS n FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND table_name = ? AND column_name = ?
                ''', (table, column))
                row = cursor.fetchone()
                # Cursors are created with dictionary=True, but fall back to
                # positional access in case that ever changes.
                count = row['n'] if isinstance(row, dict) else row[0]
                exists = count > 0
                col_type = mysql_type
            else:
                cursor.execute(f"PRAGMA table_info({table})")  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                exists = any(row[1] == column for row in cursor.fetchall())
                col_type = sqlite_type

            if not exists:
                cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                    f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'
                )
                print(f"  Added missing column {table}.{column}")
        except Exception as e:
            # A missing table is fine here - the module that owns it will
            # create it (with the column already present) on first use.
            print(f"  Note: could not check {table}.{column}: {e}")


def init_database():
    """Initialize database with all required tables."""
    from database import get_db_config

    db_config = get_db_config()
    is_mysql = db_config.get('type') == 'mysql'

    with get_db() as conn:
        cursor = conn.cursor()

        if is_mysql:
            # Create everything from the bundled schema, then top up any
            # columns an older database is missing.
            apply_schema_file(cursor)
            ensure_required_columns(cursor, is_mysql)

            cursor.execute("SHOW TABLES LIKE 'users'")
            if cursor.fetchone():
                # Tables already exist - nothing further to create.
                conn.commit()
                return

            # MySQL syntax - use VARCHAR instead of TEXT for columns with defaults
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    email VARCHAR(255),
                    display_name VARCHAR(255),
                    phone VARCHAR(100),
                    timezone VARCHAR(100) DEFAULT 'Europe/London',
                    bio TEXT,
                    avatar_path VARCHAR(500),
                    role VARCHAR(50) DEFAULT 'owner',
                    parent_user_id INT,
                    totp_secret VARCHAR(255),
                    totp_enabled TINYINT DEFAULT 0,
                    backup_codes TEXT,
                    login_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP NULL,
                    active TINYINT DEFAULT 1
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS team_members (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    owner_user_id INT NOT NULL,
                    member_user_id INT NOT NULL,
                    role VARCHAR(50) DEFAULT 'viewer',
                    permissions TEXT,
                    invited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accepted_at TIMESTAMP NULL,
                    active TINYINT DEFAULT 1,
                    UNIQUE KEY unique_team (owner_user_id, member_user_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS company_settings (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    company_name VARCHAR(255),
                    address_line1 VARCHAR(255),
                    address_line2 VARCHAR(255),
                    city VARCHAR(100),
                    state VARCHAR(100),
                    postal_code VARCHAR(50),
                    country VARCHAR(100),
                    phone VARCHAR(100),
                    email VARCHAR(255),
                    website VARCHAR(255),
                    logo_path VARCHAR(500),
                    default_tax_rate DECIMAL(10,2) DEFAULT 0,
                    default_currency VARCHAR(10) DEFAULT 'GBP',
                    invoice_prefix VARCHAR(50) DEFAULT 'INV',
                    invoice_next_number INT DEFAULT 1001,
                    payment_terms TEXT,
                    bank_details TEXT,
                    smtp_host VARCHAR(255),
                    smtp_port INT DEFAULT 587,
                    smtp_username VARCHAR(255),
                    smtp_password VARCHAR(255),
                    smtp_use_tls TINYINT DEFAULT 1,
                    smtp_from_email VARCHAR(255),
                    reminders_enabled TINYINT DEFAULT 0,
                    reminder_1_days INT DEFAULT 7,
                    reminder_2_days INT DEFAULT 0,
                    reminder_3_days INT DEFAULT -7,
                    max_reminders INT DEFAULT 3,
                    send_payment_thanks TINYINT DEFAULT 0,
                    brand_name VARCHAR(255),
                    brand_logo_path VARCHAR(500),
                    show_brand_name TINYINT DEFAULT 1,
                    show_brand_logo TINYINT DEFAULT 0,
                    show_powered_by TINYINT DEFAULT 0,
                    tax_rates VARCHAR(255) DEFAULT '0,5,10,15,20,25',
                    show_footer TINYINT DEFAULT 1,
                    footer_text VARCHAR(500) DEFAULT 'Powered by Invoice Manager',
                    currency_api_key VARCHAR(255),
                    currency_api_provider VARCHAR(100) DEFAULT 'currencyapi',
                    auto_update_rates TINYINT DEFAULT 0,
                    rates_last_updated TIMESTAMP NULL
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customers (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    uuid VARCHAR(36),
                    user_id INT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    email VARCHAR(255),
                    phone VARCHAR(100),
                    address_line1 VARCHAR(255),
                    address_line2 VARCHAR(255),
                    city VARCHAR(100),
                    state VARCHAR(100),
                    postal_code VARCHAR(50),
                    country VARCHAR(100),
                    tax_number VARCHAR(100),
                    custom_tax_rate DECIMAL(10,2),
                    custom_currency VARCHAR(10),
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    unit_price DECIMAL(15,2) NOT NULL DEFAULT 0,
                    unit VARCHAR(50) DEFAULT 'unit',
                    sku VARCHAR(100),
                    is_service TINYINT DEFAULT 0,
                    billing_term VARCHAR(100),
                    taxable TINYINT DEFAULT 1,
                    active TINYINT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS invoices (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    customer_id INT,
                    invoice_number VARCHAR(100) NOT NULL,
                    status VARCHAR(50) DEFAULT 'draft',
                    issue_date DATE,
                    due_date DATE,
                    currency VARCHAR(10) DEFAULT 'GBP',
                    tax_rate DECIMAL(10,2) DEFAULT 0,
                    subtotal DECIMAL(15,2) DEFAULT 0,
                    tax_amount DECIMAL(15,2) DEFAULT 0,
                    total DECIMAL(15,2) DEFAULT 0,
                    amount_paid DECIMAL(15,2) DEFAULT 0,
                    notes TEXT,
                    payment_terms TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    paid_at TIMESTAMP NULL
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS invoice_items (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    invoice_id INT NOT NULL,
                    product_id INT,
                    description TEXT NOT NULL,
                    quantity DECIMAL(15,4) DEFAULT 1,
                    unit_price DECIMAL(15,2) DEFAULT 0,
                    tax_rate DECIMAL(10,2) DEFAULT 0,
                    line_total DECIMAL(15,2) DEFAULT 0,
                    sort_order INT DEFAULT 0
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    invoice_id INT NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    payment_date DATE NOT NULL,
                    payment_method VARCHAR(100),
                    reference VARCHAR(255),
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    key_hash VARCHAR(255) NOT NULL,
                    key_prefix VARCHAR(20) NOT NULL,
                    permissions TEXT,
                    last_used TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    active TINYINT DEFAULT 1
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS webhooks (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    url VARCHAR(500) NOT NULL,
                    events TEXT,
                    secret VARCHAR(255),
                    active TINYINT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_triggered TIMESTAMP NULL,
                    failure_count INT DEFAULT 0
                )
            ''')
            
            conn.commit()
            return
        
        # SQLite syntax (original code)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT,
                display_name TEXT,
                phone TEXT,
                timezone TEXT DEFAULT 'Europe/London',
                bio TEXT,
                avatar_path TEXT,
                role TEXT DEFAULT 'owner',
                parent_user_id INTEGER,
                totp_secret TEXT,
                totp_enabled INTEGER DEFAULT 0,
                backup_codes TEXT,
                login_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                active INTEGER DEFAULT 1,
                FOREIGN KEY (parent_user_id) REFERENCES users (id)
            )
        ''')
        
        # Team members / sub-users table
        cursor.execute('''
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
        ''')
        
        # Company Settings table (global settings per user)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS company_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                company_name TEXT,
                address_line1 TEXT,
                address_line2 TEXT,
                city TEXT,
                state TEXT,
                postal_code TEXT,
                country TEXT,
                phone TEXT,
                email TEXT,
                website TEXT,
                logo_path TEXT,
                default_tax_rate REAL DEFAULT 0,
                default_currency TEXT DEFAULT 'GBP',
                invoice_prefix TEXT DEFAULT 'INV',
                invoice_next_number INTEGER DEFAULT 1001,
                payment_terms TEXT,
                bank_details TEXT,
                smtp_host TEXT,
                smtp_port INTEGER DEFAULT 587,
                smtp_username TEXT,
                smtp_password TEXT,
                smtp_use_tls INTEGER DEFAULT 1,
                smtp_from_email TEXT,
                reminders_enabled INTEGER DEFAULT 0,
                reminder_1_days INTEGER DEFAULT 7,
                reminder_2_days INTEGER DEFAULT 0,
                reminder_3_days INTEGER DEFAULT -7,
                max_reminders INTEGER DEFAULT 3,
                send_payment_thanks INTEGER DEFAULT 0,
                brand_name TEXT,
                brand_logo_path TEXT,
                show_brand_name INTEGER DEFAULT 1,
                show_brand_logo INTEGER DEFAULT 0,
                show_powered_by INTEGER DEFAULT 0,
                tax_rates TEXT DEFAULT '0,5,10,15,20,25',
                show_footer INTEGER DEFAULT 1,
                footer_text TEXT DEFAULT 'Powered by Invoice Manager',
                currency_api_key TEXT,
                currency_api_provider TEXT DEFAULT 'currencyapi',
                auto_update_rates INTEGER DEFAULT 0,
                rates_last_updated TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Customers table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                address_line1 TEXT,
                address_line2 TEXT,
                city TEXT,
                state TEXT,
                postal_code TEXT,
                country TEXT,
                tax_number TEXT,
                custom_tax_rate REAL,
                custom_currency TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Products/Services table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                unit_price REAL NOT NULL DEFAULT 0,
                unit TEXT DEFAULT 'unit',
                sku TEXT,
                is_service INTEGER DEFAULT 0,
                billing_term TEXT,
                taxable INTEGER DEFAULT 1,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Invoices table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                customer_id INTEGER,
                invoice_number TEXT NOT NULL,
                status TEXT DEFAULT 'draft',
                issue_date DATE DEFAULT CURRENT_DATE,
                due_date DATE,
                currency TEXT DEFAULT 'GBP',
                tax_rate REAL DEFAULT 0,
                subtotal REAL DEFAULT 0,
                tax_amount REAL DEFAULT 0,
                total REAL DEFAULT 0,
                amount_paid REAL DEFAULT 0,
                notes TEXT,
                payment_terms TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (customer_id) REFERENCES customers (id)
            )
        ''')
        
        # Invoice Line Items table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                product_id INTEGER,
                description TEXT NOT NULL,
                quantity REAL DEFAULT 1,
                unit_price REAL DEFAULT 0,
                tax_rate REAL DEFAULT 0,
                line_total REAL DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')
        
        # Payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                payment_method TEXT,
                reference TEXT,
                notes TEXT,
                payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_via TEXT DEFAULT 'manual',
                FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE CASCADE
            )
        ''')
        
        # API Keys table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                key_hash TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                permissions TEXT DEFAULT '["read", "write"]',
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Webhooks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS webhooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                webhook_id TEXT UNIQUE NOT NULL,
                name TEXT,
                url TEXT NOT NULL,
                events TEXT NOT NULL,
                secret TEXT NOT NULL,
                headers TEXT DEFAULT '{}',
                auth_type TEXT,
                auth_value TEXT,
                active INTEGER DEFAULT 1,
                trigger_count INTEGER DEFAULT 0,
                last_triggered TIMESTAMP,
                last_status INTEGER,
                last_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Email templates table
        cursor.execute('''
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
        ''')
        
        # Email log table
        cursor.execute('''
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
        ''')
        
        # Invoice reminders table
        cursor.execute('''
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
        ''')
        
        # User preferences table (for storing UI state like filters)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                preference_key TEXT NOT NULL,
                preference_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(user_id, preference_key)
            )
        ''')
        
        # Currency rates table
        cursor.execute('''
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
        ''')
        
        # Enabled currencies table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS enabled_currencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                currency_code TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(user_id, currency_code)
            )
        ''')
        
        conn.commit()


# =============================================================================
# User Authentication
# =============================================================================

def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return hashlib.sha256(password.encode()).hexdigest()


def create_user(username: str, password: str, email: str = None) -> Tuple[bool, str]:
    """Create a new user."""
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)',
                (username, hash_password(password), email)
            )
            user_id = cursor.lastrowid
            
            # Create default company settings
            cursor.execute(
                'INSERT INTO company_settings (user_id) VALUES (?)',
                (user_id,)
            )
            
            conn.commit()
            return True, 'User created successfully'
        except sqlite3.IntegrityError:
            return False, 'Username already exists'


def authenticate_user(username: str, password: str) -> Optional[Dict]:
    """Authenticate a user and return user data if valid."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM users WHERE username = ? AND password_hash = ?',
            (username, hash_password(password))
        )
        row = cursor.fetchone()
        
        if row:
            # Update last login
            cursor.execute(
                'UPDATE users SET last_login = ? WHERE id = ?',
                (datetime.now().isoformat(), row['id'])
            )
            conn.commit()
            return dict(row)
        return None


def change_password(user_id: int, old_password: str, new_password: str) -> Tuple[bool, str]:
    """Change a user's password."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT password_hash FROM users WHERE id = ?',
            (user_id,)
        )
        row = cursor.fetchone()
        
        if not row or row['password_hash'] != hash_password(old_password):
            return False, 'Current password is incorrect'
        
        cursor.execute(
            'UPDATE users SET password_hash = ? WHERE id = ?',
            (hash_password(new_password), user_id)
        )
        conn.commit()
        return True, 'Password changed successfully'


# =============================================================================
# Company Settings Manager
# =============================================================================

class SettingsManager:
    """Manage company settings for a user."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def get_settings(self) -> Dict:
        """Get company settings."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM company_settings WHERE user_id = ?',
                (self.user_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else {}
    
    # Alias for consistency
    get_all = get_settings
    
    def update_settings(self, updates: Dict) -> bool:
        """Update company settings."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Build dynamic update query
            fields = []
            values = []
            for key, value in updates.items():
                if key not in ('id', 'user_id'):
                    fields.append(f'{key} = ?')
                    values.append(value)
            
            if fields:
                values.append(self.user_id)
                cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                    f'UPDATE company_settings SET {", ".join(fields)} WHERE user_id = ?',
                    values
                )
                conn.commit()
                return True
            return False
    
    def get_next_invoice_number(self) -> str:
        """Get and increment the next invoice number."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT invoice_prefix, invoice_next_number FROM company_settings WHERE user_id = ?',
                (self.user_id,)
            )
            row = cursor.fetchone()
            
            prefix = row['invoice_prefix'] if row else 'INV'
            number = row['invoice_next_number'] if row else 1001
            
            # Increment for next time
            cursor.execute(
                'UPDATE company_settings SET invoice_next_number = ? WHERE user_id = ?',
                (number + 1, self.user_id)
            )
            conn.commit()
            
            return f'{prefix}-{number:05d}'


# =============================================================================
# Customer Manager
# =============================================================================

class CustomerManager:
    """Manage customers for a user."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def create(self, name: str, **kwargs) -> int:
        """Create a new customer."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # uuid is NOT NULL with no DB default - always generate one here
            fields = ['uuid', 'user_id', 'name']
            values = [str(uuid_lib.uuid4()), self.user_id, name]

            allowed_fields = ['email', 'phone', 'address_line1', 'address_line2',
                            'city', 'state', 'postal_code', 'country',
                            'tax_number', 'custom_tax_rate', 'custom_currency', 'notes']
            
            for field in allowed_fields:
                if field in kwargs and kwargs[field] is not None:
                    fields.append(field)
                    values.append(kwargs[field])
            
            placeholders = ', '.join(['?'] * len(values))
            cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                f'INSERT INTO customers ({", ".join(fields)}) VALUES ({placeholders})',
                values
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_all(self) -> List[Dict]:
        """Get all customers."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM customers WHERE user_id = ? ORDER BY name',
                (self.user_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get(self, customer_id: int) -> Optional[Dict]:
        """Get a specific customer."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM customers WHERE id = ? AND user_id = ?',
                (customer_id, self.user_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update(self, customer_id: int, updates: Dict) -> bool:
        """Update a customer."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            fields = []
            values = []
            for key, value in updates.items():
                if key not in ('id', 'uuid', 'user_id', 'created_at'):
                    fields.append(f'{key} = ?')
                    values.append(value)

            if fields:
                fields.append('updated_at = ?')
                values.append(datetime.now().isoformat())
                values.extend([customer_id, self.user_id])

                cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                    f'UPDATE customers SET {", ".join(fields)} WHERE id = ? AND user_id = ?',
                    values
                )
                conn.commit()
                return cursor.rowcount > 0
            return False
    
    def delete(self, customer_id: int) -> bool:
        """Delete a customer. Will fail if customer has invoices."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Check if customer has any invoices
            cursor.execute(
                'SELECT COUNT(*) AS cnt FROM invoices WHERE customer_id = ? AND user_id = ?',
                (customer_id, self.user_id)
            )
            result = cursor.fetchone()
            count = result['cnt'] if isinstance(result, dict) else result[0]
            if count > 0:
                raise ValueError(f"Cannot delete customer with {count} invoice(s). Delete or reassign invoices first.")
            
            # Delete related records first
            related_tables = [
                ('gocardless_mandates', 'customer_id'),
                ('gocardless_billing_requests', 'customer_id'),
                ('recurring_invoices', 'customer_id'),
                ('credit_notes', 'customer_id'),
            ]
            
            for table, column in related_tables:
                try:
                    cursor.execute(f'DELETE FROM {table} WHERE {column} = ?', (customer_id,))  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                except Exception:
                    pass  # Table might not exist
            
            cursor.execute(
                'DELETE FROM customers WHERE id = ? AND user_id = ?',
                (customer_id, self.user_id)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def get_by_email(self, email: str) -> Optional[Dict]:
        """Get a customer by email."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM customers WHERE email = ? AND user_id = ?',
                (email, self.user_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_by_name(self, name: str) -> Optional[Dict]:
        """Get a customer by name (exact match)."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM customers WHERE name = ? AND user_id = ?',
                (name, self.user_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None


# =============================================================================
# Product/Service Manager
# =============================================================================

class ProductManager:
    """Manage products and services for a user."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def create(self, name: str, unit_price: float, **kwargs) -> int:
        """Create a new product/service."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            fields = ['user_id', 'name', 'unit_price']
            values = [self.user_id, name, unit_price]
            
            allowed_fields = ['description', 'unit', 'sku', 'is_service', 'billing_term', 'taxable']
            
            for field in allowed_fields:
                if field in kwargs and kwargs[field] is not None:
                    fields.append(field)
                    values.append(kwargs[field])
            
            placeholders = ', '.join(['?'] * len(values))
            cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                f'INSERT INTO products ({", ".join(fields)}) VALUES ({placeholders})',
                values
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_all(self, active_only: bool = True, include_inactive: bool = False) -> List[Dict]:
        """Get all products/services."""
        if include_inactive:
            active_only = False
        with get_db() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM products WHERE user_id = ?'
            if active_only:
                query += ' AND active = 1'
            query += ' ORDER BY name'
            cursor.execute(query, (self.user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get(self, product_id: int) -> Optional[Dict]:
        """Get a specific product/service."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM products WHERE id = ? AND user_id = ?',
                (product_id, self.user_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update(self, product_id: int, updates: Dict) -> bool:
        """Update a product/service."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            fields = []
            values = []
            for key, value in updates.items():
                if key not in ('id', 'user_id', 'created_at'):
                    fields.append(f'{key} = ?')
                    values.append(value)
            
            if fields:
                fields.append('updated_at = ?')
                values.append(datetime.now().isoformat())
                values.extend([product_id, self.user_id])
                
                cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                    f'UPDATE products SET {", ".join(fields)} WHERE id = ? AND user_id = ?',
                    values
                )
                conn.commit()
                return cursor.rowcount > 0
            return False
    
    def delete(self, product_id: int) -> bool:
        """Delete (deactivate) a product/service."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE products SET active = 0 WHERE id = ? AND user_id = ?',
                (product_id, self.user_id)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def get_by_sku(self, sku: str) -> Optional[Dict]:
        """Get a product by SKU."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM products WHERE sku = ? AND user_id = ?',
                (sku, self.user_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_by_name(self, name: str) -> Optional[Dict]:
        """Get a product by name (exact match)."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM products WHERE name = ? AND user_id = ?',
                (name, self.user_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None


# =============================================================================
# Invoice Manager
# =============================================================================

class InvoiceManager:
    """Manage invoices for a user."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.settings = SettingsManager(user_id)
    
    def create(self, customer_id: int = None, **kwargs) -> int:
        """Create a new invoice."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get company settings for defaults
            settings = self.settings.get_settings()
            
            # Generate invoice number
            invoice_number = self.settings.get_next_invoice_number()
            
            # Get customer-specific overrides if customer selected
            tax_rate = settings.get('default_tax_rate', 0)
            currency = settings.get('default_currency', 'GBP')
            
            if customer_id:
                customer = CustomerManager(self.user_id).get(customer_id)
                if customer:
                    if customer.get('custom_tax_rate') is not None:
                        tax_rate = customer['custom_tax_rate']
                    if customer.get('custom_currency'):
                        currency = customer['custom_currency']
            
            # Allow override via kwargs
            tax_rate = kwargs.get('tax_rate', tax_rate)
            currency = kwargs.get('currency', currency)
            
            # Calculate due date
            issue_date = kwargs.get('issue_date', datetime.now().date().isoformat())
            due_date = kwargs.get('due_date')
            if not due_date:
                due_date = (datetime.now() + timedelta(days=30)).date().isoformat()
            
            cursor.execute('''
                INSERT INTO invoices (user_id, customer_id, invoice_number, status,
                                     issue_date, due_date, currency, tax_rate,
                                     notes, payment_terms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.user_id, customer_id, invoice_number, 'draft',
                issue_date, due_date, currency, tax_rate,
                kwargs.get('notes', ''), kwargs.get('payment_terms', settings.get('payment_terms', ''))
            ))
            
            conn.commit()
            return cursor.lastrowid
    
    def get_all(self, status: str = None) -> List[Dict]:
        """Get all invoices, optionally filtered by status."""
        with get_db() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT i.*, c.name as customer_name, c.email as customer_email
                FROM invoices i
                LEFT JOIN customers c ON i.customer_id = c.id
                WHERE i.user_id = ?
            '''
            params = [self.user_id]
            
            if status:
                query += ' AND i.status = ?'
                params.append(status)
            
            query += ' ORDER BY i.created_at DESC'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get(self, invoice_id: int) -> Optional[Dict]:
        """Get a specific invoice with all its items."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get invoice
            cursor.execute('''
                SELECT i.*, c.name as customer_name, c.email as customer_email,
                       c.address_line1 as customer_address1, c.address_line2 as customer_address2,
                       c.city as customer_city, c.state as customer_state,
                       c.postal_code as customer_postal, c.country as customer_country
                FROM invoices i
                LEFT JOIN customers c ON i.customer_id = c.id
                WHERE i.id = ? AND i.user_id = ?
            ''', (invoice_id, self.user_id))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            invoice = dict(row)
            
            # Get invoice items
            cursor.execute('''
                SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY sort_order
            ''', (invoice_id,))
            invoice['items'] = [dict(item) for item in cursor.fetchall()]
            
            # Get payments
            cursor.execute('''
                SELECT * FROM payments WHERE invoice_id = ? ORDER BY payment_date DESC
            ''', (invoice_id,))
            invoice['payments'] = [dict(pay) for pay in cursor.fetchall()]
            
            return invoice
    
    def get_by_number(self, invoice_number: str) -> Optional[Dict]:
        """Get an invoice by its number."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id FROM invoices WHERE invoice_number = ? AND user_id = ?',
                (invoice_number, self.user_id)
            )
            row = cursor.fetchone()
            if row:
                return self.get(row['id'])
            return None
    
    def add_item(self, invoice_id: int, description: str, quantity: float,
                 unit_price: float, product_id: int = None, tax_rate: float = None) -> int:
        """Add an item to an invoice."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Verify invoice belongs to user
            cursor.execute(
                'SELECT tax_rate FROM invoices WHERE id = ? AND user_id = ?',
                (invoice_id, self.user_id)
            )
            invoice = cursor.fetchone()
            if not invoice:
                return 0
            
            # Use invoice tax rate if not specified
            if tax_rate is None:
                tax_rate = invoice['tax_rate']
            
            line_total = quantity * unit_price
            
            # Get next sort order
            cursor.execute(
                'SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM invoice_items WHERE invoice_id = ?',
                (invoice_id,)
            )
            result = cursor.fetchone()
            sort_order = result['next_order'] if isinstance(result, dict) else (result[0] if result else 1) or 1
            
            cursor.execute('''
                INSERT INTO invoice_items (invoice_id, product_id, description,
                                          quantity, unit_price, tax_rate, line_total, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (invoice_id, product_id, description, quantity, unit_price,
                  tax_rate, line_total, sort_order))
            
            conn.commit()
            
            # Recalculate invoice totals
            self._recalculate_totals(invoice_id)
            
            return cursor.lastrowid
    
    def update_item(self, item_id: int, updates: Dict) -> bool:
        """Update an invoice item."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get invoice_id for this item
            cursor.execute('SELECT invoice_id FROM invoice_items WHERE id = ?', (item_id,))
            row = cursor.fetchone()
            if not row:
                return False
            
            invoice_id = row['invoice_id']
            
            # Verify invoice belongs to user
            cursor.execute(
                'SELECT id FROM invoices WHERE id = ? AND user_id = ?',
                (invoice_id, self.user_id)
            )
            if not cursor.fetchone():
                return False
            
            fields = []
            values = []
            for key, value in updates.items():
                if key in ('description', 'quantity', 'unit_price', 'tax_rate'):
                    fields.append(f'{key} = ?')
                    values.append(value)
            
            if fields:
                values.append(item_id)
                cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                    f'UPDATE invoice_items SET {", ".join(fields)} WHERE id = ?',
                    values
                )
                
                # Recalculate line total
                cursor.execute(
                    'UPDATE invoice_items SET line_total = quantity * unit_price WHERE id = ?',
                    (item_id,)
                )
                
                conn.commit()
                self._recalculate_totals(invoice_id)
                return True
            return False
    
    def remove_item(self, item_id: int) -> bool:
        """Remove an item from an invoice."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get invoice_id
            cursor.execute('SELECT invoice_id FROM invoice_items WHERE id = ?', (item_id,))
            row = cursor.fetchone()
            if not row:
                return False
            
            invoice_id = row['invoice_id']
            
            # Verify invoice belongs to user
            cursor.execute(
                'SELECT id FROM invoices WHERE id = ? AND user_id = ?',
                (invoice_id, self.user_id)
            )
            if not cursor.fetchone():
                return False
            
            cursor.execute('DELETE FROM invoice_items WHERE id = ?', (item_id,))
            conn.commit()
            
            self._recalculate_totals(invoice_id)
            return True
    
    def _recalculate_totals(self, invoice_id: int):
        """Recalculate invoice totals."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get all items
            cursor.execute('''
                SELECT line_total, tax_rate FROM invoice_items WHERE invoice_id = ?
            ''', (invoice_id,))
            items = cursor.fetchall()
            
            subtotal = sum(item['line_total'] for item in items)
            tax_amount = sum(item['line_total'] * (item['tax_rate'] / 100) for item in items)
            total = subtotal + tax_amount
            
            cursor.execute('''
                UPDATE invoices SET subtotal = ?, tax_amount = ?, total = ?, updated_at = ?
                WHERE id = ?
            ''', (subtotal, tax_amount, total, datetime.now().isoformat(), invoice_id))
            
            conn.commit()
    
    def update(self, invoice_id: int, updates: Dict) -> bool:
        """Update an invoice."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            allowed_fields = ['customer_id', 'status', 'issue_date', 'due_date',
                            'currency', 'tax_rate', 'notes', 'payment_terms']
            
            fields = []
            values = []
            for key, value in updates.items():
                if key in allowed_fields:
                    fields.append(f'{key} = ?')
                    values.append(value)
            
            if fields:
                fields.append('updated_at = ?')
                values.append(datetime.now().isoformat())
                values.extend([invoice_id, self.user_id])
                
                cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                    f'UPDATE invoices SET {", ".join(fields)} WHERE id = ? AND user_id = ?',
                    values
                )
                conn.commit()
                
                # If tax_rate changed, recalculate totals
                if 'tax_rate' in updates:
                    # Update all items to new tax rate
                    cursor.execute(
                        'UPDATE invoice_items SET tax_rate = ? WHERE invoice_id = ?',
                        (updates['tax_rate'], invoice_id)
                    )
                    conn.commit()
                    self._recalculate_totals(invoice_id)
                
                return cursor.rowcount > 0
            return False
    
    def update_status(self, invoice_id: int, status: str) -> bool:
        """Update invoice status."""
        valid_statuses = ['draft', 'sent', 'paid', 'overdue', 'cancelled']
        if status not in valid_statuses:
            return False
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            update_fields = ['status = ?', 'updated_at = ?']
            values = [status, datetime.now().isoformat()]
            
            # If marking as paid, set paid_at timestamp
            if status == 'paid':
                update_fields.append('paid_at = ?')
                values.append(datetime.now().isoformat())
            
            values.extend([invoice_id, self.user_id])
            
            cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                f'UPDATE invoices SET {", ".join(update_fields)} WHERE id = ? AND user_id = ?',
                values
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def delete(self, invoice_id: int) -> bool:
        """Delete an invoice and all related records.
        
        Returns True if deleted, raises ValueError with details if blocked.
        """
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Verify invoice belongs to user
            cursor.execute(
                'SELECT id, invoice_number FROM invoices WHERE id = ? AND user_id = ?',
                (invoice_id, self.user_id)
            )
            invoice = cursor.fetchone()
            if not invoice:
                return False
            
            invoice_number = invoice.get('invoice_number', f'#{invoice_id}') if isinstance(invoice, dict) else invoice[1]
            
            # Check for blocking dependencies (credit notes linked to this invoice)
            blocking_items = []
            
            # Check credit notes
            cursor.execute('SELECT COUNT(*) AS cnt FROM credit_notes WHERE invoice_id = ?', (invoice_id,))
            result = cursor.fetchone()
            cn_count = result['cnt'] if isinstance(result, dict) else result[0]
            if cn_count > 0:
                blocking_items.append(f"{cn_count} credit note(s)")
            
            # If there are blocking items, raise an error with details
            if blocking_items:
                raise ValueError(
                    f"Cannot delete invoice {invoice_number}. "
                    f"Please delete the following linked records first: {', '.join(blocking_items)}. "
                    f"Go to Credit Notes and delete any credit notes linked to this invoice."
                )
            
            # Delete related records that can be safely removed
            # Order matters - delete child records before parent
            safe_to_delete = [
                ('email_log', 'invoice_id'),
                ('invoice_reminders', 'invoice_id'),
                ('invoice_items', 'invoice_id'),
                ('payments', 'invoice_id'),
                ('stripe_payment_sessions', 'invoice_id'),
                ('gocardless_payments', 'invoice_id'),
                ('sumup_checkouts', 'invoice_id'),
                ('wise_credits', 'invoice_id'),
                ('wise_transfers', 'invoice_id'),
                ('credit_note_applications', 'invoice_id'),
            ]
            
            for table, column in safe_to_delete:
                try:
                    cursor.execute(f'DELETE FROM {table} WHERE {column} = ?', (invoice_id,))  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                except Exception:
                    pass  # Table might not exist or column might not exist
            
            # Now delete the invoice
            cursor.execute(
                'DELETE FROM invoices WHERE id = ? AND user_id = ?',
                (invoice_id, self.user_id)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def add_payment(self, invoice_id: int, amount: float, payment_method: str = None,
                    reference: str = None, notes: str = None, created_via: str = 'manual') -> int:
        """Add a payment to an invoice."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Verify invoice belongs to user
            cursor.execute(
                'SELECT total, amount_paid FROM invoices WHERE id = ? AND user_id = ?',
                (invoice_id, self.user_id)
            )
            invoice = cursor.fetchone()
            if not invoice:
                return 0
            
            # Handle both dict (MySQL) and tuple (SQLite) results
            total = float(invoice['total'] if isinstance(invoice, dict) else invoice[0]) or 0
            amount_paid = float(invoice['amount_paid'] if isinstance(invoice, dict) else invoice[1]) or 0
            
            cursor.execute('''
                INSERT INTO payments (invoice_id, amount, payment_method, reference, notes, created_via)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (invoice_id, amount, payment_method, reference, notes, created_via))
            
            payment_id = cursor.lastrowid
            
            # Update amount paid on invoice
            new_paid = amount_paid + float(amount)
            new_status = 'paid' if new_paid >= total else 'partial'
            paid_at = datetime.now().isoformat() if new_paid >= total else None
            
            cursor.execute('''
                UPDATE invoices SET amount_paid = ?, status = ?, paid_at = ?, updated_at = ?
                WHERE id = ?
            ''', (new_paid, new_status, paid_at, datetime.now().isoformat(), invoice_id))
            
            conn.commit()
            return payment_id
    
    def mark_as_paid(self, invoice_id: int, payment_method: str = None,
                     reference: str = None, notes: str = None) -> bool:
        """Mark an invoice as fully paid."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get invoice
            cursor.execute(
                'SELECT total, amount_paid FROM invoices WHERE id = ? AND user_id = ?',
                (invoice_id, self.user_id)
            )
            invoice = cursor.fetchone()
            if not invoice:
                return False
            
            remaining = invoice['total'] - invoice['amount_paid']
            if remaining > 0:
                self.add_payment(invoice_id, remaining, payment_method, reference, notes)
            
            return True
    
    def get_statistics(self) -> Dict:
        """Get invoice statistics for the user."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Total counts by status
            cursor.execute('''
                SELECT status, COUNT(*) as count, SUM(total) as total
                FROM invoices WHERE user_id = ?
                GROUP BY status
            ''', (self.user_id,))
            
            stats = {
                'by_status': {},
                'total_invoices': 0,
                'total_revenue': 0,
                'total_outstanding': 0,
                'total_paid': 0
            }
            
            for row in cursor.fetchall():
                stats['by_status'][row['status']] = {
                    'count': row['count'],
                    'total': row['total'] or 0
                }
                stats['total_invoices'] += row['count']
                if row['status'] == 'paid':
                    stats['total_paid'] += row['total'] or 0
                elif row['status'] in ('sent', 'partial', 'overdue'):
                    stats['total_outstanding'] += row['total'] or 0
            
            stats['total_revenue'] = stats['total_paid'] + stats['total_outstanding']
            
            return stats


# =============================================================================
# User Preferences (for persistent UI state)
# =============================================================================

def get_user_preference(user_id: int, key: str, default: str = None) -> str:
    """Get a user preference value."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT preference_value FROM user_preferences WHERE user_id = ? AND preference_key = ?',
            (user_id, key)
        )
        row = cursor.fetchone()
        return row['preference_value'] if row else default


def set_user_preference(user_id: int, key: str, value: str):
    """Set a user preference value."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO user_preferences (user_id, preference_key, preference_value, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, preference_key) DO UPDATE SET
                preference_value = excluded.preference_value,
                updated_at = CURRENT_TIMESTAMP
        ''', (user_id, key, value))
        conn.commit()


def get_all_user_preferences(user_id: int) -> dict:
    """Get all preferences for a user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT preference_key, preference_value FROM user_preferences WHERE user_id = ?',
            (user_id,)
        )
        return {row['preference_key']: row['preference_value'] for row in cursor.fetchall()}


# =============================================================================
# Currency Rates Management
# =============================================================================

def get_currency_rate(user_id: int, base: str, target: str) -> float:
    """Get the exchange rate between two currencies.
    
    Will try to find the rate in either direction and calculate inverse if needed.
    """
    if base == target:
        return 1.0
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Try direct rate first (base -> target)
        cursor.execute(
            'SELECT rate FROM currency_rates WHERE user_id = ? AND base_currency = ? AND target_currency = ?',
            (user_id, base, target)
        )
        row = cursor.fetchone()
        if row and row['rate']:
            return float(row['rate'])
        
        # Try inverse rate (target -> base) and calculate inverse
        cursor.execute(
            'SELECT rate FROM currency_rates WHERE user_id = ? AND base_currency = ? AND target_currency = ?',
            (user_id, target, base)
        )
        row = cursor.fetchone()
        if row and row['rate'] and float(row['rate']) != 0:
            return 1.0 / float(row['rate'])
        
        return 1.0


def set_currency_rate(user_id: int, base: str, target: str, rate: float):
    """Set the exchange rate between two currencies."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO currency_rates (user_id, base_currency, target_currency, rate, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, base_currency, target_currency) DO UPDATE SET
                rate = excluded.rate,
                updated_at = CURRENT_TIMESTAMP
        ''', (user_id, base, target, rate))
        conn.commit()


def get_all_currency_rates(user_id: int) -> list:
    """Get all currency rates for a user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM currency_rates WHERE user_id = ? ORDER BY base_currency, target_currency',
            (user_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_enabled_currencies(user_id: int) -> list:
    """Get list of enabled currencies for a user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT currency_code FROM enabled_currencies WHERE user_id = ? AND enabled = 1',
            (user_id,)
        )
        return [row['currency_code'] for row in cursor.fetchall()]


def set_enabled_currencies(user_id: int, currencies: list):
    """Set the list of enabled currencies for a user."""
    with get_db() as conn:
        cursor = conn.cursor()
        # First disable all
        cursor.execute('DELETE FROM enabled_currencies WHERE user_id = ?', (user_id,))
        # Then enable selected ones
        for code in currencies:
            cursor.execute(
                'INSERT INTO enabled_currencies (user_id, currency_code, enabled) VALUES (?, ?, 1)',
                (user_id, code)
            )
        conn.commit()


def convert_currency(user_id: int, amount: float, from_currency: str, to_currency: str) -> float:
    """Convert an amount from one currency to another."""
    if from_currency == to_currency:
        return amount
    
    rate = get_currency_rate(user_id, from_currency, to_currency)
    return amount * rate


# =============================================================================
# Currency Configuration
# =============================================================================

CURRENCIES = {
    'GBP': {'symbol': '£', 'name': 'British Pound'},
    'USD': {'symbol': '$', 'name': 'US Dollar'},
    'EUR': {'symbol': '€', 'name': 'Euro'},
    'ZAR': {'symbol': 'R', 'name': 'South African Rand'},
    'CAD': {'symbol': 'C$', 'name': 'Canadian Dollar'},
    'AUD': {'symbol': 'A$', 'name': 'Australian Dollar'},
    'NZD': {'symbol': 'NZ$', 'name': 'New Zealand Dollar'},
    'CHF': {'symbol': 'CHF', 'name': 'Swiss Franc'},
    'JPY': {'symbol': '¥', 'name': 'Japanese Yen'},
    'INR': {'symbol': '₹', 'name': 'Indian Rupee'},
    'SEK': {'symbol': 'kr', 'name': 'Swedish Krona'},
    'NOK': {'symbol': 'kr', 'name': 'Norwegian Krone'},
    'DKK': {'symbol': 'kr', 'name': 'Danish Krone'},
    'PLN': {'symbol': 'zł', 'name': 'Polish Zloty'},
    'CZK': {'symbol': 'Kč', 'name': 'Czech Koruna'},
    'HUF': {'symbol': 'Ft', 'name': 'Hungarian Forint'},
    'SGD': {'symbol': 'S$', 'name': 'Singapore Dollar'},
    'HKD': {'symbol': 'HK$', 'name': 'Hong Kong Dollar'},
    'MXN': {'symbol': '$', 'name': 'Mexican Peso'},
    'BRL': {'symbol': 'R$', 'name': 'Brazilian Real'},
    'CNY': {'symbol': '¥', 'name': 'Chinese Yuan'},
    'KRW': {'symbol': '₩', 'name': 'South Korean Won'},
    'AED': {'symbol': 'د.إ', 'name': 'UAE Dirham'},
}


def get_currency_symbol(currency_code: str) -> str:
    """Get the symbol for a currency code."""
    return CURRENCIES.get(currency_code, {}).get('symbol', currency_code)


# Initialize database on import
init_database()
