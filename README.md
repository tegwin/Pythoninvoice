# Invoice Manager

Free, self-hosted invoicing and light accounting. Sales and purchases,
financial reports, card and Direct Debit payments, a REST API and a customer
portal. Your data stays on your server.

**[Live demo](https://pythoninvoice-demo-production.up.railway.app)** — sign in
with `demo` / `demo`. Resets nightly.

MIT licensed. No per-user fees, no account required.

---

## What's in it

**Sales** — invoices with PDF export, recurring invoices, multi-currency with
live FX rates, partial payments, credit notes, CSV import/export.

**Purchases** — suppliers, bills, expenses with receipts and approval, chart of
accounts.

**Reports** — profit & loss, balance sheet, VAT return with submission
checklist, tax summary, aged receivables and payables.

**Getting paid** — Stripe (cards, checkout links), GoCardless (Direct Debit),
SumUp, Wise. Incoming webhooks record payments automatically.

**Integrations** — full REST API with scoped keys, outgoing webhooks, SMTP or
Microsoft 365 email, customer portal.

**Team** — six roles (Owner, Administrator, Accountant, Bookkeeper, Sales,
Viewer), TOTP 2FA with backup codes.

### Not built yet

Quotes/estimates, purchase orders, full bank reconciliation (Wise transaction
matching only), customisable PDF templates (one layout, your logo and details).

---

## Requirements

- **MySQL 8.0 or MariaDB 10.6+** — SQLite is not supported; `database.py` is
  MySQL-only
- **Python 3.12+** if running without Docker
- Docker and Docker Compose for the quickest path

---

## Install with Docker (recommended)

Two commands from a clean checkout.

### 1. Clone and configure

```bash
git clone https://github.com/tegwin/Pythoninvoice.git
cd Pythoninvoice
cp .env.example .env
```

Open `.env` and set real values:

```bash
MYSQL_ROOT_PASSWORD=pick-something-long
MYSQL_DATABASE=invoice_manager
MYSQL_USER=invoice
MYSQL_PASSWORD=pick-something-else-long
SECRET_KEY=
APP_PORT=5001
```

Generate `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

`SECRET_KEY` signs session cookies. If it changes, everyone is logged out, so
set it once and keep it.

### 2. Start

```bash
docker compose up -d --build
```

First run pulls MySQL and builds the image — a couple of minutes. The app waits
for the database, applies `schema.sql` (all 51 tables), then starts gunicorn.

### 3. Open it

```
http://localhost:5001
```

Register — **the first account created becomes the Owner.**

> Port 5001, not 5000: on macOS, port 5000 is taken by AirPlay Receiver.
> Change `APP_PORT` in `.env` to move it.

### Everyday commands

```bash
docker compose logs -f app      # follow logs
docker compose restart app      # restart
docker compose down             # stop
docker compose down -v          # stop AND delete all data
```

---

## Install without Docker

### 1. Database

```bash
sudo mysql -e "CREATE DATABASE invoice_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER 'invoice'@'localhost' IDENTIFIED BY 'your-password'; GRANT ALL ON invoice_manager.* TO 'invoice'@'localhost'; FLUSH PRIVILEGES;"
```

### 2. Load the schema

```bash
mysql -uinvoice -p invoice_manager < schema.sql
```

`schema.sql` is the complete database — 51 tables, no data. Every statement is
`CREATE TABLE IF NOT EXISTS`, so it is safe to re-run.

### 3. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

A virtualenv is required on macOS — Homebrew Python refuses a plain
`pip install` (PEP 668).

### 4. Point it at the database

Create `data/db_config.json`:

```json
{
  "type": "mysql",
  "mysql_host": "127.0.0.1",
  "mysql_port": 3306,
  "mysql_user": "invoice",
  "mysql_password": "your-password",
  "mysql_database": "invoice_manager",
  "mysql_ssl": false
}
```

This file holds a live password. It is gitignored — keep it that way, and
`chmod 600` it on a server.

### 5. Run

```bash
PORT=5001 python run.py
```

`run.py` starts Flask's development server. Fine locally, **not** for a server —
use gunicorn behind nginx. Full production setup with systemd, nginx and
Let's Encrypt is in **[INSTALL.md](INSTALL.md)**.

---

## Deploying to a server

**[INSTALL.md](INSTALL.md)** covers the full production path:

- Ubuntu/Debian with systemd + gunicorn + nginx + certbot
- Docker on a VPS
- Backups and restores
- A cron job for recurring invoice generation

### Environment variables

| Variable | Required | What it does |
|---|---|---|
| `MYSQL_URL` | one of these | Full connection URL, e.g. `mysql://user:pass@host:3306/db` |
| `MYSQL_HOST` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | one of these | Individual settings, if you'd rather not use a URL |
| `SECRET_KEY` | yes | Signs session cookies. Must be stable |
| `PORT` | no | Port to bind. Defaults to 5000 |
| `DEMO_MODE` | no | `true` puts the app in read-only demo mode |
| `FOOTER_OWNER` | no | Your company name in the login footer |

A connection URL is easier on hosts like Railway, where matching five separate
variable names is error-prone.

### Recurring invoices

Nothing generates them on a schedule by itself. Add a cron job:

```cron
5 2 * * * curl -s -X POST -H "X-API-Key: YOUR_KEY" http://127.0.0.1:5001/api/v1/recurring/generate > /dev/null
```

Create the API key under **Settings → API Keys** first.

---

## Running a public demo

Set `DEMO_MODE=true`. The app then blocks anything that would reach a third
party — payment providers, outgoing email, API keys, webhooks — and shows
integration pages read-only so visitors can still see them.

`reset_demo.py` wipes the demo and reseeds it with sample companies and
invoices. Point a nightly cron at it. It refuses to run unless `DEMO_MODE` is
set, and refuses again if the database contains any account other than the demo
user, so it cannot be pointed at a real install by accident.

---

## Documentation

| File | What's in it |
|---|---|
| [INSTALL.md](INSTALL.md) | Docker, local and Linux server installs, troubleshooting |
| [FEATURES.md](FEATURES.md) | Verified feature list, and what isn't built |
| [USER_GUIDE.md](USER_GUIDE.md) | Using the app day to day |
| [API_DOCUMENTATION.md](API_DOCUMENTATION.md) | REST API reference |
| `schema.sql` | Complete database schema |

---

## Security

- Never commit `data/db_config.json` or `.env` — both are gitignored
- Run `./scan_secrets.sh` before pushing; it checks for tracked config files,
  live provider keys, literal secret defaults and hardcoded hosts
- Use HTTPS in production — the app handles payment provider keys, SMTP
  passwords and customer data
- `DEBUG` defaults to `True` in `run.py`. Do not leave that on a server

---

## Licence

MIT. Use it, change it, run it for your clients.
