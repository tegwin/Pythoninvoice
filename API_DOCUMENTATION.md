# Invoice Manager API Documentation

## Overview

The Invoice Manager provides a full REST API for programmatic access to all data. This allows you to integrate with other systems, automate invoice creation, receive payment notifications, and more.

**Base URL:** `http://localhost:5000/api/v1`

---

## Table of Contents

1. [Authentication](#authentication)
2. [Response Format](#response-format)
3. [Customers API](#customers-api)
4. [Products API](#products-api)
5. [Invoices API](#invoices-api)
6. [Payments API](#payments-api)
7. [Recurring Invoices API](#recurring-invoices-api)
8. [Suppliers API](#suppliers-api)
9. [Bills API](#bills-api)
10. [Expenses API](#expenses-api)
11. [Accounts Payable Summary](#accounts-payable-summary)
12. [Webhooks](#webhooks)
13. [Code Examples](#code-examples)
14. [Error Handling](#error-handling)
15. [API Endpoint Summary](#api-endpoint-summary)

---

## Authentication

All API requests require an API key. Create API keys from **Settings → API Keys**.

### How to Authenticate

**Option 1: Header (Recommended)**
```
X-API-Key: inv_your_api_key_here
```

**Option 2: Query Parameter**
```
?api_key=inv_your_api_key_here
```

### API Key Permissions

- **read** - View data (GET requests)
- **write** - Create, update, delete data (POST, PUT, DELETE, PATCH requests)

---

## Response Format

### Success Response
```json
{
  "success": true,
  "data": { ... },
  "message": "Optional message"
}
```

### Error Response
```json
{
  "success": false,
  "error": "Error description"
}
```

### HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 500 | Server Error |

---

## Customers API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/customers` | List all customers |
| GET | `/api/v1/customers/{id}` | Get single customer |
| POST | `/api/v1/customers` | Create customer |
| PUT | `/api/v1/customers/{id}` | Update customer |
| DELETE | `/api/v1/customers/{id}` | Delete customer |
| POST | `/api/v1/customers/bulk` | Bulk import customers |

### GET /api/v1/customers

List all customers.

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "Acme Corp",
      "email": "billing@acme.com",
      "phone": "+44 123 456 7890",
      "address_line1": "123 Business Street",
      "city": "London",
      "postal_code": "SW1A 1AA",
      "country": "United Kingdom",
      "tax_number": "GB123456789",
      "created_at": "2026-01-01T10:00:00"
    }
  ]
}
```

### GET /api/v1/customers/{id}

Get a single customer by ID.

### POST /api/v1/customers

Create a new customer.

**Request Body:**
```json
{
  "name": "New Customer Ltd",
  "email": "contact@newcustomer.com",
  "phone": "+44 987 654 3210",
  "address_line1": "456 Commerce Road",
  "city": "Manchester",
  "postal_code": "M1 1AA",
  "country": "United Kingdom",
  "tax_number": "GB987654321"
}
```

**Required Fields:** `name`

### PUT /api/v1/customers/{id}

Update an existing customer. Partial updates supported.

### DELETE /api/v1/customers/{id}

Delete a customer.

### POST /api/v1/customers/bulk

Bulk import customers.

**Request Body:**
```json
{
  "customers": [
    {"name": "Customer One", "email": "one@example.com"},
    {"name": "Customer Two", "email": "two@example.com"}
  ],
  "update_existing": false
}
```

---

## Products API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/products` | List all products |
| GET | `/api/v1/products/{id}` | Get single product |
| POST | `/api/v1/products` | Create product |
| PUT | `/api/v1/products/{id}` | Update product |
| DELETE | `/api/v1/products/{id}` | Delete product |
| POST | `/api/v1/products/bulk` | Bulk import products |

### GET /api/v1/products

List all products.

**Query Parameters:**
- `include_inactive` - Include inactive products (default: false)

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "Web Development",
      "description": "Custom web development services",
      "unit_price": 150.00,
      "unit": "hour",
      "sku": "WEB-DEV-001",
      "is_service": true,
      "taxable": true,
      "active": true
    }
  ]
}
```

### POST /api/v1/products

Create a new product.

**Request Body:**
```json
{
  "name": "Consulting Services",
  "description": "Business consulting",
  "unit_price": 200.00,
  "unit": "hour",
  "sku": "CONS-001",
  "is_service": true,
  "taxable": true
}
```

**Required Fields:** `name`

### POST /api/v1/products/bulk

Bulk import products.

**Request Body:**
```json
{
  "products": [
    {"name": "Product One", "unit_price": 100.00, "sku": "PROD-001"},
    {"name": "Product Two", "unit_price": 200.00, "sku": "PROD-002"}
  ],
  "update_existing": false
}
```

---

## Invoices API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/invoices` | List all invoices |
| GET | `/api/v1/invoices/{id}` | Get single invoice |
| POST | `/api/v1/invoices` | Create invoice |
| PUT | `/api/v1/invoices/{id}` | Update invoice |
| DELETE | `/api/v1/invoices/{id}` | Delete invoice (draft only) |
| POST | `/api/v1/invoices/bulk` | Bulk import invoices |
| POST | `/api/v1/invoices/{id}/payments` | Record payment |
| POST | `/api/v1/invoices/{id}/mark-paid` | Mark as fully paid |

### GET /api/v1/invoices

List all invoices.

**Query Parameters:**
- `status` - Filter by status (draft, sent, paid, overdue, cancelled)
- `customer_id` - Filter by customer ID

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "invoice_number": "INV-00001",
      "customer_id": 1,
      "customer_name": "Acme Corp",
      "issue_date": "2026-01-15",
      "due_date": "2026-02-14",
      "currency": "GBP",
      "tax_rate": 20,
      "subtotal": 1000.00,
      "tax_amount": 200.00,
      "total": 1200.00,
      "amount_paid": 0,
      "status": "sent",
      "items": [...],
      "payments": [...]
    }
  ]
}
```

### POST /api/v1/invoices

Create a new invoice.

**Request Body:**
```json
{
  "customer_id": 1,
  "issue_date": "2026-01-20",
  "due_date": "2026-02-19",
  "currency": "GBP",
  "tax_rate": 20,
  "notes": "Thank you for your business",
  "items": [
    {"description": "Web Development", "quantity": 10, "unit_price": 100.00, "product_id": 1},
    {"description": "Custom Item", "quantity": 5, "unit_price": 50.00}
  ]
}
```

**Required Fields:** `customer_id`, `items`

### POST /api/v1/invoices/bulk

Bulk import invoices.

**Request Body:**
```json
{
  "invoices": [
    {
      "customer_id": 1,
      "issue_date": "2026-01-20",
      "items": [{"description": "Service", "quantity": 1, "unit_price": 500}]
    }
  ]
}
```

---

## Payments API

### POST /api/v1/invoices/{id}/payments

Record a payment on an invoice.

**Request Body:**
```json
{
  "amount": 500.00,
  "payment_date": "2026-01-25",
  "payment_method": "Bank Transfer",
  "reference": "TXN-12345",
  "notes": "Partial payment"
}
```

**Required Fields:** `amount`

**Response:**
```json
{
  "success": true,
  "data": {
    "payment_id": 1,
    "invoice_id": 1,
    "amount": 500.00,
    "new_balance": 700.00,
    "invoice_status": "partial"
  }
}
```

### POST /api/v1/invoices/{id}/mark-paid

Mark an invoice as fully paid.

**Request Body (optional):**
```json
{
  "payment_date": "2026-01-25",
  "payment_method": "Bank Transfer",
  "reference": "TXN-12345"
}
```

---

## Recurring Invoices API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/recurring` | List all recurring invoices |
| GET | `/api/v1/recurring/{id}` | Get single recurring invoice |
| GET | `/api/v1/recurring/due` | Get due recurring invoices |
| POST | `/api/v1/recurring/generate` | Generate all due invoices |
| POST | `/api/v1/recurring/{id}/generate` | Generate single invoice |
| POST | `/api/v1/recurring/{id}/toggle` | Toggle active status |

### GET /api/v1/recurring

List all recurring invoices.

**Query Parameters:**
- `active` - Filter by active status (true/false)

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "Monthly Retainer",
      "customer_id": 1,
      "customer_name": "Acme Corp",
      "frequency": "monthly",
      "interval": 1,
      "next_date": "2026-02-01",
      "active": true,
      "auto_send": true
    }
  ]
}
```

### GET /api/v1/recurring/due

Get all recurring invoices that are due for generation.

### POST /api/v1/recurring/generate

Generate invoices for all due recurring templates.

**Response:**
```json
{
  "success": true,
  "data": {
    "generated": 2,
    "results": [
      {"recurring_id": 1, "invoice_id": 15, "invoice_number": "INV-00015"}
    ],
    "errors": []
  }
}
```

### POST /api/v1/recurring/{id}/generate

Generate a single recurring invoice.

**Request Body (optional):**
```json
{
  "send_email": true
}
```

### POST /api/v1/recurring/{id}/toggle

Toggle a recurring invoice between active and paused states.

---

## Suppliers API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/suppliers` | List all suppliers |
| GET | `/api/v1/suppliers/{id}` | Get single supplier |
| POST | `/api/v1/suppliers` | Create supplier |
| PUT | `/api/v1/suppliers/{id}` | Update supplier |
| DELETE | `/api/v1/suppliers/{id}` | Delete (deactivate) supplier |
| POST | `/api/v1/suppliers/import` | Bulk import suppliers |

### GET /api/v1/suppliers

List all suppliers.

**Query Parameters:**
- `include_inactive` - Include inactive suppliers (default: false)

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "name": "Office Supplies Ltd",
      "contact_name": "John Smith",
      "email": "accounts@officesupplies.com",
      "phone": "+44 123 456 7890",
      "address": {
        "line1": "123 Business Park",
        "city": "London",
        "postal_code": "SW1A 1AA",
        "country": "United Kingdom"
      },
      "tax_id": "GB123456789",
      "payment_terms": 30,
      "is_active": true,
      "bill_count": 12,
      "outstanding": 450.00
    }
  ]
}
```

### POST /api/v1/suppliers

Create a new supplier.

**Request Body:**
```json
{
  "name": "New Supplier Ltd",
  "contact_name": "Jane Doe",
  "email": "jane@newsupplier.com",
  "address": {
    "line1": "456 Industrial Estate",
    "city": "Manchester",
    "postal_code": "M1 1AA",
    "country": "United Kingdom"
  },
  "tax_id": "GB987654321",
  "payment_terms": 14
}
```

**Required Fields:** `name`

### POST /api/v1/suppliers/import

Bulk import suppliers.

**Request Body:**
```json
{
  "update_existing": true,
  "suppliers": [
    {"name": "Supplier One", "email": "one@supplier.com", "payment_terms": 30},
    {"name": "Supplier Two", "email": "two@supplier.com", "payment_terms": 14}
  ]
}
```

**Response:**
```json
{
  "success": true,
  "data": {"imported": 2, "updated": 0, "errors": null}
}
```

---

## Bills API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/bills` | List all bills |
| GET | `/api/v1/bills/{id}` | Get single bill |
| POST | `/api/v1/bills` | Create bill |
| PUT | `/api/v1/bills/{id}` | Update bill |
| DELETE | `/api/v1/bills/{id}` | Delete bill (draft only) |
| POST | `/api/v1/bills/{id}/payments` | Record payment |
| PATCH | `/api/v1/bills/{id}/status` | Update status |

