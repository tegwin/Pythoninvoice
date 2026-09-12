# Roadmap Manager

A standalone Flask application for displaying your product roadmap publicly.
Host this at `roadmap.yourdomain.com` for your SaaS customers to view.

## Features

- **Public Roadmap View** - Anyone can see your product roadmap
- **Feature Requests** - Users can submit feature suggestions
- **Voting** - Users can vote on features they want
- **Admin Panel** - Password-protected admin for YOU (the vendor) only
- **API Endpoint** - JSON API for integration

## Quick Start

### 1. Install Dependencies

```bash
pip install flask
```

### 2. Set Environment Variables

```bash
# Required: Set a secure admin password
export ROADMAP_ADMIN_PASSWORD="your_secure_password_here"

# Optional: Set a secret key for sessions
export ROADMAP_SECRET_KEY="your_secret_key_here"
```

### 3. Run the Application

```bash
python app.py
```

The app runs on `http://localhost:5001`

## URLs

| URL | Description | Access |
|-----|-------------|--------|
| `/` | Public roadmap view | Everyone |
| `/request` | Submit feature request | Everyone |
| `/admin/login` | Admin login | Vendor only |
| `/admin` | Admin dashboard | Vendor only |
| `/api/roadmap` | JSON API | Everyone |

## Admin Access

The admin panel is password-protected. Only YOU (the software vendor) should know the password.

1. Go to `/admin/login`
2. Enter your admin password
3. Manage phases, features, and review requests

**Important:** Set `ROADMAP_ADMIN_PASSWORD` environment variable in production!

## Deployment

### For Production (e.g., on your server)

1. Set environment variables:
```bash
export ROADMAP_ADMIN_PASSWORD="your_very_secure_password"
export ROADMAP_SECRET_KEY="random_secret_key_here"
```

2. Run with Gunicorn:
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5001 app:app
```

3. Set up nginx to proxy to port 5001 and point `roadmap.yourdomain.com` to it.

### Integration with Invoice Manager

In your Invoice Manager's About page, the links point to:
- `https://roadmap.sondelaconsulting.com` - Your hosted roadmap
- `https://docs.sondelaconsulting.com` - Your hosted documentation

When you update the roadmap here, all your SaaS customers see it instantly!

## API

Get roadmap data as JSON:

```bash
curl https://roadmap.yourdomain.com/api/roadmap
```

## File Structure

```
roadmap_app/
├── app.py              # Main application
├── data/
│   └── roadmap.db      # SQLite database (auto-created)
├── templates/
│   ├── base.html
│   ├── public_roadmap.html
│   ├── feature_request.html
│   ├── admin_login.html
│   ├── admin_dashboard.html
│   ├── admin_phases.html
│   ├── admin_features.html
│   └── admin_requests.html
└── README.md
```

## License

Copyright © 2026 Sondela Consulting Ltd. All rights reserved.
