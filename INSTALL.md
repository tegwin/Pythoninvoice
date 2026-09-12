# Invoice Manager — Installation Guide

Covers three ways to install: **Docker** (easiest, recommended), **local dev**
on macOS or Windows, and **a Linux server** for production.

Everything below was tested end to end against MySQL 8.0 on 2026-08-01:
schema loaded, app booted, user registered, customer/product/supplier/
invoice/expense/API-key created, PDF generated.

---

## Before you start

**SQLite is not supported.** `database.py` forces `type = 'mysql'` regardless of
config, so you need MySQL or MariaDB.

Nothing else to do — a fresh install comes up clean either way.

---

## Option 1 — Docker (recommended)

Needs Docker Desktop (macOS/Windows) or Docker Engine + Compose plugin (Linux).

### 1. Create your `.env`

```bash
cp .env.example .env
```

Edit `.env` and set real values. Generate the secret key with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

`SECRET_KEY` signs session cookies — if it changes, everyone is logged out.

### 2. Start it

```bash
docker compose up -d --build
```

First run takes a couple of minutes (pulls MySQL, builds the image). The app
container waits for MySQL to be healthy, writes `data/db_config.json` from the
env vars, applies `schema.sql`, then starts gunicorn.

### 3. Open it

```
http://localhost:5001
```

Register the first account — it becomes the Owner.

> Port 5001, not 5000: on macOS port 5000 is taken by AirPlay Receiver and by
> Docker itself. Change `APP_PORT` in `.env` to move it.

### Everyday commands

```bash
docker compose logs -f app
```

```bash
docker compose restart app
```

```bash
docker compose down
```

To wipe the database and start clean (destroys all data):

```bash
docker compose down -v
```

### Backups

```bash
docker compose exec db mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" invoice_manager > backup-$(date +%F).sql
```

Restore:

```bash
docker compose exec -T db mysql -uroot -p"$MYSQL_ROOT_PASSWORD" invoice_manager < backup-2026-08-01.sql
```

Uploaded logos and avatars live in the `app_uploads` volume, not in the SQL
dump — back that up separately if you care about it:

```bash
docker run --rm -v pythoninvoice_app_uploads:/u -v "$PWD":/out alpine tar czf /out/uploads.tar.gz -C /u .
```

---

## Option 2 — Local development (macOS / Windows)

### 1. Install MySQL

macOS:

```bash
brew install mysql && brew services start mysql
```

Windows: install MySQL Community Server, or just run the DB in Docker:

```bash
docker run -d --name invoice-db -e MYSQL_ROOT_PASSWORD=changeme -p 3306:3306 mysql:8.0
```

### 2. Create the database and a user

```bash
mysql -uroot -p -e "CREATE DATABASE invoice_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER 'invoice'@'localhost' IDENTIFIED BY 'changeme'; GRANT ALL ON invoice_manager.* TO 'invoice'@'localhost'; FLUSH PRIVILEGES;"
```

### 3. Load the schema

```bash
mysql -uinvoice -p invoice_manager < schema.sql
```

### 4. Create a virtualenv

Homebrew Python is externally managed (PEP 668), so a venv is required —
a plain `pip install` will fail.

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

On Windows use `.venv\Scripts\activate` instead.

```bash
pip install -r requirements.txt
```

### 5. Point the app at the database

Create `data/db_config.json`:

```json
{
  "type": "mysql",
  "mysql_host": "127.0.0.1",
  "mysql_port": 3306,
  "mysql_user": "invoice",
  "mysql_password": "changeme",
  "mysql_database": "invoice_manager",
  "mysql_ssl": false
}
```

This file holds a live password — make sure it is gitignored.

### 6. Run it

```bash
PORT=5001 python run.py
```

Then open `http://localhost:5001` and register.

`run.py` starts the Flask development server. That is fine locally, but do not
use it on a server — see below.

---

## Option 3 — Linux server (production)

Ubuntu 22.04/24.04 or Debian 12. Two approaches: Docker (simplest — use
Option 1 on the server and skip to the nginx section), or systemd + gunicorn
as described here.

