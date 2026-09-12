"""
Invoice Manager - Accounts Payable API
REST API endpoints for Bills and Expenses.
Enables external applications to manage accounts payable data.

Copyright (c) 2026 Sondela Consulting Ltd.
"""

import os
import base64
import secrets
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

from flask import request, jsonify

from app_core import get_db
from accounts_payable import (
    BillManager, ExpenseManager, SupplierManager,
    EXPENSE_CATEGORIES, PAYMENT_METHODS,
    allowed_receipt_file, allowed_bill_file,
    get_receipt_upload_path, get_bill_upload_path
)


# =============================================================================
# Serializers
# =============================================================================

def serialize_supplier(supplier: Dict) -> Dict:
    """Serialize supplier for API response."""
    return {
        'id': supplier.get('id'),
        'name': supplier.get('name'),
        'contact_name': supplier.get('contact_name'),
        'email': supplier.get('email'),
        'phone': supplier.get('phone'),
        'address': {
            'line1': supplier.get('address_line1'),
            'line2': supplier.get('address_line2'),
            'city': supplier.get('city'),
            'state': supplier.get('state'),
            'postal_code': supplier.get('postal_code'),
            'country': supplier.get('country')
        },
        'tax_id': supplier.get('tax_id'),
        'payment_terms': supplier.get('payment_terms'),
        'default_coa_id': supplier.get('default_coa_id'),
        'notes': supplier.get('notes'),
        'is_active': bool(supplier.get('is_active')),
        'bill_count': supplier.get('bill_count', 0),
        'outstanding': supplier.get('outstanding', 0),
        'created_at': supplier.get('created_at'),
        'updated_at': supplier.get('updated_at')
    }


def serialize_bill(bill: Dict) -> Dict:
    """Serialize bill for API response."""
    return {
        'id': bill.get('id'),
        'bill_number': bill.get('bill_number'),
        'reference': bill.get('reference'),
        'supplier_id': bill.get('supplier_id'),
        'supplier_name': bill.get('supplier_name'),
        'bill_date': bill.get('bill_date'),
        'due_date': bill.get('due_date'),
        'currency': bill.get('currency'),
        'tax_rate': bill.get('tax_rate'),
        'subtotal': bill.get('subtotal'),
        'tax_amount': bill.get('tax_amount'),
        'total': bill.get('total'),
        'amount_paid': bill.get('amount_paid'),
        'balance_due': (bill.get('total') or 0) - (bill.get('amount_paid') or 0),
        'status': bill.get('status'),
        'notes': bill.get('notes'),
        'has_attachment': bool(bill.get('attachment_path')),
        'items': [serialize_bill_item(item) for item in bill.get('items', [])],
        'payments': [serialize_bill_payment(p) for p in bill.get('payments', [])],
        'created_at': bill.get('created_at'),
        'updated_at': bill.get('updated_at')
    }


def serialize_bill_item(item: Dict) -> Dict:
    """Serialize bill item for API response."""
    return {
        'id': item.get('id'),
        'description': item.get('description'),
        'quantity': item.get('quantity'),
        'unit_price': item.get('unit_price'),
        'total': item.get('total'),
        'coa_id': item.get('coa_id'),
        'coa_name': item.get('coa_name'),
        'coa_code': item.get('coa_code')
    }


def serialize_bill_payment(payment: Dict) -> Dict:
    """Serialize bill payment for API response."""
    return {
        'id': payment.get('id'),
        'amount': payment.get('amount'),
        'payment_date': payment.get('payment_date'),
        'payment_method': payment.get('payment_method'),
        'reference': payment.get('reference'),
        'notes': payment.get('notes'),
        'created_at': payment.get('created_at')
    }


def serialize_expense(expense: Dict) -> Dict:
    """Serialize expense for API response."""
    return {
        'id': expense.get('id'),
        'description': expense.get('description'),
        'expense_date': expense.get('expense_date'),
        'category': expense.get('category'),
        'amount': expense.get('amount'),
        'currency': expense.get('currency'),
        'tax_rate': expense.get('tax_rate'),
        'tax_amount': expense.get('tax_amount'),
        'net_amount': expense.get('net_amount'),
        'payment_method': expense.get('payment_method'),
        'reference': expense.get('reference'),
        'supplier_id': expense.get('supplier_id'),
        'supplier_name': expense.get('supplier_name'),
        'coa_id': expense.get('coa_id'),
        'coa_name': expense.get('coa_name'),
        'coa_code': expense.get('coa_code'),
        'is_billable': bool(expense.get('is_billable')),
        'is_reimbursable': bool(expense.get('is_reimbursable')),
        'status': expense.get('status'),
        'notes': expense.get('notes'),
        'has_receipt': bool(expense.get('receipt_path')),
        'created_at': expense.get('created_at'),
        'updated_at': expense.get('updated_at')
    }