### GET /api/v1/bills

List all bills.

**Query Parameters:**
- `status` - Filter by status (draft, approved, partial, paid, cancelled)
- `supplier_id` - Filter by supplier ID

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "bill_number": "BILL-00001",
      "reference": "INV-2026-001",
      "supplier_id": 1,
      "supplier_name": "Office Supplies Ltd",
      "bill_date": "2026-01-15",
      "due_date": "2026-02-14",
      "currency": "GBP",
      "tax_rate": 20,
      "subtotal": 100.00,
      "tax_amount": 20.00,
      "total": 120.00,
      "amount_paid": 0,
      "status": "approved",
      "has_attachment": true,
      "items": [...],
      "payments": [...]
    }
  ]
}
```

### POST /api/v1/bills

Create a new bill.

**Request Body:**
```json
{
  "supplier_id": 1,
  "bill_number": "BILL-00002",
  "reference": "SUP-INV-123",
  "bill_date": "2026-01-20",
  "due_date": "2026-02-19",
  "currency": "GBP",
  "tax_rate": 20,
  "items": [
    {"description": "Office Chair", "quantity": 2, "unit_price": 150.00, "coa_id": 12},
    {"description": "Standing Desk", "quantity": 1, "unit_price": 450.00, "coa_id": 12}
  ],
  "attachment_base64": "data:application/pdf;base64,JVBERi0xLjQK..."
}
```

**Required Fields:** `supplier_id`, `items`

**Note:** `attachment_base64` accepts base64-encoded PDF, image, or document.

### PUT /api/v1/bills/{id}

Update a bill.

**Special Fields:**
- `attachment_base64` - New attachment (replaces existing)
- `remove_attachment` - Set to `true` to remove attachment

### POST /api/v1/bills/{id}/payments

Record a payment on a bill.

**Request Body:**
```json
{
  "amount": 120.00,
  "payment_date": "2026-02-01",
  "payment_method": "Bank Transfer",
  "reference": "TXN-12345"
}
```

### PATCH /api/v1/bills/{id}/status

Update bill status.

**Request Body:**
```json
{
  "status": "approved"
}
```

**Valid Statuses:** `draft`, `approved`, `paid`, `cancelled`

---

## Expenses API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/expenses` | List all expenses |
| GET | `/api/v1/expenses/{id}` | Get single expense |
| POST | `/api/v1/expenses` | Create expense |
| PUT | `/api/v1/expenses/{id}` | Update expense |
| DELETE | `/api/v1/expenses/{id}` | Delete expense |
| POST | `/api/v1/expenses/{id}/approve` | Approve expense |
| POST | `/api/v1/expenses/{id}/reject` | Reject expense |
| GET | `/api/v1/expenses/categories` | Get categories & payment methods |

