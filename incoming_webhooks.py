"""
Invoice Manager - Incoming Webhooks Module
Handles incoming payment webhooks from external services.
Copyright (c) 2026 Sondela Consulting Ltd.
"""

import hashlib
import hmac
import json
import secrets
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from app_core import get_db, InvoiceManager


# =============================================================================
# Supported Providers
# =============================================================================

WEBHOOK_PROVIDERS = {
    'generic': {
        'name': 'Generic / Custom',
        'description': 'Custom integration - use your own payload format',
        'fields': {
            'invoice_id': 'Invoice ID field path',
            'invoice_number': 'Invoice number field path',
            'amount': 'Payment amount field path',
            'reference': 'Payment reference field path'
        }
    },
    'stripe': {
        'name': 'Stripe',
        'description': 'Stripe payment webhooks',
        'signature_header': 'Stripe-Signature',
        'events': ['payment_intent.succeeded', 'checkout.session.completed', 'invoice.paid']
    },
    'paypal': {
        'name': 'PayPal',
        'description': 'PayPal IPN and webhooks',
        'signature_header': 'PAYPAL-TRANSMISSION-SIG'
    },
    'gocardless': {
        'name': 'GoCardless',
        'description': 'GoCardless Direct Debit webhooks',
        'signature_header': 'Webhook-Signature'
    },
    'wise': {
        'name': 'Wise (TransferWise)',
        'description': 'Wise payment notifications',
        'signature_header': 'X-Signature-SHA256'
    },
    'mollie': {
        'name': 'Mollie',
        'description': 'Mollie payment webhooks'
    },
    'square': {
        'name': 'Square',
        'description': 'Square payment webhooks',
        'signature_header': 'X-Square-Signature'
    }
}


# =============================================================================
# Incoming Webhook Manager
# =============================================================================

