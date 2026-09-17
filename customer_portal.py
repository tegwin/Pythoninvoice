"""
Invoice Manager - Customer Portal Module
Allows customers to view their invoices and make payments.
Copyright (c) 2026 Sondela Consulting Ltd.
"""

import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from functools import wraps
from flask import session, redirect, url_for, flash, request

from database import get_db


# =============================================================================
# Customer Portal User Management
# =============================================================================

class CustomerPortalManager:
    """Manage customer portal users and access."""
    
    def __init__(self, user_id: int):
        """Initialize with the admin/business user_id."""
        self.user_id = user_id
    
    def create_portal_user(self, customer_id: int, email: str, 
                           send_email: bool = True) -> Tuple[bool, str, Optional[str]]:
        """
        Create a portal user for a customer.
        Returns (success, message, temporary_password or None)
        """
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Verify customer belongs to this user
            cursor.execute(
                'SELECT id, name, email FROM customers WHERE id = ? AND user_id = ?',
                (customer_id, self.user_id)
            )
            customer = cursor.fetchone()
            if not customer:
                return False, 'Customer not found', None
            
            # Check if portal user already exists
            cursor.execute(
                'SELECT id FROM customer_portal_users WHERE customer_id = ? AND user_id = ?',
                (customer_id, self.user_id)
            )
            if cursor.fetchone():
                return False, 'Portal user already exists for this customer', None
            
            # Generate temporary password
            temp_password = secrets.token_urlsafe(12)
            password_hash = hashlib.sha256(temp_password.encode()).hexdigest()
            
            # Create portal user
            cursor.execute('''
                INSERT INTO customer_portal_users 
                (user_id, customer_id, email, password_hash, is_active, must_change_password, created_at)
                VALUES (?, ?, ?, ?, 1, 1, ?)
            ''', (self.user_id, customer_id, email, password_hash, datetime.now().isoformat()))
            
            conn.commit()
            
            return True, 'Portal user created successfully', temp_password
    
    def get_portal_users(self) -> List[Dict]:
        """Get all portal users for this business."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT cpu.*, c.name as customer_name
                FROM customer_portal_users cpu
                JOIN customers c ON cpu.customer_id = c.id
                WHERE cpu.user_id = ?
                ORDER BY c.name
            ''', (self.user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_portal_user(self, portal_user_id: int) -> Optional[Dict]:
        """Get a specific portal user."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT cpu.*, c.name as customer_name
                FROM customer_portal_users cpu
                JOIN customers c ON cpu.customer_id = c.id
                WHERE cpu.id = ? AND cpu.user_id = ?
            ''', (portal_user_id, self.user_id))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_portal_user(self, portal_user_id: int, updates: Dict) -> bool:
        """Update a portal user."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            allowed_fields = ['email', 'is_active']
            fields = []
            values = []
            
            for key, value in updates.items():
                if key in allowed_fields:
                    fields.append(f'{key} = ?')
                    values.append(value)
            
            if not fields:
                return False
            
            values.append(datetime.now().isoformat())
            values.append(portal_user_id)
            values.append(self.user_id)
            
            cursor.execute(f'''  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                UPDATE customer_portal_users 
                SET {", ".join(fields)}, updated_at = ?
                WHERE id = ? AND user_id = ?
            ''', values)
            conn.commit()
            return cursor.rowcount > 0
    
    def revoke_access(self, portal_user_id: int) -> bool:
        """Revoke portal access for a user."""
        return self.update_portal_user(portal_user_id, {'is_active': 0})
    
    def restore_access(self, portal_user_id: int) -> bool:
        """Restore portal access for a user."""
        return self.update_portal_user(portal_user_id, {'is_active': 1})
    
    def reset_password(self, portal_user_id: int) -> Tuple[bool, str, Optional[str]]:
        """Reset password for a portal user."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Verify user exists and belongs to us
            cursor.execute(
                'SELECT id FROM customer_portal_users WHERE id = ? AND user_id = ?',
                (portal_user_id, self.user_id)
            )
            if not cursor.fetchone():
                return False, 'Portal user not found', None
            
            # Generate new password
            temp_password = secrets.token_urlsafe(12)
            password_hash = hashlib.sha256(temp_password.encode()).hexdigest()
            
            cursor.execute('''
                UPDATE customer_portal_users 
                SET password_hash = ?, must_change_password = 1, updated_at = ?
                WHERE id = ?
            ''', (password_hash, datetime.now().isoformat(), portal_user_id))
            conn.commit()
            
            return True, 'Password reset successfully', temp_password
    
    def delete_portal_user(self, portal_user_id: int) -> bool:
        """Delete a portal user."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM customer_portal_users WHERE id = ? AND user_id = ?',
                (portal_user_id, self.user_id)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def generate_impersonation_token(self, portal_user_id: int) -> Optional[str]:
        """Generate a one-time impersonation token for admin access."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Verify portal user exists
            cursor.execute(
                'SELECT id FROM customer_portal_users WHERE id = ? AND user_id = ?',
                (portal_user_id, self.user_id)
            )
            if not cursor.fetchone():
                return None
            
            # Generate token
            token = secrets.token_urlsafe(32)
            expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()
            
            cursor.execute('''
                UPDATE customer_portal_users 
                SET impersonation_token = ?, impersonation_expires = ?
                WHERE id = ?
            ''', (token, expires_at, portal_user_id))
            conn.commit()
            
            return token


# =============================================================================
# Portal Authentication
# =============================================================================

def authenticate_portal_user(email: str, password: str, business_id: int = None) -> Optional[Dict]:
    """
    Authenticate a portal user.
    Returns user dict if successful, None otherwise.
    """
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        query = '''
            SELECT cpu.*, c.name as customer_name,
                   COALESCE(cs.company_name, u.display_name, u.username) as business_name
            FROM customer_portal_users cpu
            JOIN customers c ON cpu.customer_id = c.id
            JOIN users u ON cpu.user_id = u.id
            LEFT JOIN company_settings cs ON cpu.user_id = cs.user_id
            WHERE cpu.email = ? AND cpu.password_hash = ? AND cpu.is_active = 1
        '''
        params = [email, password_hash]
        
        if business_id:
            query += ' AND cpu.user_id = ?'
            params.append(business_id)
        
        cursor.execute(query, params)
        row = cursor.fetchone()
        
        if row:
            user = dict(row)
            # Update last login
            cursor.execute('''
                UPDATE customer_portal_users 
                SET last_login = ? WHERE id = ?
            ''', (datetime.now().isoformat(), user['id']))
            conn.commit()
            return user
        
        return None


def authenticate_with_token(token: str) -> Optional[Dict]:
    """Authenticate using an impersonation token (for admin access)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT cpu.*, c.name as customer_name,
                   COALESCE(cs.company_name, u.display_name, u.username) as business_name
            FROM customer_portal_users cpu
            JOIN customers c ON cpu.customer_id = c.id
            JOIN users u ON cpu.user_id = u.id
            LEFT JOIN company_settings cs ON cpu.user_id = cs.user_id
            WHERE cpu.impersonation_token = ? 
            AND cpu.impersonation_expires > ?
        ''', (token, datetime.now().isoformat()))
        row = cursor.fetchone()
        
        if row:
            user = dict(row)
            # Clear the token (one-time use)
            cursor.execute('''
                UPDATE customer_portal_users 
                SET impersonation_token = NULL, impersonation_expires = NULL
                WHERE id = ?
            ''', (user['id'],))
            conn.commit()
            return user
        
        return None