### 1. System packages

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip mysql-server nginx
```

### 2. Database

```bash
sudo mysql -e "CREATE DATABASE invoice_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER 'invoice'@'localhost' IDENTIFIED BY 'STRONG-PASSWORD-HERE'; GRANT ALL ON invoice_manager.* TO 'invoice'@'localhost'; FLUSH PRIVILEGES;"
```

### 3. Deploy the code

```bash
sudo mkdir -p /opt/invoice-manager && sudo chown $USER:$USER /opt/invoice-manager
```

Copy the application into `/opt/invoice-manager`, then:

```bash
cd /opt/invoice-manager && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt gunicorn
```

### 4. Load the schema

```bash
mysql -uinvoice -p invoice_manager < /opt/invoice-manager/schema.sql
```

### 5. Configure

Create `/opt/invoice-manager/data/db_config.json` exactly as in Option 2 step 5,
but with the server's password. Lock it down — it contains a live credential:

```bash
chmod 600 /opt/invoice-manager/data/db_config.json
```

### 6. systemd service

Create `/etc/systemd/system/invoice-manager.service`:

```ini
[Unit]
Description=Invoice Manager
After=network.target mysql.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/invoice-manager
# Stable secret, or every restart logs all users out.
Environment="SECRET_KEY=REPLACE-WITH-64-HEX-CHARS"
ExecStart=/opt/invoice-manager/.venv/bin/gunicorn \
  --bind 127.0.0.1:5001 \
  --workers 2 --threads 4 --timeout 120 \
  app_web:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /opt/invoice-manager
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now invoice-manager
```

```bash
sudo systemctl status invoice-manager
```

### 7. nginx in front

Create `/etc/nginx/sites-available/invoice-manager`:

```nginx
server {
    listen 80;
    server_name invoices.example.com;

    # PDF and CSV uploads can exceed the 1 MB default.
    client_max_body_size 20M;

    location / {
        proxy_pass         http://127.0.0.1:5001;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/invoice-manager /etc/nginx/sites-enabled/ && sudo nginx -t && sudo systemctl reload nginx
```

### 8. HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d invoices.example.com
```

TLS is not optional here — the app handles Stripe and GoCardless keys, SMTP
passwords and customer data.

### 9. Recurring invoices

Nothing generates recurring invoices on a schedule by itself. Add a cron job:

```bash
sudo crontab -e
```

```cron
5 2 * * * curl -s -X POST -H "X-API-Key: YOUR_KEY" http://127.0.0.1:5001/api/v1/recurring/generate > /dev/null
```

Create the API key under **Settings → API Keys** first.

---

## The SQL file

`schema.sql` is the complete database — **51 tables**, generated from the
application source and verified by loading it into MySQL 8.0 and running the
app against it. Every statement is `CREATE TABLE IF NOT EXISTS`, so it is safe
to re-run on an existing database.

```bash
mysql -uinvoice -p invoice_manager < schema.sql
```

It creates the database itself if missing, so this also works:

```bash
mysql -uroot -p < schema.sql
```

### Why load it rather than letting the app self-create

The app builds tables lazily — each module creates its own the first time you
visit that part of the UI. Loading `schema.sql` up front creates all 51 at once,
which keeps the logs clean and means backups cover everything from day one.

### What is in it

| Area | Tables |
|---|---|
| Core | `users`, `team_members`, `company_settings`, `user_preferences` |
| Sales | `customers`, `products`, `invoices`, `invoice_items`, `payments`, `recurring_invoices`, `recurring_invoice_items`, `invoice_reminders`, `credit_notes`, `credit_note_items`, `credit_note_applications` |
| Purchases | `suppliers`, `bills`, `bill_items`, `bill_payments`, `expenses` |
| Accounting | `chart_of_accounts`, `vat_submissions`, `currency_rates`, `enabled_currencies` |
| Payments | `stripe_settings`, `stripe_payment_sessions`, `stripe_webhook_logs`, `gocardless_*` (6), `sumup_settings`, `sumup_checkouts`, `sumup_webhook_logs`, `wise_*` (5) |
| Integration | `api_keys`, `webhooks`, `incoming_webhooks`, `incoming_webhook_logs` |
| Email | `email_templates`, `email_log` |
| Portal | `customer_portal_users` |
| Roadmap app | `roadmap_phases`, `roadmap_features`, `roadmap_requests` |

---

## Troubleshooting

**`Can't connect to MySQL server`** — check the host. From inside the app
container the host is `db`, not `localhost`. From the host machine to a
Dockerised MySQL it is `127.0.0.1` on the published port.

**Everyone logged out after a restart** — `SECRET_KEY` is not set, so
`app_web.py:57` falls back to `os.urandom(24)`, which changes each boot.

**Port 5000 already in use on macOS** — AirPlay Receiver and Docker both grab
it. Use 5001.

**`externally-managed-environment` on `pip install`** — Homebrew Python needs a
venv; see Option 2 step 4.

**PDFs fail** — `reportlab` did not install. Inside Docker this is handled;
locally on Linux you may need `sudo apt install libjpeg-dev zlib1g-dev`.

---

## Security checklist before going live

- [ ] `data/db_config.json` is gitignored and `chmod 600` — it stores the DB password in plain text
- [ ] `.env` is gitignored
- [ ] `SECRET_KEY` set to a long random value, and stable across restarts
- [ ] HTTPS enabled
- [ ] MySQL not exposed to the internet (the compose file keeps it unpublished)
- [ ] `DEBUG` not set to `True` — `run.py` defaults it to `True`, which is wrong for a server
- [ ] Automated `mysqldump` backups
