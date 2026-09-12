"""
Invoice Manager - Stripe Integration Module
Handles Stripe payment links, webhooks, and payment processing.
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
# Stripe Settings Manager
# =============================================================================

class StripeManager:
    """Manage Stripe integration settings and operations."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self._settings = None
    
    def get_settings(self) -> Dict:
        """Get Stripe settings for user."""
        if self._settings:
            return self._settings
            
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM stripe_settings WHERE user_id = ?',
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
                    'test_publishable_key': None,
                    'test_secret_key': None,
                    'live_publishable_key': None,
                    'live_secret_key': None,
                    'webhook_secret': None,
                    'include_in_invoice_pdf': 1,
                    'include_in_email': 1,
                    'payment_button_text': 'Pay Now with Card',
                    'success_url': None,
                    'cancel_url': None
                }
            
            return self._settings
    
    def save_settings(self, data: Dict) -> bool:
        """Save Stripe settings."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Check if exists
            cursor.execute(
                'SELECT id FROM stripe_settings WHERE user_id = ?',
                (self.user_id,)
            )
            exists = cursor.fetchone()
            
            if exists:
                # Update
                fields = []
                values = []
                for key in ['enabled', 'live_mode', 'test_publishable_key', 'test_secret_key',
                           'live_publishable_key', 'live_secret_key', 'webhook_secret',
                           'include_in_invoice_pdf', 'include_in_email', 'payment_button_text',
                           'success_url', 'cancel_url']:
                    if key in data:
                        fields.append(f'{key} = ?')
                        values.append(data[key])
                
                if fields:
                    values.append(self.user_id)
                    cursor.execute(
                        f'UPDATE stripe_settings SET {", ".join(fields)} WHERE user_id = ?',
                        values
                    )
            else:
                # Insert
                cursor.execute('''
                    INSERT INTO stripe_settings (
                        user_id, enabled, live_mode, test_publishable_key, test_secret_key,
                        live_publishable_key, live_secret_key, webhook_secret,
                        include_in_invoice_pdf, include_in_email, payment_button_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    self.user_id,
                    data.get('enabled', 0),
                    data.get('live_mode', 0),
                    data.get('test_publishable_key'),
                    data.get('test_secret_key'),
                    data.get('live_publishable_key'),
                    data.get('live_secret_key'),
                    data.get('webhook_secret'),
                    data.get('include_in_invoice_pdf', 1),
                    data.get('include_in_email', 1),
                    data.get('payment_button_text', 'Pay Now with Card')
                ))
            
            conn.commit()
            self._settings = None  # Clear cache
            return True
    
    def is_configured(self) -> bool:
        """Check if Stripe is properly configured."""
        settings = self.get_settings()
        if not settings.get('enabled'):
            return False
        
        if settings.get('live_mode'):
            return bool(settings.get('live_secret_key'))
        else:
            return bool(settings.get('test_secret_key'))
    
    def get_api_key(self) -> Optional[str]:
        """Get the current API secret key (test or live based on mode)."""
        settings = self.get_settings()
        if settings.get('live_mode'):
            return settings.get('live_secret_key')
        return settings.get('test_secret_key')
    
    def get_publishable_key(self) -> Optional[str]:
        """Get the current publishable key (test or live based on mode)."""
        settings = self.get_settings()
        if settings.get('live_mode'):
            return settings.get('live_publishable_key')
        return settings.get('test_publishable_key')


# =============================================================================
# Payment Link Generation
# =============================================================================

def create_payment_link(user_id: int, invoice_id: int, base_url: str) -> Optional[Dict]:
    """
    Create a Stripe Checkout Session for an invoice.
    Returns dict with payment URL and session ID.
    """
    import requests
    
    stripe_manager = StripeManager(user_id)
    if not stripe_manager.is_configured():
        return None
    
    settings = stripe_manager.get_settings()
    api_key = stripe_manager.get_api_key()
    
    # Get invoice details
    invoice_manager = InvoiceManager(user_id)
    invoice = invoice_manager.get(invoice_id)
    
    if not invoice:
        return None
    
    # Calculate amount due
    amount_due = invoice.get('total', 0) - invoice.get('amount_paid', 0)
    if amount_due <= 0:
        return None
    
    # Convert to cents/pence (Stripe uses smallest currency unit)
    amount_cents = int(amount_due * 100)
    
    # Determine currency
    currency = invoice.get('currency', 'GBP').lower()
    
    # Build line items
    line_items = [{
        'price_data': {
            'currency': currency,
            'unit_amount': amount_cents,
            'product_data': {
                'name': f"Invoice {invoice['invoice_number']}",
                'description': f"Payment for invoice {invoice['invoice_number']}" + 
                              (f" - {invoice.get('customer_name', '')}" if invoice.get('customer_name') else "")
            }
        },
        'quantity': 1
    }]
    
    # Success and cancel URLs
    success_url = settings.get('success_url') or f"{base_url}/invoices/{invoice_id}?payment=success"
    cancel_url = settings.get('cancel_url') or f"{base_url}/invoices/{invoice_id}?payment=cancelled"
    
    # Create Checkout Session via Stripe API
    try:
        response = requests.post(
            'https://api.stripe.com/v1/checkout/sessions',
            auth=(api_key, ''),
            data={
                'payment_method_types[]': 'card',
                'line_items[0][price_data][currency]': currency,
                'line_items[0][price_data][unit_amount]': amount_cents,
                'line_items[0][price_data][product_data][name]': f"Invoice {invoice['invoice_number']}",
                'line_items[0][quantity]': 1,
                'mode': 'payment',
                'success_url': success_url,
                'cancel_url': cancel_url,
                'metadata[invoice_id]': str(invoice_id),
                'metadata[invoice_number]': invoice['invoice_number'],
                'metadata[user_id]': str(user_id),
                'customer_email': invoice.get('customer_email') or '',
            },
            timeout=30
        )
        
        if response.status_code == 200:
            session = response.json()
            
            # Store the session ID for tracking
            save_payment_session(user_id, invoice_id, session['id'], session['url'])
            
            return {
                'session_id': session['id'],
                'payment_url': session['url'],
                'amount': amount_due,
                'currency': currency.upper()
            }
        else:
            error = response.json()
            print(f"Stripe API error: {error}")
            return None
            
    except Exception as e:
        print(f"Error creating Stripe session: {e}")
        return None


def get_payment_link(user_id: int, invoice_id: int) -> Optional[str]:
    """Get existing payment link for an invoice, or return None."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT payment_url FROM stripe_payment_sessions 
            WHERE user_id = ? AND invoice_id = ? AND status = 'pending'
            ORDER BY created_at DESC LIMIT 1
        ''', (user_id, invoice_id))
        row = cursor.fetchone()
        return row['payment_url'] if row else None


def save_payment_session(user_id: int, invoice_id: int, session_id: str, payment_url: str):
    """Save a Stripe payment session for tracking."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO stripe_payment_sessions (user_id, invoice_id, session_id, payment_url, status)
            VALUES (?, ?, ?, ?, 'pending')
        ''', (user_id, invoice_id, session_id, payment_url))
        conn.commit()


