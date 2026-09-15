#!/usr/bin/env python3
"""Wipe the demo database and reseed it with believable sample data.

Run nightly by a Railway cron service. Refuses to run unless DEMO_MODE is
set, so it can never be pointed at a real install by accident.

    DEMO_MODE=true python reset_demo.py
"""
import os
import random
import sys
import uuid
from datetime import date, timedelta

import mysql.connector

from bootstrap_db import resolve_config, connect, write_config

# app_core is NOT imported here on purpose: importing it runs init_database(),
# which reads data/db_config.json. Under a Railway custom start command the
# entrypoint is bypassed, so that file does not exist yet. main() writes it
# first, then imports.

DEMO_USERNAME = os.environ.get('DEMO_USERNAME', 'demo')
DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', 'demo')

# Every table is emptied. Listed explicitly rather than discovered, so a new
# table added later is a deliberate decision, not a silent survivor.
TABLES = [
    'users', 'team_members', 'company_settings', 'user_preferences',
    'customers', 'products', 'invoices', 'invoice_items', 'payments',
    'recurring_invoices', 'recurring_invoice_items', 'invoice_reminders',
    'credit_notes', 'credit_note_items', 'credit_note_applications',
    'suppliers', 'bills', 'bill_items', 'bill_payments', 'expenses',
    'chart_of_accounts', 'vat_submissions', 'currency_rates',
    'enabled_currencies', 'api_keys', 'webhooks', 'incoming_webhooks',
    'incoming_webhook_logs', 'email_templates', 'email_log',
    'customer_portal_users',
    'stripe_settings', 'stripe_payment_sessions', 'stripe_webhook_logs',
    'gocardless_settings', 'gocardless_customers', 'gocardless_payments',
    'gocardless_mandates', 'gocardless_billing_requests',
    'gocardless_webhook_logs',
    'sumup_settings', 'sumup_checkouts', 'sumup_webhook_logs',
    'wise_settings', 'wise_transactions', 'wise_credits', 'wise_transfers',
    'wise_webhook_logs',
]

COMPANIES = [
    ("Test Customer", "accounts@testcustomer.example", "London"),
    ("Northwind Traders", "billing@northwind.example", "Manchester"),
    ("Redcliffe Dental Group", "finance@redcliffedental.example", "Bristol"),
    ("Apex Legal LLP", "ap@apexlegal.example", "Leeds"),
    ("Fairhaven Property", "accounts@fairhaven.example", "Brighton"),
    ("Kestrel Engineering", "purchasing@kestreleng.example", "Sheffield"),
    ("Bluebird Travel", "invoices@bluebirdtravel.example", "Glasgow"),
    ("Morley & Sons Builders", "office@morleysons.example", "Nottingham"),
    ("Clearwater Marketing", "finance@clearwatermktg.example", "Cardiff"),
    ("Sable Financial Advisors", "ap@sablefinancial.example", "Edinburgh"),
    ("Greenfield Care Homes", "accounts@greenfieldcare.example", "Norwich"),
    ("Harbour Point Hotels", "billing@harbourpoint.example", "Plymouth"),
    ("Verity Recruitment", "finance@verityrec.example", "Birmingham"),
    ("Oakline Logistics", "invoices@oaklinelogistics.example", "Hull"),
]

PRODUCTS = [
    ("Managed IT Support", "Per-user monthly support", 38.00, "user/month", "MSP-SUP", 1),
    ("Microsoft 365 Business Premium", "Licence, billed monthly", 19.60, "licence", "M365-BP", 0),
    ("Consultancy Day Rate", "On-site or remote project work", 850.00, "day", "CONS-DAY", 1),
    ("Backup & DR", "Per-device cloud backup", 12.50, "device/month", "BKP-01", 1),
    ("Firewall Appliance", "Supplied hardware", 645.00, "unit", "HW-FW", 0),
    ("Onboarding Project", "New client setup", 1200.00, "project", "PROJ-ONB", 1),
]

ACCOUNTS = [
    ('4000', 'Sales - Services', 'revenue'),
    ('4010', 'Sales - Hardware', 'revenue'),
    ('4020', 'Sales - Licences', 'revenue'),
    ('5000', 'Cost of Sales', 'expense'),
    ('6000', 'Office Costs', 'expense'),
    ('6200', 'Travel', 'expense'),
    ('1200', 'Bank Account', 'asset'),
    ('2100', 'Accounts Payable', 'liability'),
]


