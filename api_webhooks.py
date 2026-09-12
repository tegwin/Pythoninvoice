"""
Invoice Manager - API & Webhooks Module
Provides RESTful API endpoints with API key authentication and webhook notifications.
"""

import os
import json
import hashlib
import secrets
import requests
from datetime import datetime, date
from decimal import Decimal
from functools import wraps
from flask import request, jsonify, g

from app_core import get_db


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles Decimal and datetime types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

# =============================================================================
# Webhook Event Types
# =============================================================================

WEBHOOK_EVENTS = [
    'invoice.created',
    'invoice.updated',
    'invoice.deleted',
    'invoice.sent',
    'invoice.paid',
    'invoice.partially_paid',
    'invoice.overdue',
    'customer.created',
    'customer.updated',
    'customer.deleted',
    'product.created',
    'product.updated',
    'product.deleted',
    'payment.received',
]


# =============================================================================
# API Key Management
# =============================================================================

def generate_api_key() -> str:
    """Generate a new API key."""
    return f"inv_{secrets.token_hex(32)}"


def hash_api_key(key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def create_api_key(user_id: int, name: str, permissions: list = None) -> str:
    """Create a new API key for a user."""
    if permissions is None:
        permissions = ['read', 'write']
    
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    # The full key is never stored, so keep the leading characters to let the
    # user tell their keys apart in the UI. key_prefix is NOT NULL.
    key_prefix = api_key[:12]

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO api_keys (user_id, key_hash, key_prefix, name, permissions)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, key_hash, key_prefix, name, json.dumps(permissions)))
        conn.commit()
    
    return api_key  # Return unhashed key (only time it's visible)


def validate_api_key(api_key: str) -> dict:
    """Validate an API key and return user info if valid."""
    if not api_key:
        return None
    
    key_hash = hash_api_key(api_key)
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM api_keys WHERE key_hash = ? AND active = 1
        ''', (key_hash,))
        row = cursor.fetchone()
        
        if row:
            # Update last used
            cursor.execute(
                'UPDATE api_keys SET last_used = ? WHERE id = ?',
                (datetime.now().isoformat(), row['id'])
            )
            conn.commit()
            
            result = dict(row)
            result['permissions'] = json.loads(result['permissions'])
            return result
    
    return None


def get_user_api_keys(user_id: int) -> list:
    """Get all API keys for a user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, permissions, active, created_at, last_used, key_hash
            FROM api_keys WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (user_id,))
        
        keys = []
        for row in cursor.fetchall():
            key_data = dict(row)
            key_data['permissions'] = json.loads(key_data['permissions'])
            key_data['key_hash'] = key_data['key_hash'][:16] + '...'  # Partial for identification
            keys.append(key_data)
        
        return keys


def revoke_api_key(user_id: int, key_id: int) -> bool:
    """Revoke an API key."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE api_keys SET active = 0 WHERE id = ? AND user_id = ?
        ''', (key_id, user_id))
        conn.commit()
        return cursor.rowcount > 0


