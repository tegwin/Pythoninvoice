# Invoice Manager

A comprehensive Python Flask-based invoice management application with API support, webhooks, and PDF generation.

## Features

### Phase 1 (Implemented)

- **Customer Management**
  - Add, edit, delete customers
  - Custom tax rates and currencies per customer
  - Address and contact information

- **Products & Services**
  - Create reusable products/services
  - Set default pricing and descriptions
  - Quick add to invoices

- **Invoice Management**
  - Create invoices with multiple line items
  - Add items from products or manually
  - Set tax rate and currency per invoice
  - Customer-specific defaults
  - PDF export and HTML print view
  - Invoice statuses: draft, sent, paid, partial, overdue, cancelled

- **Payment Tracking**
  - Record payments manually
  - Mark invoices as paid
  - Payment history per invoice
  - Partial payment support

- **API Access**
  - Full REST API for all entities
  - GET, POST, PUT, DELETE operations
  - API key authentication with permissions
  - Multiple API keys per user

- **Outbound Webhooks**
  - Configure webhooks for events
  - Events: invoice.created, invoice.paid, payment.received, etc.
  - Authentication options: Bearer, API Key, Basic, Custom Header
  - Test webhooks functionality

- **Global Settings**
  - Company name and address
  - Logo upload
  - Default tax rate and currency
  - Invoice number prefix
  - Payment terms and bank details

## Installation

1. **Clone or extract the application:**
   ```bash
   cd invoice_app
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application:**
   ```bash
   python run.py
   ```

4. **Open in browser:**
   ```
   http://localhost:5000
   ```

5. **Register a new account** and start creating invoices!

## API Documentation

### Authentication

Include your API key in requests:
```
Header: X-API-Key: inv_your_api_key_here
```
Or as query parameter:
```
?api_key=inv_your_api_key_here
```

### Endpoints

#### Customers
- `GET /api/v1/customers` - List all customers
- `POST /api/v1/customers` - Create customer
- `GET /api/v1/customers/{id}` - Get customer
- `PUT /api/v1/customers/{id}` - Update customer
- `DELETE /api/v1/customers/{id}` - Delete customer

#### Products
- `GET /api/v1/products` - List all products
- `POST /api/v1/products` - Create product
- `GET /api/v1/products/{id}` - Get product
- `PUT /api/v1/products/{id}` - Update product
- `DELETE /api/v1/products/{id}` - Deactivate product

#### Invoices
- `GET /api/v1/invoices` - List all invoices
- `POST /api/v1/invoices` - Create invoice
- `GET /api/v1/invoices/{id}` - Get invoice with items
- `PUT /api/v1/invoices/{id}` - Update invoice
- `DELETE /api/v1/invoices/{id}` - Delete invoice

#### Payments
- `POST /api/v1/invoices/{id}/payments` - Add payment
- `POST /api/v1/invoices/{id}/mark-paid` - Mark as fully paid

#### External Payment Webhook
- `POST /api/webhook/payment` - Receive external payment notifications

### Example: Create Invoice via API

```bash
curl -X POST "http://localhost:5000/api/v1/invoices" \
  -H "X-API-Key: inv_your_key" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": 1,
    "currency": "GBP",
    "tax_rate": 20,
    "items": [
      {"description": "Consulting Services", "quantity": 10, "unit_price": 100},
      {"description": "Software License", "quantity": 1, "unit_price": 500}
    ],
    "notes": "Thank you for your business!"
  }'
```

### Example: Record Payment via API

```bash
curl -X POST "http://localhost:5000/api/v1/invoices/1/payments" \
  -H "X-API-Key: inv_your_key" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 1500.00,
    "payment_method": "Bank Transfer",
    "reference": "TXN-12345"
  }'
```

## Webhook Events

Configure outbound webhooks to receive notifications:

- `invoice.created` - New invoice created
- `invoice.updated` - Invoice modified
- `invoice.sent` - Invoice marked as sent
- `invoice.paid` - Invoice fully paid
- `invoice.partially_paid` - Partial payment received
- `invoice.deleted` - Invoice deleted
- `customer.created` - New customer added
- `customer.updated` - Customer modified
- `customer.deleted` - Customer removed
- `product.created` - New product added
- `product.updated` - Product modified
- `product.deleted` - Product deactivated
- `payment.received` - Payment recorded

### Webhook Payload Format

```json
{
  "event": "invoice.paid",
  "timestamp": "2024-01-15T10:30:00Z",
  "webhook_id": "abc123def",
  "data": {
    "id": 1,
    "invoice_number": "INV-01001",
    "customer_name": "Acme Corp",
    "total": 1500.00,
    "status": "paid",
    ...
  }
}
```

### Webhook Headers

- `Content-Type: application/json`
- `X-Webhook-Event: invoice.paid`
- `X-Webhook-Signature: sha256_hash`
- `User-Agent: InvoiceManager-Webhook/1.0`

## Supported Currencies

- GBP (£) - British Pound
- USD ($) - US Dollar
- EUR (€) - Euro
- ZAR (R) - South African Rand
- CAD (C$) - Canadian Dollar
- AUD (A$) - Australian Dollar
- NZD (NZ$) - New Zealand Dollar
- CHF - Swiss Franc
- JPY (¥) - Japanese Yen
- INR (₹) - Indian Rupee

## File Structure

```
invoice_app/
├── app_core.py          # Database models and business logic
├── app_web.py           # Flask routes and web interface
├── api_webhooks.py      # API authentication and webhooks
├── pdf_generator.py     # PDF invoice generation
├── run.py               # Application entry point
├── requirements.txt     # Python dependencies
├── data/                # Database and uploaded files
│   ├── invoices.db      # SQLite database
│   └── invoices/        # Generated invoice files
├── static/
│   └── uploads/         # Uploaded logos
└── templates/           # HTML templates
```

## Styling

This application uses the same dark theme styling as the Pokemon Card Collection Manager, featuring:
- Dark purple/blue color scheme
- Accent colors: Red (#e94560), Yellow (#f0a500), Blue (#3b82f6), Green (#10b981)
- Space Grotesk and Outfit fonts
- Card-based UI with smooth transitions

## License

MIT License - Feel free to use and modify for your needs.
