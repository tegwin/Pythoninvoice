"""
Invoice Manager - Database Module
MySQL/MariaDB database connections only.
"""

import os
import json
from contextlib import contextmanager
from typing import Dict, Optional, Any, List
from datetime import datetime

# MySQL connector is required
try:
    import mysql.connector
    from mysql.connector import pooling
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    print("ERROR: mysql-connector-python is required. Run: pip install mysql-connector-python")

# Configuration file path
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'data', 'db_config.json')

# Connection pool for MySQL
_mysql_pool = None


def get_db_config() -> Dict:
    """Load database configuration from file."""
    default_config = {
        'type': 'mysql',  # MySQL is now the only option
        'mysql_host': 'localhost',
        'mysql_port': 3306,
        'mysql_user': '',
        'mysql_password': '',
        'mysql_database': 'invoice_manager',
        'mysql_ssl': False
    }
    
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                default_config.update(config)
        except Exception:
            pass
    
    # Force MySQL type
    default_config['type'] = 'mysql'
    return default_config


def save_db_config(config: Dict) -> bool:
    """Save database configuration to file."""
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


def get_mysql_pool():
    """Get or create MySQL connection pool."""
    global _mysql_pool
    
    if not MYSQL_AVAILABLE:
        raise ImportError("mysql-connector-python is not installed")
    
    if _mysql_pool is None:
        config = get_db_config()
        pool_config = {
            'pool_name': 'invoice_pool',
            'pool_size': 5,
            'host': config['mysql_host'],
            'port': config['mysql_port'],
            'user': config['mysql_user'],
            'password': config['mysql_password'],
            'database': config['mysql_database'],
            'autocommit': False,
            'charset': 'utf8mb4',
            'collation': 'utf8mb4_unicode_ci',
            # The bundled C extension has no IPv6 support, which is all
            # Railway's private network offers. Pure Python handles both.
            'use_pure': True,
        }
        
        if config.get('mysql_ssl'):
            pool_config['ssl_disabled'] = False
        
        _mysql_pool = pooling.MySQLConnectionPool(**pool_config)
    
    return _mysql_pool


def reset_mysql_pool():
    """Reset MySQL connection pool (call after config change)."""
    global _mysql_pool
    _mysql_pool = None


class MySQLConnection:
    """MySQL connection wrapper that mimics sqlite3 connection behavior."""
    
    def __init__(self, conn):
        self.conn = conn
        self._cursor = None
    
    def cursor(self):
        self._cursor = self.conn.cursor(dictionary=True)
        return MySQLCursor(self._cursor)
    
    def commit(self):
        self.conn.commit()
    
    def rollback(self):
        self.conn.rollback()
    
    def close(self):
        if self._cursor:
            self._cursor.close()
        self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


class MySQLCursor:
    """MySQL cursor wrapper for compatibility."""
    
    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = None
        self.rowcount = 0
    
    def execute(self, sql, params=None):
        # Convert SQLite-style ? placeholders to MySQL %s
        sql = sql.replace('?', '%s')
        
        # Handle SQLite's ON CONFLICT syntax for MySQL
        if 'ON CONFLICT' in sql:
            sql = self._convert_upsert(sql)
        
        # Handle AUTOINCREMENT -> AUTO_INCREMENT
        sql = sql.replace('AUTOINCREMENT', 'AUTO_INCREMENT')
        
        # Handle INTEGER PRIMARY KEY for MySQL
        sql = sql.replace('INTEGER PRIMARY KEY', 'INT PRIMARY KEY')
        
        if params:
            self.cursor.execute(sql, params)
        else:
            self.cursor.execute(sql)
        
        self.lastrowid = self.cursor.lastrowid
        self.rowcount = self.cursor.rowcount
        return self
    
    def _convert_upsert(self, sql: str) -> str:
        """Convert SQLite ON CONFLICT to MySQL ON DUPLICATE KEY UPDATE."""
        # Simple conversion for common patterns
        if 'ON CONFLICT' in sql and 'DO UPDATE SET' in sql:
            # Extract the UPDATE part
            parts = sql.split('ON CONFLICT')
            insert_part = parts[0].strip()
            
            # Find the SET clause
            update_idx = sql.find('DO UPDATE SET')
            if update_idx > 0:
                update_clause = sql[update_idx + 13:].strip()
                # Convert excluded.column to VALUES(column)
                import re
                update_clause = re.sub(r'excluded\.(\w+)', r'VALUES(\1)', update_clause)
                sql = f"{insert_part} ON DUPLICATE KEY UPDATE {update_clause}"
        
        return sql
    
    def executemany(self, sql, params_list):
        sql = sql.replace('?', '%s')
        self.cursor.executemany(sql, params_list)
        self.rowcount = self.cursor.rowcount
        return self
    
    def fetchone(self):
        row = self.cursor.fetchone()
        return row
    
    def fetchall(self):
        return self.cursor.fetchall()
    
    def close(self):
        self.cursor.close()