def delete_api_key(user_id: int, key_id: int) -> bool:
    """Delete an API key."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM api_keys WHERE id = ? AND user_id = ?
        ''', (key_id, user_id))
        conn.commit()
        return cursor.rowcount > 0


# =============================================================================
# API Authentication Decorator
# =============================================================================

def api_key_required(permissions=None):
    """Decorator to require API key authentication."""
    if permissions is None:
        permissions = ['read']
    
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check for API key in header or query param
            api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
            
            if not api_key:
                return jsonify({
                    'success': False,
                    'error': 'API key required',
                    'message': 'Provide API key via X-API-Key header or api_key query parameter'
                }), 401
            
            key_data = validate_api_key(api_key)
            
            if not key_data:
                return jsonify({
                    'success': False,
                    'error': 'Invalid API key',
                    'message': 'The provided API key is invalid or has been revoked'
                }), 401
            
            # Check permissions
            for perm in permissions:
                if perm not in key_data['permissions']:
                    return jsonify({
                        'success': False,
                        'error': 'Insufficient permissions',
                        'message': f'This API key does not have "{perm}" permission'
                    }), 403
            
            # Store user info in g for use in the route
            g.api_user_id = key_data['user_id']
            g.api_permissions = key_data['permissions']
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# =============================================================================
# Webhook Management
# =============================================================================

def create_webhook(user_id: int, url: str, events: list, name: str = None,
                   headers: dict = None, auth_type: str = None, auth_value: str = None) -> dict:
    """Create a new webhook."""
    webhook_id = secrets.token_hex(8)
    secret = secrets.token_hex(32)
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO webhooks (user_id, webhook_id, name, url, events, secret,
                                 headers, auth_type, auth_value)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, webhook_id, name or f"Webhook {datetime.now().strftime('%Y-%m-%d')}",
            url, json.dumps(events), secret,
            json.dumps(headers or {}), auth_type, auth_value
        ))
        conn.commit()
    
    return {
        'id': webhook_id,
        'secret': secret,
        'name': name,
        'url': url,
        'events': events
    }


def get_user_webhooks(user_id: int) -> list:
    """Get all webhooks for a user."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM webhooks WHERE user_id = ? ORDER BY created_at DESC
        ''', (user_id,))
        
        webhooks = []
        for row in cursor.fetchall():
            webhook = dict(row)
            webhook['events'] = json.loads(webhook['events'])
            webhook['headers'] = json.loads(webhook['headers'])
            webhooks.append(webhook)
        
        return webhooks


def get_webhook(webhook_id: str, user_id: int) -> dict:
    """Get a specific webhook."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM webhooks WHERE webhook_id = ? AND user_id = ?
        ''', (webhook_id, user_id))
        
        row = cursor.fetchone()
        if row:
            webhook = dict(row)
            webhook['events'] = json.loads(webhook['events'])
            webhook['headers'] = json.loads(webhook['headers'])
            return webhook
    return None