def wipe(cur):
    cur.execute('SET FOREIGN_KEY_CHECKS = 0')
    for table in TABLES:
        try:
            cur.execute(f'TRUNCATE TABLE `{table}`')
        except mysql.connector.Error as e:
            if e.errno != 1146:      # table does not exist - fine
                print(f"  skipped {table}: {e}")
    cur.execute('SET FOREIGN_KEY_CHECKS = 1')


def seed(cur):
    today = date.today()

    from app_core import hash_password      # safe now: config is on disk

    cur.execute(
        "INSERT INTO users (username, password_hash, email, display_name, role, active) "
        "VALUES (?, ?, ?, ?, 'owner', 1)".replace('?', '%s'),
        (DEMO_USERNAME, hash_password(DEMO_PASSWORD),
         'demo@example.com', 'Demo User'))
    user_id = cur.lastrowid

    cur.execute(
        "INSERT INTO company_settings (user_id, company_name, address_line1, city, "
        "postal_code, country, email, default_tax_rate, default_currency, "
        "invoice_prefix, invoice_next_number, payment_terms, brand_name) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (user_id, 'Demo Managed Services Ltd', '1 Example Way', 'London',
         'EC1A 1AA', 'United Kingdom', 'accounts@example.com', 20.0, 'GBP',
         'INV', 1001, 'Payment due within 30 days', 'Demo Managed Services'))

    for code, name, acc_type in ACCOUNTS:
        cur.execute(
            "INSERT INTO chart_of_accounts (user_id, code, name, account_type, active) "
            "VALUES (%s, %s, %s, %s, 1)", (user_id, code, name, acc_type))

    product_ids = []
    for name, desc, price, unit, sku, is_service in PRODUCTS:
        cur.execute(
            "INSERT INTO products (user_id, name, description, unit_price, unit, "
            "sku, is_service, taxable, active) VALUES (%s,%s,%s,%s,%s,%s,%s,1,1)",
            (user_id, name, desc, price, unit, sku, is_service))
        product_ids.append((cur.lastrowid, name, desc, price))

    customer_ids = []
    for name, email, city in COMPANIES:
        cur.execute(
            "INSERT INTO customers (uuid, user_id, name, email, address_line1, city, "
            "country, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), user_id, name, email, '1 High Street', city,
             'United Kingdom', today - timedelta(days=random.randint(120, 400))))
        customer_ids.append(cur.lastrowid)

    # Deterministic spread so the dashboard and reports always look populated:
    # a mix of paid, sent, overdue and draft across the last few months.
    rng = random.Random(42)
    invoice_no = 1001
    for idx, customer_id in enumerate(customer_ids):
        for _ in range(rng.randint(1, 4)):
            issued = today - timedelta(days=rng.randint(0, 150))
            due = issued + timedelta(days=30)

            if due < today:
                status = rng.choice(['paid', 'paid', 'paid', 'overdue'])
            else:
                status = rng.choice(['sent', 'sent', 'paid', 'draft'])

            lines = rng.sample(product_ids, rng.randint(1, 3))
            subtotal = 0.0
            rows = []
            for pid, pname, pdesc, price in lines:
                qty = rng.choice([1, 1, 2, 3, 5, 10])
                line_total = round(price * qty, 2)
                subtotal += line_total
                rows.append((pid, pdesc or pname, qty, price, line_total))

            subtotal = round(subtotal, 2)
            tax = round(subtotal * 0.20, 2)
            total = round(subtotal + tax, 2)
            paid = total if status == 'paid' else 0.0

            cur.execute(
                "INSERT INTO invoices (user_id, customer_id, invoice_number, status, "
                "issue_date, due_date, currency, tax_rate, subtotal, tax_amount, "
                "total, amount_paid, exchange_rate, base_currency, base_total, "
                "created_at, paid_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,'GBP',20,%s,%s,%s,%s,1,'GBP',%s,%s,%s)",
                (user_id, customer_id, f'INV-{invoice_no:05d}', status, issued, due,
                 subtotal, tax, total, paid, total, issued,
                 due - timedelta(days=rng.randint(1, 20)) if status == 'paid' else None))
            invoice_id = cur.lastrowid
            invoice_no += 1

            for sort_order, (pid, desc, qty, price, line_total) in enumerate(rows, 1):
                cur.execute(
                    "INSERT INTO invoice_items (invoice_id, product_id, description, "
                    "quantity, unit_price, tax_rate, line_total, sort_order) "
                    "VALUES (%s,%s,%s,%s,%s,20,%s,%s)",
                    (invoice_id, pid, desc, qty, price, line_total, sort_order))

            if status == 'paid':
                cur.execute(
                    "INSERT INTO payments (invoice_id, amount, payment_date, "
                    "payment_method, reference, created_via) "
                    "VALUES (%s,%s,%s,'Bank Transfer',%s,'demo-seed')",
                    (invoice_id, total, due - timedelta(days=rng.randint(1, 20)),
                     f'FT{rng.randint(100000, 999999)}'))

    # A little Accounts Payable so those screens and the P&L aren't empty.
    for sname, scontact in [('Ingram Micro', 'Sales Desk'),
                            ('Pax8', 'Account Manager'),
                            ('Crown Office Supplies', 'Orders')]:
        cur.execute(
            "INSERT INTO suppliers (user_id, name, contact_name, email, country, "
            "is_active) VALUES (%s,%s,%s,%s,'United Kingdom',1)",
            (user_id, sname, scontact,
             f"accounts@{sname.split()[0].lower()}.example"))

    for desc, cat, amount in [('Monthly rail travel', 'Travel', 210.40),
                              ('Office broadband', 'Office Costs', 65.00),
                              ('Team lunch', 'Office Costs', 88.25),
                              ('Cloud hosting', 'Cost of Sales', 412.90)]:
        net = round(amount / 1.2, 2)
        cur.execute(
            "INSERT INTO expenses (user_id, expense_date, description, category, "
            "amount, tax_rate, tax_amount, net_amount, currency, status) "
            "VALUES (%s,%s,%s,%s,%s,20,%s,%s,'GBP','approved')",
            (user_id, today - timedelta(days=rng.randint(1, 60)), desc, cat,
             amount, round(amount - net, 2), net))

    return invoice_no - 1001


