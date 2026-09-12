# Invoice Manager User Guide

Welcome to Invoice Manager - a complete invoicing solution for small businesses and freelancers.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Dashboard](#dashboard)
3. [Managing Customers](#managing-customers)
4. [Managing Products & Services](#managing-products--services)
5. [Creating Invoices](#creating-invoices)
6. [Recording Payments](#recording-payments)
7. [Email Integration](#email-integration)
8. [Import & Export](#import--export)
9. [Team Management](#team-management)
10. [Branding & Customization](#branding--customization)
11. [Tax Configuration](#tax-configuration)
12. [Database Options](#database-options)
13. [API Integration](#api-integration)
14. [User Profile & Security](#user-profile--security)
15. [Keyboard Shortcuts](#keyboard-shortcuts)

---

## Getting Started

### First-Time Setup

1. **Access the Application**: Open your browser and navigate to the Invoice Manager URL
2. **Login**: Enter your username and password
3. **Configure Settings**: Go to **Settings** to set up your company information
4. **Add Your Logo**: Upload your company logo for professional invoices
5. **Set Tax Rates**: Configure your default tax rates
6. **Add Customers**: Create your customer database
7. **Create Products**: Set up your products and services catalog
8. **Start Invoicing**: Create your first invoice!

### Navigation

The main navigation bar provides quick access to:
- **Dashboard** - Overview and statistics
- **Invoices** - Create and manage invoices
- **Customers** - Customer database
- **Products** - Products and services catalog
- **Settings** - Configuration options
- **Help** - Documentation and support

---

## Dashboard

The dashboard provides a real-time overview of your business:

### Statistics Cards
- **Total Revenue** - All-time invoice total
- **Outstanding** - Unpaid invoice amounts
- **Paid This Month** - Payments received this month
- **Total Invoices** - Number of invoices created

### Recent Invoices
View your most recent invoices with status filters:
- **All** - Show all invoices
- **Draft** - Unpublished invoices
- **Sent** - Invoices sent to customers
- **Paid** - Fully paid invoices
- **Overdue** - Past due date invoices

### Sticky Filters
Filter selections are remembered between sessions. Click "All" to clear filters.

---

## Managing Customers

### Adding a Customer

1. Go to **Customers** → **Add Customer**
2. Enter customer details:
   - **Name** (required)
   - **Email** - For sending invoices
   - **Phone** - Contact number
   - **Address** - Full billing address
   - **Tax Number** - VAT/Tax ID
3. Set custom options:
   - **Custom Tax Rate** - Override default tax
   - **Custom Currency** - Override default currency
4. Click **Create Customer**

### Customer Tax Rates

Each customer can have a custom tax rate:
- Leave blank to use your default rate
- Set to 0 for tax-exempt customers
- Choose from your configured tax rates dropdown

### Bulk Operations

Go to **Customers** → **Bulk Edit** to:
- Update multiple customers at once
- Change country, tax rate, or currency in bulk
- Delete multiple customers

### Import/Export Customers

**Export**: Click **Export** to download all customers as CSV

**Import**: Click **Import** to upload customers from CSV
- Required column: `name`
- Optional: `email`, `phone`, `address_line1`, `city`, `country`, etc.
- Check "Update existing" to update records with matching emails

---

## Managing Products & Services

### Adding a Product

1. Go to **Products** → **Add Product/Service**
2. Enter product details:
   - **Name** (required)
   - **Description** - Shown on invoices
   - **SKU** - Product code for inventory
   - **Unit Price** - Default price
   - **Unit** - hour, piece, license, etc.
3. Set options:
   - **Is Service** - Mark as service vs product
   - **Taxable** - Whether tax applies
4. Click **Create Product**

### Import/Export Products

**Export**: Download all products as CSV

**Import**: Upload products from CSV
- Required: `name`, `unit_price`
- Optional: `description`, `sku`, `unit`, `is_service`, `taxable`

---

## Creating Invoices

### New Invoice

1. Go to **Invoices** → **Create Invoice**
2. Select a **Customer** (or leave blank)
3. Set invoice details:
   - **Currency** - GBP, USD, EUR, etc.
   - **Tax Rate** - Select from your configured rates
   - **Issue Date** - Invoice date
   - **Due Date** - Payment due date
4. Add line items:
   - Select from products or enter custom items
   - Adjust quantity and price as needed
   - Add multiple items
5. Add **Notes** and **Payment Terms**
6. Click **Create Invoice**

### Invoice Statuses

| Status | Description |
|--------|-------------|
| Draft | Not yet finalized |
| Sent | Sent to customer |
| Partial | Partially paid |
| Paid | Fully paid |
| Overdue | Past due date |
| Cancelled | Voided invoice |

### Invoice Actions

From the invoice detail page:
- **Edit** - Modify invoice details
- **Download PDF** - Generate PDF document
- **Send Email** - Email to customer (auto-marks as Sent)
- **Record Payment** - Add a payment
- **Duplicate** - Create a copy

### Bulk Invoice Operations

Go to **Invoices** → **Bulk Edit** to:
- Change status of multiple invoices
- Delete multiple invoices
- Mark multiple as sent/paid

---

## Recording Payments

### Adding a Payment

1. View an invoice
2. Click **Record Payment**
3. Enter payment details:
   - **Amount** - Payment amount
   - **Payment Method** - Bank Transfer, Card, Cash, etc.
   - **Reference** - Transaction ID
   - **Notes** - Additional information
4. Click **Record Payment**

### Payment Status Updates

- Partial payment → Invoice marked as "Partial"
- Full payment → Invoice marked as "Paid"
- Payments are tracked with timestamps

### External Payment Webhooks

Receive payment notifications from:
- Stripe
- PayPal
- GoCardless
- Other payment processors

Configure via API - see API Documentation.

---

## Email Integration

### Setting Up Email

1. Go to **Settings** → **Email Settings**
2. Configure SMTP:
   - **SMTP Host** - e.g., smtp.gmail.com
   - **SMTP Port** - Usually 587
   - **Username** - Your email address
   - **Password** - App password (not main password)
   - **From Email** - Sender address
3. Test your configuration
4. Save settings

### Email Templates

Customize email content for:
- **Invoice Sent** - When sending invoices
- **Payment Received** - Thank you emails
- **Payment Reminder** - Overdue notices

Use placeholders:
- `{invoice_number}` - Invoice number
- `{customer_name}` - Customer name
- `{total}` - Invoice total
- `{due_date}` - Due date

### Sending Invoices

1. View an invoice
2. Click **Send Email**
3. Invoice PDF is attached automatically
4. Invoice status changes to "Sent"

---

## Import & Export

### CSV Import

Import data from CSV files:

**Customers**: Name, email, phone, address fields
**Products**: Name, price, SKU, description
**Invoices**: Customer, items (as JSON), dates, status

### CSV Export

Export data for:
- Backup purposes
- Reporting in Excel
- Migration to other systems

### API Bulk Import

For large imports, use the API:
```
POST /api/v1/customers/bulk
POST /api/v1/products/bulk
POST /api/v1/invoices/bulk
```

See API Documentation for details.

---

## Team Management

### User Roles

| Role | Permissions |
|------|-------------|
| **Owner** | Full access to everything |
| **Admin** | Full access including team management |
| **Accountant** | Invoices, payments, customers, reports |
| **Bookkeeper** | View-only access to all data |
| **Sales** | Create invoices and manage customers |
| **Viewer** | Read-only access |

### Adding Team Members

1. Go to **Settings** → **Team Management**
2. Click **Add Team Member**
3. Enter:
   - Username
   - Email
   - Password
   - Role
4. Share login credentials with team member

### Managing Team Members

- **Change Role** - Update permissions
- **Reset Password** - Set new password
- **Deactivate** - Suspend access
- **Delete** - Remove permanently

### Data Access

Team members access the owner's data:
- See all invoices, customers, products
- Actions limited by role permissions
- API keys are shared across the team

---

## Branding & Customization

### Brand Settings

Go to **Settings** → **Branding**:

**Navigation Bar:**
- **Brand Name** - Custom name (replaces "Invoice Manager")
- **Brand Logo** - Your company logo
- **Show Brand Name** - Toggle visibility
- **Show Brand Logo** - Toggle visibility

**Footer:**
- **Show "Powered by"** - Simple footer option
- When disabled: Full copyright and support info

### Company Information

Configure for invoices:
- Company name and address
- Phone, email, website
- Company logo (for PDF invoices)
- Bank details / payment instructions

### Invoice Appearance

Invoices include:
- Your company logo and details
- Customer information
- Line items with descriptions
- Tax breakdown
- Payment terms and bank details
- Professional stamps: PAID, CANCELLED, OVERDUE

---

## Tax Configuration

### Setting Up Tax Rates

1. Go to **Settings**
2. Find **Available Tax Rates**
3. Enter comma-separated rates: `0,5,15,20,25`
4. **0** creates a "No Tax" option
5. Select your **Default Tax Rate**

### Using Tax Rates

**On Invoices:**
- Select tax rate from dropdown
- Applies to all line items

**Per Customer:**
- Set custom tax rate for customer
- Overrides default on their invoices

**Tax-Exempt Customers:**
- Set customer tax rate to 0 (No Tax)
- All their invoices are tax-free

---

## Database Options

### SQLite (Default)

- Built-in, no setup required
- Perfect for single-user or small teams
- Data stored in `data/invoices.db`

### MySQL/MariaDB

For larger installations:

1. Go to **Settings** → **Database**
2. Select **MySQL/MariaDB**
3. Enter connection details:
   - Host, Port, Database
   - Username, Password
4. Click **Test Connection**
5. Check **Migrate existing data** if needed
6. Save and restart application

---

## API Integration

### API Keys

1. Go to **Settings** → **API Keys**
2. Click **Create API Key**
3. Set permissions:
   - **Read** - View data
   - **Write** - Create/update/delete
4. Copy and save the key (shown once only)

### Webhooks

Receive notifications when events occur:

1. Go to **Settings** → **Webhooks**
2. Click **Add Webhook**
3. Configure:
   - **URL** - Your endpoint
   - **Events** - What to notify
   - **Secret** - For verification
4. Test and activate

### API Endpoints

Full REST API available:
- Customers CRUD
- Products CRUD
- Invoices CRUD
- Payments
- Bulk imports

See **Help** → **API Documentation**

---

## User Profile & Security

### Profile Settings

Click your username → **My Profile**:
- Update display name
- Change email and phone
- Upload avatar
- Set timezone

### Two-Factor Authentication

Enable 2FA for enhanced security:

1. Go to **Profile** → **Two-Factor Authentication**
2. Scan QR code with authenticator app:
   - Google Authenticator
   - Authy
   - Microsoft Authenticator
3. Enter verification code
4. Save backup codes securely

### Backup Codes

- 10 one-time use codes
- Use if you lose your authenticator
- Regenerate codes if needed
- Store securely offline

### Change Password

1. Go to **Profile** → **Change Password**
2. Enter current password
3. Enter new password (twice)
4. Click **Update Password**

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `/` | Focus search |
| `n` | New invoice (from invoices page) |
| `Esc` | Close modal/dropdown |

---

## Tips & Best Practices

### Invoice Numbering

- Set a prefix in Settings (e.g., "INV")
- Numbers auto-increment
- Keep consistent for accounting

### Customer Management

- Always include email for sending invoices
- Set custom tax rates for exempt customers
- Use notes for internal reminders

### Product Catalog

- Create products for frequently used items
- Set accurate default prices
- Use SKUs for inventory tracking

### Regular Backups

- Export data regularly
- Use MySQL for automatic backups
- Keep CSV exports for records

### Team Security

- Use role-based access
- Enable 2FA for all users
- Review team access regularly

---

## Troubleshooting

### Login Issues

- Clear browser cache
- Check username/password
- Try password reset

### Email Not Sending

- Verify SMTP settings
- Use app-specific password
- Check spam folder

### PDF Generation

- Ensure fonts are installed
- Check server memory
- Review error logs

### Database Errors

- Run migration script
- Check file permissions
- Verify MySQL connection

---

## Getting Help

**Documentation**: Help → API Documentation

**Support**: helpdesk@sondelaconsulting.com

---

**Copyright © 2026 Sondela Consulting Limited. All rights reserved.**