# =============================================================================
# Helper Functions
# =============================================================================

def api_success(data=None, message=None, status_code=200):
    """Return a success API response."""
    response = {'success': True}
    if message:
        response['message'] = message
    if data is not None:
        response['data'] = data
    return jsonify(response), status_code


def api_error(message, status_code=400, errors=None):
    """Return an error API response."""
    response = {'success': False, 'error': message}
    if errors:
        response['errors'] = errors
    return jsonify(response), status_code


def save_base64_file(base64_data: str, user_id: int, file_type: str = 'receipt') -> str:
    """
    Save a base64-encoded file and return the path.
    file_type: 'receipt' or 'bill'
    """
    # Parse base64 data (may include data URI prefix)
    if ',' in base64_data:
        header, base64_data = base64_data.split(',', 1)
        # Extract extension from header if possible
        if 'pdf' in header.lower():
            ext = 'pdf'
        elif 'png' in header.lower():
            ext = 'png'
        elif 'jpeg' in header.lower() or 'jpg' in header.lower():
            ext = 'jpg'
        elif 'gif' in header.lower():
            ext = 'gif'
        elif 'webp' in header.lower():
            ext = 'webp'
        else:
            ext = 'jpg'  # Default
    else:
        ext = 'jpg'  # Default if no header
    
    try:
        file_data = base64.b64decode(base64_data)
    except Exception as e:
        raise ValueError(f"Invalid base64 data: {e}")
    
    # Determine upload path
    if file_type == 'bill':
        upload_path = get_bill_upload_path(user_id)
    else:
        upload_path = get_receipt_upload_path(user_id)
    
    # Generate unique filename
    filename = f"{secrets.token_hex(12)}.{ext}"
    file_path = os.path.join(upload_path, filename)
    
    # Save file
    with open(file_path, 'wb') as f:
        f.write(file_data)
    
    return file_path


# =============================================================================
# Supplier API Endpoints
# =============================================================================

def api_list_suppliers(user_id: int):
    """GET /api/v1/suppliers - List all suppliers."""
    include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
    
    manager = SupplierManager(user_id)
    suppliers = manager.get_all(include_inactive=include_inactive)
    
    return api_success([serialize_supplier(s) for s in suppliers])


def api_get_supplier(user_id: int, supplier_id: int):
    """GET /api/v1/suppliers/<id> - Get a supplier."""
    manager = SupplierManager(user_id)
    supplier = manager.get(supplier_id)
    
    if not supplier:
        return api_error('Supplier not found', 404)
    
    return api_success(serialize_supplier(supplier))


def api_create_supplier(user_id: int):
    """POST /api/v1/suppliers - Create a supplier."""
    data = request.get_json()
    if not data:
        return api_error('No data provided')
    
    if not data.get('name'):
        return api_error('Supplier name is required')
    
    manager = SupplierManager(user_id)
    
    supplier_data = {
        'name': data.get('name'),
        'contact_name': data.get('contact_name'),
        'email': data.get('email'),
        'phone': data.get('phone'),
        'address_line1': data.get('address', {}).get('line1') or data.get('address_line1'),
        'address_line2': data.get('address', {}).get('line2') or data.get('address_line2'),
        'city': data.get('address', {}).get('city') or data.get('city'),
        'state': data.get('address', {}).get('state') or data.get('state'),
        'postal_code': data.get('address', {}).get('postal_code') or data.get('postal_code'),
        'country': data.get('address', {}).get('country') or data.get('country', 'United Kingdom'),
        'tax_id': data.get('tax_id'),
        'payment_terms': data.get('payment_terms', 30),
        'default_coa_id': data.get('default_coa_id'),
        'notes': data.get('notes')
    }
    
    supplier_id = manager.create(supplier_data)
    supplier = manager.get(supplier_id)
    
    return api_success(serialize_supplier(supplier), 'Supplier created', 201)


