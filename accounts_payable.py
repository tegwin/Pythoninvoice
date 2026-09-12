"""
Invoice Manager - Accounts Payable Module
Handles Suppliers, Bills (invoices you receive), and Expenses with receipt uploads.
Copyright (c) 2026 Sondela Consulting Ltd.
"""

import os
import secrets
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
from werkzeug.utils import secure_filename

from app_core import get_db


# =============================================================================
# Configuration
# =============================================================================

ALLOWED_RECEIPT_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'webp'}
ALLOWED_BILL_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'webp', 'doc', 'docx'}
MAX_RECEIPT_SIZE = 10 * 1024 * 1024  # 10MB
MAX_BILL_ATTACHMENT_SIZE = 20 * 1024 * 1024  # 20MB


def allowed_receipt_file(filename: str) -> bool:
    """Check if file extension is allowed for receipts."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_RECEIPT_EXTENSIONS


def allowed_bill_file(filename: str) -> bool:
    """Check if file extension is allowed for bill attachments."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_BILL_EXTENSIONS


def get_receipt_upload_path(user_id: int) -> str:
    """Get the path for storing receipts."""
    path = os.path.join('static', 'uploads', 'receipts', str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def get_bill_upload_path(user_id: int) -> str:
    """Get the path for storing bill attachments."""
    path = os.path.join('static', 'uploads', 'bills', str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


# =============================================================================
# Supplier Manager
# =============================================================================

class SupplierManager:
    """Manage suppliers/vendors."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def get_all(self, include_inactive: bool = False) -> List[Dict]:
        """Get all suppliers."""
        with get_db() as conn:
            cursor = conn.cursor()
            if include_inactive:
                cursor.execute('''
                    SELECT s.*, 
                           COUNT(DISTINCT b.id) as bill_count,
                           SUM(CASE WHEN b.status != 'paid' THEN b.total ELSE 0 END) as outstanding
                    FROM suppliers s
                    LEFT JOIN bills b ON s.id = b.supplier_id
                    WHERE s.user_id = ?
                    GROUP BY s.id
                    ORDER BY s.name
                ''', (self.user_id,))
            else:
                cursor.execute('''
                    SELECT s.*, 
                           COUNT(DISTINCT b.id) as bill_count,
                           SUM(CASE WHEN b.status != 'paid' THEN b.total ELSE 0 END) as outstanding
                    FROM suppliers s
                    LEFT JOIN bills b ON s.id = b.supplier_id
                    WHERE s.user_id = ? AND s.is_active = 1
                    GROUP BY s.id
                    ORDER BY s.name
                ''', (self.user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get(self, supplier_id: int) -> Optional[Dict]:
        """Get a single supplier."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM suppliers WHERE id = ? AND user_id = ?
            ''', (supplier_id, self.user_id))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_by_email(self, email: str) -> Optional[Dict]:
        """Get a supplier by email."""
        if not email:
            return None
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM suppliers WHERE email = ? AND user_id = ?
            ''', (email, self.user_id))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_by_name(self, name: str) -> Optional[Dict]:
        """Get a supplier by name."""
        if not name:
            return None
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM suppliers WHERE LOWER(name) = LOWER(?) AND user_id = ?
            ''', (name, self.user_id))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def create(self, data: Dict) -> int:
        """Create a new supplier."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO suppliers (
                    user_id, name, contact_name, email, phone,
                    address_line1, address_line2, city, state, postal_code, country,
                    tax_id, payment_terms, default_coa_id, notes, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (
                self.user_id,
                data.get('name'),
                data.get('contact_name'),
                data.get('email'),
                data.get('phone'),
                data.get('address_line1'),
                data.get('address_line2'),
                data.get('city'),
                data.get('state'),
                data.get('postal_code'),
                data.get('country'),
                data.get('tax_id'),
                data.get('payment_terms', 30),
                data.get('default_coa_id'),
                data.get('notes')
            ))
            conn.commit()
            return cursor.lastrowid
    
    def update(self, supplier_id: int, data: Dict) -> bool:
        """Update a supplier."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE suppliers SET
                    name = ?, contact_name = ?, email = ?, phone = ?,
                    address_line1 = ?, address_line2 = ?, city = ?, state = ?,
                    postal_code = ?, country = ?, tax_id = ?, payment_terms = ?,
                    default_coa_id = ?, notes = ?, is_active = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
            ''', (
                data.get('name'),
                data.get('contact_name'),
                data.get('email'),
                data.get('phone'),
                data.get('address_line1'),
                data.get('address_line2'),
                data.get('city'),
                data.get('state'),
                data.get('postal_code'),
                data.get('country'),
                data.get('tax_id'),
                data.get('payment_terms', 30),
                data.get('default_coa_id'),
                data.get('notes'),
                1 if data.get('is_active', True) else 0,
                supplier_id,
                self.user_id
            ))
            conn.commit()
            return cursor.rowcount > 0
    
    def delete(self, supplier_id: int) -> bool:
        """Delete a supplier (soft delete by setting inactive)."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE suppliers SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
            ''', (supplier_id, self.user_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_bills(self, supplier_id: int) -> List[Dict]:
        """Get all bills for a supplier."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM bills 
                WHERE supplier_id = ? AND user_id = ?
                ORDER BY bill_date DESC
            ''', (supplier_id, self.user_id))
            return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# Bill Manager
# =============================================================================

class BillManager:
    """Manage bills (invoices from suppliers)."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def get_all(self, status: str = None, supplier_id: int = None) -> List[Dict]:
        """Get all bills with optional filters."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT b.*, s.name as supplier_name
                FROM bills b
                LEFT JOIN suppliers s ON b.supplier_id = s.id
                WHERE b.user_id = ?
            '''
            params = [self.user_id]
            
            if status:
                query += ' AND b.status = ?'
                params.append(status)
            
            if supplier_id:
                query += ' AND b.supplier_id = ?'
                params.append(supplier_id)
            
            query += ' ORDER BY b.due_date ASC, b.bill_date DESC'
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get(self, bill_id: int) -> Optional[Dict]:
        """Get a single bill with items."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get bill
            cursor.execute('''
                SELECT b.*, s.name as supplier_name
                FROM bills b
                LEFT JOIN suppliers s ON b.supplier_id = s.id
                WHERE b.id = ? AND b.user_id = ?
            ''', (bill_id, self.user_id))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            bill = dict(row)
            
            # Get items
            cursor.execute('''
                SELECT bi.*, coa.name as coa_name, coa.code as coa_code
                FROM bill_items bi
                LEFT JOIN chart_of_accounts coa ON bi.coa_id = coa.id
                WHERE bi.bill_id = ?
                ORDER BY bi.id
            ''', (bill_id,))
            bill['items'] = [dict(row) for row in cursor.fetchall()]
            
            # Get payments
            cursor.execute('''
                SELECT * FROM bill_payments WHERE bill_id = ? ORDER BY payment_date DESC
            ''', (bill_id,))
            bill['payments'] = [dict(row) for row in cursor.fetchall()]
            
            return bill
    
    def create(self, data: Dict, items: List[Dict]) -> int:
        """Create a new bill."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Generate bill number
            cursor.execute('''
                SELECT COUNT(*) + 1 as next_num FROM bills WHERE user_id = ?
            ''', (self.user_id,))
            next_num = cursor.fetchone()['next_num']
            bill_number = data.get('bill_number') or f"BILL-{next_num:05d}"
            
            # Calculate totals
            subtotal = sum(item.get('quantity', 1) * item.get('unit_price', 0) for item in items)
            tax_rate = data.get('tax_rate', 0)
            tax_amount = subtotal * (tax_rate / 100)
            total = subtotal + tax_amount
            
            cursor.execute('''
                INSERT INTO bills (
                    user_id, supplier_id, bill_number, reference,
                    bill_date, due_date, currency, tax_rate,
                    subtotal, tax_amount, total, amount_paid,
                    status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'draft', ?)
            ''', (
                self.user_id,
                data.get('supplier_id'),
                bill_number,
                data.get('reference'),
                data.get('bill_date', date.today().isoformat()),
                data.get('due_date'),
                data.get('currency', 'GBP'),
                tax_rate,
                subtotal,
                tax_amount,
                total,
                data.get('notes')
            ))
            bill_id = cursor.lastrowid
            
            # Add items
            for item in items:
                line_total = item.get('quantity', 1) * item.get('unit_price', 0)
                cursor.execute('''
                    INSERT INTO bill_items (
                        bill_id, description, quantity, unit_price, total, coa_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    bill_id,
                    item.get('description'),
                    item.get('quantity', 1),
                    item.get('unit_price', 0),
                    line_total,
                    item.get('coa_id')
                ))
            
            conn.commit()
            return bill_id
    
    def update(self, bill_id: int, data: Dict, items: List[Dict]) -> bool:
        """Update a bill."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Check bill exists and get current status
            cursor.execute('SELECT status FROM bills WHERE id = ? AND user_id = ?', 
                          (bill_id, self.user_id))
            bill = cursor.fetchone()
            if not bill:
                return False
            
            # Calculate totals
            subtotal = sum(item.get('quantity', 1) * item.get('unit_price', 0) for item in items)
            tax_rate = data.get('tax_rate', 0)
            tax_amount = subtotal * (tax_rate / 100)
            total = subtotal + tax_amount
            
            cursor.execute('''
                UPDATE bills SET
                    supplier_id = ?, reference = ?, bill_date = ?, due_date = ?,
                    currency = ?, tax_rate = ?, subtotal = ?, tax_amount = ?,
                    total = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
            ''', (
                data.get('supplier_id'),
                data.get('reference'),
                data.get('bill_date'),
                data.get('due_date'),
                data.get('currency', 'GBP'),
                tax_rate,
                subtotal,
                tax_amount,
                total,
                data.get('notes'),
                bill_id,
                self.user_id
            ))
            
            # Update items - delete and recreate
            cursor.execute('DELETE FROM bill_items WHERE bill_id = ?', (bill_id,))
            
            for item in items:
                line_total = item.get('quantity', 1) * item.get('unit_price', 0)
                cursor.execute('''
                    INSERT INTO bill_items (
                        bill_id, description, quantity, unit_price, total, coa_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    bill_id,
                    item.get('description'),
                    item.get('quantity', 1),
                    item.get('unit_price', 0),
                    line_total,
                    item.get('coa_id')
                ))
            
            conn.commit()
            return True
    
    def update_status(self, bill_id: int, status: str) -> bool:
        """Update bill status."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE bills SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
            ''', (status, bill_id, self.user_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def add_payment(self, bill_id: int, amount: float, payment_date: str,
                    payment_method: str = None, reference: str = None, notes: str = None) -> int:
        """Add a payment to a bill."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get bill
            cursor.execute('SELECT total, amount_paid FROM bills WHERE id = ? AND user_id = ?',
                          (bill_id, self.user_id))
            bill = cursor.fetchone()
            if not bill:
                raise ValueError("Bill not found")
            
            # Record payment
            cursor.execute('''
                INSERT INTO bill_payments (
                    bill_id, amount, payment_date, payment_method, reference, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (bill_id, amount, payment_date, payment_method, reference, notes))
            payment_id = cursor.lastrowid
            
            # Update amount paid
            new_amount_paid = (bill['amount_paid'] or 0) + amount
            
            # Determine new status
            if new_amount_paid >= bill['total']:
                new_status = 'paid'
            elif new_amount_paid > 0:
                new_status = 'partial'
            else:
                new_status = 'approved'
            
            cursor.execute('''
                UPDATE bills SET amount_paid = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_amount_paid, new_status, bill_id))
            
            conn.commit()
            return payment_id
    
    def delete(self, bill_id: int) -> bool:
        """Delete a bill (only if draft)."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get attachment path first
            cursor.execute('SELECT attachment_path FROM bills WHERE id = ? AND user_id = ?',
                          (bill_id, self.user_id))
            bill = cursor.fetchone()
            
            # Delete attachment file if exists
            if bill and bill.get('attachment_path') and os.path.exists(bill['attachment_path']):
                try:
                    os.remove(bill['attachment_path'])
                except:
                    pass
            
            # Delete related records first (foreign key constraints)
            cursor.execute('DELETE FROM bill_payments WHERE bill_id = ?', (bill_id,))
            cursor.execute('DELETE FROM bill_items WHERE bill_id = ?', (bill_id,))
            
            cursor.execute('''
                DELETE FROM bills WHERE id = ? AND user_id = ? AND status = 'draft'
            ''', (bill_id, self.user_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def add_attachment(self, bill_id: int, file) -> bool:
        """Add or update attachment (supplier invoice) for a bill."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get current bill
            cursor.execute('SELECT attachment_path FROM bills WHERE id = ? AND user_id = ?',
                          (bill_id, self.user_id))
            bill = cursor.fetchone()
            if not bill:
                return False
            
            # Delete old attachment if exists
            if bill['attachment_path'] and os.path.exists(bill['attachment_path']):
                try:
                    os.remove(bill['attachment_path'])
                except:
                    pass
            
            # Save new attachment
            attachment_path = self._save_attachment(file)
            
            cursor.execute('''
                UPDATE bills SET attachment_path = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
            ''', (attachment_path, bill_id, self.user_id))
            conn.commit()
            return True
    
    def remove_attachment(self, bill_id: int) -> bool:
        """Remove attachment from a bill."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT attachment_path FROM bills WHERE id = ? AND user_id = ?',
                          (bill_id, self.user_id))
            bill = cursor.fetchone()
            if not bill:
                return False
            
            # Delete file
            if bill['attachment_path'] and os.path.exists(bill['attachment_path']):
                try:
                    os.remove(bill['attachment_path'])
                except:
                    pass
            
            cursor.execute('''
                UPDATE bills SET attachment_path = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
            ''', (bill_id, self.user_id))
            conn.commit()
            return True
    
    def _save_attachment(self, file) -> str:
        """Save an attachment file and return the path."""
        if not allowed_bill_file(file.filename):
            raise ValueError("File type not allowed")
        
        filename = secure_filename(file.filename)
        unique_filename = f"{secrets.token_hex(8)}_{filename}"
        
        upload_path = get_bill_upload_path(self.user_id)
        file_path = os.path.join(upload_path, unique_filename)
        
        file.save(file_path)
        return file_path
    
    def get_overdue(self) -> List[Dict]:
        """Get all overdue bills."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT b.*, s.name as supplier_name
                FROM bills b
                LEFT JOIN suppliers s ON b.supplier_id = s.id
                WHERE b.user_id = ? AND b.status NOT IN ('paid', 'cancelled')
                AND b.due_date < date('now')
                ORDER BY b.due_date ASC
            ''', (self.user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_summary(self) -> Dict:
        """Get bills summary."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_bills,
                    SUM(CASE WHEN status = 'draft' THEN 1 ELSE 0 END) as draft_count,
                    SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved_count,
                    SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END) as paid_count,
                    SUM(CASE WHEN status NOT IN ('paid', 'cancelled') THEN total - amount_paid ELSE 0 END) as total_outstanding,
                    SUM(CASE WHEN status NOT IN ('paid', 'cancelled') AND due_date < date('now') THEN total - amount_paid ELSE 0 END) as total_overdue
                FROM bills WHERE user_id = ?
            ''', (self.user_id,))
            return dict(cursor.fetchone())


