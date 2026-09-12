"""
Invoice Manager - Recurring Invoices & Chart of Accounts Module
Handles recurring invoice generation and account categorization.
Copyright (c) 2026 Sondela Consulting Ltd.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import json

from app_core import get_db

# =============================================================================
# Chart of Accounts
# =============================================================================

# Default Chart of Accounts categories
DEFAULT_COA = [
    # Revenue Accounts (4xxx)
    {'code': '4000', 'name': 'Sales Revenue', 'type': 'revenue', 'description': 'Income from product sales'},
    {'code': '4100', 'name': 'Service Revenue', 'type': 'revenue', 'description': 'Income from services rendered'},
    {'code': '4200', 'name': 'Consulting Revenue', 'type': 'revenue', 'description': 'Income from consulting services'},
    {'code': '4300', 'name': 'Subscription Revenue', 'type': 'revenue', 'description': 'Recurring subscription income'},
    {'code': '4400', 'name': 'License Revenue', 'type': 'revenue', 'description': 'Software/product license income'},
    {'code': '4500', 'name': 'Commission Revenue', 'type': 'revenue', 'description': 'Commission and referral income'},
    {'code': '4900', 'name': 'Other Revenue', 'type': 'revenue', 'description': 'Miscellaneous income'},
    
    # Expense Accounts (5xxx) - for future expense tracking
    {'code': '5000', 'name': 'Cost of Goods Sold', 'type': 'expense', 'description': 'Direct costs of products sold'},
    {'code': '5100', 'name': 'Direct Labor', 'type': 'expense', 'description': 'Direct labor costs'},
    {'code': '5200', 'name': 'Subcontractor Costs', 'type': 'expense', 'description': 'Outsourced service costs'},
]

COA_TYPES = {
    'revenue': {'name': 'Revenue', 'description': 'Income accounts'},
    'expense': {'name': 'Expense', 'description': 'Cost and expense accounts'},
    'asset': {'name': 'Asset', 'description': 'Asset accounts'},
    'liability': {'name': 'Liability', 'description': 'Liability accounts'},
    'equity': {'name': 'Equity', 'description': 'Equity accounts'},
}


class ChartOfAccounts:
    """Manage Chart of Accounts for a user."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def get_all(self, account_type: str = None, active_only: bool = True) -> List[Dict]:
        """Get all accounts, optionally filtered by type."""
        with get_db() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM chart_of_accounts WHERE user_id = ?'
            params = [self.user_id]
            
            if account_type:
                query += ' AND account_type = ?'
                params.append(account_type)
            
            if active_only:
                query += ' AND active = 1'
            
            query += ' ORDER BY code'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get(self, account_id: int) -> Optional[Dict]:
        """Get a specific account."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM chart_of_accounts WHERE id = ? AND user_id = ?',
                (account_id, self.user_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_by_code(self, code: str) -> Optional[Dict]:
        """Get account by code."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM chart_of_accounts WHERE code = ? AND user_id = ?',
                (code, self.user_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def create(self, code: str, name: str, account_type: str, description: str = None) -> int:
        """Create a new account."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO chart_of_accounts (user_id, code, name, account_type, description)
                VALUES (?, ?, ?, ?, ?)
            ''', (self.user_id, code, name, account_type, description))
            conn.commit()
            return cursor.lastrowid
    
    def update(self, account_id: int, data: Dict) -> bool:
        """Update an account."""
        allowed_fields = ['code', 'name', 'account_type', 'description', 'active']
        updates = []
        values = []
        
        for field in allowed_fields:
            if field in data:
                updates.append(f'{field} = ?')
                values.append(data[field])
        
        if not updates:
            return False
        
        values.append(account_id)
        values.append(self.user_id)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE chart_of_accounts SET {", ".join(updates)} WHERE id = ? AND user_id = ?',
                values
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def delete(self, account_id: int) -> bool:
        """Delete (deactivate) an account."""
        return self.update(account_id, {'active': 0})
    
    def initialize_defaults(self) -> int:
        """Initialize default chart of accounts. Returns number created."""
        count = 0
        for account in DEFAULT_COA:
            existing = self.get_by_code(account['code'])
            if not existing:
                self.create(
                    code=account['code'],
                    name=account['name'],
                    account_type=account['type'],
                    description=account['description']
                )
                count += 1
        return count


# =============================================================================
# Recurring Invoice Frequencies
# =============================================================================

RECURRING_FREQUENCIES = {
    'weekly': {'name': 'Weekly', 'days': 7, 'months': 0},
    'biweekly': {'name': 'Bi-Weekly', 'days': 14, 'months': 0},
    'monthly': {'name': 'Monthly', 'days': 0, 'months': 1},
    'quarterly': {'name': 'Quarterly', 'days': 0, 'months': 3},
    'biannually': {'name': 'Bi-Annually', 'days': 0, 'months': 6},
    'annually': {'name': 'Annually', 'days': 0, 'months': 12},
}


def calculate_next_date(current_date: date, frequency: str) -> date:
    """Calculate the next invoice date based on frequency."""
    freq = RECURRING_FREQUENCIES.get(frequency)
    if not freq:
        return current_date + timedelta(days=30)  # Default to monthly
    
    if freq['months'] > 0:
        return current_date + relativedelta(months=freq['months'])
    else:
        return current_date + timedelta(days=freq['days'])


# =============================================================================
# Recurring Invoice Manager
# =============================================================================

class RecurringInvoiceManager:
    """Manage recurring invoice templates and generation."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def get_all(self, active_only: bool = True) -> List[Dict]:
        """Get all recurring invoice templates."""
        with get_db() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT ri.*, c.name as customer_name, c.email as customer_email
                FROM recurring_invoices ri
                LEFT JOIN customers c ON ri.customer_id = c.id
                WHERE ri.user_id = ?
            '''
            if active_only:
                query += ' AND ri.active = 1'
            query += ' ORDER BY ri.next_invoice_date'
            
            cursor.execute(query, (self.user_id,))
            templates = []
            for row in cursor.fetchall():
                template = dict(row)
                template['frequency_info'] = RECURRING_FREQUENCIES.get(template['frequency'], {})
                templates.append(template)
            return templates
    
    def get(self, recurring_id: int) -> Optional[Dict]:
        """Get a specific recurring invoice template with items."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ri.*, c.name as customer_name, c.email as customer_email
                FROM recurring_invoices ri
                LEFT JOIN customers c ON ri.customer_id = c.id
                WHERE ri.id = ? AND ri.user_id = ?
            ''', (recurring_id, self.user_id))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            template = dict(row)
            template['frequency_info'] = RECURRING_FREQUENCIES.get(template['frequency'], {})
            
            # Get items
            cursor.execute('''
                SELECT rii.*, p.name as product_name, p.billing_term
                FROM recurring_invoice_items rii
                LEFT JOIN products p ON rii.product_id = p.id
                WHERE rii.recurring_invoice_id = ?
                ORDER BY rii.sort_order
            ''', (recurring_id,))
            template['items'] = [dict(item) for item in cursor.fetchall()]
            
            return template
    
    def create(self, customer_id: int, frequency: str, **kwargs) -> int:
        """Create a new recurring invoice template."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Calculate first invoice date
            start_date = kwargs.get('start_date') or date.today()
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            
            cursor.execute('''
                INSERT INTO recurring_invoices (
                    user_id, customer_id, frequency, start_date, next_invoice_date,
                    end_date, currency, tax_rate, notes, payment_terms,
                    auto_send, send_days_before, invoice_prefix
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.user_id,
                customer_id,
                frequency,
                start_date.isoformat(),
                start_date.isoformat(),  # First invoice on start date
                kwargs.get('end_date'),
                kwargs.get('currency', 'GBP'),
                kwargs.get('tax_rate', 0),
                kwargs.get('notes'),
                kwargs.get('payment_terms'),
                1 if kwargs.get('auto_send') else 0,
                kwargs.get('send_days_before', 0),
                kwargs.get('invoice_prefix', 'REC-')
            ))
            conn.commit()
            return cursor.lastrowid
    
    def update(self, recurring_id: int, data: Dict) -> bool:
        """Update a recurring invoice template."""
        allowed_fields = [
            'customer_id', 'frequency', 'start_date', 'next_invoice_date',
            'end_date', 'currency', 'tax_rate', 'notes', 'payment_terms',
            'auto_send', 'send_days_before', 'invoice_prefix', 'active'
        ]
        updates = []
        values = []
        
        for field in allowed_fields:
            if field in data:
                updates.append(f'{field} = ?')
                values.append(data[field])
        
        if not updates:
            return False
        
        updates.append('updated_at = CURRENT_TIMESTAMP')
        values.extend([recurring_id, self.user_id])
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE recurring_invoices SET {", ".join(updates)} WHERE id = ? AND user_id = ?',
                values
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def add_item(self, recurring_id: int, description: str, quantity: float, 
                 unit_price: float, product_id: int = None, tax_rate: float = 0,
                 is_recurring_item: bool = True) -> int:
        """Add an item to a recurring invoice template."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get next sort order
            cursor.execute(
                'SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM recurring_invoice_items WHERE recurring_invoice_id = ?',
                (recurring_id,)
            )
            result = cursor.fetchone()
            sort_order = result['next_order'] if isinstance(result, dict) else (result[0] if result else 1) or 1
            
            line_total = quantity * unit_price
            
            cursor.execute('''
                INSERT INTO recurring_invoice_items (
                    recurring_invoice_id, product_id, description, quantity,
                    unit_price, tax_rate, line_total, is_recurring_item, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                recurring_id, product_id, description, quantity,
                unit_price, tax_rate, line_total,
                1 if is_recurring_item else 0, sort_order
            ))
            conn.commit()
            return cursor.lastrowid
    
    def update_item(self, item_id: int, data: Dict) -> bool:
        """Update a recurring invoice item."""
        allowed_fields = ['product_id', 'description', 'quantity', 'unit_price', 
                         'tax_rate', 'is_recurring_item', 'sort_order']
        updates = []
        values = []
        
        for field in allowed_fields:
            if field in data:
                updates.append(f'{field} = ?')
                values.append(data[field])
        
        # Recalculate line total if quantity or price changed
        if 'quantity' in data or 'unit_price' in data:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT quantity, unit_price FROM recurring_invoice_items WHERE id = ?', (item_id,))
                row = cursor.fetchone()
                if row:
                    qty = data.get('quantity', row['quantity'])
                    price = data.get('unit_price', row['unit_price'])
                    updates.append('line_total = ?')
                    values.append(qty * price)
        
        if not updates:
            return False
        
        values.append(item_id)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE recurring_invoice_items SET {", ".join(updates)} WHERE id = ?',
                values
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_item(self, item_id: int) -> bool:
        """Delete an item from a recurring invoice template."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM recurring_invoice_items WHERE id = ?', (item_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def clear_items(self, recurring_id: int) -> int:
        """Clear all items from a recurring invoice template."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM recurring_invoice_items WHERE recurring_invoice_id = ?', (recurring_id,))
            conn.commit()
            return cursor.rowcount
    
    def delete(self, recurring_id: int) -> bool:
        """Deactivate a recurring invoice template."""
        return self.update(recurring_id, {'active': 0})
    
    def get_due_invoices(self, as_of_date: date = None) -> List[Dict]:
        """Get recurring invoices that are due to be generated."""
        if as_of_date is None:
            as_of_date = date.today()
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ri.*, c.name as customer_name
                FROM recurring_invoices ri
                LEFT JOIN customers c ON ri.customer_id = c.id
                WHERE ri.user_id = ? AND ri.active = 1
                AND ri.next_invoice_date <= ?
                AND (ri.end_date IS NULL OR ri.end_date >= ?)
            ''', (self.user_id, as_of_date.isoformat(), as_of_date.isoformat()))
            return [dict(row) for row in cursor.fetchall()]
    
    def generate_invoice(self, recurring_id: int, invoice_date: date = None) -> Optional[int]:
        """Generate an actual invoice from a recurring template."""
        from app_core import InvoiceManager, SettingsManager
        
        template = self.get(recurring_id)
        if not template:
            return None
        
        if invoice_date is None:
            invoice_date = date.today()
        
        # Get settings for invoice number generation
        settings_manager = SettingsManager(self.user_id)
        settings = settings_manager.get_all()
        
        # Create the invoice
        invoice_manager = InvoiceManager(self.user_id)
        
        # Generate invoice number
        prefix = template.get('invoice_prefix', 'REC-')
        next_num = settings.get('next_invoice_number', 1)
        invoice_number = f"{prefix}{next_num:05d}"
        
        # Calculate due date based on payment terms
        payment_terms = template.get('payment_terms', 'Net 30')
        try:
            days = int(''.join(filter(str.isdigit, payment_terms)) or '30')
        except:
            days = 30
        due_date = invoice_date + timedelta(days=days)
        
        # Create invoice
        invoice_id = invoice_manager.create(
            customer_id=template['customer_id'],
            invoice_number=invoice_number,
            issue_date=invoice_date.isoformat(),
            due_date=due_date.isoformat(),
            currency=template.get('currency', 'GBP'),
            tax_rate=template.get('tax_rate', 0),
            notes=template.get('notes'),
            payment_terms=template.get('payment_terms')
        )
        
        # Add items
        for item in template.get('items', []):
            invoice_manager.add_item(
                invoice_id=invoice_id,
                description=item['description'],
                quantity=item['quantity'],
                unit_price=item['unit_price'],
                tax_rate=item.get('tax_rate', 0),
                product_id=item.get('product_id')
            )
        
        # Recalculate totals
        invoice_manager._recalculate_totals(invoice_id)
        
        # Update next invoice number
        settings_manager.update_settings({'invoice_next_number': next_num + 1})
        
        # Update recurring invoice - set next date and increment count
        # Handle both string (SQLite) and date object (MySQL) for next_invoice_date
        next_invoice_date = template['next_invoice_date']
        if isinstance(next_invoice_date, str):
            next_invoice_date = datetime.strptime(next_invoice_date, '%Y-%m-%d').date()
        next_date = calculate_next_date(next_invoice_date, template['frequency'])
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE recurring_invoices 
                SET next_invoice_date = ?, 
                    last_invoice_date = ?,
                    invoices_generated = invoices_generated + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (next_date.isoformat(), invoice_date.isoformat(), recurring_id))
            conn.commit()
        
        return invoice_id
    
    def get_generated_invoices(self, recurring_id: int) -> List[Dict]:
        """Get all invoices generated from this recurring template."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT i.* FROM invoices i
                WHERE i.user_id = ? 
                AND i.invoice_number LIKE (
                    SELECT invoice_prefix || '%' FROM recurring_invoices WHERE id = ?
                )
                ORDER BY i.issue_date DESC
            ''', (self.user_id, recurring_id))
            return [dict(row) for row in cursor.fetchall()]


# =============================================================================
# Database Initialization
# =============================================================================

def init_recurring_tables():
    """Initialize recurring invoice and COA tables."""
    from database import is_mysql, should_skip_table_creation
    
    # Skip if MySQL and tables exist
    if is_mysql() and should_skip_table_creation('chart_of_accounts'):
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        if is_mysql():
            # MySQL syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chart_of_accounts (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    code VARCHAR(50) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    account_type VARCHAR(100) NOT NULL,
                    description TEXT,
                    parent_id INT,
                    active TINYINT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_code (user_id, code)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS recurring_invoices (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    user_id INT NOT NULL,
                    customer_id INT NOT NULL,
                    frequency VARCHAR(50) NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE,
                    next_invoice_date DATE NOT NULL,
                    last_invoice_date DATE,
                    currency VARCHAR(10) DEFAULT 'GBP',
                    tax_rate DECIMAL(10,2) DEFAULT 0,
                    notes TEXT,
                    payment_terms TEXT,
                    auto_send TINYINT DEFAULT 0,
                    send_days_before INT DEFAULT 0,
                    invoice_prefix VARCHAR(50) DEFAULT 'REC-',
                    invoices_generated INT DEFAULT 0,
                    active TINYINT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS recurring_invoice_items (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    recurring_invoice_id INT NOT NULL,
                    product_id INT,
                    description TEXT NOT NULL,
                    quantity DECIMAL(15,4) DEFAULT 1,
                    unit_price DECIMAL(15,2) DEFAULT 0,
                    tax_rate DECIMAL(10,2) DEFAULT 0,
                    line_total DECIMAL(15,2) DEFAULT 0,
                    is_recurring_item TINYINT DEFAULT 1,
                    sort_order INT DEFAULT 0,
                    coa_id INT
                )
            ''')
        else:
            # SQLite syntax
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chart_of_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    description TEXT,
                    parent_id INTEGER,
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (parent_id) REFERENCES chart_of_accounts (id),
                    UNIQUE(user_id, code)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS recurring_invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    customer_id INTEGER NOT NULL,
                    frequency TEXT NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE,
                    next_invoice_date DATE NOT NULL,
                    last_invoice_date DATE,
                    currency TEXT DEFAULT 'GBP',
                    tax_rate REAL DEFAULT 0,
                    notes TEXT,
                    payment_terms TEXT,
                    auto_send INTEGER DEFAULT 0,
                    send_days_before INTEGER DEFAULT 0,
                    invoice_prefix TEXT DEFAULT 'REC-',
                    invoices_generated INTEGER DEFAULT 0,
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (customer_id) REFERENCES customers (id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS recurring_invoice_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recurring_invoice_id INTEGER NOT NULL,
                    product_id INTEGER,
                    description TEXT NOT NULL,
                    quantity REAL DEFAULT 1,
                    unit_price REAL DEFAULT 0,
                    tax_rate REAL DEFAULT 0,
                    line_total REAL DEFAULT 0,
                    is_recurring_item INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    coa_id INTEGER,
                    FOREIGN KEY (recurring_invoice_id) REFERENCES recurring_invoices (id) ON DELETE CASCADE,
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            ''')
            
            # Add COA reference to products table if not exists
            try:
                cursor.execute("PRAGMA table_info(products)")
                columns = [row[1] for row in cursor.fetchall()]
                if 'coa_id' not in columns:
                    cursor.execute('ALTER TABLE products ADD COLUMN coa_id INTEGER REFERENCES chart_of_accounts(id)')
            except:
                pass
        
        conn.commit()