def api_update_supplier(user_id: int, supplier_id: int):
    """PUT /api/v1/suppliers/<id> - Update a supplier."""
    data = request.get_json()
    if not data:
        return api_error('No data provided')
    
    manager = SupplierManager(user_id)
    supplier = manager.get(supplier_id)
    
    if not supplier:
        return api_error('Supplier not found', 404)
    
    # Merge with existing data
    supplier_data = {
        'name': data.get('name', supplier['name']),
        'contact_name': data.get('contact_name', supplier['contact_name']),
        'email': data.get('email', supplier['email']),
        'phone': data.get('phone', supplier['phone']),
        'address_line1': data.get('address', {}).get('line1') or data.get('address_line1', supplier['address_line1']),
        'address_line2': data.get('address', {}).get('line2') or data.get('address_line2', supplier['address_line2']),
        'city': data.get('address', {}).get('city') or data.get('city', supplier['city']),
        'state': data.get('address', {}).get('state') or data.get('state', supplier['state']),
        'postal_code': data.get('address', {}).get('postal_code') or data.get('postal_code', supplier['postal_code']),
        'country': data.get('address', {}).get('country') or data.get('country', supplier['country']),
        'tax_id': data.get('tax_id', supplier['tax_id']),
        'payment_terms': data.get('payment_terms', supplier['payment_terms']),
        'default_coa_id': data.get('default_coa_id', supplier['default_coa_id']),
        'notes': data.get('notes', supplier['notes']),
        'is_active': data.get('is_active', supplier['is_active'])
    }
    
    manager.update(supplier_id, supplier_data)
    supplier = manager.get(supplier_id)
    
    return api_success(serialize_supplier(supplier), 'Supplier updated')


def api_delete_supplier(user_id: int, supplier_id: int):
    """DELETE /api/v1/suppliers/<id> - Delete (deactivate) a supplier."""
    manager = SupplierManager(user_id)
    
    if not manager.get(supplier_id):
        return api_error('Supplier not found', 404)
    
    manager.delete(supplier_id)
    return api_success(message='Supplier deactivated')


def api_import_suppliers(user_id: int):
    """POST /api/v1/suppliers/import - Bulk import suppliers."""
    data = request.get_json()
    if not data:
        return api_error('No data provided')
    
    suppliers_data = data.get('suppliers', [])
    if not suppliers_data:
        return api_error('No suppliers data provided')
    
    update_existing = data.get('update_existing', False)
    
    manager = SupplierManager(user_id)
    imported = 0
    updated = 0
    errors = []
    
    for idx, supplier_data in enumerate(suppliers_data):
        try:
            if not supplier_data.get('name'):
                errors.append({'index': idx, 'error': 'Name is required'})
                continue
            
            # Check if exists
            existing = None
            if supplier_data.get('email'):
                existing = manager.get_by_email(supplier_data['email'])
            if not existing:
                existing = manager.get_by_name(supplier_data['name'])
            
            supplier_record = {
                'name': supplier_data.get('name'),
                'contact_name': supplier_data.get('contact_name'),
                'email': supplier_data.get('email'),
                'phone': supplier_data.get('phone'),
                'address_line1': supplier_data.get('address', {}).get('line1') or supplier_data.get('address_line1'),
                'address_line2': supplier_data.get('address', {}).get('line2') or supplier_data.get('address_line2'),
                'city': supplier_data.get('address', {}).get('city') or supplier_data.get('city'),
                'state': supplier_data.get('address', {}).get('state') or supplier_data.get('state'),
                'postal_code': supplier_data.get('address', {}).get('postal_code') or supplier_data.get('postal_code'),
                'country': supplier_data.get('address', {}).get('country') or supplier_data.get('country', 'United Kingdom'),
                'tax_id': supplier_data.get('tax_id'),
                'payment_terms': supplier_data.get('payment_terms', 30),
                'notes': supplier_data.get('notes'),
            }
            
            if existing and update_existing:
                manager.update(existing['id'], supplier_record)
                updated += 1
            elif not existing:
                manager.create(supplier_record)
                imported += 1
            else:
                errors.append({'index': idx, 'error': f"Supplier '{supplier_data['name']}' already exists"})
        
        except Exception as e:
            errors.append({'index': idx, 'error': str(e)})
    
    return api_success({
        'imported': imported,
        'updated': updated,
        'errors': errors if errors else None
    }, f'Import complete: {imported} created, {updated} updated')