# =============================================================================
# Expense Manager
# =============================================================================

class ExpenseManager:
    """Manage expenses with receipt uploads."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def get_all(self, category: str = None, date_from: str = None, 
                date_to: str = None, status: str = None) -> List[Dict]:
        """Get all expenses with optional filters."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT e.*, s.name as supplier_name, coa.name as coa_name, coa.code as coa_code
                FROM expenses e
                LEFT JOIN suppliers s ON e.supplier_id = s.id
                LEFT JOIN chart_of_accounts coa ON e.coa_id = coa.id
                WHERE e.user_id = ?
            '''
            params = [self.user_id]
            
            if category:
                query += ' AND e.category = ?'
                params.append(category)
            
            if date_from:
                query += ' AND e.expense_date >= ?'
                params.append(date_from)
            
            if date_to:
                query += ' AND e.expense_date <= ?'
                params.append(date_to)
            
            if status:
                query += ' AND e.status = ?'
                params.append(status)
            
            query += ' ORDER BY e.expense_date DESC'
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get(self, expense_id: int) -> Optional[Dict]:
        """Get a single expense."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT e.*, s.name as supplier_name, coa.name as coa_name, coa.code as coa_code
                FROM expenses e
                LEFT JOIN suppliers s ON e.supplier_id = s.id
                LEFT JOIN chart_of_accounts coa ON e.coa_id = coa.id
                WHERE e.id = ? AND e.user_id = ?
            ''', (expense_id, self.user_id))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def create(self, data: Dict, receipt_file=None) -> int:
        """Create a new expense with optional receipt upload."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Handle receipt upload
            receipt_path = None
            if receipt_file and receipt_file.filename:
                receipt_path = self._save_receipt(receipt_file)
            
            # Calculate tax if applicable
            amount = data.get('amount', 0)
            tax_rate = data.get('tax_rate', 0)
            if data.get('amount_includes_tax') and tax_rate > 0:
                # Amount includes tax, calculate net and tax
                net_amount = amount / (1 + tax_rate / 100)
                tax_amount = amount - net_amount
            else:
                net_amount = amount
                tax_amount = amount * (tax_rate / 100) if tax_rate else 0
            
            cursor.execute('''
                INSERT INTO expenses (
                    user_id, supplier_id, coa_id, expense_date, description,
                    category, amount, tax_rate, tax_amount, net_amount,
                    currency, payment_method, reference, receipt_path,
                    is_billable, is_reimbursable, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.user_id,
                data.get('supplier_id'),
                data.get('coa_id'),
                data.get('expense_date', date.today().isoformat()),
                data.get('description'),
                data.get('category'),
                amount,
                tax_rate,
                tax_amount,
                net_amount,
                data.get('currency', 'GBP'),
                data.get('payment_method'),
                data.get('reference'),
                receipt_path,
                1 if data.get('is_billable') else 0,
                1 if data.get('is_reimbursable') else 0,
                data.get('status', 'pending'),
                data.get('notes')
            ))
            conn.commit()
            return cursor.lastrowid
    
    def update(self, expense_id: int, data: Dict, receipt_file=None) -> bool:
        """Update an expense."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get current expense
            cursor.execute('SELECT receipt_path FROM expenses WHERE id = ? AND user_id = ?',
                          (expense_id, self.user_id))
            expense = cursor.fetchone()
            if not expense:
                return False
            
            # Handle receipt upload
            receipt_path = expense['receipt_path']
            if receipt_file and receipt_file.filename:
                # Delete old receipt if exists
                if receipt_path and os.path.exists(receipt_path):
                    try:
                        os.remove(receipt_path)
                    except:
                        pass
                receipt_path = self._save_receipt(receipt_file)
            elif data.get('remove_receipt'):
                if receipt_path and os.path.exists(receipt_path):
                    try:
                        os.remove(receipt_path)
                    except:
                        pass
                receipt_path = None
            
            # Calculate tax
            amount = data.get('amount', 0)
            tax_rate = data.get('tax_rate', 0)
            if data.get('amount_includes_tax') and tax_rate > 0:
                net_amount = amount / (1 + tax_rate / 100)
                tax_amount = amount - net_amount
            else:
                net_amount = amount
                tax_amount = amount * (tax_rate / 100) if tax_rate else 0
            
            cursor.execute('''
                UPDATE expenses SET
                    supplier_id = ?, coa_id = ?, expense_date = ?, description = ?,
                    category = ?, amount = ?, tax_rate = ?, tax_amount = ?, net_amount = ?,
                    currency = ?, payment_method = ?, reference = ?, receipt_path = ?,
                    is_billable = ?, is_reimbursable = ?, status = ?, notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
            ''', (
                data.get('supplier_id'),
                data.get('coa_id'),
                data.get('expense_date'),
                data.get('description'),
                data.get('category'),
                amount,
                tax_rate,
                tax_amount,
                net_amount,
                data.get('currency', 'GBP'),
                data.get('payment_method'),
                data.get('reference'),
                receipt_path,
                1 if data.get('is_billable') else 0,
                1 if data.get('is_reimbursable') else 0,
                data.get('status', 'pending'),
                data.get('notes'),
                expense_id,
                self.user_id
            ))
            conn.commit()
            return cursor.rowcount > 0
    
    def _save_receipt(self, file) -> str:
        """Save a receipt file and return the path."""
        if not allowed_receipt_file(file.filename):
            raise ValueError("File type not allowed")
        
        filename = secure_filename(file.filename)
        # Add unique prefix
        unique_filename = f"{secrets.token_hex(8)}_{filename}"
        
        upload_path = get_receipt_upload_path(self.user_id)
        file_path = os.path.join(upload_path, unique_filename)
        
        file.save(file_path)
        return file_path
    
    def update_receipt(self, expense_id: int, receipt_file) -> bool:
        """Update just the receipt for an expense."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT receipt_path FROM expenses WHERE id = ? AND user_id = ?',
                          (expense_id, self.user_id))
            expense = cursor.fetchone()
            if not expense:
                return False
            
            # Delete old receipt
            if expense['receipt_path'] and os.path.exists(expense['receipt_path']):
                try:
                    os.remove(expense['receipt_path'])
                except:
                    pass
            
            # Save new receipt
            receipt_path = self._save_receipt(receipt_file)
            
            cursor.execute('''
                UPDATE expenses SET receipt_path = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
            ''', (receipt_path, expense_id, self.user_id))
            conn.commit()
            return True
    
    def delete(self, expense_id: int) -> bool:
        """Delete an expense."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get receipt path first
            cursor.execute('SELECT receipt_path FROM expenses WHERE id = ? AND user_id = ?',
                          (expense_id, self.user_id))
            expense = cursor.fetchone()
            if not expense:
                return False
            
            # Delete receipt file
            if expense['receipt_path'] and os.path.exists(expense['receipt_path']):
                try:
                    os.remove(expense['receipt_path'])
                except:
                    pass
            
            cursor.execute('DELETE FROM expenses WHERE id = ? AND user_id = ?',
                          (expense_id, self.user_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def approve(self, expense_id: int) -> bool:
        """Approve an expense."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE expenses SET status = 'approved', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ? AND status = 'pending'
            ''', (expense_id, self.user_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def reject(self, expense_id: int, reason: str = None) -> bool:
        """Reject an expense."""
        with get_db() as conn:
            cursor = conn.cursor()
            notes = f"Rejected: {reason}" if reason else "Rejected"
            cursor.execute('''
                UPDATE expenses SET status = 'rejected', notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ? AND status = 'pending'
            ''', (notes, expense_id, self.user_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_categories(self) -> List[str]:
        """Get list of expense categories used."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT category FROM expenses 
                WHERE user_id = ? AND category IS NOT NULL
                ORDER BY category
            ''', (self.user_id,))
            return [row['category'] for row in cursor.fetchall()]
    
    def get_summary(self, date_from: str = None, date_to: str = None) -> Dict:
        """Get expense summary."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT 
                    COUNT(*) as total_expenses,
                    SUM(amount) as total_amount,
                    SUM(tax_amount) as total_tax,
                    SUM(net_amount) as total_net,
                    SUM(CASE WHEN status = 'pending' THEN amount ELSE 0 END) as pending_amount,
                    SUM(CASE WHEN status = 'approved' THEN amount ELSE 0 END) as approved_amount,
                    SUM(CASE WHEN is_billable = 1 THEN amount ELSE 0 END) as billable_amount,
                    SUM(CASE WHEN is_reimbursable = 1 AND status != 'reimbursed' THEN amount ELSE 0 END) as reimbursable_amount
                FROM expenses WHERE user_id = ?
            '''
            params = [self.user_id]
            
            if date_from:
                query = query.replace('WHERE user_id = ?', 'WHERE user_id = ? AND expense_date >= ?')
                params.append(date_from)
            
            if date_to:
                query += ' AND expense_date <= ?'
                params.append(date_to)
            
            cursor.execute(query, params)
            return dict(cursor.fetchone())
    
    def get_by_category(self, date_from: str = None, date_to: str = None) -> List[Dict]:
        """Get expenses grouped by category."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT 
                    COALESCE(category, 'Uncategorized') as category,
                    COUNT(*) as count,
                    SUM(amount) as total
                FROM expenses WHERE user_id = ?
            '''
            params = [self.user_id]
            
            if date_from:
                query += ' AND expense_date >= ?'
                params.append(date_from)
            
            if date_to:
                query += ' AND expense_date <= ?'
                params.append(date_to)
            
            query += ' GROUP BY category ORDER BY total DESC'
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# Expense Categories (predefined)
# =============================================================================

EXPENSE_CATEGORIES = [
    'Advertising & Marketing',
    'Bank Charges & Fees',
    'Computer & Software',
    'Consulting & Professional Fees',
    'Education & Training',
    'Entertainment',
    'Equipment & Tools',
    'Insurance',
    'Internet & Phone',
    'Legal & Accounting',
    'Meals & Dining',
    'Office Supplies',
    'Postage & Shipping',
    'Printing',
    'Rent & Utilities',
    'Repairs & Maintenance',
    'Subscriptions',
    'Travel & Transport',
    'Vehicle Expenses',
    'Other'
]

PAYMENT_METHODS = [
    'Cash',
    'Bank Transfer',
    'Credit Card',
    'Debit Card',
    'PayPal',
    'Company Card',
    'Personal Card (Reimbursable)',
    'Direct Debit',
    'Cheque',
    'Other'
]


# =============================================================================
# Database Initialization
# =============================================================================

def init_accounts_payable_tables():
    """Initialize accounts payable database tables."""
    from database import get_db_config
    
    db_config = get_db_config()
    is_mysql = db_config.get('type') == 'mysql'
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        if is_mysql:
            # MySQL syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS suppliers (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    contact_name VARCHAR(255),
                    email VARCHAR(255),
                    phone VARCHAR(100),
                    address_line1 VARCHAR(255),
                    address_line2 VARCHAR(255),
                    city VARCHAR(100),
                    state VARCHAR(100),
                    postal_code VARCHAR(50),
                    country VARCHAR(100) DEFAULT 'United Kingdom',
                    tax_id VARCHAR(100),
                    payment_terms INT DEFAULT 30,
                    default_coa_id INT,
                    notes TEXT,
                    is_active TINYINT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bills (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    supplier_id INT,
                    bill_number VARCHAR(100) NOT NULL,
                    reference VARCHAR(255),
                    bill_date DATE NOT NULL,
                    due_date DATE,
                    currency VARCHAR(10) DEFAULT 'GBP',
                    tax_rate DECIMAL(10,2) DEFAULT 0,
                    subtotal DECIMAL(15,2) DEFAULT 0,
                    tax_amount DECIMAL(15,2) DEFAULT 0,
                    total DECIMAL(15,2) DEFAULT 0,
                    amount_paid DECIMAL(15,2) DEFAULT 0,
                    status VARCHAR(50) DEFAULT 'draft',
                    notes TEXT,
                    attachment_path VARCHAR(500),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bill_items (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    bill_id INT NOT NULL,
                    description TEXT,
                    quantity DECIMAL(15,4) DEFAULT 1,
                    unit_price DECIMAL(15,2) DEFAULT 0,
                    total DECIMAL(15,2) DEFAULT 0,
                    coa_id INT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bill_payments (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    bill_id INT NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    payment_date DATE NOT NULL,
                    payment_method VARCHAR(100),
                    reference VARCHAR(255),
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS expenses (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    supplier_id INT,
                    coa_id INT,
                    expense_date DATE NOT NULL,
                    description TEXT,
                    category VARCHAR(100),
                    amount DECIMAL(15,2) NOT NULL,
                    tax_rate DECIMAL(10,2) DEFAULT 0,
                    tax_amount DECIMAL(15,2) DEFAULT 0,
                    net_amount DECIMAL(15,2) DEFAULT 0,
                    currency VARCHAR(10) DEFAULT 'GBP',
                    payment_method VARCHAR(100),
                    reference VARCHAR(255),
                    receipt_path VARCHAR(500),
                    is_billable TINYINT DEFAULT 0,
                    is_reimbursable TINYINT DEFAULT 0,
                    status VARCHAR(50) DEFAULT 'pending',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            ''')
        else:
            # SQLite syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS suppliers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    contact_name TEXT,
                    email TEXT,
                    phone TEXT,
                    address_line1 TEXT,
                    address_line2 TEXT,
                    city TEXT,
                    state TEXT,
                    postal_code TEXT,
                    country TEXT DEFAULT 'United Kingdom',
                    tax_id TEXT,
                    payment_terms INTEGER DEFAULT 30,
                    default_coa_id INTEGER,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    supplier_id INTEGER,
                    bill_number TEXT NOT NULL,
                    reference TEXT,
                    bill_date DATE NOT NULL,
                    due_date DATE,
                    currency TEXT DEFAULT 'GBP',
                    tax_rate REAL DEFAULT 0,
                    subtotal REAL DEFAULT 0,
                    tax_amount REAL DEFAULT 0,
                    total REAL DEFAULT 0,
                    amount_paid REAL DEFAULT 0,
                    status TEXT DEFAULT 'draft',
                    notes TEXT,
                    attachment_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bill_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bill_id INTEGER NOT NULL,
                    description TEXT,
                    quantity REAL DEFAULT 1,
                    unit_price REAL DEFAULT 0,
                    total REAL DEFAULT 0,
                    coa_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bill_id) REFERENCES bills (id) ON DELETE CASCADE,
                    FOREIGN KEY (coa_id) REFERENCES chart_of_accounts (id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bill_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bill_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    payment_date DATE NOT NULL,
                    payment_method TEXT,
                    reference TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bill_id) REFERENCES bills (id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    supplier_id INTEGER,
                    coa_id INTEGER,
                    expense_date DATE NOT NULL,
                    description TEXT,
                    category TEXT,
                    amount REAL NOT NULL,
                    tax_rate REAL DEFAULT 0,
                    tax_amount REAL DEFAULT 0,
                    net_amount REAL DEFAULT 0,
                    currency TEXT DEFAULT 'GBP',
                    payment_method TEXT,
                    reference TEXT,
                    receipt_path TEXT,
                    is_billable INTEGER DEFAULT 0,
                    is_reimbursable INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
                    FOREIGN KEY (coa_id) REFERENCES chart_of_accounts (id)
                )
            ''')
        
        # Create indexes (works for both MySQL and SQLite)
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_suppliers_user ON suppliers(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_bills_user ON bills(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_bills_supplier ON bills(supplier_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_bills_status ON bills(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_bills_due_date ON bills(due_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_expenses_user ON expenses(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category)')
        except:
            pass  # Indexes might already exist
        
        conn.commit()