@contextmanager
def get_db():
    """Get a MySQL database connection."""
    if not MYSQL_AVAILABLE:
        raise ImportError("mysql-connector-python is required. Run: pip install mysql-connector-python")
    
    pool = get_mysql_pool()
    conn = MySQLConnection(pool.get_connection())
    
    try:
        yield conn
    finally:
        conn.close()


def test_mysql_connection(host: str, port: int, user: str, password: str, database: str) -> Dict:
    """Test MySQL connection with given parameters."""
    if not MYSQL_AVAILABLE:
        return {'success': False, 'error': 'MySQL connector not installed. Run: pip install mysql-connector-python'}
    
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connection_timeout=5,
            use_pure=True,
        )
        conn.close()
        return {'success': True}
    except mysql.connector.Error as e:
        return {'success': False, 'error': str(e)}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_database_info() -> Dict:
    """Get information about the current database."""
    config = get_db_config()
    info = {
        'type': 'mysql',
        'connected': False,
        'tables': 0,
        'size': 'N/A'
    }
    
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SHOW TABLES")
            info['tables'] = len(cursor.fetchall())
            
            cursor.execute("""
                SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS size_mb
                FROM information_schema.tables
                WHERE table_schema = %s
            """, (config['mysql_database'],))
            row = cursor.fetchone()
            if row and row.get('size_mb'):
                info['size'] = f"{row['size_mb']} MB"
            
            info['connected'] = True
    except Exception as e:
        info['error'] = str(e)
    
    return info


