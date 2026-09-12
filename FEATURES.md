# Invoice Manager — Feature Summary (verified 2026-08-01)

Checked against the source, not the old README. Every ✅ below was confirmed by
finding the route, the module and the database table; the app was also run
against a clean MySQL 8.0 database and driven through the main flows.

Corrections to the previous summary are marked **⚠️**.

## Core invoicing

- ✅ Create, edit, delete invoices
- ✅ PDF generation and an HTML print view
- ⚠️ **Not "customisable templates"** — `pdf_generator.py` has one fixed layout
  with hardcoded colours (`#e94560` / `#1a1a35` / `#f0a500`). You can change the
  logo and company details, nothing else.
- ✅ Invoice numbering with prefixes (`INV-01001` style)
- ✅ Multi-currency with exchange rates, base-currency totals
- ✅ Tax rates and calculations
- ✅ Line items, optionally linked to products
- ✅ Payment tracking, partial and full
- ✅ Statuses: draft, sent, paid, partial, overdue, cancelled

## Customers & products

- ✅ Customer management with addresses
- ✅ Per-customer email preferences
- ✅ Product catalogue with SKUs
- ✅ Billing terms
- ✅ Bulk import/export (CSV) for customers, products, invoices, suppliers

## Financial management

- ✅ Chart of Accounts with account types
- ✅ COA on line items, optional or mandatory (`company_settings.coa_mandatory`)
- ✅ Multi-currency with automatic rate updates
- ✅ Payment recording with methods and references

## Recurring & automation

- ✅ Recurring invoices, auto-generation on schedule
- ⚠️ **Frequencies are weekly, bi-weekly, monthly, quarterly, bi-annually,
  annually** — there is no daily option, and "bi-annually" was missing from the
  old list (`recurring_invoices.py:151`).
- ⚠️ Auto-generation is **not self-scheduling**. Something external must call
  `POST /api/v1/recurring/generate` — see the cron job in INSTALL.md.
- ✅ Email reminders

## Payment integrations

- ✅ Stripe — card payments, checkout links, webhooks
- ✅ GoCardless — Direct Debit, mandates, webhooks
- ✅ **SumUp** — was missing from the old summary
- ✅ Wise — incoming transaction matching
- ✅ Incoming webhooks: generic, Stripe, PayPal, GoCardless, Wise, Mollie, Square
- ✅ Automatic payment recording via webhooks

## Team & security

- ✅ Multi-user with roles
- ⚠️ **Six roles, not four**: Owner, Administrator, Accountant, Bookkeeper,
  Sales, Viewer. There is no "Member" role (`team_management.py:12`).
- ✅ Team management and invitations
- ✅ Two-factor authentication (TOTP) with backup codes

## API & integrations

- ✅ REST API covering customers, products, invoices, payments, recurring,
  suppliers, bills, expenses
- ✅ Outgoing webhooks on invoice/customer/product/payment events
- ✅ Incoming webhooks for payment events

## Email

- ✅ SMTP configuration
- ✅ **Microsoft Graph / M365 sending** — was missing from the old summary
  (`graph_email.py`)
- ✅ Customisable email templates
- ✅ Send invoices and reminders

## Other

- ✅ Custom branding (logo, company name, footer text)
- ✅ Dashboard with statistics
- ⚠️ **SQLite is gone.** `database.py` is MySQL/MariaDB only and forces
  `type = 'mysql'` whatever the config says. The old "SQLite or MySQL" claim is
  no longer true.
- ✅ Public roadmap app (separate Flask app under `roadmap/`)
- ✅ **Customer portal** — was missing from the old summary: portal logins,
  customers view their own invoices, admin impersonation
  (`customer_portal.py`, `portal_routes.py`)

---

## The "what's left for full accounting" list is largely done

| Feature | Old status | Actual |
|---|---|---|
| Expenses | To do | ✅ Built — `expenses.py` routes, approve/reject flow, receipts |
| Credit Notes | To do | ✅ Built — issue, apply to invoice, line items |
| Suppliers/Vendors | To do | ✅ Built — full CRUD, CSV import/export |
| Bills | To do | ✅ Built — bills, line items, payments, approval, attachments |
| Profit & Loss | To do | ✅ Built — `/reports/profit-loss` |
| Balance Sheet | To do | ✅ Built — `/reports/balance-sheet` |
| VAT/Tax Reports | To do | ✅ Built — `/reports/vat`, `/reports/tax-summary`, VAT PDF, submission checklist, `vat_submissions` table |
| Bank Reconciliation | To do | 🟡 Partial — Wise credits can be matched to invoices; no general bank feed or reconciliation screen |
| Quotes/Estimates | To do | ❌ Still absent — no route, template or table |
| Purchase Orders | To do | ❌ Still absent |

Also built but not on either list: **aged receivables** and **aged payables**
reports.

So the accurate summary is: this is no longer just Accounts Receivable. Both AR
and AP are built, along with the core financial reports. What genuinely remains
is **quotes/estimates**, **purchase orders**, and **real bank reconciliation**.