def update_payment_session_status(session_id: str, status: str, payment_intent: str = None):
    """Update a payment session status."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE stripe_payment_sessions 
            SET status = ?, payment_intent_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE session_id = ?
        ''', (status, payment_intent, session_id))
        conn.commit()


# =============================================================================
# Webhook Processing
# =============================================================================

def verify_stripe_signature(payload: bytes, signature: str, webhook_secret: str) -> bool:
    """Verify Stripe webhook signature."""
    try:
        # Parse signature header
        parts = dict(item.split('=') for item in signature.split(','))
        timestamp = parts.get('t', '')
        sig = parts.get('v1', '')
        
        # Create signed payload
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
        
        # Compute expected signature
        expected = hmac.new(
            webhook_secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(sig, expected)
    except Exception as e:
        print(f"Signature verification error: {e}")
        return False


def process_stripe_webhook(payload: Dict, user_id: int) -> Tuple[bool, str, Optional[int]]:
    """
    Process a Stripe webhook event.
    Returns (success, message, invoice_id)
    """
    event_type = payload.get('type', '')
    data = payload.get('data', {}).get('object', {})
    
    if event_type == 'checkout.session.completed':
        return handle_checkout_completed(data, user_id)
    
    elif event_type == 'payment_intent.succeeded':
        return handle_payment_intent_succeeded(data, user_id)
    
    elif event_type == 'charge.succeeded':
        # Often fires alongside payment_intent.succeeded
        return True, 'Charge noted', None
    
    else:
        return True, f'Event {event_type} acknowledged', None


def handle_checkout_completed(data: Dict, user_id: int) -> Tuple[bool, str, Optional[int]]:
    """Handle checkout.session.completed event."""
    session_id = data.get('id')
    payment_intent = data.get('payment_intent')
    payment_status = data.get('payment_status')
    
    # Get invoice from metadata
    metadata = data.get('metadata', {})
    invoice_id = metadata.get('invoice_id')
    invoice_number = metadata.get('invoice_number')
    
    if not invoice_id:
        # Try to find from our stored sessions
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT invoice_id, user_id FROM stripe_payment_sessions WHERE session_id = ?',
                (session_id,)
            )
            row = cursor.fetchone()
            if row:
                invoice_id = row['invoice_id']
                user_id = row['user_id']
    
    if not invoice_id:
        return False, 'Invoice not found in webhook data', None
    
    invoice_id = int(invoice_id)
    
    # Update session status
    update_payment_session_status(session_id, 'completed', payment_intent)
    
    # Only process if payment was successful
    if payment_status != 'paid':
        return True, f'Session completed but payment status is {payment_status}', invoice_id
    
    # Get payment amount
    amount_total = data.get('amount_total', 0) / 100  # Convert from cents
    
    # Record payment on invoice
    invoice_manager = InvoiceManager(user_id)
    invoice = invoice_manager.get(invoice_id)
    
    if not invoice:
        return False, 'Invoice not found', invoice_id
    
    if invoice['status'] == 'paid':
        return True, 'Invoice already paid', invoice_id
    
    # Add payment
    try:
        invoice_manager.add_payment(
            invoice_id=invoice_id,
            amount=amount_total,
            payment_method='stripe',
            reference=payment_intent or session_id,
            notes=f"Stripe payment via Checkout Session"
        )
        
        # Check if fully paid
        updated_invoice = invoice_manager.get(invoice_id)
        status = 'fully paid' if updated_invoice['status'] == 'paid' else 'partially paid'
        
        return True, f'Payment recorded: {status}', invoice_id
        
    except Exception as e:
        return False, f'Error recording payment: {str(e)}', invoice_id


def handle_payment_intent_succeeded(data: Dict, user_id: int) -> Tuple[bool, str, Optional[int]]:
    """Handle payment_intent.succeeded event."""
    payment_intent_id = data.get('id')
    amount = data.get('amount_received', 0) / 100
    
    # Get invoice from metadata
    metadata = data.get('metadata', {})
    invoice_id = metadata.get('invoice_id')
    
    if not invoice_id:
        # This might be from a different source, not our checkout
        return True, 'Payment intent noted (no invoice linked)', None
    
    invoice_id = int(invoice_id)
    
    # Record payment
    invoice_manager = InvoiceManager(user_id)
    invoice = invoice_manager.get(invoice_id)
    
    if not invoice:
        return False, 'Invoice not found', invoice_id
    
    if invoice['status'] == 'paid':
        return True, 'Invoice already paid', invoice_id
    
    try:
        invoice_manager.add_payment(
            invoice_id=invoice_id,
            amount=amount,
            payment_method='stripe',
            reference=payment_intent_id,
            notes='Stripe payment intent'
        )
        
        updated_invoice = invoice_manager.get(invoice_id)
        status = 'fully paid' if updated_invoice['status'] == 'paid' else 'partially paid'
        
        return True, f'Payment recorded: {status}', invoice_id
        
    except Exception as e:
        return False, f'Error recording payment: {str(e)}', invoice_id


# =============================================================================
# Helper Functions
# =============================================================================

def get_stripe_payment_button_html(user_id: int, invoice_id: int, base_url: str) -> Optional[str]:
    """Generate HTML for a Stripe payment button."""
    stripe_manager = StripeManager(user_id)
    settings = stripe_manager.get_settings()
    
    if not settings.get('enabled') or not stripe_manager.is_configured():
        return None
    
    # Get or create payment link
    payment_url = get_payment_link(user_id, invoice_id)
    
    if not payment_url:
        result = create_payment_link(user_id, invoice_id, base_url)
        if result:
            payment_url = result['payment_url']
    
    if not payment_url:
        return None
    
    button_text = settings.get('payment_button_text', 'Pay Now with Card')
    
    return f'''
    <a href="{payment_url}" 
       style="display: inline-block; background: #635bff; color: white; padding: 12px 24px; 
              text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 14px;"
       target="_blank">
        💳 {button_text}
    </a>
    '''


def get_stripe_payment_link_for_email(user_id: int, invoice_id: int, base_url: str) -> Optional[Dict]:
    """Get payment link info for email inclusion."""
    stripe_manager = StripeManager(user_id)
    settings = stripe_manager.get_settings()
    
    if not settings.get('enabled') or not settings.get('include_in_email'):
        return None
    
    if not stripe_manager.is_configured():
        return None
    
    # Get or create payment link
    payment_url = get_payment_link(user_id, invoice_id)
    
    if not payment_url:
        result = create_payment_link(user_id, invoice_id, base_url)
        if result:
            payment_url = result['payment_url']
    
    if not payment_url:
        return None
    
    return {
        'url': payment_url,
        'button_text': settings.get('payment_button_text', 'Pay Now with Card')
    }


# =============================================================================
# Database Initialization
# =============================================================================

def init_stripe_tables():
    """Initialize Stripe-related database tables."""
    from database import is_mysql, should_skip_table_creation
    
    # Skip if MySQL and tables exist
    if is_mysql() and should_skip_table_creation('stripe_settings'):
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        if is_mysql():
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stripe_settings (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL UNIQUE,
                    enabled TINYINT DEFAULT 0,
                    live_mode TINYINT DEFAULT 0,
                    test_publishable_key VARCHAR(255),
                    test_secret_key VARCHAR(255),
                    live_publishable_key VARCHAR(255),
                    live_secret_key VARCHAR(255),
                    webhook_secret VARCHAR(255),
                    include_in_invoice_pdf TINYINT DEFAULT 1,
                    include_in_email TINYINT DEFAULT 1,
                    payment_button_text VARCHAR(255) DEFAULT 'Pay Now with Card',
                    success_url VARCHAR(500),
                    cancel_url VARCHAR(500),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stripe_payment_sessions (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    invoice_id INT NOT NULL,
                    session_id VARCHAR(255) NOT NULL,
                    payment_intent_id VARCHAR(255),
                    payment_url VARCHAR(500),
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stripe_webhook_logs (
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
            ''')
            conn.commit()
            return
        
        # SQLite syntax
        cursor.execute('''
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
        ''')
        
        # Payment sessions table (track checkout sessions)
        cursor.execute('''
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
        ''')
        
        # Webhook logs
        cursor.execute('''
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
        ''')
        
        conn.commit()


def log_stripe_webhook(user_id: int, event_type: str, event_id: str, 
                       status: str, message: str, invoice_id: int = None, 
                       payload: str = None):
    """Log a Stripe webhook event."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO stripe_webhook_logs 
            (user_id, event_type, event_id, invoice_id, status, message, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, event_type, event_id, invoice_id, status, message, payload))
        conn.commit()