# =============================================================================
# Bill API Endpoints
# =============================================================================

def api_list_bills(user_id: int):
    """GET /api/v1/bills - List all bills."""
    status = request.args.get('status')
    supplier_id = request.args.get('supplier_id', type=int)
    
    manager = BillManager(user_id)
    bills = manager.get_all(status=status, supplier_id=supplier_id)
    
    # Get full details for each bill
    detailed_bills = []
    for bill in bills:
        full_bill = manager.get(bill['id'])
        if full_bill:
            detailed_bills.append(serialize_bill(full_bill))
    
    return api_success(detailed_bills)


def api_get_bill(user_id: int, bill_id: int):
    """GET /api/v1/bills/<id> - Get a bill."""
    manager = BillManager(user_id)
    bill = manager.get(bill_id)
    
    if not bill:
        return api_error('Bill not found', 404)
    
    return api_success(serialize_bill(bill))


def api_create_bill(user_id: int):
    """POST /api/v1/bills - Create a bill."""
    data = request.get_json()
    if not data:
        return api_error('No data provided')
    
    items = data.get('items', [])
    if not items:
        return api_error('At least one item is required')
    
    manager = BillManager(user_id)
    
    bill_data = {
        'supplier_id': data.get('supplier_id'),
        'bill_number': data.get('bill_number'),
        'reference': data.get('reference'),
        'bill_date': data.get('bill_date', date.today().isoformat()),
        'due_date': data.get('due_date'),
        'currency': data.get('currency', 'GBP'),
        'tax_rate': data.get('tax_rate', 0),
        'notes': data.get('notes')
    }
    
    bill_items = []
    for item in items:
        bill_items.append({
            'description': item.get('description'),
            'quantity': item.get('quantity', 1),
            'unit_price': item.get('unit_price', 0),
            'coa_id': item.get('coa_id')
        })
    
    bill_id = manager.create(bill_data, bill_items)
    
    # Handle attachment if provided as base64
    if data.get('attachment_base64'):
        try:
            attachment_path = save_base64_file(data['attachment_base64'], user_id, 'bill')
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE bills SET attachment_path = ? WHERE id = ?',
                              (attachment_path, bill_id))
                conn.commit()
        except Exception as e:
            pass  # Attachment failed but bill created
    
    bill = manager.get(bill_id)
    return api_success(serialize_bill(bill), 'Bill created', 201)


def api_update_bill(user_id: int, bill_id: int):
    """PUT /api/v1/bills/<id> - Update a bill."""
    data = request.get_json()
    if not data:
        return api_error('No data provided')
    
    manager = BillManager(user_id)
    bill = manager.get(bill_id)
    
    if not bill:
        return api_error('Bill not found', 404)
    
    # Get items - use existing if not provided
    items = data.get('items')
    if items is None:
        items = bill.get('items', [])
    
    bill_data = {
        'supplier_id': data.get('supplier_id', bill['supplier_id']),
        'reference': data.get('reference', bill['reference']),
        'bill_date': data.get('bill_date', bill['bill_date']),
        'due_date': data.get('due_date', bill['due_date']),
        'currency': data.get('currency', bill['currency']),
        'tax_rate': data.get('tax_rate', bill['tax_rate']),
        'notes': data.get('notes', bill['notes'])
    }
    
    bill_items = []
    for item in items:
        bill_items.append({
            'description': item.get('description'),
            'quantity': item.get('quantity', 1),
            'unit_price': item.get('unit_price', 0),
            'coa_id': item.get('coa_id')
        })
    
    manager.update(bill_id, bill_data, bill_items)
    
    # Handle attachment if provided
    if data.get('attachment_base64'):
        try:
            # Remove old attachment
            if bill.get('attachment_path') and os.path.exists(bill['attachment_path']):
                os.remove(bill['attachment_path'])
            
            attachment_path = save_base64_file(data['attachment_base64'], user_id, 'bill')
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE bills SET attachment_path = ? WHERE id = ?',
                              (attachment_path, bill_id))
                conn.commit()
        except Exception as e:
            pass
    elif data.get('remove_attachment'):
        manager.remove_attachment(bill_id)
    
    bill = manager.get(bill_id)
    return api_success(serialize_bill(bill), 'Bill updated')


