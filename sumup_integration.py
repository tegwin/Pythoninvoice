"""
Invoice Manager - SumUp Integration Module
Handles SumUp payment checkouts using the Payment Widget.
Flow: Create checkout (server) → Widget (client) → onResponse callback → Verify & record payment

Copyright (c) 2026 Sondela Consulting Ltd.
"""

import hashlib
import hmac
import json
import secrets
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from app_core import get_db, InvoiceManager, SettingsManager


# =============================================================================
# SumUp Settings Manager
# =============================================================================

class SumUpManager:
    """Manage SumUp integration settings and operations."""
    
    API_URL = "https://api.sumup.com"
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self._settings = None
    
    def get_settings(self) -> Dict:
        """Get SumUp settings for user."""
        if self._settings:
            return self._settings
            
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM sumup_settings WHERE user_id = ?',
                (self.user_id,)
            )
            row = cursor.fetchone()
            
            if row:
                self._settings = dict(row)
            else:
                # Return defaults
                self._settings = {
                    'user_id': self.user_id,
                    'enabled': 0,
                    'api_key': None,
                    'merchant_code': None,
                    'include_in_invoice_pdf': 1,
                    'include_in_email': 1,
                    'payment_description': 'Invoice Payment'
                }
            
            return self._settings
    
    def save_settings(self, data: Dict) -> bool:
        """Save SumUp settings."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Check if exists
            cursor.execute(
                'SELECT id FROM sumup_settings WHERE user_id = ?',
                (self.user_id,)
            )
            exists = cursor.fetchone()
            
            if exists:
                # Update
                fields = []
                values = []
                for key in ['enabled', 'api_key', 'merchant_code',
                           'include_in_invoice_pdf', 'include_in_email', 'payment_description']:
                    if key in data:
                        fields.append(f'{key} = ?')
                        values.append(data[key])
                
                if fields:
                    values.append(self.user_id)
                    cursor.execute(
                        f'UPDATE sumup_settings SET {", ".join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
                        values
                    )
            else:
                # Insert
                cursor.execute('''
                    INSERT INTO sumup_settings (
                        user_id, enabled, api_key, merchant_code,
                        include_in_invoice_pdf, include_in_email, payment_description
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    self.user_id,
                    data.get('enabled', 0),
                    data.get('api_key'),
                    data.get('merchant_code'),
                    data.get('include_in_invoice_pdf', 1),
                    data.get('include_in_email', 1),
                    data.get('payment_description', 'Invoice Payment')
                ))
            
            conn.commit()
            self._settings = None  # Clear cache
            return True
    
    def is_configured(self) -> bool:
        """Check if SumUp is properly configured."""
        settings = self.get_settings()
        if not settings.get('enabled'):
            return False
        return bool(settings.get('api_key') and settings.get('merchant_code'))
    
    def get_api_key(self) -> Optional[str]:
        """Get the API key."""
        settings = self.get_settings()
        return settings.get('api_key')
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Optional[Dict]:
        """Make an API request to SumUp."""
        import requests
        
        api_key = self.get_api_key()
        if not api_key:
            return None
        
        url = f"{self.API_URL}{endpoint}"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, timeout=30)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=30)
            else:
                return None
            
            if response.status_code in [200, 201]:
                return response.json()
            else:
                print(f"SumUp API error: {response.status_code} - {response.text}")
                return {'error': response.text, 'status_code': response.status_code}
                
        except Exception as e:
            print(f"SumUp request error: {e}")
            return {'error': str(e)}
    
    def get_checkout_status(self, checkout_id: str) -> Optional[Dict]:
        """Get the current status of a checkout."""
        return self._make_request('GET', f'/v0.1/checkouts/{checkout_id}')


# =============================================================================
# Checkout Creation
# =============================================================================

def create_sumup_checkout(user_id: int, invoice_id: int, redirect_url: str = None) -> Optional[Dict]:
    """
    Create a SumUp checkout for an invoice.
    Returns checkout details including ID for the Payment Widget.
    
    The redirect_url is where the user will be sent after 3DS authentication.
    """
    sumup_manager = SumUpManager(user_id)
    if not sumup_manager.is_configured():
        return {'error': 'SumUp is not configured'}
    
    settings = sumup_manager.get_settings()
    
    # Get invoice details
    invoice_manager = InvoiceManager(user_id)
    invoice = invoice_manager.get(invoice_id)
    if not invoice:
        return {'error': 'Invoice not found'}
    
    # Calculate amount due
    amount_due = invoice.get('total', 0) - invoice.get('amount_paid', 0)
    if amount_due <= 0:
        return {'error': 'Invoice already paid'}
    
    # Generate unique reference
    checkout_reference = f"INV-{invoice['invoice_number']}-{secrets.token_hex(4)}"
    
    # Create checkout via API
    checkout_data = {
        "checkout_reference": checkout_reference,
        "amount": float(amount_due),
        "currency": invoice.get('currency', 'GBP'),
        "merchant_code": settings['merchant_code'],
        "description": f"{settings.get('payment_description', 'Invoice Payment')} - {invoice['invoice_number']}",
    }
    
    # Add redirect URL for 3DS if provided
    if redirect_url:
        checkout_data['redirect_url'] = redirect_url
    
    result = sumup_manager._make_request('POST', '/v0.1/checkouts', checkout_data)
    if not result:
        return {'error': 'Failed to create checkout'}
    
    if 'error' in result:
        return result
    
    checkout_id = result.get('id')
    if not checkout_id:
        return {'error': 'No checkout ID returned'}
    
    # Save checkout record
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO sumup_checkouts 
            (user_id, invoice_id, checkout_id, checkout_reference, amount, currency, status)
            VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
        ''', (
            user_id, invoice_id, checkout_id, checkout_reference,
            amount_due, invoice.get('currency', 'GBP')
        ))
        conn.commit()
    
    return {
        'checkout_id': checkout_id,
        'checkout_reference': checkout_reference,
        'amount': amount_due,
        'currency': invoice.get('currency', 'GBP'),
        'merchant_code': settings['merchant_code'],
        'status': 'PENDING'
    }


def get_sumup_checkout(user_id: int, invoice_id: int) -> Optional[Dict]:
    """Get existing SumUp checkout for an invoice."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM sumup_checkouts 
            WHERE user_id = ? AND invoice_id = ? AND status = 'PENDING'
            ORDER BY created_at DESC LIMIT 1
        ''', (user_id, invoice_id))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_or_create_checkout(user_id: int, invoice_id: int, redirect_url: str = None) -> Dict:
    """Get existing pending checkout or create a new one."""
    existing = get_sumup_checkout(user_id, invoice_id)
    if existing:
        return {
            'checkout_id': existing['checkout_id'],
            'checkout_reference': existing['checkout_reference'],
            'amount': existing['amount'],
            'currency': existing['currency'],
            'status': existing['status']
        }
    
    return create_sumup_checkout(user_id, invoice_id, redirect_url)


# =============================================================================
# Payment Verification & Recording
# =============================================================================

def verify_and_record_payment(user_id: int, checkout_id: str) -> Tuple[bool, str, Optional[int]]:
    """
    Verify checkout status with SumUp API and record payment if successful.
    Called after the Payment Widget reports success.
    
    Returns (success, message, invoice_id)
    """
    sumup_manager = SumUpManager(user_id)
    
    # Get checkout from our database
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM sumup_checkouts WHERE checkout_id = ? AND user_id = ?
        ''', (checkout_id, user_id))
        checkout_record = cursor.fetchone()
    
    if not checkout_record:
        return False, 'Checkout not found in database', None
    
    checkout_record = dict(checkout_record)
    invoice_id = checkout_record.get('invoice_id')
    
    # Verify with SumUp API
    result = sumup_manager.get_checkout_status(checkout_id)
    if not result:
        return False, 'Failed to verify checkout with SumUp', invoice_id
    
    if 'error' in result:
        return False, f"SumUp API error: {result['error']}", invoice_id
    
    status = result.get('status', '').upper()
    
    # Update our checkout record
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE sumup_checkouts 
            SET status = ?, transaction_id = ?, transaction_code = ?, updated_at = CURRENT_TIMESTAMP
            WHERE checkout_id = ?
        ''', (
            status,
            result.get('transaction_id'),
            result.get('transaction_code'),
            checkout_id
        ))
        conn.commit()
    
    # If paid, record payment on invoice
    if status == 'PAID':
        invoice_manager = InvoiceManager(user_id)
        invoice = invoice_manager.get(invoice_id)
        
        if not invoice:
            return False, 'Invoice not found', invoice_id
        
        if invoice['status'] == 'paid':
            return True, 'Invoice already marked as paid', invoice_id
        
        try:
            amount = checkout_record.get('amount', 0)
            invoice_manager.add_payment(
                invoice_id=invoice_id,
                amount=amount,
                payment_method='sumup',
                reference=result.get('transaction_code') or checkout_id,
                notes=f"SumUp payment - {checkout_record.get('checkout_reference')}"
            )
            
            return True, 'Payment recorded successfully', invoice_id
            
        except Exception as e:
            return False, f'Error recording payment: {str(e)}', invoice_id
    
    elif status == 'FAILED':
        return False, 'Payment failed', invoice_id
    
    elif status == 'PENDING':
        return False, 'Payment still pending', invoice_id
    
    return False, f'Unknown status: {status}', invoice_id


# =============================================================================
# Callback Handler (for redirect after 3DS)
# =============================================================================

def handle_sumup_callback(checkout_id: str) -> Tuple[bool, str, Optional[int], Optional[int]]:
    """
    Handle callback after SumUp payment/3DS redirect.
    Returns (success, message, invoice_id, user_id)
    """
    # Find the checkout record
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM sumup_checkouts WHERE checkout_id = ?
        ''', (checkout_id,))
        checkout_record = cursor.fetchone()
    
    if not checkout_record:
        return False, 'Checkout not found', None, None
    
    checkout_record = dict(checkout_record)
    user_id = checkout_record['user_id']
    invoice_id = checkout_record['invoice_id']
    
    # Verify and record
    success, message, _ = verify_and_record_payment(user_id, checkout_id)
    
    return success, message, invoice_id, user_id