def check_payment_status(user_id: int, invoice_id: int) -> Tuple[bool, str]:
    """
    Manually check payment status for an invoice by querying Stripe.
    Useful for testing when webhooks are not set up.
    
    Returns (success, message)
    """
    import requests
    
    stripe_manager = StripeManager(user_id)
    if not stripe_manager.is_configured():
        return False, 'Stripe is not configured'
    
    api_key = stripe_manager.get_api_key()
    
    # Get our stored session
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT session_id, status FROM stripe_payment_sessions
            WHERE user_id = ? AND invoice_id = ?
            ORDER BY created_at DESC LIMIT 1
        ''', (user_id, invoice_id))
        session_record = cursor.fetchone()
    
    if not session_record:
        return False, 'No payment session found for this invoice'
    
    session_id = session_record['session_id']
    current_status = session_record['status']
    
    if current_status == 'completed':
        return True, 'Payment already recorded'
    
    # Query Stripe for session status
    try:
        response = requests.get(
            f'https://api.stripe.com/v1/checkout/sessions/{session_id}',
            auth=(api_key, ''),
            timeout=30
        )
        
        if response.status_code != 200:
            return False, f'Failed to check Stripe: {response.text}'
        
        session = response.json()
        payment_status = session.get('payment_status')
        
        if payment_status == 'paid':
            # Payment was successful! Record it
            amount = session.get('amount_total', 0) / 100
            payment_intent = session.get('payment_intent')
            
            # Update session status
            update_payment_session_status(session_id, 'completed', payment_intent)
            
            # Record payment on invoice
            invoice_manager = InvoiceManager(user_id)
            invoice = invoice_manager.get(invoice_id)
            
            if not invoice:
                return False, 'Invoice not found'
            
            if invoice['status'] == 'paid':
                return True, 'Invoice already marked as paid'
            
            try:
                invoice_manager.add_payment(
                    invoice_id=invoice_id,
                    amount=amount,
                    payment_method='stripe',
                    reference=payment_intent or session_id,
                    notes='Stripe payment (manually verified)'
                )
                
                return True, f'Payment of {amount:.2f} recorded successfully!'
                
            except Exception as e:
                return False, f'Error recording payment: {str(e)}'
        
        elif payment_status == 'unpaid':
            return False, 'Payment not yet completed. Customer may have abandoned checkout.'
        
        else:
            return False, f'Payment status: {payment_status}'
            
    except Exception as e:
        return False, f'Error checking Stripe: {str(e)}'
