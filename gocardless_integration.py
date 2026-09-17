"""
Invoice Manager - GoCardless Integration Module
Handles GoCardless Direct Debit payments, mandates, and webhooks.
Copyright (c) 2026 Sondela Consulting Ltd.
"""

import hashlib
import hmac
import json
import secrets
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from app_core import get_db, InvoiceManager, SettingsManager, CustomerManager


# =============================================================================
# GoCardless Settings Manager
# =============================================================================

class GoCardlessManager:
    """Manage GoCardless integration settings and operations."""
    
    # GoCardless API endpoints
    SANDBOX_API_URL = "https://api-sandbox.gocardless.com"
    LIVE_API_URL = "https://api.gocardless.com"
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self._settings = None
    
    def get_settings(self) -> Dict:
        """Get GoCardless settings for user."""
        if self._settings:
            return self._settings
            
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM gocardless_settings WHERE user_id = ?',
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
                    'sandbox_access_token': None,
                    'live_access_token': None,
                    'webhook_secret': None,
                    'include_in_invoice_pdf': 1,
                    'include_in_email': 1,
                    'payment_description': 'Invoice Payment',
                    'days_until_collection': 5,
                    'success_redirect_url': None,
                    'creditor_id': None
                }
            
            return self._settings
    
    def save_settings(self, data: Dict) -> bool:
        """Save GoCardless settings."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Check if exists
            cursor.execute(
                'SELECT id FROM gocardless_settings WHERE user_id = ?',
                (self.user_id,)
            )
            exists = cursor.fetchone()
            
            if exists:
                # Update
                fields = []
                values = []
                for key in ['enabled', 'live_mode', 'sandbox_access_token', 'live_access_token',
                           'webhook_secret', 'include_in_invoice_pdf', 'include_in_email',
                           'payment_description', 'days_until_collection', 'success_redirect_url',
                           'creditor_id']:
                    if key in data:
                        fields.append(f'{key} = ?')
                        values.append(data[key])
                
                if fields:
                    values.append(self.user_id)
                    cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                        f'UPDATE gocardless_settings SET {", ".join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
                        values
                    )
            else:
                # Insert
                cursor.execute('''
                    INSERT INTO gocardless_settings (
                        user_id, enabled, live_mode, sandbox_access_token, live_access_token,
                        webhook_secret, include_in_invoice_pdf, include_in_email,
                        payment_description, days_until_collection
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    self.user_id,
                    data.get('enabled', 0),
                    data.get('live_mode', 0),
                    data.get('sandbox_access_token'),
                    data.get('live_access_token'),
                    data.get('webhook_secret'),
                    data.get('include_in_invoice_pdf', 1),
                    data.get('include_in_email', 1),
                    data.get('payment_description', 'Invoice Payment'),
                    data.get('days_until_collection', 5)
                ))
            
            conn.commit()
            self._settings = None  # Clear cache
            return True
    
    def is_configured(self) -> bool:
        """Check if GoCardless is properly configured."""
        settings = self.get_settings()
        if not settings.get('enabled'):
            return False
        
        if settings.get('live_mode'):
            return bool(settings.get('live_access_token'))
        else:
            return bool(settings.get('sandbox_access_token'))
    
    def get_access_token(self) -> Optional[str]:
        """Get the current API access token (sandbox or live based on mode)."""
        settings = self.get_settings()
        if settings.get('live_mode'):
            return settings.get('live_access_token')
        return settings.get('sandbox_access_token')
    
    def get_api_url(self) -> str:
        """Get the API URL based on mode."""
        settings = self.get_settings()
        if settings.get('live_mode'):
            return self.LIVE_API_URL
        return self.SANDBOX_API_URL
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Optional[Dict]:
        """Make an API request to GoCardless."""
        import requests
        
        access_token = self.get_access_token()
        if not access_token:
            return None
        
        url = f"{self.get_api_url()}{endpoint}"
        headers = {
            'Authorization': f'Bearer {access_token}',
            'GoCardless-Version': '2015-07-06',
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
                print(f"GoCardless API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"GoCardless request error: {e}")
            return None


# =============================================================================
# Customer Mandate Management
# =============================================================================

def get_customer_mandate(user_id: int, customer_id: int) -> Optional[Dict]:
    """Get the active mandate for a customer."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM gocardless_mandates 
            WHERE user_id = ? AND customer_id = ? AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
        ''', (user_id, customer_id))
        row = cursor.fetchone()
        return dict(row) if row else None


def save_customer_mandate(user_id: int, customer_id: int, mandate_data: Dict):
    """Save a customer mandate."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Check if exists
        cursor.execute('''
            SELECT id FROM gocardless_mandates 
            WHERE user_id = ? AND gc_mandate_id = ?
        ''', (user_id, mandate_data['id']))
        
        if cursor.fetchone():
            cursor.execute('''
                UPDATE gocardless_mandates 
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND gc_mandate_id = ?
            ''', (mandate_data.get('status', 'pending_submission'), user_id, mandate_data['id']))
        else:
            cursor.execute('''
                INSERT INTO gocardless_mandates 
                (user_id, customer_id, gc_mandate_id, gc_customer_id, status, scheme, reference)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                customer_id,
                mandate_data['id'],
                mandate_data.get('links', {}).get('customer'),
                mandate_data.get('status', 'pending_submission'),
                mandate_data.get('scheme', 'bacs'),
                mandate_data.get('reference')
            ))
        
        conn.commit()