# =============================================================================
# Helper Functions
# =============================================================================

def get_sumup_checkout_info(user_id: int, invoice_id: int) -> Optional[Dict]:
    """Get SumUp checkout info for display on invoice."""
    sumup_manager = SumUpManager(user_id)
    if not sumup_manager.is_configured():
        return None
    
    checkout = get_sumup_checkout(user_id, invoice_id)
    if checkout:
        return {
            'checkout_id': checkout['checkout_id'],
            'merchant_code': sumup_manager.get_settings().get('merchant_code'),
            'status': checkout['status']
        }
    
    return None


def log_sumup_event(user_id: int, event_type: str, checkout_id: str, status: str,
                    message: str, invoice_id: int = None, payload: str = None):
    """Log a SumUp event."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO sumup_webhook_logs 
            (user_id, event_type, event_id, invoice_id, status, message, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, event_type, checkout_id, invoice_id, status, message, payload))
        conn.commit()


# =============================================================================
# Database Initialization
# =============================================================================

def init_sumup_tables():
    """Initialize SumUp-related database tables."""
    from database import is_mysql, should_skip_table_creation
    
    # Skip if MySQL and tables exist
    if is_mysql() and should_skip_table_creation('sumup_settings'):
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # SumUp settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sumup_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                enabled INTEGER DEFAULT 0,
                api_key TEXT,
                merchant_code TEXT,
                include_in_invoice_pdf INTEGER DEFAULT 1,
                include_in_email INTEGER DEFAULT 1,
                payment_description TEXT DEFAULT 'Invoice Payment',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Checkouts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sumup_checkouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                invoice_id INTEGER NOT NULL,
                checkout_id TEXT NOT NULL,
                checkout_reference TEXT,
                amount REAL,
                currency TEXT DEFAULT 'GBP',
                status TEXT DEFAULT 'PENDING',
                transaction_id TEXT,
                transaction_code TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (invoice_id) REFERENCES invoices (id)
            )
        ''')
        
        # Event logs (renamed from webhook_logs but keeping for compatibility)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sumup_webhook_logs (
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
        ''')
        
        # Add new columns if they don't exist (for existing databases)
        try:
            cursor.execute('ALTER TABLE sumup_checkouts ADD COLUMN transaction_id TEXT')
        except:
            pass
        
        try:
            cursor.execute('ALTER TABLE sumup_checkouts ADD COLUMN transaction_code TEXT')
        except:
            pass
        
        conn.commit()