class IncomingWebhookManager:
    """Manage incoming webhook endpoints."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def get_all(self, active_only: bool = False) -> List[Dict]:
        """Get all incoming webhooks for user."""
        with get_db() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM incoming_webhooks WHERE user_id = ?'
            if active_only:
                query += ' AND active = 1'
            query += ' ORDER BY created_at DESC'
            cursor.execute(query, (self.user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get(self, webhook_id: int) -> Optional[Dict]:
        """Get a specific webhook."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM incoming_webhooks WHERE id = ? AND user_id = ?',
                (webhook_id, self.user_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_by_endpoint_key(self, endpoint_key: str) -> Optional[Dict]:
        """Get webhook by endpoint key (for processing incoming requests)."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT iw.*, u.id as owner_user_id FROM incoming_webhooks iw '
                'JOIN users u ON iw.user_id = u.id '
                'WHERE iw.endpoint_key = ? AND iw.active = 1',
                (endpoint_key,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def create(self, name: str, provider: str = 'generic', description: str = None) -> Tuple[int, str, str]:
        """Create a new incoming webhook. Returns (id, endpoint_key, secret_key)."""
        endpoint_key = secrets.token_urlsafe(24)
        secret_key = secrets.token_urlsafe(32)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO incoming_webhooks (user_id, name, description, endpoint_key, secret_key, provider)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (self.user_id, name, description, endpoint_key, secret_key, provider))
            conn.commit()
            return cursor.lastrowid, endpoint_key, secret_key
    
    def update(self, webhook_id: int, data: Dict) -> bool:
        """Update a webhook."""
        allowed_fields = ['name', 'description', 'provider', 'active']
        updates = []
        values = []
        
        for field in allowed_fields:
            if field in data:
                updates.append(f'{field} = ?')
                values.append(data[field])
        
        if not updates:
            return False
        
        values.extend([webhook_id, self.user_id])
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                f'UPDATE incoming_webhooks SET {", ".join(updates)} WHERE id = ? AND user_id = ?',
                values
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def delete(self, webhook_id: int) -> bool:
        """Delete a webhook."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM incoming_webhooks WHERE id = ? AND user_id = ?',
                (webhook_id, self.user_id)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def regenerate_secret(self, webhook_id: int) -> Optional[str]:
        """Regenerate the secret key for a webhook."""
        new_secret = secrets.token_urlsafe(32)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE incoming_webhooks SET secret_key = ? WHERE id = ? AND user_id = ?',
                (new_secret, webhook_id, self.user_id)
            )
            conn.commit()
            if cursor.rowcount > 0:
                return new_secret
        return None
    
    def log_request(self, webhook_id: int, payload: str, headers: str, 
                    status: str = 'received', response: str = None, 
                    invoice_id: int = None) -> int:
        """Log an incoming webhook request."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO incoming_webhook_logs 
                (webhook_id, payload, headers, status, response, invoice_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (webhook_id, payload, headers, status, response, invoice_id))
            
            # Update webhook stats
            cursor.execute('''
                UPDATE incoming_webhooks 
                SET last_received_at = CURRENT_TIMESTAMP, receive_count = receive_count + 1
                WHERE id = ?
            ''', (webhook_id,))
            
            conn.commit()
            return cursor.lastrowid
    
    def get_logs(self, webhook_id: int, limit: int = 50) -> List[Dict]:
        """Get logs for a webhook."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT l.*, i.invoice_number 
                FROM incoming_webhook_logs l
                LEFT JOIN invoices i ON l.invoice_id = i.id
                WHERE l.webhook_id = ?
                ORDER BY l.received_at DESC
                LIMIT ?
            ''', (webhook_id, limit))
            return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# Webhook Processing
# =============================================================================

def verify_signature(payload: bytes, signature: str, secret: str, provider: str) -> bool:
    """Verify webhook signature based on provider."""
    if provider == 'stripe':
        # Stripe uses timestamp.signature format
        try:
            parts = dict(item.split('=') for item in signature.split(','))
            timestamp = parts.get('t', '')
            sig = parts.get('v1', '')
            
            signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
            expected = hmac.new(
                secret.encode('utf-8'),
                signed_payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(sig, expected)
        except:
            return False
    
    elif provider in ['wise', 'gocardless']:
        # SHA256 HMAC
        expected = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature.lower(), expected.lower())
    
    elif provider == 'generic':
        # For generic, check simple HMAC-SHA256
        if signature:
            expected = hmac.new(
                secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(signature.lower(), expected.lower())
        return True  # No signature required for generic
    
    return True  # Skip verification for unsupported providers


def extract_payment_data(payload: Dict, provider: str) -> Dict:
    """Extract payment data from webhook payload based on provider."""
    result = {
        'invoice_id': None,
        'invoice_number': None,
        'amount': None,
        'reference': None,
        'payment_method': provider,
        'metadata': {}
    }
    
    if provider == 'stripe':
        # Handle different Stripe event types
        event_type = payload.get('type', '')
        data = payload.get('data', {}).get('object', {})
        
        if event_type == 'payment_intent.succeeded':
            result['amount'] = data.get('amount_received', 0) / 100  # Stripe uses cents
            result['reference'] = data.get('id')
            metadata = data.get('metadata', {})
            result['invoice_id'] = metadata.get('invoice_id')
            result['invoice_number'] = metadata.get('invoice_number')
            
        elif event_type == 'checkout.session.completed':
            result['amount'] = data.get('amount_total', 0) / 100
            result['reference'] = data.get('payment_intent') or data.get('id')
            metadata = data.get('metadata', {})
            result['invoice_id'] = metadata.get('invoice_id')
            result['invoice_number'] = metadata.get('invoice_number')
            
        elif event_type == 'invoice.paid':
            result['amount'] = data.get('amount_paid', 0) / 100
            result['reference'] = data.get('payment_intent')
            # Check custom fields or metadata
            metadata = data.get('metadata', {})
            result['invoice_number'] = metadata.get('invoice_number') or data.get('number')
            
        result['metadata'] = {'stripe_event': event_type}
    
    elif provider == 'paypal':
        # PayPal IPN format
        result['amount'] = float(payload.get('mc_gross', 0) or payload.get('payment_gross', 0))
        result['reference'] = payload.get('txn_id')
        result['invoice_number'] = payload.get('invoice')
        result['metadata'] = {'paypal_status': payload.get('payment_status')}
    
    elif provider == 'gocardless':
        events = payload.get('events', [])
        for event in events:
            if event.get('action') == 'confirmed' and event.get('resource_type') == 'payments':
                links = event.get('links', {})
                result['reference'] = links.get('payment')
                # GoCardless uses metadata for invoice reference
                result['metadata'] = event
    
    elif provider == 'generic':
        # Generic format - look for common field names
        result['invoice_id'] = (
            payload.get('invoice_id') or 
            payload.get('invoiceId') or 
            payload.get('InvoiceId')
        )
        result['invoice_number'] = (
            payload.get('invoice_number') or 
            payload.get('invoiceNumber') or 
            payload.get('InvoiceNumber') or
            payload.get('invoice_ref') or
            payload.get('reference')
        )
        result['amount'] = (
            payload.get('amount') or 
            payload.get('payment_amount') or 
            payload.get('paymentAmount') or
            payload.get('total')
        )
        result['reference'] = (
            payload.get('transaction_id') or 
            payload.get('transactionId') or 
            payload.get('payment_reference') or
            payload.get('txn_id')
        )
        
        if result['amount']:
            try:
                result['amount'] = float(result['amount'])
            except:
                result['amount'] = None
    
    return result


def process_payment_webhook(webhook: Dict, payload: Dict, headers: Dict) -> Tuple[bool, str, Optional[int]]:
    """
    Process an incoming payment webhook.
    Returns (success, message, invoice_id)
    """
    provider = webhook.get('provider', 'generic')
    user_id = webhook.get('user_id')
    
    # Extract payment data
    payment_data = extract_payment_data(payload, provider)
    
    # Find the invoice
    invoice_manager = InvoiceManager(user_id)
    invoice = None
    
    if payment_data['invoice_id']:
        try:
            invoice = invoice_manager.get(int(payment_data['invoice_id']))
        except:
            pass
    
    if not invoice and payment_data['invoice_number']:
        # Search by invoice number
        all_invoices = invoice_manager.get_all()
        for inv in all_invoices:
            if inv['invoice_number'] == payment_data['invoice_number']:
                invoice = inv
                break
    
    if not invoice:
        return False, 'Invoice not found', None
    
    if not payment_data['amount'] or payment_data['amount'] <= 0:
        return False, 'Invalid payment amount', invoice['id']
    
    # Check if invoice is already paid
    if invoice['status'] == 'paid':
        return True, 'Invoice already marked as paid', invoice['id']
    
    # Record the payment
    try:
        payment_id = invoice_manager.add_payment(
            invoice_id=invoice['id'],
            amount=payment_data['amount'],
            payment_method=payment_data['payment_method'],
            reference=payment_data['reference'],
            notes=f"Payment received via {provider} webhook"
        )
        
        # Check if invoice is now fully paid
        updated_invoice = invoice_manager.get(invoice['id'])
        status = 'fully paid' if updated_invoice['status'] == 'paid' else 'partially paid'
        
        return True, f'Payment recorded: {status}', invoice['id']
        
    except Exception as e:
        return False, f'Error recording payment: {str(e)}', invoice['id']


# =============================================================================
# Database Initialization
# =============================================================================

def init_incoming_webhook_tables():
    """Initialize incoming webhook tables."""
    from database import is_mysql, should_skip_table_creation
    
    # Skip if MySQL and tables exist
    if is_mysql() and should_skip_table_creation('incoming_webhooks'):
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
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
        ''')
        
        cursor.execute('''
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
        ''')
        
        conn.commit()