def create_billing_request_flow(user_id: int, customer_id: int, base_url: str) -> Optional[Dict]:
    """
    Create a GoCardless Billing Request Flow for a customer to set up a mandate.
    Returns dict with authorisation_url for customer to complete setup.
    """
    gc_manager = GoCardlessManager(user_id)
    if not gc_manager.is_configured():
        return None
    
    # Get customer details
    customer_manager = CustomerManager(user_id)
    customer = customer_manager.get(customer_id)
    if not customer:
        return None
    
    settings = gc_manager.get_settings()
    
    # Create billing request
    billing_request_data = {
        "billing_requests": {
            "mandate_request": {
                "scheme": "bacs"  # UK Direct Debit
            }
        }
    }
    
    result = gc_manager._make_request('POST', '/billing_requests', billing_request_data)
    if not result:
        return None
    
    billing_request = result.get('billing_requests')
    if not billing_request:
        return None
    
    # Create billing request flow
    redirect_url = settings.get('success_redirect_url') or f"{base_url}/settings/integrations/gocardless/mandate-complete"
    
    flow_data = {
        "billing_request_flows": {
            "redirect_uri": redirect_url,
            "exit_uri": f"{base_url}/customers/{customer_id}",
            "links": {
                "billing_request": billing_request['id']
            },
            "prefilled_customer": {
                "email": customer.get('email'),
                "given_name": customer.get('name', '').split()[0] if customer.get('name') else None,
                "family_name": ' '.join(customer.get('name', '').split()[1:]) if customer.get('name') and len(customer.get('name', '').split()) > 1 else None,
                "address_line1": customer.get('address_line1'),
                "city": customer.get('city'),
                "postal_code": customer.get('postal_code'),
                "country_code": customer.get('country') or "GB"
            }
        }
    }
    
    # Remove None values from prefilled_customer
    flow_data['billing_request_flows']['prefilled_customer'] = {
        k: v for k, v in flow_data['billing_request_flows']['prefilled_customer'].items() if v
    }
    
    flow_result = gc_manager._make_request('POST', '/billing_request_flows', flow_data)
    if not flow_result:
        return None
    
    flow = flow_result.get('billing_request_flows')
    if not flow:
        return None
    
    # Save the billing request for tracking
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO gocardless_billing_requests 
            (user_id, customer_id, billing_request_id, flow_id, authorisation_url, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        ''', (user_id, customer_id, billing_request['id'], flow['id'], flow['authorisation_url']))
        conn.commit()
    
    return {
        'billing_request_id': billing_request['id'],
        'flow_id': flow['id'],
        'authorisation_url': flow['authorisation_url']
    }


# =============================================================================
# Payment Creation
# =============================================================================

def create_payment(user_id: int, invoice_id: int) -> Optional[Dict]:
    """
    Create a GoCardless payment for an invoice.
    Customer must have an active mandate.
    """
    import requests
    
    gc_manager = GoCardlessManager(user_id)
    if not gc_manager.is_configured():
        return None
    
    settings = gc_manager.get_settings()
    
    # Get invoice details
    invoice_manager = InvoiceManager(user_id)
    invoice = invoice_manager.get(invoice_id)
    if not invoice:
        return None
    
    # Calculate amount due
    amount_due = invoice.get('total', 0) - invoice.get('amount_paid', 0)
    if amount_due <= 0:
        return None
    
    # Get customer's mandate
    customer_id = invoice.get('customer_id')
    if not customer_id:
        return None
    
    mandate = get_customer_mandate(user_id, customer_id)
    if not mandate:
        return {'error': 'No active mandate for this customer. Please set up Direct Debit first.'}
    
    # Convert to pence (GoCardless uses smallest currency unit)
    amount_pence = int(amount_due * 100)
    
    # Calculate charge date (must be in the future)
    days_until = settings.get('days_until_collection', 5)
    charge_date = (datetime.now() + timedelta(days=days_until)).strftime('%Y-%m-%d')
    
    # Create payment
    payment_data = {
        "payments": {
            "amount": amount_pence,
            "currency": invoice.get('currency', 'GBP'),
            "charge_date": charge_date,
            "description": f"{settings.get('payment_description', 'Invoice Payment')} - {invoice['invoice_number']}",
            "metadata": {
                "invoice_id": str(invoice_id),
                "invoice_number": invoice['invoice_number'],
                "user_id": str(user_id)
            },
            "links": {
                "mandate": mandate['gc_mandate_id']
            }
        }
    }
    
    result = gc_manager._make_request('POST', '/payments', payment_data)
    if not result:
        return {'error': 'Failed to create payment with GoCardless'}
    
    payment = result.get('payments')
    if not payment:
        return {'error': 'Invalid response from GoCardless'}
    
    # Save payment record
    save_payment_record(user_id, invoice_id, payment)
    
    return {
        'payment_id': payment['id'],
        'amount': amount_due,
        'currency': invoice.get('currency', 'GBP'),
        'charge_date': payment.get('charge_date'),
        'status': payment.get('status')
    }


def save_payment_record(user_id: int, invoice_id: int, payment_data: Dict):
    """Save a GoCardless payment record."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO gocardless_payments 
            (user_id, invoice_id, gc_payment_id, amount, currency, charge_date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            invoice_id,
            payment_data['id'],
            payment_data.get('amount', 0) / 100,  # Convert from pence
            payment_data.get('currency', 'GBP'),
            payment_data.get('charge_date'),
            payment_data.get('status', 'pending_submission')
        ))
        conn.commit()


def get_payment_status(user_id: int, invoice_id: int) -> Optional[Dict]:
    """Get the latest GoCardless payment status for an invoice."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM gocardless_payments 
            WHERE user_id = ? AND invoice_id = ?
            ORDER BY created_at DESC LIMIT 1
        ''', (user_id, invoice_id))
        row = cursor.fetchone()
        return dict(row) if row else None


