"""
Invoice Manager - Import/Export Module
Handles CSV import/export for customers, products, and invoices.
"""

import csv
import io
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional

from app_core import get_db, CustomerManager, ProductManager, InvoiceManager


def export_customers_csv(customers: List[dict]) -> str:
    """Export a list of customers to CSV format."""
    output = io.StringIO()
    fieldnames = [
        'id', 'name', 'email', 'phone', 'address_line1', 'address_line2',
        'city', 'state', 'postal_code', 'country', 'tax_number',
        'custom_tax_rate', 'custom_currency', 'notes', 'created_at'
    ]
    
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    
    for customer in customers:
        writer.writerow(customer)
    
    return output.getvalue()


class DataExporter:
    """Export data to CSV format."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def export_customers(self) -> str:
        """Export all customers to CSV."""
        customer_manager = CustomerManager(self.user_id)
        customers = customer_manager.get_all()
        
        output = io.StringIO()
        fieldnames = [
            'id', 'name', 'email', 'phone', 'address_line1', 'address_line2',
            'city', 'state', 'postal_code', 'country', 'tax_number',
            'custom_tax_rate', 'custom_currency', 'notes', 'created_at'
        ]
        
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        
        for customer in customers:
            writer.writerow(customer)
        
        return output.getvalue()
    
    def export_products(self) -> str:
        """Export all products to CSV."""
        product_manager = ProductManager(self.user_id)
        products = product_manager.get_all(include_inactive=True)
        
        output = io.StringIO()
        fieldnames = [
            'id', 'name', 'description', 'unit_price', 'unit', 'sku',
            'is_service', 'taxable', 'active', 'created_at'
        ]
        
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        
        for product in products:
            writer.writerow(product)
        
        return output.getvalue()
    
    def export_invoices(self, include_items: bool = True) -> str:
        """Export all invoices to CSV."""
        invoice_manager = InvoiceManager(self.user_id)
        invoices = invoice_manager.get_all()
        
        output = io.StringIO()
        fieldnames = [
            'id', 'invoice_number', 'customer_id', 'customer_name', 'status',
            'issue_date', 'due_date', 'currency', 'tax_rate', 'subtotal',
            'tax_amount', 'total', 'amount_paid', 'notes', 'payment_terms',
            'created_at', 'paid_at'
        ]
        
        if include_items:
            fieldnames.append('items_json')
        
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        
        for invoice in invoices:
            row = dict(invoice)
            if include_items:
                # Get full invoice with items
                full_invoice = invoice_manager.get(invoice['id'])
                if full_invoice and full_invoice.get('items'):
                    row['items_json'] = json.dumps(full_invoice['items'])
            writer.writerow(row)
        
        return output.getvalue()
    
    def export_invoice_items(self) -> str:
        """Export all invoice items to CSV."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ii.*, i.invoice_number
                FROM invoice_items ii
                JOIN invoices i ON ii.invoice_id = i.id
                WHERE i.user_id = ?
                ORDER BY i.invoice_number, ii.sort_order
            ''', (self.user_id,))
            items = [dict(row) for row in cursor.fetchall()]
        
        output = io.StringIO()
        fieldnames = [
            'id', 'invoice_id', 'invoice_number', 'product_id', 'description',
            'quantity', 'unit_price', 'tax_rate', 'line_total', 'sort_order'
        ]
        
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        
        for item in items:
            writer.writerow(item)
        
        return output.getvalue()


class DataImporter:
    """Import data from CSV format."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def import_customers(self, csv_data: str, update_existing: bool = False) -> Tuple[int, int, List[str]]:
        """
        Import customers from CSV.
        Returns: (imported_count, updated_count, errors)
        """
        customer_manager = CustomerManager(self.user_id)
        imported = 0
        updated = 0
        errors = []
        
        try:
            reader = csv.DictReader(io.StringIO(csv_data))
            
            for row_num, row in enumerate(reader, start=2):
                try:
                    # Required field
                    if not row.get('name'):
                        errors.append(f"Row {row_num}: Name is required")
                        continue
                    
                    # Check if customer exists (by email or name)
                    existing = None
                    if row.get('email'):
                        existing = customer_manager.get_by_email(row['email'])
                    
                    if existing and update_existing:
                        # Update existing customer
                        customer_manager.update(existing['id'], {
                            'name': row.get('name', existing['name']),
                            'phone': row.get('phone'),
                            'address_line1': row.get('address_line1'),
                            'address_line2': row.get('address_line2'),
                            'city': row.get('city'),
                            'state': row.get('state'),
                            'postal_code': row.get('postal_code'),
                            'country': row.get('country'),
                            'tax_number': row.get('tax_number'),
                            'custom_tax_rate': float(row['custom_tax_rate']) if row.get('custom_tax_rate') else None,
                            'custom_currency': row.get('custom_currency'),
                            'notes': row.get('notes'),
                        })
                        updated += 1
                    elif not existing:
                        # Create new customer
                        customer_manager.create(
                            name=row['name'],
                            email=row.get('email'),
                            phone=row.get('phone'),
                            address_line1=row.get('address_line1'),
                            address_line2=row.get('address_line2'),
                            city=row.get('city'),
                            state=row.get('state'),
                            postal_code=row.get('postal_code'),
                            country=row.get('country'),
                            tax_number=row.get('tax_number'),
                            custom_tax_rate=float(row['custom_tax_rate']) if row.get('custom_tax_rate') else None,
                            custom_currency=row.get('custom_currency') or None,
                            notes=row.get('notes'),
                        )
                        imported += 1
                    else:
                        errors.append(f"Row {row_num}: Customer with email '{row['email']}' already exists (skipped)")
                
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")
        
        except Exception as e:
            errors.append(f"CSV parsing error: {str(e)}")
        
        return imported, updated, errors
    
    def import_products(self, csv_data: str, update_existing: bool = False) -> Tuple[int, int, List[str]]:
        """
        Import products from CSV.
        Returns: (imported_count, updated_count, errors)
        """
        product_manager = ProductManager(self.user_id)
        imported = 0
        updated = 0
        errors = []
        
        try:
            reader = csv.DictReader(io.StringIO(csv_data))
            
            for row_num, row in enumerate(reader, start=2):
                try:
                    # Required fields
                    if not row.get('name'):
                        errors.append(f"Row {row_num}: Name is required")
                        continue
                    
                    # Check if product exists (by SKU or name)
                    existing = None
                    if row.get('sku'):
                        existing = product_manager.get_by_sku(row['sku'])
                    if not existing:
                        existing = product_manager.get_by_name(row['name'])
                    
                    unit_price = float(row.get('unit_price', 0) or 0)
                    is_service = row.get('is_service', '0') in ('1', 'true', 'True', 'yes', 'Yes')
                    taxable = row.get('taxable', '1') in ('1', 'true', 'True', 'yes', 'Yes', '')
                    active = row.get('active', '1') in ('1', 'true', 'True', 'yes', 'Yes', '')
                    
                    if existing and update_existing:
                        # Update existing product
                        product_manager.update(existing['id'], {
                            'name': row.get('name', existing['name']),
                            'description': row.get('description'),
                            'unit_price': unit_price,
                            'unit': row.get('unit', 'unit'),
                            'sku': row.get('sku'),
                            'is_service': is_service,
                            'taxable': taxable,
                            'active': active,
                        })
                        updated += 1
                    elif not existing:
                        # Create new product
                        product_manager.create(
                            name=row['name'],
                            description=row.get('description'),
                            unit_price=unit_price,
                            unit=row.get('unit', 'unit'),
                            sku=row.get('sku'),
                            is_service=is_service,
                            taxable=taxable,
                        )
                        imported += 1
                    else:
                        errors.append(f"Row {row_num}: Product '{row['name']}' already exists (skipped)")
                
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")
        
        except Exception as e:
            errors.append(f"CSV parsing error: {str(e)}")
        
        return imported, updated, errors
    
    def import_invoices(self, csv_data: str) -> Tuple[int, List[str]]:
        """
        Import invoices from CSV.
        Returns: (imported_count, errors)
        Note: This creates new invoices only, does not update existing ones.
        """
        invoice_manager = InvoiceManager(self.user_id)
        customer_manager = CustomerManager(self.user_id)
        imported = 0
        errors = []
        
        try:
            reader = csv.DictReader(io.StringIO(csv_data))
            
            for row_num, row in enumerate(reader, start=2):
                try:
                    # Find or skip customer
                    customer_id = None
                    if row.get('customer_id'):
                        customer_id = int(row['customer_id'])
                    elif row.get('customer_name'):
                        customer = customer_manager.get_by_name(row['customer_name'])
                        if customer:
                            customer_id = customer['id']
                    
                    # Create invoice
                    invoice_id = invoice_manager.create(
                        customer_id=customer_id,
                        issue_date=row.get('issue_date'),
                        due_date=row.get('due_date'),
                        currency=row.get('currency', 'GBP'),
                        tax_rate=float(row.get('tax_rate', 0) or 0),
                        notes=row.get('notes'),
                        payment_terms=row.get('payment_terms'),
                    )
                    
                    # Update status if specified
                    if row.get('status') and row['status'] != 'draft':
                        invoice_manager.update_status(invoice_id, row['status'])
                    
                    # Import items if provided as JSON
                    if row.get('items_json'):
                        try:
                            items = json.loads(row['items_json'])
                            for item in items:
                                invoice_manager.add_item(
                                    invoice_id,
                                    description=item.get('description', ''),
                                    quantity=float(item.get('quantity', 1)),
                                    unit_price=float(item.get('unit_price', 0)),
                                    tax_rate=float(item.get('tax_rate', 0)) if item.get('tax_rate') else None,
                                )
                        except json.JSONDecodeError:
                            errors.append(f"Row {row_num}: Invalid items_json format")
                    
                    imported += 1
                
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")
        
        except Exception as e:
            errors.append(f"CSV parsing error: {str(e)}")
        
        return imported, errors


# Helper functions for API bulk import
def bulk_import_customers_api(user_id: int, customers: List[Dict], update_existing: bool = False) -> Dict:
    """
    Bulk import customers via API.
    
    Args:
        user_id: The user ID to import for
        customers: List of customer dictionaries
        update_existing: Whether to update existing customers
    
    Returns:
        Dict with imported, updated, errors
    """
    customer_manager = CustomerManager(user_id)
    imported = 0
    updated = 0
    errors = []
    created_ids = []
    
    for idx, customer in enumerate(customers):
        try:
            if not customer.get('name'):
                errors.append({'index': idx, 'error': 'Name is required'})
                continue
            
            # Check if exists
            existing = None
            if customer.get('email'):
                existing = customer_manager.get_by_email(customer['email'])
            
            if existing and update_existing:
                customer_manager.update(existing['id'], customer)
                updated += 1
            elif not existing:
                customer_id = customer_manager.create(**customer)
                imported += 1
                created_ids.append(customer_id)
            else:
                errors.append({'index': idx, 'error': f"Customer with email '{customer['email']}' already exists"})
        
        except Exception as e:
            errors.append({'index': idx, 'error': str(e)})
    
    return {
        'imported': imported,
        'updated': updated,
        'errors': errors,
        'created_ids': created_ids
    }


def bulk_import_products_api(user_id: int, products: List[Dict], update_existing: bool = False) -> Dict:
    """
    Bulk import products via API.
    """
    product_manager = ProductManager(user_id)
    imported = 0
    updated = 0
    errors = []
    created_ids = []
    
    for idx, product in enumerate(products):
        try:
            if not product.get('name'):
                errors.append({'index': idx, 'error': 'Name is required'})
                continue
            
            # Check if exists
            existing = None
            if product.get('sku'):
                existing = product_manager.get_by_sku(product['sku'])
            if not existing:
                existing = product_manager.get_by_name(product['name'])
            
            if existing and update_existing:
                product_manager.update(existing['id'], product)
                updated += 1
            elif not existing:
                product_id = product_manager.create(**product)
                imported += 1
                created_ids.append(product_id)
            else:
                errors.append({'index': idx, 'error': f"Product '{product['name']}' already exists"})
        
        except Exception as e:
            errors.append({'index': idx, 'error': str(e)})
    
    return {
        'imported': imported,
        'updated': updated,
        'errors': errors,
        'created_ids': created_ids
    }


def bulk_import_invoices_api(user_id: int, invoices: List[Dict]) -> Dict:
    """
    Bulk import invoices via API.
    """
    invoice_manager = InvoiceManager(user_id)
    customer_manager = CustomerManager(user_id)
    imported = 0
    errors = []
    created_ids = []
    
    for idx, invoice_data in enumerate(invoices):
        try:
            # Resolve customer
            customer_id = invoice_data.get('customer_id')
            if not customer_id and invoice_data.get('customer_email'):
                customer = customer_manager.get_by_email(invoice_data['customer_email'])
                if customer:
                    customer_id = customer['id']
            
            # Create invoice
            invoice_id = invoice_manager.create(
                customer_id=customer_id,
                issue_date=invoice_data.get('issue_date'),
                due_date=invoice_data.get('due_date'),
                currency=invoice_data.get('currency', 'GBP'),
                tax_rate=float(invoice_data.get('tax_rate', 0) or 0),
                notes=invoice_data.get('notes'),
                payment_terms=invoice_data.get('payment_terms'),
            )
            
            # Add items
            for item in invoice_data.get('items', []):
                invoice_manager.add_item(
                    invoice_id,
                    description=item.get('description', ''),
                    quantity=float(item.get('quantity', 1)),
                    unit_price=float(item.get('unit_price', 0)),
                    product_id=item.get('product_id'),
                    tax_rate=float(item.get('tax_rate')) if item.get('tax_rate') is not None else None,
                )
            
            # Update status if specified
            if invoice_data.get('status') and invoice_data['status'] != 'draft':
                invoice_manager.update_status(invoice_id, invoice_data['status'])
            
            imported += 1
            created_ids.append(invoice_id)
        
        except Exception as e:
            errors.append({'index': idx, 'error': str(e)})
    
    return {
        'imported': imported,
        'errors': errors,
        'created_ids': created_ids
    }


# =============================================================================
# Supplier Import/Export Functions
# =============================================================================

def export_suppliers_csv(suppliers: List[dict]) -> str:
    """Export a list of suppliers to CSV format."""
    output = io.StringIO()
    fieldnames = [
        'id', 'name', 'contact_name', 'email', 'phone',
        'address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country',
        'tax_id', 'payment_terms', 'notes', 'is_active', 'created_at'
    ]
    
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    
    for supplier in suppliers:
        writer.writerow(supplier)
    
    return output.getvalue()


def import_suppliers_csv(user_id: int, csv_data: str, update_existing: bool = False) -> Tuple[int, int, List[str]]:
    """
    Import suppliers from CSV.
    Returns: (imported_count, updated_count, errors)
    
    CSV format:
    name,contact_name,email,phone,address_line1,address_line2,city,state,postal_code,country,tax_id,payment_terms,notes
    """
    from accounts_payable import SupplierManager
    
    supplier_manager = SupplierManager(user_id)
    imported = 0
    updated = 0
    errors = []
    
    try:
        reader = csv.DictReader(io.StringIO(csv_data))
        
        for row_num, row in enumerate(reader, start=2):
            try:
                # Required fields
                if not row.get('name'):
                    errors.append(f"Row {row_num}: Name is required")
                    continue
                
                # Check if supplier exists (by email or name)
                existing = None
                if row.get('email'):
                    existing = supplier_manager.get_by_email(row['email'])
                if not existing:
                    existing = supplier_manager.get_by_name(row['name'])
                
                is_active = row.get('is_active', '1') in ('1', 'true', 'True', 'yes', 'Yes', '')
                payment_terms = int(row.get('payment_terms', 30) or 30)
                
                if existing and update_existing:
                    # Update existing supplier
                    supplier_manager.update(existing['id'], {
                        'name': row.get('name', existing['name']),
                        'contact_name': row.get('contact_name'),
                        'email': row.get('email'),
                        'phone': row.get('phone'),
                        'address_line1': row.get('address_line1'),
                        'address_line2': row.get('address_line2'),
                        'city': row.get('city'),
                        'state': row.get('state'),
                        'postal_code': row.get('postal_code'),
                        'country': row.get('country', 'United Kingdom'),
                        'tax_id': row.get('tax_id'),
                        'payment_terms': payment_terms,
                        'notes': row.get('notes'),
                        'is_active': is_active,
                    })
                    updated += 1
                elif not existing:
                    # Create new supplier
                    supplier_manager.create({
                        'name': row['name'],
                        'contact_name': row.get('contact_name'),
                        'email': row.get('email'),
                        'phone': row.get('phone'),
                        'address_line1': row.get('address_line1'),
                        'address_line2': row.get('address_line2'),
                        'city': row.get('city'),
                        'state': row.get('state'),
                        'postal_code': row.get('postal_code'),
                        'country': row.get('country', 'United Kingdom'),
                        'tax_id': row.get('tax_id'),
                        'payment_terms': payment_terms,
                        'notes': row.get('notes'),
                    })
                    imported += 1
                else:
                    errors.append(f"Row {row_num}: Supplier '{row['name']}' already exists (skipped)")
            
            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")
    
    except Exception as e:
        errors.append(f"CSV parsing error: {str(e)}")
    
    return imported, updated, errors


def get_supplier_csv_template() -> str:
    """Get a CSV template for supplier import."""
    output = io.StringIO()
    fieldnames = [
        'name', 'contact_name', 'email', 'phone',
        'address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country',
        'tax_id', 'payment_terms', 'notes'
    ]
    
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    
    # Add example row
    writer.writerow({
        'name': 'Example Supplier Ltd',
        'contact_name': 'John Smith',
        'email': 'accounts@example.com',
        'phone': '+44 123 456 7890',
        'address_line1': '123 Business Park',
        'address_line2': 'Suite 100',
        'city': 'London',
        'state': 'Greater London',
        'postal_code': 'SW1A 1AA',
        'country': 'United Kingdom',
        'tax_id': 'GB123456789',
        'payment_terms': '30',
        'notes': 'Preferred supplier'
    })
    
    return output.getvalue()