def looks_like_live(cur):
    """Return the name of a non-demo account, if the database has one.

    DEMO_MODE only proves which *service* this is, not which *database* it is
    pointed at - a mistyped MYSQL_URL on the cron service would otherwise wipe
    live. A demo database only ever contains the demo account, so any other
    user means we are somewhere we should not be.
    """
    try:
        cur.execute("SELECT username FROM users WHERE username <> %s LIMIT 1",
                    (DEMO_USERNAME,))
        row = cur.fetchone()
    except mysql.connector.Error:
        return None          # no users table yet - a fresh database, fine
    if not row:
        return None
    return row['username'] if isinstance(row, dict) else row[0]


def main():
    if os.environ.get('DEMO_MODE', '').lower() not in ('1', 'true', 'yes'):
        sys.exit("Refusing to run: DEMO_MODE is not set. This wipes every table.")

    cfg = resolve_config()
    # Must happen before anything imports app_core.
    write_config(cfg)
    print(f"Resetting demo data in {cfg['mysql_host']}/{cfg['mysql_database']}")
    conn = connect(cfg, timeout=30)
    cur = conn.cursor(dictionary=True)

    intruder = looks_like_live(cur)
    if intruder and os.environ.get('DEMO_RESET_FORCE', '').lower() not in ('1', 'true', 'yes'):
        sys.exit(
            f"Refusing to run: this database contains the account '{intruder}', "
            f"which is not the demo account '{DEMO_USERNAME}'.\n"
            f"  This looks like a real install, not the demo. Check MYSQL_URL on "
            f"this service.\n"
            f"  Set DEMO_RESET_FORCE=true only if you are certain."
        )

    wipe(cur)
    count = seed(cur)
    conn.commit()
    cur.close()
    conn.close()
    print(f"Demo reset: {len(COMPANIES)} customers, {count} invoices, "
          f"login {DEMO_USERNAME}/{DEMO_PASSWORD}")


if __name__ == '__main__':
    main()