def api_delete_bill(user_id: int, bill_id: int):
    """DELETE /api/v1/bills/<id> - Delete a bill."""
    manager = BillManager(user_id)
    
    if not manager.get(bill_id):
        return api_error('Bill not found', 404)
    
    if manager.delete(bill_id):
        return api_success(message='Bill deleted')
    else:
        return api_error('Cannot delete bill. Only draft bills can be deleted.', 400)


def api_bill_add_payment(user_id: int, bill_id: int):
    """POST /api/v1/bills/<id>/payments - Add payment to a bill."""
    data = request.get_json()
    if not data:
        return api_error('No data provided')
    
    amount = data.get('amount')
    if not amount or amount <= 0:
        return api_error('Valid amount is required')
    
    manager = BillManager(user_id)
    bill = manager.get(bill_id)
    
    if not bill:
        return api_error('Bill not found', 404)
    
    try:
        payment_id = manager.add_payment(
            bill_id=bill_id,
            amount=float(amount),
            payment_date=data.get('payment_date', date.today().isoformat()),
            payment_method=data.get('payment_method'),
            reference=data.get('reference'),
            notes=data.get('notes')
        )
        
        bill = manager.get(bill_id)
        return api_success(serialize_bill(bill), 'Payment recorded')
        
    except ValueError as e:
        return api_error(str(e), 400)


def api_bill_update_status(user_id: int, bill_id: int):
    """PATCH /api/v1/bills/<id>/status - Update bill status."""
    data = request.get_json()
    if not data:
        return api_error('No data provided')
    
    status = data.get('status')
    if status not in ['draft', 'approved', 'paid', 'cancelled']:
        return api_error('Invalid status. Must be: draft, approved, paid, cancelled')
    
    manager = BillManager(user_id)
    
    if not manager.get(bill_id):
        return api_error('Bill not found', 404)
    
    manager.update_status(bill_id, status)
    bill = manager.get(bill_id)
    
    return api_success(serialize_bill(bill), f'Status updated to {status}')


# =============================================================================
# Expense API Endpoints
# =============================================================================

def api_list_expenses(user_id: int):
    """GET /api/v1/expenses - List all expenses."""
    category = request.args.get('category')
    status = request.args.get('status')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    manager = ExpenseManager(user_id)
    expenses = manager.get_all(
        category=category,
        status=status,
        date_from=date_from,
        date_to=date_to
    )
    
    return api_success([serialize_expense(e) for e in expenses])


def api_get_expense(user_id: int, expense_id: int):
    """GET /api/v1/expenses/<id> - Get an expense."""
    manager = ExpenseManager(user_id)
    expense = manager.get(expense_id)
    
    if not expense:
        return api_error('Expense not found', 404)
    
    return api_success(serialize_expense(expense))


def api_create_expense(user_id: int):
    """POST /api/v1/expenses - Create an expense."""
    data = request.get_json()
    if not data:
        return api_error('No data provided')
    
    if not data.get('amount'):
        return api_error('Amount is required')
    
    manager = ExpenseManager(user_id)
    
    expense_data = {
        'description': data.get('description'),
        'expense_date': data.get('expense_date', date.today().isoformat()),
        'amount': float(data.get('amount', 0)),
        'currency': data.get('currency', 'GBP'),
        'tax_rate': float(data.get('tax_rate', 0)),
        'amount_includes_tax': data.get('amount_includes_tax', True),
        'category': data.get('category'),
        'supplier_id': data.get('supplier_id'),
        'coa_id': data.get('coa_id'),
        'payment_method': data.get('payment_method'),
        'reference': data.get('reference'),
        'is_billable': data.get('is_billable', False),
        'is_reimbursable': data.get('is_reimbursable', False),
        'notes': data.get('notes'),
        'status': data.get('status', 'pending')
    }
    
    # Handle receipt if provided as base64
    receipt_path = None
    if data.get('receipt_base64'):
        try:
            receipt_path = save_base64_file(data['receipt_base64'], user_id, 'receipt')
        except Exception as e:
            return api_error(f'Invalid receipt data: {e}', 400)
    
    # Create expense
    expense_id = manager.create(expense_data, receipt_file=None)
    
    # Update receipt path if we saved one
    if receipt_path:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE expenses SET receipt_path = ? WHERE id = ?',
                          (receipt_path, expense_id))
            conn.commit()
    
    expense = manager.get(expense_id)
    return api_success(serialize_expense(expense), 'Expense created', 201)