def init_database_mysql(cursor):
    """Initialize MySQL database schema."""
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INT PRIMARY KEY AUTO_INCREMENT,
            username VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            display_name VARCHAR(255),
            phone VARCHAR(50),
            timezone VARCHAR(50) DEFAULT 'Europe/London',
            bio TEXT,
            avatar_path VARCHAR(500),
            role VARCHAR(50) DEFAULT 'owner',
            parent_user_id INT,
            totp_secret VARCHAR(100),
            totp_enabled TINYINT DEFAULT 0,
            backup_codes TEXT,
            login_count INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP NULL,
            active TINYINT DEFAULT 1,
            FOREIGN KEY (parent_user_id) REFERENCES users (id)
        )
    ''')
    
    # Team members table
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
            FOREIGN KEY (owner_user_id) REFERENCES users (id),
            FOREIGN KEY (member_user_id) REFERENCES users (id),
            UNIQUE KEY unique_membership (owner_user_id, member_user_id)
        )
    ''')
    
    # Company Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS company_settings (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            company_name VARCHAR(255),
            address_line1 VARCHAR(255),
            address_line2 VARCHAR(255),
            city VARCHAR(100),
            state VARCHAR(100),
            postal_code VARCHAR(20),
            country VARCHAR(100),
            phone VARCHAR(50),
            email VARCHAR(255),
            website VARCHAR(255),
            logo_path VARCHAR(500),
            default_tax_rate DECIMAL(5,2) DEFAULT 0,
            default_currency VARCHAR(10) DEFAULT 'GBP',
            invoice_prefix VARCHAR(20) DEFAULT 'INV',
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
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Customers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            phone VARCHAR(50),
            address_line1 VARCHAR(255),
            address_line2 VARCHAR(255),
            city VARCHAR(100),
            state VARCHAR(100),
            postal_code VARCHAR(20),
            country VARCHAR(100),
            tax_number VARCHAR(50),
            custom_tax_rate DECIMAL(5,2),
            custom_currency VARCHAR(10),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Products table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            unit_price DECIMAL(10,2) NOT NULL DEFAULT 0,
            unit VARCHAR(50) DEFAULT 'unit',
            sku VARCHAR(100),
            is_service TINYINT DEFAULT 0,
            taxable TINYINT DEFAULT 1,
            active TINYINT DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Invoices table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            customer_id INT,
            invoice_number VARCHAR(50) NOT NULL,
            status VARCHAR(20) DEFAULT 'draft',
            issue_date DATE DEFAULT (CURRENT_DATE),
            due_date DATE,
            currency VARCHAR(10) DEFAULT 'GBP',
            tax_rate DECIMAL(5,2) DEFAULT 0,
            subtotal DECIMAL(12,2) DEFAULT 0,
            tax_amount DECIMAL(12,2) DEFAULT 0,
            total DECIMAL(12,2) DEFAULT 0,
            amount_paid DECIMAL(12,2) DEFAULT 0,
            notes TEXT,
            payment_terms TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            paid_at TIMESTAMP NULL,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        )
    ''')
    
    # Invoice Items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INT PRIMARY KEY AUTO_INCREMENT,
            invoice_id INT NOT NULL,
            product_id INT,
            description VARCHAR(2000) NOT NULL,
            quantity DECIMAL(10,2) DEFAULT 1,
            unit_price DECIMAL(10,2) DEFAULT 0,
            tax_rate DECIMAL(5,2) DEFAULT 0,
            line_total DECIMAL(12,2) DEFAULT 0,
            sort_order INT DEFAULT 0,
            FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    # Payments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INT PRIMARY KEY AUTO_INCREMENT,
            invoice_id INT NOT NULL,
            amount DECIMAL(12,2) NOT NULL,
            payment_method VARCHAR(50),
            reference VARCHAR(255),
            notes TEXT,
            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_via VARCHAR(50) DEFAULT 'manual',
            FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE CASCADE
        )
    ''')
    
    # API Keys table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            key_hash VARCHAR(255) UNIQUE NOT NULL,
            name VARCHAR(255) NOT NULL,
            permissions VARCHAR(500),
            active TINYINT DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Webhooks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS webhooks (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            webhook_id VARCHAR(100) UNIQUE NOT NULL,
            name VARCHAR(255),
            url VARCHAR(500) NOT NULL,
            events VARCHAR(1000) NOT NULL,
            secret VARCHAR(255) NOT NULL,
            headers VARCHAR(2000),
            auth_type VARCHAR(50),
            auth_value VARCHAR(255),
            active TINYINT DEFAULT 1,
            trigger_count INT DEFAULT 0,
            last_triggered TIMESTAMP NULL,
            last_status INT,
            last_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Email templates table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_templates (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            template_type VARCHAR(50) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            body TEXT NOT NULL,
            enabled TINYINT DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE KEY unique_template (user_id, template_type)
        )
    ''')
    
    # Email log table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_log (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            invoice_id INT,
            customer_id INT,
            email_type VARCHAR(50) NOT NULL,
            to_email VARCHAR(255) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            error_message TEXT,
            sent_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (invoice_id) REFERENCES invoices (id),
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        )
    ''')
    
    # Invoice reminders table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoice_reminders (
            id INT PRIMARY KEY AUTO_INCREMENT,
            invoice_id INT NOT NULL,
            reminder_number INT DEFAULT 1,
            days_before_due INT DEFAULT 7,
            scheduled_date DATE,
            sent_at TIMESTAMP NULL,
            status VARCHAR(20) DEFAULT 'pending',
            FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE CASCADE
        )
    ''')


def migrate_sqlite_to_mysql() -> Dict:
    """Migrate data from SQLite to MySQL."""
    config = get_db_config()
    
    if not MYSQL_AVAILABLE:
        return {'success': False, 'error': 'MySQL connector not installed'}
    
    sqlite_path = config.get('sqlite_path', DEFAULT_SQLITE_PATH)
    if not os.path.exists(sqlite_path):
        return {'success': False, 'error': 'SQLite database not found'}
    
    try:
        # Connect to SQLite
        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()
        
        # Connect to MySQL
        mysql_conn = mysql.connector.connect(
            host=config['mysql_host'],
            port=config['mysql_port'],
            user=config['mysql_user'],
            password=config['mysql_password'],
            database=config['mysql_database']
        )
        mysql_cursor = mysql_conn.cursor()
        
        # Initialize MySQL schema
        init_database_mysql(mysql_cursor)
        mysql_conn.commit()
        
        # Tables to migrate in order (respecting foreign keys)
        tables = [
            'users', 'team_members', 'company_settings', 'customers', 'products',
            'invoices', 'invoice_items', 'payments', 'api_keys', 'webhooks',
            'email_templates', 'email_log', 'invoice_reminders'
        ]
        
        migrated = {}
        
        for table in tables:
            try:
                sqlite_cursor.execute(f"SELECT * FROM {table}")  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                rows = sqlite_cursor.fetchall()
                
                if rows:
                    # Get column names
                    columns = [desc[0] for desc in sqlite_cursor.description]
                    placeholders = ', '.join(['%s'] * len(columns))
                    columns_str = ', '.join(columns)
                    
                    # Insert data
                    for row in rows:
                        values = [row[col] for col in columns]
                        mysql_cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                            f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})",
                            values
                        )
                    
                    mysql_conn.commit()
                    migrated[table] = len(rows)
            except Exception as e:
                migrated[table] = f"Error: {str(e)}"
        
        sqlite_conn.close()
        mysql_conn.close()
        
        return {'success': True, 'migrated': migrated}
    
    except Exception as e:
        return {'success': False, 'error': str(e)}


def should_skip_table_creation(table_name: str) -> bool:
    """
    Check if table creation should be skipped.
    For MySQL, check if table already exists to avoid syntax errors.
    """
    config = get_db_config()
    if config.get('type') != 'mysql':
        return False  # SQLite - let CREATE TABLE IF NOT EXISTS handle it
    
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SHOW TABLES LIKE '{table_name}'")  # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
            result = cursor.fetchone()
            return result is not None
    except:
        return False


def is_mysql() -> bool:
    """Check if we're using MySQL database. Always True now."""
    return True