### GET /api/v1/expenses

List all expenses.

**Query Parameters:**
- `category` - Filter by category
- `status` - Filter by status (pending, approved, rejected, reimbursed)
- `date_from` - Start date (YYYY-MM-DD)
- `date_to` - End date (YYYY-MM-DD)

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "description": "Client lunch meeting",
      "expense_date": "2026-01-18",
      "category": "Meals & Dining",
      "amount": 85.50,
      "currency": "GBP",
      "tax_rate": 20,
      "tax_amount": 14.25,
      "net_amount": 71.25,
      "payment_method": "Company Card",
      "is_billable": true,
      "is_reimbursable": false,
      "status": "approved",
      "has_receipt": true
    }
  ]
}
```

### POST /api/v1/expenses

Create a new expense.

**Request Body:**
```json
{
  "description": "Taxi to client meeting",
  "expense_date": "2026-01-20",
  "amount": 25.00,
  "currency": "GBP",
  "tax_rate": 0,
  "category": "Travel & Transport",
  "payment_method": "Personal Card (Reimbursable)",
  "is_reimbursable": true,
  "notes": "Meeting at ABC Corp HQ",
  "receipt_base64": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
}
```

**Required Fields:** `description`, `amount`

**Note:** `receipt_base64` accepts base64-encoded image or PDF.

### PUT /api/v1/expenses/{id}

Update an expense.

**Special Fields:**
- `receipt_base64` - New receipt (replaces existing)
- `remove_receipt` - Set to `true` to remove receipt

### POST /api/v1/expenses/{id}/approve

Approve an expense.

### POST /api/v1/expenses/{id}/reject

Reject an expense.

**Request Body (optional):**
```json
{
  "reason": "Missing receipt"
}
```

### GET /api/v1/expenses/categories

Get available expense categories and payment methods.

**Response:**
```json
{
  "success": true,
  "data": {
    "categories": [
      "Advertising & Marketing",
      "Meals & Dining",
      "Travel & Transport",
      ...
    ],
    "payment_methods": [
      "Cash",
      "Bank Transfer",
      "Company Card",
      ...
    ]
  }
}
```

---

## Accounts Payable Summary

### GET /api/v1/accounts-payable/summary

Get summary statistics for bills and expenses.

**Response:**
```json
{
  "success": true,
  "data": {
    "bills": {
      "total_bills": 25,
      "draft_count": 3,
      "approved_count": 8,
      "paid_count": 14,
      "total_outstanding": 2450.00,
      "total_overdue": 350.00
    },
    "expenses": {
      "total_expenses": 150,
      "total_amount": 8500.00,
      "pending_amount": 450.00,
      "approved_amount": 6800.00,
      "reimbursable_amount": 850.00
    }
  }
}
```

---

## Webhooks

### Outgoing Webhooks

Configure in **Settings → Integrations → Webhooks**.

**Available Events:**
- `invoice.created` - New invoice created
- `invoice.sent` - Invoice sent
- `invoice.paid` - Invoice fully paid
- `invoice.partial` - Partial payment received
- `invoice.overdue` - Invoice overdue
- `payment.received` - Payment recorded
- `customer.created` - Customer created
- `customer.updated` - Customer updated

---

## Code Examples

### Python
```python
import requests

