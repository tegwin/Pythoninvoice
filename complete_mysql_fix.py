#!/usr/bin/env python3
"""
Complete MySQL Schema Fix
Creates ALL tables and adds ALL missing columns based on SQLite schema.
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

def execute_sql(cursor, sql, description):
    try:
        cursor.execute(sql)
        print(f"  ✓ {description}")
        return True
    except mysql.connector.Error as e:
        if e.errno in [1060, 1050, 1061]:  # Duplicate column/table/key
            return False
        else:
            print(f"  ✗ {description}: {e}")
            return False

def complete_fix():
    print("=" * 60)
    print("Complete MySQL Schema Fix")
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
    
    print("\n1. Creating missing tables...\n")
    
    # Missing tables from SQLite
    missing_tables = [
        ("gocardless_billing_requests", '''
            CREATE TABLE IF NOT EXISTS gocardless_billing_requests (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                customer_id INT,
                billing_request_id VARCHAR(255),
                flow_id VARCHAR(255),
                authorisation_url VARCHAR(500),
                status VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''),
        ("gocardless_mandates", '''
            CREATE TABLE IF NOT EXISTS gocardless_mandates (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                customer_id INT,
                gc_mandate_id VARCHAR(255),
                gc_customer_id VARCHAR(255),
                status VARCHAR(50),
                scheme VARCHAR(50),
                reference VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        '''),
        ("gocardless_webhook_logs", '''
            CREATE TABLE IF NOT EXISTS gocardless_webhook_logs (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT,
                event_type VARCHAR(100),
                event_id VARCHAR(255),
                resource_type VARCHAR(100),
                action VARCHAR(100),
                invoice_id INT,
                status VARCHAR(50),
                message TEXT,
                payload LONGTEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''),
        ("roadmap_requests", '''
            CREATE TABLE IF NOT EXISTS roadmap_requests (
                id INT PRIMARY KEY AUTO_INCREMENT,
                title VARCHAR(255),
                description TEXT,
                submitted_by VARCHAR(255),
                email VARCHAR(255),
                status VARCHAR(50) DEFAULT 'pending',
                votes INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''),
        ("sumup_webhook_logs", '''
            CREATE TABLE IF NOT EXISTS sumup_webhook_logs (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT,
                event_type VARCHAR(100),
                event_id VARCHAR(255),
                invoice_id INT,
                status VARCHAR(50),
                message TEXT,
                payload LONGTEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''),
        ("wise_credits", '''
            CREATE TABLE IF NOT EXISTS wise_credits (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                invoice_id INT,
                transaction_id VARCHAR(255),
                reference VARCHAR(255),
                amount DECIMAL(15,2),
                currency VARCHAR(10),
                status VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        '''),
        ("wise_transfers", '''
            CREATE TABLE IF NOT EXISTS wise_transfers (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                invoice_id INT,
                transfer_id VARCHAR(255),
                quote_id VARCHAR(255),
                status VARCHAR(50),
                amount DECIMAL(15,2),
                currency VARCHAR(10),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        '''),
        ("wise_webhook_logs", '''
            CREATE TABLE IF NOT EXISTS wise_webhook_logs (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT,
                event_type VARCHAR(100),
                event_id VARCHAR(255),
                invoice_id INT,
                status VARCHAR(50),
                message TEXT,
                payload LONGTEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''),
    ]
    
    for table_name, create_sql in missing_tables:
        execute_sql(cursor, create_sql, table_name)
    
    conn.commit()
    
    print("\n2. Adding missing columns to existing tables...\n")
    
    # All missing columns
    columns_to_add = [
        # company_settings - ALL columns
        ("company_settings", "currency_api_key", "VARCHAR(255)"),
        ("company_settings", "currency_api_provider", "VARCHAR(100) DEFAULT 'currencyapi'"),
        ("company_settings", "auto_update_rates", "TINYINT DEFAULT 0"),
        ("company_settings", "rates_last_updated", "TIMESTAMP NULL"),
        
        # api_keys
        ("api_keys", "key_prefix", "VARCHAR(20)"),
        
        # payments
        ("payments", "created_via", "VARCHAR(100)"),
        
        # webhooks - different structure in SQLite
        ("webhooks", "webhook_id", "VARCHAR(255)"),
        ("webhooks", "name", "VARCHAR(255)"),
        ("webhooks", "headers", "TEXT"),
        ("webhooks", "auth_type", "VARCHAR(50)"),
        ("webhooks", "auth_value", "VARCHAR(255)"),
        ("webhooks", "trigger_count", "INT DEFAULT 0"),
        ("webhooks", "last_status", "VARCHAR(50)"),
        ("webhooks", "last_error", "TEXT"),
        
        # sumup_checkouts
        ("sumup_checkouts", "transaction_id", "VARCHAR(255)"),
        ("sumup_checkouts", "transaction_code", "VARCHAR(255)"),
        
        # gocardless_payments - missing columns
        ("gocardless_payments", "gc_mandate_id", "VARCHAR(255)"),
        ("gocardless_payments", "description", "VARCHAR(255)"),
        ("gocardless_payments", "charge_date", "DATE"),
    ]
    
    for table, column, col_type in columns_to_add:
        sql = f"ALTER TABLE `{table}` ADD COLUMN `{column}` {col_type}"
        execute_sql(cursor, sql, f"{table}.{column}")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print("\n" + "=" * 60)
    print("Schema fix complete!")
    print("=" * 60)
    print("\nNow run: python migrate_sqlite_to_mysql.py")
    
    return True

if __name__ == '__main__':
    complete_fix()