def change_portal_password(portal_user_id: int, old_password: str, new_password: str) -> Tuple[bool, str]:
    """Change password for a portal user."""
    old_hash = hashlib.sha256(old_password.encode()).hexdigest()
    new_hash = hashlib.sha256(new_password.encode()).hexdigest()
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT id FROM customer_portal_users WHERE id = ? AND password_hash = ?',
            (portal_user_id, old_hash)
        )
        if not cursor.fetchone():
            return False, 'Current password is incorrect'
        
        cursor.execute('''
            UPDATE customer_portal_users 
            SET password_hash = ?, must_change_password = 0, updated_at = ?
            WHERE id = ?
        ''', (new_hash, datetime.now().isoformat(), portal_user_id))
        conn.commit()
        
        return True, 'Password changed successfully'


# =============================================================================
# Portal Data Access
# =============================================================================

class CustomerPortalData:
    """Access invoice and payment data for a customer portal user."""
    
    def __init__(self, portal_user: Dict):
        """Initialize with authenticated portal user dict."""
        self.portal_user = portal_user
        self.user_id = portal_user['user_id']  # Business user ID
        self.customer_id = portal_user['customer_id']
    
    def get_dashboard_stats(self) -> Dict:
        """Get dashboard statistics for the customer."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Total invoices
            cursor.execute('''
                SELECT COUNT(*) as cnt FROM invoices 
                WHERE customer_id = ? AND user_id = ?
            ''', (self.customer_id, self.user_id))
            result = cursor.fetchone()
            total_invoices = result['cnt'] if isinstance(result, dict) else result[0]
            
            # Paid invoices
            cursor.execute('''
                SELECT COUNT(*) as cnt FROM invoices 
                WHERE customer_id = ? AND user_id = ? AND status = 'paid'
            ''', (self.customer_id, self.user_id))
            result = cursor.fetchone()
            paid_invoices = result['cnt'] if isinstance(result, dict) else result[0]
            
            # Unpaid invoices
            cursor.execute('''
                SELECT COUNT(*) as cnt FROM invoices 
                WHERE customer_id = ? AND user_id = ? AND status NOT IN ('paid', 'cancelled', 'draft')
            ''', (self.customer_id, self.user_id))
            result = cursor.fetchone()
            unpaid_invoices = result['cnt'] if isinstance(result, dict) else result[0]
            
            # Total outstanding
            cursor.execute('''
                SELECT COALESCE(SUM(total - amount_paid), 0) as total_outstanding
                FROM invoices 
                WHERE customer_id = ? AND user_id = ? AND status NOT IN ('paid', 'cancelled', 'draft')
            ''', (self.customer_id, self.user_id))
            result = cursor.fetchone()
            total_outstanding = float(result['total_outstanding'] if isinstance(result, dict) else result[0]) or 0
            
            # Overdue invoices
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT COUNT(*) as cnt FROM invoices 
                WHERE customer_id = ? AND user_id = ? 
                AND status NOT IN ('paid', 'cancelled', 'draft')
                AND due_date < ?
            ''', (self.customer_id, self.user_id, today))
            result = cursor.fetchone()
            overdue_invoices = result['cnt'] if isinstance(result, dict) else result[0]
            
            # Overdue amount
            cursor.execute('''
                SELECT COALESCE(SUM(total - amount_paid), 0) as overdue_amount
                FROM invoices 
                WHERE customer_id = ? AND user_id = ? 
                AND status NOT IN ('paid', 'cancelled', 'draft')
                AND due_date < ?
            ''', (self.customer_id, self.user_id, today))
            result = cursor.fetchone()
            overdue_amount = float(result['overdue_amount'] if isinstance(result, dict) else result[0]) or 0
            
            return {
                'total_invoices': total_invoices,
                'paid_invoices': paid_invoices,
                'unpaid_invoices': unpaid_invoices,
                'total_outstanding': total_outstanding,
                'overdue_invoices': overdue_invoices,
                'overdue_amount': overdue_amount
            }
    
    def get_invoices(self, status_filter: str = None) -> List[Dict]:
        """Get all invoices for this customer."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT i.*, 
                       (i.total - i.amount_paid) as balance
                FROM invoices i
                WHERE i.customer_id = ? AND i.user_id = ?
                AND i.status != 'draft'
            '''
            params = [self.customer_id, self.user_id]
            
            if status_filter == 'paid':
                query += " AND i.status = 'paid'"
            elif status_filter == 'unpaid':
                query += " AND i.status NOT IN ('paid', 'cancelled', 'draft')"
            elif status_filter == 'overdue':
                today = datetime.now().strftime('%Y-%m-%d')
                query += " AND i.status NOT IN ('paid', 'cancelled', 'draft') AND i.due_date < ?"
                params.append(today)
            
            query += ' ORDER BY i.issue_date DESC'
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_invoice(self, invoice_id: int) -> Optional[Dict]:
        """Get a specific invoice (if it belongs to this customer)."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT i.*,
                       (i.total - i.amount_paid) as balance
                FROM invoices i
                WHERE i.id = ? AND i.customer_id = ? AND i.user_id = ?
                AND i.status != 'draft'
            ''', (invoice_id, self.customer_id, self.user_id))
            row = cursor.fetchone()
            
            if row:
                invoice = dict(row)
                
                # Get items
                cursor.execute('''
                    SELECT * FROM invoice_items WHERE invoice_id = ?
                    ORDER BY sort_order, id
                ''', (invoice_id,))
                invoice['items'] = [dict(r) for r in cursor.fetchall()]
                
                # Get payments
                cursor.execute('''
                    SELECT * FROM payments WHERE invoice_id = ?
                    ORDER BY payment_date DESC
                ''', (invoice_id,))
                invoice['payments'] = [dict(r) for r in cursor.fetchall()]
                
                return invoice
            
            return None
    
    def get_payment_options(self, invoice_id: int) -> Dict:
        """Get available payment options for an invoice."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            options = {
                'stripe': None,
                'gocardless': None,
                'sumup': None
            }
            
            # Check Stripe
            cursor.execute('''
                SELECT enabled FROM stripe_settings WHERE user_id = ? AND enabled = 1
            ''', (self.user_id,))
            if cursor.fetchone():
                # Get or create payment link
                cursor.execute('''
                    SELECT payment_url FROM stripe_payment_sessions 
                    WHERE invoice_id = ? AND user_id = ? AND status = 'pending'
                    ORDER BY created_at DESC LIMIT 1
                ''', (invoice_id, self.user_id))
                row = cursor.fetchone()
                if row:
                    options['stripe'] = row['payment_url'] if isinstance(row, dict) else row[0]
                else:
                    options['stripe'] = 'available'  # Can be generated
            
            # Check GoCardless
            cursor.execute('''
                SELECT enabled FROM gocardless_settings WHERE user_id = ? AND enabled = 1
            ''', (self.user_id,))
            if cursor.fetchone():
                # Check if customer has mandate
                cursor.execute('''
                    SELECT mandate_id FROM gocardless_mandates 
                    WHERE customer_id = ? AND status = 'active'
                ''', (self.customer_id,))
                if cursor.fetchone():
                    options['gocardless'] = 'mandate_active'
                else:
                    options['gocardless'] = 'setup_required'
            
            # Check SumUp
            cursor.execute('''
                SELECT enabled FROM sumup_settings WHERE user_id = ? AND enabled = 1
            ''', (self.user_id,))
            if cursor.fetchone():
                cursor.execute('''
                    SELECT checkout_url FROM sumup_checkouts 
                    WHERE invoice_id = ? AND status = 'pending'
                    ORDER BY created_at DESC LIMIT 1
                ''', (invoice_id,))
                row = cursor.fetchone()
                if row:
                    options['sumup'] = row['checkout_url'] if isinstance(row, dict) else row[0]
                else:
                    options['sumup'] = 'available'
            
            return options
    
    def get_business_info(self) -> Dict:
        """Get business information for display."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT company_name, email, phone, address_line1 as address, city, 
                       postal_code as postcode, country, logo_path, default_currency
                FROM company_settings WHERE user_id = ?
            ''', (self.user_id,))
            row = cursor.fetchone()
            return dict(row) if row else {}
    
    def get_credit_notes(self) -> List[Dict]:
        """Get all credit notes for this customer."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT cn.*, i.invoice_number as original_invoice_number
                FROM credit_notes cn
                LEFT JOIN invoices i ON cn.invoice_id = i.id
                WHERE cn.customer_id = ? AND cn.user_id = ?
                ORDER BY cn.credit_note_date DESC
            ''', (self.customer_id, self.user_id))
            return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# Portal Login Decorator
# =============================================================================

def portal_login_required(f):
    """Decorator to require portal login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'portal_user_id' not in session:
            return redirect(url_for('portal_login'))
        return f(*args, **kwargs)
    return decorated_function


def get_portal_user_from_session() -> Optional[Dict]:
    """Get current portal user from session."""
    if 'portal_user_id' not in session:
        return None
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT cpu.*, c.name as customer_name,
                   COALESCE(cs.company_name, u.display_name, u.username) as business_name
            FROM customer_portal_users cpu
            JOIN customers c ON cpu.customer_id = c.id
            JOIN users u ON cpu.user_id = u.id
            LEFT JOIN company_settings cs ON cpu.user_id = cs.user_id
            WHERE cpu.id = ? AND cpu.is_active = 1
        ''', (session['portal_user_id'],))
        row = cursor.fetchone()
        return dict(row) if row else None


# =============================================================================
# Database Schema for Customer Portal
# =============================================================================

def get_portal_schema() -> str:
    """Return SQL schema for customer portal tables."""
    return '''
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
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            UNIQUE KEY unique_customer_portal (user_id, customer_id)
        );
    '''
