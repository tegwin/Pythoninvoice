# Installation

This guide covers how to install and set up Invoice Manager on your system.

## System Requirements

- **Python**: 3.8 or higher
- **Operating System**: Windows, macOS, or Linux
- **Database**: SQLite (default) or MySQL/MariaDB
- **Memory**: 512MB RAM minimum
- **Storage**: 100MB for application + database storage

## Quick Installation

### 1. Download the Application

Download the latest version from your account portal or extract the provided ZIP file.

### 2. Install Dependencies

Open a terminal and navigate to the application directory:

```bash
cd invoice_app
pip install -r requirements.txt
```

### 3. Run the Application

```bash
python run.py
```

The application will start on `http://localhost:5000`

## First-Time Setup

1. Open your browser and navigate to `http://localhost:5000`
2. You'll be prompted to create an admin account
3. Fill in your username, email, and password
4. Click **Register** to create your account

!!! tip "Secure Your Password"
    Choose a strong password with at least 8 characters, including numbers and special characters.

## Configuration Options

### Environment Variables

You can configure the application using environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask secret key for sessions | Random |
| `DATABASE_URL` | Database connection string | SQLite |
| `PORT` | Port to run on | 5000 |
| `DEBUG` | Enable debug mode | False |

### Example Configuration

```bash
export SECRET_KEY="your-secure-secret-key"
export PORT=8080
python run.py
```

## Production Deployment

For production environments, we recommend using a proper WSGI server:

### Using Gunicorn (Linux/macOS)

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app_web:app
```

### Using Waitress (Windows)

```bash
pip install waitress
waitress-serve --port=5000 app_web:app
```

## Database Options

### SQLite (Default)

SQLite is used by default and requires no additional configuration. The database file is stored in `data/invoices.db`.

### MySQL/MariaDB

1. Install the MySQL connector:
```bash
pip install mysql-connector-python
```

2. Go to **Settings → Database**
3. Enter your MySQL connection details
4. Click **Migrate Data** to transfer existing data

!!! warning "Backup First"
    Always backup your data before migrating to a new database.

## Updating

To update to a new version:

1. Backup your `data` folder
2. Extract the new version
3. Copy your `data` folder to the new installation
4. Run the migration script:
```bash
python migrate_db.py
```

## Troubleshooting

### Common Issues

**Port already in use**
```bash
# Change the port
python run.py --port 8080
```

**Database locked**
```
Make sure no other instance of the application is running.
```

**Module not found**
```bash
pip install -r requirements.txt
```

## Next Steps

- [Quick Start Guide](quick-start.md) - Create your first invoice
- [Company Settings](../settings/company.md) - Configure your business details
- [Team Management](../features/team-management.md) - Add team members