API_KEY = 'inv_your_api_key'
BASE_URL = 'http://localhost:5000/api/v1'
headers = {'X-API-Key': API_KEY, 'Content-Type': 'application/json'}

# Create invoice
response = requests.post(f'{BASE_URL}/invoices', json={
    'customer_id': 1,
    'items': [{'description': 'Service', 'quantity': 10, 'unit_price': 100}]
}, headers=headers)
print(response.json())
```

### cURL
```bash
# List customers
curl -H "X-API-Key: inv_your_api_key" http://localhost:5000/api/v1/customers

# Create expense
curl -X POST -H "X-API-Key: inv_your_api_key" -H "Content-Type: application/json" \
  -d '{"description": "Lunch", "amount": 25, "category": "Meals & Dining"}' \
  http://localhost:5000/api/v1/expenses
```

---

## Error Handling

**401 Unauthorized** - Invalid or missing API key
**403 Forbidden** - Insufficient permissions
**404 Not Found** - Resource not found
**400 Bad Request** - Validation error

---

## API Endpoint Summary

### Customers
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/customers` | List all |
| GET | `/api/v1/customers/{id}` | Get one |
| POST | `/api/v1/customers` | Create |
| PUT | `/api/v1/customers/{id}` | Update |
| DELETE | `/api/v1/customers/{id}` | Delete |
| POST | `/api/v1/customers/bulk` | Bulk import |

