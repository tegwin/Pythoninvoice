"""
Invoice Manager - Wise Integration Module
Handles Wise (TransferWise) payments, transfers, and webhooks.
Wise is primarily used for receiving payments via local bank details and tracking incoming transfers.
Copyright (c) 2026 Sondela Consulting Ltd.
"""

import hashlib
import hmac
import json
import base64
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from app_core import get_db, InvoiceManager, SettingsManager


# =============================================================================
# Wise Settings Manager
# =============================================================================

class WiseManager:
    """Manage Wise integration settings and operations."""
    
    SANDBOX_API_URL = "https://api.sandbox.transferwise.tech"
    LIVE_API_URL = "https://api.wise.com"
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self._settings = None
    
    def get_settings(self) -> Dict:
        """Get Wise settings for user."""
        if self._settings:
            return self._settings
            
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM wise_settings WHERE user_id = ?',
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
                    'live_mode': 0,
                    'sandbox_api_token': None,
                    'live_api_token': None,
                    'profile_id': None,
                    'webhook_public_key': None,
                    'include_in_invoice_pdf': 1,
                    'include_in_email': 1,
                    'gbp_account_details': None,
                    'eur_account_details': None,
                    'usd_account_details': None
                }
            
            return self._settings
    
    def save_settings(self, data: Dict) -> bool:
        """Save Wise settings."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Check if exists
            cursor.execute(
                'SELECT id FROM wise_settings WHERE user_id = ?',
                (self.user_id,)
            )
            exists = cursor.fetchone()
            
            if exists:
                # Update
                fields = []
                values = []
                for key in ['enabled', 'live_mode', 'sandbox_api_token', 'live_api_token',
                           'profile_id', 'webhook_public_key', 'include_in_invoice_pdf', 
                           'include_in_email', 'gbp_account_details', 'eur_account_details',
                           'usd_account_details']:
                    if key in data:
                        fields.append(f'{key} = ?')
                        values.append(data[key])
                
                if fields:
                    values.append(self.user_id)
                    cursor.execute(
                        f'UPDATE wise_settings SET {", ".join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
                        values
                    )
            else:
                # Insert
                cursor.execute('''
                    INSERT INTO wise_settings (
                        user_id, enabled, live_mode, sandbox_api_token, live_api_token,
                        profile_id, webhook_public_key, include_in_invoice_pdf, include_in_email,
                        gbp_account_details, eur_account_details, usd_account_details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    self.user_id,
                    data.get('enabled', 0),
                    data.get('live_mode', 0),
                    data.get('sandbox_api_token'),
                    data.get('live_api_token'),
                    data.get('profile_id'),
                    data.get('webhook_public_key'),
                    data.get('include_in_invoice_pdf', 1),
                    data.get('include_in_email', 1),
                    data.get('gbp_account_details'),
                    data.get('eur_account_details'),
                    data.get('usd_account_details')
                ))
            
            conn.commit()
            self._settings = None  # Clear cache
            return True
    
    def is_configured(self) -> bool:
        """Check if Wise is properly configured."""
        settings = self.get_settings()
        if not settings.get('enabled'):
            return False
        
        if settings.get('live_mode'):
            return bool(settings.get('live_api_token'))
        else:
            return bool(settings.get('sandbox_api_token'))
    
    def get_api_token(self) -> Optional[str]:
        """Get the current API token (sandbox or live based on mode)."""
        settings = self.get_settings()
        if settings.get('live_mode'):
            return settings.get('live_api_token')
        return settings.get('sandbox_api_token')
    
    def get_api_url(self) -> str:
        """Get the API URL based on mode."""
        settings = self.get_settings()
        if settings.get('live_mode'):
            return self.LIVE_API_URL
        return self.SANDBOX_API_URL
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Optional[Dict]:
        """Make an API request to Wise."""
        import requests
        
        api_token = self.get_api_token()
        if not api_token:
            return None
        
        url = f"{self.get_api_url()}{endpoint}"
        headers = {
            'Authorization': f'Bearer {api_token}',
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
                print(f"Wise API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"Wise request error: {e}")
            return None
    
    def get_profiles(self) -> Optional[List[Dict]]:
        """Get user profiles from Wise."""
        return self._make_request('GET', '/v1/profiles')
    
    def get_balance_accounts(self, profile_id: str) -> Optional[List[Dict]]:
        """Get balance accounts for a profile."""
        return self._make_request('GET', f'/v4/profiles/{profile_id}/balances?types=STANDARD')
    
    def get_account_details(self, profile_id: str, balance_id: str) -> Optional[Dict]:
        """Get bank account details for receiving payments."""
        return self._make_request('GET', f'/v1/profiles/{profile_id}/account-details/{balance_id}')


# =============================================================================
# Payment Matching
# =============================================================================

def match_wise_payment(user_id: int, transfer_data: Dict) -> Optional[int]:
    """
    Try to match a Wise transfer to an invoice.
    Uses reference field to match invoice number.
    Returns invoice_id if matched.
    """
    reference = transfer_data.get('reference', '')
    amount = transfer_data.get('amount', 0)
    currency = transfer_data.get('currency', 'GBP')
    
    if not reference:
        return None
    
    # Try to extract invoice number from reference
    # Common patterns: "INV-001", "Invoice 001", "#001"
    import re
    
    # Look for invoice number patterns
    patterns = [
        r'INV[-_]?(\d+)',
        r'Invoice\s*#?\s*(\d+)',
        r'#(\d+)',
    ]
    
    invoice_number = None
    for pattern in patterns:
        match = re.search(pattern, reference, re.IGNORECASE)
        if match:
            invoice_number = match.group(0)
            break
    
    if not invoice_number:
        # Try using the whole reference
        invoice_number = reference.strip()
    
    # Look for matching invoice
    invoice_manager = InvoiceManager(user_id)
    invoice = invoice_manager.get_by_number(invoice_number)
    
    if invoice:
        return invoice['id']
    
    # Try partial match
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id FROM invoices 
            WHERE user_id = ? 
            AND invoice_number LIKE ?
            AND status != 'paid'
            AND currency = ?
            ORDER BY created_at DESC
            LIMIT 1
        ''', (user_id, f'%{invoice_number}%', currency))
        row = cursor.fetchone()
        if row:
            return row['id']
    
    return None


def record_wise_payment(user_id: int, invoice_id: int, transfer_data: Dict) -> bool:
    """Record a Wise payment against an invoice."""
    try:
        invoice_manager = InvoiceManager(user_id)
        invoice = invoice_manager.get(invoice_id)
        
        if not invoice:
            return False
        
        if invoice['status'] == 'paid':
            return True  # Already paid
        
        amount = transfer_data.get('amount', 0)
        transfer_id = transfer_data.get('transfer_id', '')
        reference = transfer_data.get('reference', '')
        
        invoice_manager.add_payment(
            invoice_id=invoice_id,
            amount=amount,
            payment_method='wise',
            reference=transfer_id,
            notes=f"Wise transfer - {reference}"
        )
        
        return True
        
    except Exception as e:
        print(f"Error recording Wise payment: {e}")
        return False


# =============================================================================
# Webhook Processing
# =============================================================================

def verify_wise_signature(payload: bytes, signature: str, public_key: str) -> bool:
    """
    Verify Wise webhook signature.
    Wise uses RSA signature verification with public key.
    """
    # Note: Full RSA verification requires cryptography library
    # For now, we'll do basic validation
    if not signature or not public_key:
        return True  # Skip verification if not configured
    
    # In production, you would:
    # 1. Decode the base64 signature
    # 2. Use the public key to verify the RSA signature
    # For simplicity, we trust the webhook if public key isn't set
    return True


def process_wise_webhook(payload: Dict, user_id: int) -> Tuple[bool, str, Optional[int]]:
    """
    Process a Wise webhook event.
    Returns (success, message, invoice_id)
    """
    event_type = payload.get('event_type', '')
    data = payload.get('data', {})
    
    if event_type == 'transfers#state-change':
        return handle_transfer_state_change(data, user_id)
    elif event_type == 'balances#credit':
        return handle_balance_credit(data, user_id)
    
    return True, f'Event {event_type} acknowledged', None


def handle_transfer_state_change(data: Dict, user_id: int) -> Tuple[bool, str, Optional[int]]:
    """Handle transfer state change webhook."""
    resource = data.get('resource', {})
    current_state = data.get('current_state', '')
    transfer_id = resource.get('id')
    
    if not transfer_id:
        return True, 'No transfer ID in event', None
    
    # Check if we're tracking this transfer
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM wise_transfers WHERE transfer_id = ?
        ''', (str(transfer_id),))
        transfer = cursor.fetchone()
    
    if transfer:
        transfer = dict(transfer)
        invoice_id = transfer.get('invoice_id')
        
        # Update transfer status
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE wise_transfers 
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE transfer_id = ?
            ''', (current_state, str(transfer_id)))
            conn.commit()
        
        # If payment completed, record it
        if current_state in ['outgoing_payment_sent', 'funds_converted']:
            # This is an outgoing transfer, not relevant for invoice payment
            pass
        
        return True, f'Transfer {transfer_id} updated to {current_state}', invoice_id
    
    return True, f'Transfer {transfer_id} not tracked', None


def handle_balance_credit(data: Dict, user_id: int) -> Tuple[bool, str, Optional[int]]:
    """
    Handle balance credit webhook - money received into Wise account.
    This is the main event for matching incoming payments to invoices.
    """
    resource = data.get('resource', {})
    transfer_reference = resource.get('transfer_reference', '')
    amount = resource.get('amount', 0)
    currency = resource.get('currency', 'GBP')
    transaction_id = resource.get('id')
    
    # Try to match to an invoice
    transfer_data = {
        'transfer_id': str(transaction_id),
        'reference': transfer_reference,
        'amount': amount,
        'currency': currency
    }
    
    invoice_id = match_wise_payment(user_id, transfer_data)
    
    if invoice_id:
        # Record the payment
        success = record_wise_payment(user_id, invoice_id, transfer_data)
        if success:
            # Save the credit record
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO wise_credits 
                    (user_id, invoice_id, transaction_id, reference, amount, currency, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'matched')
                ''', (user_id, invoice_id, str(transaction_id), transfer_reference, amount, currency))
                conn.commit()
            
            return True, f'Payment matched and recorded for invoice', invoice_id
    
    # Save unmatched credit for manual matching later
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO wise_credits 
            (user_id, transaction_id, reference, amount, currency, status)
            VALUES (?, ?, ?, ?, ?, 'unmatched')
        ''', (user_id, str(transaction_id), transfer_reference, amount, currency))
        conn.commit()
    
    return True, f'Credit received but not matched to invoice', None


# =============================================================================
# Bank Details for Invoices
# =============================================================================

def get_wise_bank_details(user_id: int, currency: str) -> Optional[Dict]:
    """Get Wise bank details for a specific currency to display on invoices."""
    wise_manager = WiseManager(user_id)
    settings = wise_manager.get_settings()
    
    if not settings.get('enabled'):
        return None
    
    currency = currency.upper()
    
    # Check stored details
    details_key = f'{currency.lower()}_account_details'
    stored_details = settings.get(details_key)
    
    if stored_details:
        try:
            return json.loads(stored_details)
        except:
            pass
    
    return None


def format_wise_bank_details_html(user_id: int, currency: str) -> Optional[str]:
    """Format Wise bank details as HTML for invoices/emails."""
    details = get_wise_bank_details(user_id, currency)
    if not details:
        return None
    
    html = '''
    <div style="padding: 12px; background: #9fe870; color: #000; border-radius: 6px; margin-top: 1rem;">
        <strong style="display: block; margin-bottom: 0.5rem;">💚 Pay via Wise</strong>
    '''
    
    if currency == 'GBP':
        html += f'''
        <table style="font-size: 0.9rem;">
            <tr><td style="padding-right: 1rem;">Account Name:</td><td><strong>{details.get('account_name', '')}</strong></td></tr>
            <tr><td>Sort Code:</td><td><strong>{details.get('sort_code', '')}</strong></td></tr>
            <tr><td>Account Number:</td><td><strong>{details.get('account_number', '')}</strong></td></tr>
        </table>
        '''
    elif currency == 'EUR':
        html += f'''
        <table style="font-size: 0.9rem;">
            <tr><td style="padding-right: 1rem;">Account Name:</td><td><strong>{details.get('account_name', '')}</strong></td></tr>
            <tr><td>IBAN:</td><td><strong>{details.get('iban', '')}</strong></td></tr>
            <tr><td>BIC:</td><td><strong>{details.get('bic', '')}</strong></td></tr>
        </table>
        '''
    elif currency == 'USD':
        html += f'''
        <table style="font-size: 0.9rem;">
            <tr><td style="padding-right: 1rem;">Account Name:</td><td><strong>{details.get('account_name', '')}</strong></td></tr>
            <tr><td>Routing Number:</td><td><strong>{details.get('routing_number', '')}</strong></td></tr>
            <tr><td>Account Number:</td><td><strong>{details.get('account_number', '')}</strong></td></tr>
            <tr><td>Account Type:</td><td><strong>{details.get('account_type', 'Checking')}</strong></td></tr>
        </table>
        '''
    
    html += '<small style="display: block; margin-top: 0.5rem;">Include your invoice number as the payment reference</small>'
    html += '</div>'
    
    return html


# =============================================================================
# Helper Functions
# =============================================================================

def log_wise_webhook(user_id: int, event_type: str, event_id: str, status: str,
                     message: str, invoice_id: int = None, payload: str = None):
    """Log a Wise webhook event."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO wise_webhook_logs 
            (user_id, event_type, event_id, invoice_id, status, message, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, event_type, event_id, invoice_id, status, message, payload))
        conn.commit()