# =============================================================================
# Webhook Processing
# =============================================================================

def verify_gocardless_signature(payload: bytes, signature: str, webhook_secret: str) -> bool:
    """Verify GoCardless webhook signature."""
    try:
        expected = hmac.new(
            webhook_secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected)
    except Exception as e:
        print(f"GoCardless signature verification error: {e}")
        return False


def process_gocardless_webhook(payload: Dict, user_id: int) -> Tuple[bool, str, Optional[int]]:
    """
    Process a GoCardless webhook event.
    Returns (success, message, invoice_id)
    """
    events = payload.get('events', [])
    
    results = []
    for event in events:
        resource_type = event.get('resource_type')
        action = event.get('action')
        
        if resource_type == 'payments':
            result = handle_payment_event(event, user_id)
            results.append(result)
        elif resource_type == 'mandates':
            result = handle_mandate_event(event, user_id)
            results.append(result)
        else:
            results.append((True, f'Event {resource_type}.{action} acknowledged', None))
    
    # Return first error or last success
    for success, message, invoice_id in results:
        if not success:
            return success, message, invoice_id
    
    if results:
        return results[-1]
    return True, 'No events to process', None


def handle_payment_event(event: Dict, user_id: int) -> Tuple[bool, str, Optional[int]]:
    """Handle a payment-related webhook event."""
    action = event.get('action')
    links = event.get('links', {})
    payment_id = links.get('payment')
    
    if not payment_id:
        return True, 'No payment ID in event', None
    
    # Find the payment record
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM gocardless_payments WHERE gc_payment_id = ?
        ''', (payment_id,))
        payment_record = cursor.fetchone()
    
    if not payment_record:
        return True, f'Payment {payment_id} not found in our records', None
    
    payment_record = dict(payment_record)
    invoice_id = payment_record.get('invoice_id')
    record_user_id = payment_record.get('user_id')
    
    # Update payment status
    new_status = action
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE gocardless_payments 
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE gc_payment_id = ?
        ''', (new_status, payment_id))
        conn.commit()
    
    # Handle confirmed/paid payments
    if action in ['confirmed', 'paid_out']:
        # Record payment on invoice
        invoice_manager = InvoiceManager(record_user_id)
        invoice = invoice_manager.get(invoice_id)
        
        if not invoice:
            return False, 'Invoice not found', invoice_id
        
        if invoice['status'] == 'paid':
            return True, 'Invoice already paid', invoice_id
        
        try:
            amount = payment_record.get('amount', 0)
            invoice_manager.add_payment(
                invoice_id=invoice_id,
                amount=amount,
                payment_method='gocardless',
                reference=payment_id,
                notes=f"GoCardless Direct Debit - {action}"
            )
            
            updated_invoice = invoice_manager.get(invoice_id)
            status = 'fully paid' if updated_invoice['status'] == 'paid' else 'partially paid'
            
            return True, f'Payment {action}: {status}', invoice_id
            
        except Exception as e:
            return False, f'Error recording payment: {str(e)}', invoice_id
    
    elif action in ['failed', 'cancelled']:
        return True, f'Payment {action}', invoice_id
    
    return True, f'Payment event {action} noted', invoice_id