### Products
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/products` | List all |
| GET | `/api/v1/products/{id}` | Get one |
| POST | `/api/v1/products` | Create |
| PUT | `/api/v1/products/{id}` | Update |
| DELETE | `/api/v1/products/{id}` | Delete |
| POST | `/api/v1/products/bulk` | Bulk import |

### Invoices
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/invoices` | List all |
| GET | `/api/v1/invoices/{id}` | Get one |
| POST | `/api/v1/invoices` | Create |
| PUT | `/api/v1/invoices/{id}` | Update |
| DELETE | `/api/v1/invoices/{id}` | Delete (draft) |
| POST | `/api/v1/invoices/bulk` | Bulk import |
| POST | `/api/v1/invoices/{id}/payments` | Record payment |
| POST | `/api/v1/invoices/{id}/mark-paid` | Mark paid |

### Recurring Invoices
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/recurring` | List all |
| GET | `/api/v1/recurring/{id}` | Get one |
| GET | `/api/v1/recurring/due` | Get due |
| POST | `/api/v1/recurring/generate` | Generate all |
| POST | `/api/v1/recurring/{id}/generate` | Generate one |
| POST | `/api/v1/recurring/{id}/toggle` | Toggle active |

### Suppliers
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/suppliers` | List all |
| GET | `/api/v1/suppliers/{id}` | Get one |
| POST | `/api/v1/suppliers` | Create |
| PUT | `/api/v1/suppliers/{id}` | Update |
| DELETE | `/api/v1/suppliers/{id}` | Delete |
| POST | `/api/v1/suppliers/import` | Bulk import |

### Bills
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/bills` | List all |
| GET | `/api/v1/bills/{id}` | Get one |
| POST | `/api/v1/bills` | Create |
| PUT | `/api/v1/bills/{id}` | Update |
| DELETE | `/api/v1/bills/{id}` | Delete (draft) |
| POST | `/api/v1/bills/{id}/payments` | Record payment |
| PATCH | `/api/v1/bills/{id}/status` | Update status |

### Expenses
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/expenses` | List all |
| GET | `/api/v1/expenses/{id}` | Get one |
| POST | `/api/v1/expenses` | Create |
| PUT | `/api/v1/expenses/{id}` | Update |
| DELETE | `/api/v1/expenses/{id}` | Delete |
| POST | `/api/v1/expenses/{id}/approve` | Approve |
| POST | `/api/v1/expenses/{id}/reject` | Reject |
| GET | `/api/v1/expenses/categories` | Get categories |

### Summary
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/accounts-payable/summary` | AP summary |

---

**Copyright © 2026 Sondela Consulting Limited. All rights reserved.**