def update_webhook(webhook_id: str, user_id: int, updates: dict) -> bool:
    """Update a webhook."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        fields = []
        values = []
        
        if 'name' in updates:
            fields.append('name = ?')
            values.append(updates['name'])
        if 'url' in updates:
            fields.append('url = ?')
            values.append(updates['url'])
        if 'events' in updates:
            fields.append('events = ?')
            values.append(json.dumps(updates['events']))
        if 'active' in updates:
            fields.append('active = ?')
            values.append(1 if updates['active'] else 0)
        if 'headers' in updates:
            fields.append('headers = ?')
            values.append(json.dumps(updates['headers']))
        if 'auth_type' in updates:
            fields.append('auth_type = ?')
            values.append(updates['auth_type'])
        if 'auth_value' in updates:
            fields.append('auth_value = ?')
            values.append(updates['auth_value'])
        
        if fields:
            values.extend([webhook_id, user_id])
            cursor.execute(
                f'UPDATE webhooks SET {", ".join(fields)} WHERE webhook_id = ? AND user_id = ?',
                values
            )
            conn.commit()
            return cursor.rowcount > 0
    return False


def delete_webhook(webhook_id: str, user_id: int) -> bool:
    """Delete a webhook."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM webhooks WHERE webhook_id = ? AND user_id = ?
        ''', (webhook_id, user_id))
        conn.commit()
        return cursor.rowcount > 0


def update_webhook(webhook_id: str, user_id: int, name: str = None, url: str = None, events: list = None) -> bool:
    """Update a webhook's properties."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Build update query dynamically
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if url is not None:
            updates.append("url = ?")
            params.append(url)
        if events is not None:
            updates.append("events = ?")
            params.append(json.dumps(events))
        
        if not updates:
            return False
        
        params.extend([webhook_id, user_id])
        
        cursor.execute(f'''
            UPDATE webhooks 
            SET {", ".join(updates)}
            WHERE webhook_id = ? AND user_id = ?
        ''', params)
        conn.commit()
        return cursor.rowcount > 0


def trigger_webhooks(event: str, user_id: int, payload: dict):
    """Trigger all webhooks for a specific event."""
    webhooks = get_user_webhooks(user_id)
    results = []
    
    for webhook in webhooks:
        if webhook['active'] and event in webhook['events']:
            result = send_webhook(webhook, event, payload)
            results.append(result)
    
    return results


def send_webhook(webhook: dict, event: str, payload: dict) -> dict:
    """Send a webhook notification."""
    import base64
    
    # Prepare the webhook payload
    data = {
        'event': event,
        'timestamp': datetime.now().isoformat(),
        'webhook_id': webhook['webhook_id'],
        'data': payload
    }
    
    # Create signature
    signature = hashlib.sha256(
        (webhook['secret'] + json.dumps(data, sort_keys=True, cls=DecimalEncoder)).encode()
    ).hexdigest()
    
    # Prepare headers
    headers = {
        'Content-Type': 'application/json',
        'X-Webhook-Event': event,
        'X-Webhook-Signature': signature,
        'User-Agent': 'InvoiceManager-Webhook/1.0'
    }
    
    # Add authentication
    auth_type = webhook.get('auth_type')
    auth_value = webhook.get('auth_value')
    
    if auth_type and auth_value:
        if auth_type == 'bearer':
            headers['Authorization'] = f'Bearer {auth_value}'
        elif auth_type == 'api_key':
            headers['X-API-Key'] = auth_value
        elif auth_type == 'basic':
            encoded = base64.b64encode(auth_value.encode()).decode()
            headers['Authorization'] = f'Basic {encoded}'
        elif auth_type == 'custom_header':
            if ':' in auth_value:
                header_name, header_val = auth_value.split(':', 1)
                headers[header_name.strip()] = header_val.strip()
    
    # Add custom headers
    headers.update(webhook.get('headers', {}))
    
    # Convert data to JSON-safe format (handle Decimals and datetimes)
    json_safe_data = json.loads(json.dumps(data, cls=DecimalEncoder))
    
    # Send the webhook
    try:
        response = requests.post(
            webhook['url'],
            json=json_safe_data,
            headers=headers,
            timeout=10
        )
        
        success = 200 <= response.status_code < 300
        
        # Update webhook stats
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE webhooks SET
                    last_triggered = ?,
                    trigger_count = trigger_count + 1,
                    last_status = ?,
                    last_error = ?
                WHERE webhook_id = ?
            ''', (
                datetime.now().isoformat(),
                response.status_code,
                None if success else response.text[:500],
                webhook['webhook_id']
            ))
            conn.commit()
        
        return {
            'webhook_id': webhook['webhook_id'],
            'success': success,
            'status_code': response.status_code,
            'response': response.text[:200] if not success else None
        }
        
    except requests.RequestException as e:
        # Update webhook with error
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE webhooks SET
                    last_triggered = ?,
                    trigger_count = trigger_count + 1,
                    last_status = 0,
                    last_error = ?
                WHERE webhook_id = ?
            ''', (
                datetime.now().isoformat(),
                str(e)[:500],
                webhook['webhook_id']
            ))
            conn.commit()
        
        return {
            'webhook_id': webhook['webhook_id'],
            'success': False,
            'error': str(e)
        }


def test_webhook(webhook_id: str, user_id: int) -> dict:
    """Send a test ping to a webhook."""
    webhook = get_webhook(webhook_id, user_id)
    if not webhook:
        return {'error': 'Webhook not found'}
    
    test_payload = {
        'test': True,
        'message': 'This is a test webhook from Invoice Manager',
        'timestamp': datetime.now().isoformat()
    }
    
    return send_webhook(webhook, 'test.ping', test_payload)


# =============================================================================
# API Response Helpers
# =============================================================================

def api_success(data=None, message=None, status=200):
    """Return a successful API response."""
    response = {'success': True}
    if data is not None:
        response['data'] = data
    if message:
        response['message'] = message
    return jsonify(response), status


def api_error(message, status=400, errors=None):
    """Return an error API response."""
    response = {
        'success': False,
        'error': message
    }
    if errors:
        response['errors'] = errors
    return jsonify(response), status


# =============================================================================
# Serialization Helpers
# =============================================================================

def serialize_customer(customer: dict) -> dict:
    """Serialize a customer for API response."""
    return {
        'id': customer.get('id'),
        'name': customer.get('name'),
        'email': customer.get('email'),
        'phone': customer.get('phone'),
        'address': {
            'line1': customer.get('address_line1'),
            'line2': customer.get('address_line2'),
            'city': customer.get('city'),
            'state': customer.get('state'),
            'postal_code': customer.get('postal_code'),
            'country': customer.get('country'),
        },
        'tax_number': customer.get('tax_number'),
        'custom_tax_rate': customer.get('custom_tax_rate'),
        'custom_currency': customer.get('custom_currency'),
        'notes': customer.get('notes'),
        'created_at': customer.get('created_at'),
        'updated_at': customer.get('updated_at'),
    }


def serialize_product(product: dict) -> dict:
    """Serialize a product for API response."""
    return {
        'id': product.get('id'),
        'name': product.get('name'),
        'description': product.get('description'),
        'unit_price': product.get('unit_price'),
        'unit': product.get('unit'),
        'sku': product.get('sku'),
        'is_service': bool(product.get('is_service')),
        'billing_term': product.get('billing_term'),
        'taxable': bool(product.get('taxable')),
        'coa_id': product.get('coa_id'),
        'active': bool(product.get('active')),
        'created_at': product.get('created_at'),
        'updated_at': product.get('updated_at'),
    }


def serialize_invoice(invoice: dict) -> dict:
    """Serialize an invoice for API response."""
    return {
        'id': invoice.get('id'),
        'invoice_number': invoice.get('invoice_number'),
        'customer_id': invoice.get('customer_id'),
        'customer_name': invoice.get('customer_name'),
        'status': invoice.get('status'),
        'issue_date': invoice.get('issue_date'),
        'due_date': invoice.get('due_date'),
        'currency': invoice.get('currency'),
        'tax_rate': invoice.get('tax_rate'),
        'subtotal': invoice.get('subtotal'),
        'tax_amount': invoice.get('tax_amount'),
        'total': invoice.get('total'),
        'amount_paid': invoice.get('amount_paid'),
        'amount_due': (invoice.get('total') or 0) - (invoice.get('amount_paid') or 0),
        'notes': invoice.get('notes'),
        'payment_terms': invoice.get('payment_terms'),
        'items': [serialize_invoice_item(item) for item in invoice.get('items', [])],
        'payments': [serialize_payment(pay) for pay in invoice.get('payments', [])],
        'created_at': invoice.get('created_at'),
        'updated_at': invoice.get('updated_at'),
        'paid_at': invoice.get('paid_at'),
    }


def serialize_invoice_item(item: dict) -> dict:
    """Serialize an invoice item for API response."""
    return {
        'id': item.get('id'),
        'product_id': item.get('product_id'),
        'description': item.get('description'),
        'quantity': item.get('quantity'),
        'unit_price': item.get('unit_price'),
        'tax_rate': item.get('tax_rate'),
        'line_total': item.get('line_total'),
    }


def serialize_payment(payment: dict) -> dict:
    """Serialize a payment for API response."""
    return {
        'id': payment.get('id'),
        'amount': payment.get('amount'),
        'payment_method': payment.get('payment_method'),
        'reference': payment.get('reference'),
        'notes': payment.get('notes'),
        'payment_date': payment.get('payment_date'),
        'created_via': payment.get('created_via'),
    }