def api_update_expense(user_id: int, expense_id: int):
    """PUT /api/v1/expenses/<id> - Update an expense."""
    data = request.get_json()
    if not data:
        return api_error('No data provided')
    
    manager = ExpenseManager(user_id)
    expense = manager.get(expense_id)
    
    if not expense:
        return api_error('Expense not found', 404)
    
    expense_data = {
        'description': data.get('description', expense['description']),
        'expense_date': data.get('expense_date', expense['expense_date']),
        'amount': float(data.get('amount', expense['amount'])),
        'currency': data.get('currency', expense['currency']),
        'tax_rate': float(data.get('tax_rate', expense['tax_rate'])),
        'amount_includes_tax': data.get('amount_includes_tax', True),
        'category': data.get('category', expense['category']),
        'supplier_id': data.get('supplier_id', expense['supplier_id']),
        'coa_id': data.get('coa_id', expense['coa_id']),
        'payment_method': data.get('payment_method', expense['payment_method']),
        'reference': data.get('reference', expense['reference']),
        'is_billable': data.get('is_billable', expense['is_billable']),
        'is_reimbursable': data.get('is_reimbursable', expense['is_reimbursable']),
        'notes': data.get('notes', expense['notes']),
        'status': data.get('status', expense['status']),
        'remove_receipt': data.get('remove_receipt', False)
    }
    
    # Handle receipt if provided
    if data.get('receipt_base64'):
        try:
            # Remove old receipt
            if expense.get('receipt_path') and os.path.exists(expense['receipt_path']):
                os.remove(expense['receipt_path'])
            
            receipt_path = save_base64_file(data['receipt_base64'], user_id, 'receipt')
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE expenses SET receipt_path = ? WHERE id = ?',
                              (receipt_path, expense_id))
                conn.commit()
        except Exception as e:
            pass  # Receipt update failed but continue
    
    manager.update(expense_id, expense_data, receipt_file=None)
    
    expense = manager.get(expense_id)
    return api_success(serialize_expense(expense), 'Expense updated')


def api_delete_expense(user_id: int, expense_id: int):
    """DELETE /api/v1/expenses/<id> - Delete an expense."""
    manager = ExpenseManager(user_id)
    
    if not manager.get(expense_id):
        return api_error('Expense not found', 404)
    
    if manager.delete(expense_id):
        return api_success(message='Expense deleted')
    else:
        return api_error('Failed to delete expense', 400)


def api_expense_approve(user_id: int, expense_id: int):
    """POST /api/v1/expenses/<id>/approve - Approve an expense."""
    manager = ExpenseManager(user_id)
    
    if not manager.get(expense_id):
        return api_error('Expense not found', 404)
    
    if manager.approve(expense_id):
        expense = manager.get(expense_id)
        return api_success(serialize_expense(expense), 'Expense approved')
    else:
        return api_error('Cannot approve expense', 400)


def api_expense_reject(user_id: int, expense_id: int):
    """POST /api/v1/expenses/<id>/reject - Reject an expense."""
    data = request.get_json() or {}
    reason = data.get('reason')
    
    manager = ExpenseManager(user_id)
    
    if not manager.get(expense_id):
        return api_error('Expense not found', 404)
    
    if manager.reject(expense_id, reason):
        expense = manager.get(expense_id)
        return api_success(serialize_expense(expense), 'Expense rejected')
    else:
        return api_error('Cannot reject expense', 400)


# =============================================================================
# Metadata Endpoints
# =============================================================================

def api_get_expense_categories():
    """GET /api/v1/expenses/categories - Get list of expense categories."""
    return api_success({
        'categories': EXPENSE_CATEGORIES,
        'payment_methods': PAYMENT_METHODS
    })


def api_get_accounts_payable_summary(user_id: int):
    """GET /api/v1/accounts-payable/summary - Get AP summary."""
    bill_manager = BillManager(user_id)
    expense_manager = ExpenseManager(user_id)
    
    bill_summary = bill_manager.get_summary()
    expense_summary = expense_manager.get_summary()
    
    return api_success({
        'bills': bill_summary,
        'expenses': expense_summary
    })