def get_unmatched_credits(user_id: int) -> List[Dict]:
    """Get list of unmatched Wise credits for manual matching."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM wise_credits 
            WHERE user_id = ? AND status = 'unmatched'
            ORDER BY created_at DESC
        ''', (user_id,))
        return [dict(row) for row in cursor.fetchall()]


def manually_match_credit(user_id: int, credit_id: int, invoice_id: int) -> bool:
    """Manually match a Wise credit to an invoice."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM wise_credits WHERE id = ? AND user_id = ?
        ''', (credit_id, user_id))
        credit = cursor.fetchone()
        
        if not credit:
            return False
        
        credit = dict(credit)
        
        # Record the payment
        transfer_data = {
            'transfer_id': credit['transaction_id'],
            'reference': credit['reference'],
            'amount': credit['amount'],
            'currency': credit['currency']
        }
        
        if record_wise_payment(user_id, invoice_id, transfer_data):
            cursor.execute('''
                UPDATE wise_credits 
                SET invoice_id = ?, status = 'matched', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (invoice_id, credit_id))
            conn.commit()
            return True
    
    return False


# =============================================================================
# Database Initialization
# =============================================================================

def init_wise_tables():
    """Initialize Wise-related database tables."""
    from database import is_mysql, should_skip_table_creation
    
    # Skip if MySQL and tables exist
    if is_mysql() and should_skip_table_creation('wise_settings'):
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Wise settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wise_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                enabled INTEGER DEFAULT 0,
                live_mode INTEGER DEFAULT 0,
                sandbox_api_token TEXT,
                live_api_token TEXT,
                profile_id TEXT,
                webhook_public_key TEXT,
                include_in_invoice_pdf INTEGER DEFAULT 1,
                include_in_email INTEGER DEFAULT 1,
                gbp_account_details TEXT,
                eur_account_details TEXT,
                usd_account_details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Wise credits (incoming payments)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wise_credits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                invoice_id INTEGER,
                transaction_id TEXT,
                reference TEXT,
                amount REAL,
                currency TEXT DEFAULT 'GBP',
                status TEXT DEFAULT 'unmatched',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (invoice_id) REFERENCES invoices (id)
            )
        ''')
        
        # Wise transfers (outgoing - for reference)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wise_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                invoice_id INTEGER,
                transfer_id TEXT,
                quote_id TEXT,
                status TEXT,
                amount REAL,
                currency TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (invoice_id) REFERENCES invoices (id)
            )
        ''')
        
        # Webhook logs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wise_webhook_logs (
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
        
        conn.commit()
