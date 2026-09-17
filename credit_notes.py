"""
Credit Notes Module
Handles credit notes for refunds and adjustments against invoices.
"""

from datetime import datetime, date
from typing import Dict, List, Optional, Any
from database import get_db, get_db_config


def init_credit_notes_tables():
    """Initialize credit notes tables."""
    from database import should_skip_table_creation
    
    # Skip if MySQL and tables exist
    config = get_db_config()
    is_mysql = config.get('type') == 'mysql'
    
    if is_mysql and should_skip_table_creation('credit_notes'):
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        if is_mysql:
            # MySQL syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS credit_notes (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    credit_note_number VARCHAR(50) NOT NULL,
                    customer_id INT,
                    invoice_id INT,
                    status VARCHAR(20) DEFAULT 'draft',
                    issue_date DATE DEFAULT (CURRENT_DATE),
                    currency VARCHAR(10) DEFAULT 'GBP',
                    tax_rate DECIMAL(5,2) DEFAULT 0,
                    subtotal DECIMAL(12,2) DEFAULT 0,
                    tax_amount DECIMAL(12,2) DEFAULT 0,
                    total DECIMAL(12,2) DEFAULT 0,
                    amount_used DECIMAL(12,2) DEFAULT 0,
                    reason TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (customer_id) REFERENCES customers (id),
                    FOREIGN KEY (invoice_id) REFERENCES invoices (id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS credit_note_items (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    credit_note_id INT NOT NULL,
                    description VARCHAR(2000) NOT NULL,
                    quantity DECIMAL(10,2) DEFAULT 1,
                    unit_price DECIMAL(10,2) DEFAULT 0,
                    tax_rate DECIMAL(5,2) DEFAULT 0,
                    line_total DECIMAL(12,2) DEFAULT 0,
                    sort_order INT DEFAULT 0,
                    FOREIGN KEY (credit_note_id) REFERENCES credit_notes (id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS credit_note_applications (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    credit_note_id INT NOT NULL,
                    invoice_id INT NOT NULL,
                    amount DECIMAL(12,2) NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    FOREIGN KEY (credit_note_id) REFERENCES credit_notes (id),
                    FOREIGN KEY (invoice_id) REFERENCES invoices (id)
                )
            ''')
        else:
            # SQLite syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS credit_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    credit_note_number TEXT NOT NULL,
                    customer_id INTEGER,
                    invoice_id INTEGER,
                    status TEXT DEFAULT 'draft',
                    issue_date DATE DEFAULT CURRENT_DATE,
                    currency TEXT DEFAULT 'GBP',
                    tax_rate REAL DEFAULT 0,
                    subtotal REAL DEFAULT 0,
                    tax_amount REAL DEFAULT 0,
                    total REAL DEFAULT 0,
                    amount_used REAL DEFAULT 0,
                    reason TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (customer_id) REFERENCES customers (id),
                    FOREIGN KEY (invoice_id) REFERENCES invoices (id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS credit_note_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    credit_note_id INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    quantity REAL DEFAULT 1,
                    unit_price REAL DEFAULT 0,
                    tax_rate REAL DEFAULT 0,
                    line_total REAL DEFAULT 0,
                    sort_order INTEGER DEFAULT 0,
                    FOREIGN KEY (credit_note_id) REFERENCES credit_notes (id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS credit_note_applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    credit_note_id INTEGER NOT NULL,
                    invoice_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    FOREIGN KEY (credit_note_id) REFERENCES credit_notes (id),
                    FOREIGN KEY (invoice_id) REFERENCES invoices (id)
                )
            ''')
        
        conn.commit()


class CreditNoteManager:
    """Manage credit notes for a user."""
    
    STATUSES = ['draft', 'issued', 'partial', 'applied', 'cancelled']
    REASONS = [
        'Goods returned',
        'Services not rendered',
        'Pricing error',
        'Duplicate invoice',
        'Customer overpayment',
        'Damaged goods',
        'Order cancelled',
        'Other'
    ]
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        init_credit_notes_tables()
    
    def get_all(self, status: str = None, customer_id: int = None) -> List[Dict]:
        """Get all credit notes, optionally filtered."""
        with get_db() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT cn.*, c.name as customer_name, c.email as customer_email,
                       i.invoice_number as original_invoice_number
                FROM credit_notes cn
                LEFT JOIN customers c ON cn.customer_id = c.id
                LEFT JOIN invoices i ON cn.invoice_id = i.id
                WHERE cn.user_id = ?
            '''
            params = [self.user_id]
            
            if status:
                query += ' AND cn.status = ?'
                params.append(status)
            
            if customer_id:
                query += ' AND cn.customer_id = ?'
                params.append(customer_id)
            
            query += ' ORDER BY cn.created_at DESC'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get(self, credit_note_id: int) -> Optional[Dict]:
        """Get a single credit note with items and applications."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get credit note
            cursor.execute('''
                SELECT cn.*, c.name as customer_name, c.email as customer_email,
                       c.address_line1, c.address_line2, c.city, c.state, 
                       c.postal_code, c.country, c.tax_number,
                       i.invoice_number as original_invoice_number
                FROM credit_notes cn
                LEFT JOIN customers c ON cn.customer_id = c.id
                LEFT JOIN invoices i ON cn.invoice_id = i.id
                WHERE cn.id = ? AND cn.user_id = ?
            ''', (credit_note_id, self.user_id))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            credit_note = dict(row)
            
            # Get items
            cursor.execute('''
                SELECT * FROM credit_note_items 
                WHERE credit_note_id = ? 
                ORDER BY sort_order, id
            ''', (credit_note_id,))
            credit_note['items'] = [dict(r) for r in cursor.fetchall()]
            
            # Get applications
            cursor.execute('''
                SELECT cna.*, i.invoice_number
                FROM credit_note_applications cna
                JOIN invoices i ON cna.invoice_id = i.id
                WHERE cna.credit_note_id = ?
                ORDER BY cna.applied_at DESC
            ''', (credit_note_id,))
            credit_note['applications'] = [dict(r) for r in cursor.fetchall()]
            
            # Calculate balance
            credit_note['balance'] = credit_note['total'] - credit_note['amount_used']
            
            return credit_note
    
    def get_next_number(self) -> str:
        """Generate the next credit note number."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT credit_note_number FROM credit_notes 
                WHERE user_id = ? 
                ORDER BY id DESC LIMIT 1
            ''', (self.user_id,))
            row = cursor.fetchone()
            
            if row and row['credit_note_number']:
                # Try to extract number from format CN-XXXXX
                try:
                    last_num = int(row['credit_note_number'].split('-')[-1])
                    return f"CN-{last_num + 1:05d}"
                except:
                    pass
            
            return "CN-00001"
    
    def create(self, data: Dict) -> int:
        """Create a new credit note."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            credit_note_number = data.get('credit_note_number') or self.get_next_number()
            
            cursor.execute('''
                INSERT INTO credit_notes (
                    user_id, credit_note_number, customer_id, invoice_id,
                    status, issue_date, currency, tax_rate, reason, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.user_id,
                credit_note_number,
                data.get('customer_id'),
                data.get('invoice_id'),
                data.get('status', 'draft'),
                data.get('issue_date', date.today().isoformat()),
                data.get('currency', 'GBP'),
                data.get('tax_rate', 0),
                data.get('reason'),
                data.get('notes')
            ))
            
            credit_note_id = cursor.lastrowid
            
            # Add items
            items = data.get('items', [])
            subtotal = 0
            
            for i, item in enumerate(items):
                quantity = float(item.get('quantity', 1))
                unit_price = float(item.get('unit_price', 0))
                line_total = quantity * unit_price
                subtotal += line_total
                
                cursor.execute('''
                    INSERT INTO credit_note_items (
                        credit_note_id, description, quantity, unit_price, 
                        tax_rate, line_total, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    credit_note_id,
                    item.get('description', ''),
                    quantity,
                    unit_price,
                    item.get('tax_rate', data.get('tax_rate', 0)),
                    line_total,
                    i
                ))
            
            # Calculate totals
            tax_rate = float(data.get('tax_rate', 0))
            tax_amount = subtotal * (tax_rate / 100)
            total = subtotal + tax_amount
            
            cursor.execute('''
                UPDATE credit_notes 
                SET subtotal = ?, tax_amount = ?, total = ?
                WHERE id = ?
            ''', (subtotal, tax_amount, total, credit_note_id))
            
            conn.commit()
            return credit_note_id
    
    def update(self, credit_note_id: int, data: Dict) -> bool:
        """Update a credit note."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Check ownership and status
            cursor.execute(
                'SELECT status FROM credit_notes WHERE id = ? AND user_id = ?',
                (credit_note_id, self.user_id)
            )
            row = cursor.fetchone()
            if not row:
                return False
            
            # Only allow editing draft credit notes
            if row['status'] != 'draft' and 'status' not in data:
                return False
            
            # Update main fields
            allowed_fields = ['customer_id', 'invoice_id', 'status', 'issue_date', 
                            'currency', 'tax_rate', 'reason', 'notes']
            updates = ['updated_at = CURRENT_TIMESTAMP']
            values = []
            
            for field in allowed_fields:
                if field in data:
                    updates.append(f'{field} = ?')
                    values.append(data[field])
            
            if len(updates) > 1:
                values.extend([credit_note_id, self.user_id])
                cursor.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query -- column names come from a fixed list in this function; values are parameterised
                    f'UPDATE credit_notes SET {", ".join(updates)} WHERE id = ? AND user_id = ?',
                    values
                )
            
            # Update items if provided
            if 'items' in data:
                # Delete existing items
                cursor.execute('DELETE FROM credit_note_items WHERE credit_note_id = ?', 
                             (credit_note_id,))
                
                # Add new items
                subtotal = 0
                tax_rate = float(data.get('tax_rate', 0))
                
                # Get current tax rate if not provided
                if 'tax_rate' not in data:
                    cursor.execute('SELECT tax_rate FROM credit_notes WHERE id = ?', 
                                 (credit_note_id,))
                    tax_rate = float(cursor.fetchone()['tax_rate'] or 0)
                
                for i, item in enumerate(data['items']):
                    quantity = float(item.get('quantity', 1))
                    unit_price = float(item.get('unit_price', 0))
                    line_total = quantity * unit_price
                    subtotal += line_total
                    
                    cursor.execute('''
                        INSERT INTO credit_note_items (
                            credit_note_id, description, quantity, unit_price,
                            tax_rate, line_total, sort_order
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        credit_note_id,
                        item.get('description', ''),
                        quantity,
                        unit_price,
                        item.get('tax_rate', tax_rate),
                        line_total,
                        i
                    ))
                
                # Recalculate totals
                tax_amount = subtotal * (tax_rate / 100)
                total = subtotal + tax_amount
                
                cursor.execute('''
                    UPDATE credit_notes 
                    SET subtotal = ?, tax_amount = ?, total = ?
                    WHERE id = ?
                ''', (subtotal, tax_amount, total, credit_note_id))
            
            conn.commit()
            return True
    
    def delete(self, credit_note_id: int) -> bool:
        """Delete a draft credit note."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM credit_notes 
                WHERE id = ? AND user_id = ? AND status = 'draft'
            ''', (credit_note_id, self.user_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def issue(self, credit_note_id: int) -> bool:
        """Issue a credit note (change status from draft to issued)."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE credit_notes 
                SET status = 'issued', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ? AND status = 'draft'
            ''', (credit_note_id, self.user_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def apply_to_invoice(self, credit_note_id: int, invoice_id: int, amount: float, 
                        notes: str = None) -> Dict:
        """Apply a credit note to an invoice."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get credit note
            cursor.execute('''
                SELECT * FROM credit_notes 
                WHERE id = ? AND user_id = ? AND status IN ('issued', 'partial')
            ''', (credit_note_id, self.user_id))
            cn = cursor.fetchone()
            if not cn:
                return {'success': False, 'error': 'Credit note not found or not available'}
            
            cn = dict(cn)
            available = cn['total'] - cn['amount_used']
            
            if amount > available:
                return {'success': False, 'error': f'Only {available:.2f} available on this credit note'}
            
            # Get invoice
            cursor.execute('''
                SELECT * FROM invoices 
                WHERE id = ? AND user_id = ? AND status IN ('sent', 'partial', 'overdue')
            ''', (invoice_id, self.user_id))
            inv = cursor.fetchone()
            if not inv:
                return {'success': False, 'error': 'Invoice not found or not applicable'}
            
            inv = dict(inv)
            balance_due = inv['total'] - inv['amount_paid']
            
            if amount > balance_due:
                return {'success': False, 'error': f'Amount exceeds invoice balance of {balance_due:.2f}'}
            
            # Verify same customer
            if cn['customer_id'] != inv['customer_id']:
                return {'success': False, 'error': 'Credit note and invoice must be for the same customer'}
            
            # Create application record
            cursor.execute('''
                INSERT INTO credit_note_applications (credit_note_id, invoice_id, amount, notes)
                VALUES (?, ?, ?, ?)
            ''', (credit_note_id, invoice_id, amount, notes))
            
            # Update credit note amount_used and status
            new_used = cn['amount_used'] + amount
            new_status = 'applied' if abs(new_used - cn['total']) < 0.01 else 'partial'
            
            cursor.execute('''
                UPDATE credit_notes 
                SET amount_used = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_used, new_status, credit_note_id))
            
            # Update invoice payment
            new_paid = inv['amount_paid'] + amount
            inv_status = 'paid' if abs(new_paid - inv['total']) < 0.01 else 'partial'
            
            cursor.execute('''
                UPDATE invoices 
                SET amount_paid = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_paid, inv_status, invoice_id))
            
            # Record as payment on invoice
            cursor.execute('''
                INSERT INTO payments (invoice_id, amount, payment_method, reference, notes, created_via)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                invoice_id, 
                amount, 
                'Credit Note',
                cn['credit_note_number'],
                f'Applied from credit note {cn["credit_note_number"]}',
                'credit_note'
            ))
            
            conn.commit()
            
            return {
                'success': True,
                'message': f'Applied {amount:.2f} from {cn["credit_note_number"]} to invoice',
                'credit_note_balance': cn['total'] - new_used,
                'invoice_balance': inv['total'] - new_paid
            }
    
    def create_from_invoice(self, invoice_id: int, reason: str = None, 
                           items: List[Dict] = None) -> int:
        """Create a credit note from an existing invoice."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get invoice
            cursor.execute('''
                SELECT * FROM invoices WHERE id = ? AND user_id = ?
            ''', (invoice_id, self.user_id))
            inv = cursor.fetchone()
            if not inv:
                raise ValueError("Invoice not found")
            
            inv = dict(inv)
            
            # If no items specified, copy all invoice items
            if items is None:
                cursor.execute('''
                    SELECT description, quantity, unit_price, tax_rate
                    FROM invoice_items WHERE invoice_id = ?
                ''', (invoice_id,))
                items = [dict(row) for row in cursor.fetchall()]
            
            # Create credit note
            data = {
                'customer_id': inv['customer_id'],
                'invoice_id': invoice_id,
                'currency': inv['currency'],
                'tax_rate': inv['tax_rate'],
                'reason': reason or 'Created from invoice',
                'notes': f'Credit note for invoice {inv["invoice_number"]}',
                'items': items
            }
            
            return self.create(data)
    
    def get_customer_credit_balance(self, customer_id: int) -> float:
        """Get total available credit for a customer."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COALESCE(SUM(total - amount_used), 0) as balance
                FROM credit_notes
                WHERE user_id = ? AND customer_id = ? AND status IN ('issued', 'partial')
            ''', (self.user_id, customer_id))
            row = cursor.fetchone()
            return float(row['balance']) if row else 0.0
    
    def get_available_for_customer(self, customer_id: int) -> List[Dict]:
        """Get all available (unused/partially used) credit notes for a customer."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT cn.*, (cn.total - cn.amount_used) as available_balance
                FROM credit_notes cn
                WHERE cn.user_id = ? AND cn.customer_id = ? 
                AND cn.status IN ('issued', 'partial')
                AND (cn.total - cn.amount_used) > 0.01
                ORDER BY cn.issue_date
            ''', (self.user_id, customer_id))
            return [dict(row) for row in cursor.fetchall()]
