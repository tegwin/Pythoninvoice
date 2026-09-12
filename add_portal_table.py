"""
Add customer portal table to existing MySQL database.
Run this once to enable the customer portal feature.
"""

import sys
sys.path.insert(0, '.')

from database import get_db

def add_portal_table():
    """Add customer_portal_users table."""
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customer_portal_users (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    customer_id INT NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    is_active TINYINT DEFAULT 1,
                    must_change_password TINYINT DEFAULT 1,
                    last_login TIMESTAMP NULL,
                    impersonation_token VARCHAR(255) NULL,
                    impersonation_expires TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_customer_portal (user_id, customer_id)
                )
            ''')
            conn.commit()
            print("✅ customer_portal_users table created successfully!")
            return True
        except Exception as e:
            if 'already exists' in str(e).lower():
                print("✓ customer_portal_users table already exists")
                return True
            print(f"❌ Error creating table: {e}")
            return False

if __name__ == '__main__':
    add_portal_table()