def handle_mandate_event(event: Dict, user_id: int) -> Tuple[bool, str, Optional[int]]:
    """Handle a mandate-related webhook event."""
    action = event.get('action')
    links = event.get('links', {})
    mandate_id = links.get('mandate')
    
    if not mandate_id:
        return True, 'No mandate ID in event', None
    
    # Update mandate status
    new_status = action
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE gocardless_mandates 
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE gc_mandate_id = ?
        ''', (new_status, mandate_id))
        conn.commit()
    
    return True, f'Mandate {action}', None


# =============================================================================
# Helper Functions
# =============================================================================

def get_gocardless_button_html(user_id: int, invoice_id: int, base_url: str) -> Optional[str]:
    """Generate HTML for a GoCardless setup/payment info."""
    gc_manager = GoCardlessManager(user_id)
    settings = gc_manager.get_settings()
    
    if not settings.get('enabled') or not gc_manager.is_configured():
        return None
    
    # Get invoice
    invoice_manager = InvoiceManager(user_id)
    invoice = invoice_manager.get(invoice_id)
    if not invoice or not invoice.get('customer_id'):
        return None
    
    # Check if customer has mandate
    mandate = get_customer_mandate(user_id, invoice['customer_id'])
    
    if mandate:
        # Customer has mandate - show payment status
        payment = get_payment_status(user_id, invoice_id)
        if payment:
            status_text = payment.get('status', 'unknown').replace('_', ' ').title()
            return f'''
            <div style="padding: 12px; background: #00b3a422; border-radius: 6px; border-left: 4px solid #00b3a4;">
                <strong style="color: #00b3a4;">🏦 Direct Debit</strong>
                <p style="margin: 0.5rem 0 0 0; font-size: 0.9rem;">
                    Status: <strong>{status_text}</strong>
                    {f" • Charge date: {payment.get('charge_date')}" if payment.get('charge_date') else ""}
                </p>
            </div>
            '''
        else:
            return f'''
            <form method="POST" action="{base_url}/invoices/{invoice_id}/gocardless-payment" style="display: inline;">
                <button type="submit" 
                        style="display: inline-block; background: #00b3a4; color: white; padding: 12px 24px; 
                               border: none; border-radius: 6px; font-weight: bold; font-size: 14px; cursor: pointer;">
                    🏦 Collect via Direct Debit
                </button>
            </form>
            '''
    else:
        # No mandate - show setup link
        return f'''
        <a href="{base_url}/customers/{invoice['customer_id']}/setup-direct-debit" 
           style="display: inline-block; background: #00b3a4; color: white; padding: 12px 24px; 
                  text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 14px;">
            🏦 Set Up Direct Debit
        </a>
        '''


# =============================================================================
# Database Initialization
# =============================================================================

def init_gocardless_tables():
    """Initialize GoCardless-related database tables."""
    from database import is_mysql, should_skip_table_creation
    
    # Skip if MySQL and tables exist
    if is_mysql() and should_skip_table_creation('gocardless_settings'):
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # GoCardless settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gocardless_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                enabled INTEGER DEFAULT 0,
                live_mode INTEGER DEFAULT 0,
                sandbox_access_token TEXT,
                live_access_token TEXT,
                webhook_secret TEXT,
                include_in_invoice_pdf INTEGER DEFAULT 1,
                include_in_email INTEGER DEFAULT 1,
                payment_description TEXT DEFAULT 'Invoice Payment',
                days_until_collection INTEGER DEFAULT 5,
                success_redirect_url TEXT,
                creditor_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Customer mandates table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gocardless_mandates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                gc_mandate_id TEXT NOT NULL,
                gc_customer_id TEXT,
                status TEXT DEFAULT 'pending_submission',
                scheme TEXT DEFAULT 'bacs',
                reference TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (customer_id) REFERENCES customers (id)
            )
        ''')
        
        # Billing requests table (for mandate setup flows)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gocardless_billing_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                billing_request_id TEXT NOT NULL,
                flow_id TEXT,
                authorisation_url TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (customer_id) REFERENCES customers (id)
            )
        ''')
        
        # Payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gocardless_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                invoice_id INTEGER NOT NULL,
                gc_payment_id TEXT NOT NULL,
                amount REAL,
                currency TEXT DEFAULT 'GBP',
                charge_date DATE,
                status TEXT DEFAULT 'pending_submission',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (invoice_id) REFERENCES invoices (id)
            )
        ''')
        
        # Webhook logs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gocardless_webhook_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event_type TEXT,
                event_id TEXT,
                resource_type TEXT,
                action TEXT,
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


def log_gocardless_webhook(user_id: int, event: Dict, status: str, message: str, 
                           invoice_id: int = None, payload: str = None):
    """Log a GoCardless webhook event."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO gocardless_webhook_logs 
            (user_id, event_type, event_id, resource_type, action, invoice_id, status, message, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            f"{event.get('resource_type')}.{event.get('action')}",
            event.get('id'),
            event.get('resource_type'),
            event.get('action'),
            invoice_id,
            status,
            message,
            payload
        ))
        conn.commit()
