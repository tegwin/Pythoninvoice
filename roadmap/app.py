"""
Roadmap Manager - Standalone roadmap application
Host this at roadmap.yourdomain.com for public viewing.
Admin panel is password-protected for vendor-only access.
Copyright (c) 2026 Sondela Consulting Ltd.
"""

import os
import json
import sqlite3
import hashlib
import secrets
from datetime import datetime
from functools import wraps
from contextlib import contextmanager
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.secret_key = os.environ.get('ROADMAP_SECRET_KEY', secrets.token_hex(32))

# Every POST here is a browser form (the only API route is read-only), so
# blanket CSRF protection needs no exemptions.
csrf = CSRFProtect(app)

# Configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DB_PATH = os.path.join(DATA_DIR, 'roadmap.db')
os.makedirs(DATA_DIR, exist_ok=True)

# App Configuration - set these per deployment. No company details are baked
# in: this app gets handed to other MSPs, and secret scanners flag a company
# domain sitting next to the word "password".
APP_CONFIG = {
    'app_name': os.environ.get('ROADMAP_APP_NAME', 'Invoice Manager'),
    'company_name': os.environ.get('ROADMAP_COMPANY_NAME', ''),
    'version': os.environ.get('ROADMAP_VERSION', '1.0.0'),
    'support_email': os.environ.get('ROADMAP_SUPPORT_EMAIL', ''),
    'website': os.environ.get('ROADMAP_WEBSITE', ''),
    'docs_url': os.environ.get('ROADMAP_DOCS_URL', ''),
}

# Admin password - CHANGE THIS!
# No default: a baked-in password is one nobody changes. Unset means the
# admin panel simply cannot be logged into.
ADMIN_PASSWORD = os.environ.get('ROADMAP_ADMIN_PASSWORD')


# =============================================================================
# Database
# =============================================================================

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_database():
    """Initialize the roadmap database."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Roadmap phases/milestones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS phases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                target_date TEXT,
                status TEXT DEFAULT 'planned',
                color TEXT DEFAULT '#3b82f6',
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Features/items within phases
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phase_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'planned',
                priority TEXT DEFAULT 'medium',
                votes INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (phase_id) REFERENCES phases (id) ON DELETE CASCADE
            )
        ''')
        
        # Feature requests from users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS feature_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                submitted_by TEXT,
                email TEXT,
                status TEXT DEFAULT 'pending',
                votes INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        
        # Create default phases if none exist
        cursor.execute('SELECT COUNT(*) FROM phases')
        if cursor.fetchone()[0] == 0:
            default_phases = [
                ('Q1 2026 - Current Release', 'Initial release with core features', '2026-03-31', 'completed', '#10b981', 1),
                ('Q2 2026 - Planned', 'Payment integrations and recurring invoices', '2026-06-30', 'in_progress', '#f59e0b', 2),
                ('Q3 2026 - Planned', 'Advanced features and integrations', '2026-09-30', 'planned', '#3b82f6', 3),
                ('Future', 'Long-term roadmap items', None, 'planned', '#6b7280', 4),
            ]
            for phase in default_phases:
                cursor.execute('''
                    INSERT INTO phases (name, description, target_date, status, color, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', phase)
            
            conn.commit()
            
            # Get phase IDs and add default features
            cursor.execute('SELECT id FROM phases ORDER BY sort_order')
            phase_ids = [row['id'] for row in cursor.fetchall()]
            
            default_features = [
                (phase_ids[0], 'Core invoicing functionality', 'Create, edit, send invoices', 'completed', 'high', 1),
                (phase_ids[0], 'Multi-user team management', 'Role-based access control', 'completed', 'high', 2),
                (phase_ids[0], 'Email integration', 'Send invoices via email', 'completed', 'high', 3),
                (phase_ids[0], 'REST API with webhooks', 'Full API access', 'completed', 'medium', 4),
                (phase_ids[0], 'Multi-currency support', 'Multiple currencies with exchange rates', 'completed', 'medium', 5),
                (phase_ids[0], 'PDF generation', 'Professional PDF invoices', 'completed', 'high', 6),
                (phase_ids[1], 'Recurring invoices', 'Automatic invoice generation', 'in_progress', 'high', 1),
                (phase_ids[1], 'Client portal', 'Customer self-service portal', 'planned', 'high', 2),
                (phase_ids[1], 'Online payments (Stripe)', 'Accept card payments', 'planned', 'high', 3),
                (phase_ids[1], 'Online payments (PayPal)', 'Accept PayPal payments', 'planned', 'medium', 4),
                (phase_ids[1], 'Advanced reporting', 'Dashboard with charts and analytics', 'planned', 'medium', 5),
                (phase_ids[2], 'Quotes & Estimates', 'Create quotes that convert to invoices', 'planned', 'high', 1),
                (phase_ids[2], 'Project tracking', 'Track projects and billable work', 'planned', 'medium', 2),
                (phase_ids[2], 'Time tracking', 'Built-in time tracking', 'planned', 'medium', 3),
                (phase_ids[2], 'Expense tracking', 'Track business expenses', 'planned', 'medium', 4),
                (phase_ids[3], 'Mobile app', 'iOS and Android apps', 'planned', 'low', 1),
                (phase_ids[3], 'Accounting integrations', 'QuickBooks, Xero, FreshBooks', 'planned', 'medium', 2),
                (phase_ids[3], 'AI-powered insights', 'Smart recommendations and forecasting', 'planned', 'low', 3),
                (phase_ids[3], 'Multi-language support', 'Internationalization', 'planned', 'low', 4),
            ]
            
            for feature in default_features:
                cursor.execute('''
                    INSERT INTO features (phase_id, title, description, status, priority, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', feature)
            
            conn.commit()


# =============================================================================
# Authentication (Simple password-based for vendor admin)
# =============================================================================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Please log in to access the admin panel.', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# Public Routes
# =============================================================================

@app.route('/')
def index():
    """Public roadmap view."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Get all phases with their features
        cursor.execute('SELECT * FROM phases ORDER BY sort_order')
        phases = []
        for phase in cursor.fetchall():
            phase_dict = dict(phase)
            cursor.execute(
                'SELECT * FROM features WHERE phase_id = ? ORDER BY sort_order',
                (phase['id'],)
            )
            phase_dict['features'] = [dict(f) for f in cursor.fetchall()]
            phases.append(phase_dict)
    
    return render_template('public_roadmap.html', phases=phases, config=APP_CONFIG)


@app.route('/request', methods=['GET', 'POST'])
def feature_request():
    """Submit a feature request."""
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        name = request.form.get('name')
        email = request.form.get('email')
        
        if not title:
            flash('Please provide a title for your feature request.', 'error')
            return redirect(url_for('feature_request'))
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO feature_requests (title, description, submitted_by, email)
                VALUES (?, ?, ?, ?)
            ''', (title, description, name, email))
            conn.commit()
        
        flash('Thank you! Your feature request has been submitted.', 'success')
        return redirect(url_for('index'))
    
    return render_template('feature_request.html', config=APP_CONFIG)


@app.route('/vote/<int:feature_id>', methods=['POST'])
def vote_feature(feature_id):
    """Vote for a feature."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE features SET votes = votes + 1 WHERE id = ?', (feature_id,))
        conn.commit()
    return jsonify({'success': True})


# =============================================================================
# Admin Routes
# =============================================================================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page - password protected."""
    if request.method == 'POST':
        password = request.form.get('password')
        
        if not ADMIN_PASSWORD:
            flash('Admin access is disabled: ROADMAP_ADMIN_PASSWORD is not set.', 'error')
        elif password == ADMIN_PASSWORD:
            session['is_admin'] = True
            flash('Welcome! You are now logged in as admin.', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid password.', 'error')
    
    return render_template('admin_login.html', config=APP_CONFIG)


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    """Admin dashboard."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM phases ORDER BY sort_order')
        phases = [dict(p) for p in cursor.fetchall()]
        
        cursor.execute('SELECT COUNT(*) as count FROM features')
        feature_count = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM feature_requests WHERE status = "pending"')
        pending_requests = cursor.fetchone()['count']
    
    return render_template('admin_dashboard.html', 
                          phases=phases, 
                          feature_count=feature_count,
                          pending_requests=pending_requests,
                          config=APP_CONFIG)


@app.route('/admin/phases', methods=['GET', 'POST'])
@admin_required
def admin_phases():
    """Manage roadmap phases."""
    if request.method == 'POST':
        action = request.form.get('action')
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            if action == 'add':
                cursor.execute('''
                    INSERT INTO phases (name, description, target_date, status, color, sort_order)
                    VALUES (?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM phases))
                ''', (
                    request.form.get('name'),
                    request.form.get('description'),
                    request.form.get('target_date') or None,
                    request.form.get('status', 'planned'),
                    request.form.get('color', '#3b82f6')
                ))
                flash('Phase added.', 'success')
            
            elif action == 'update':
                cursor.execute('''
                    UPDATE phases SET name = ?, description = ?, target_date = ?, 
                    status = ?, color = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (
                    request.form.get('name'),
                    request.form.get('description'),
                    request.form.get('target_date') or None,
                    request.form.get('status'),
                    request.form.get('color'),
                    request.form.get('phase_id')
                ))
                flash('Phase updated.', 'success')
            
            elif action == 'delete':
                cursor.execute('DELETE FROM phases WHERE id = ?', (request.form.get('phase_id'),))
                flash('Phase deleted.', 'success')
            
            conn.commit()
        
        return redirect(url_for('admin_phases'))
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM phases ORDER BY sort_order')
        phases = [dict(p) for p in cursor.fetchall()]
    
    return render_template('admin_phases.html', phases=phases, config=APP_CONFIG)


@app.route('/admin/features', methods=['GET', 'POST'])
@admin_required
def admin_features():
    """Manage roadmap features."""
    if request.method == 'POST':
        action = request.form.get('action')
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            if action == 'add':
                cursor.execute('''
                    INSERT INTO features (phase_id, title, description, status, priority, sort_order)
                    VALUES (?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM features WHERE phase_id = ?))
                ''', (
                    request.form.get('phase_id'),
                    request.form.get('title'),
                    request.form.get('description'),
                    request.form.get('status', 'planned'),
                    request.form.get('priority', 'medium'),
                    request.form.get('phase_id')
                ))
                flash('Feature added.', 'success')
            
            elif action == 'update':
                cursor.execute('''
                    UPDATE features SET phase_id = ?, title = ?, description = ?, 
                    status = ?, priority = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (
                    request.form.get('phase_id'),
                    request.form.get('title'),
                    request.form.get('description'),
                    request.form.get('status'),
                    request.form.get('priority'),
                    request.form.get('feature_id')
                ))
                flash('Feature updated.', 'success')
            
            elif action == 'delete':
                cursor.execute('DELETE FROM features WHERE id = ?', (request.form.get('feature_id'),))
                flash('Feature deleted.', 'success')
            
            conn.commit()
        
        return redirect(url_for('admin_features'))
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM phases ORDER BY sort_order')
        phases = [dict(p) for p in cursor.fetchall()]
        
        cursor.execute('''
            SELECT f.*, p.name as phase_name 
            FROM features f 
            JOIN phases p ON f.phase_id = p.id 
            ORDER BY p.sort_order, f.sort_order
        ''')
        features = [dict(f) for f in cursor.fetchall()]
    
    return render_template('admin_features.html', phases=phases, features=features, config=APP_CONFIG)


@app.route('/admin/requests')
@admin_required
def admin_requests():
    """View feature requests."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM feature_requests ORDER BY created_at DESC')
        requests_list = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute('SELECT * FROM phases ORDER BY sort_order')
        phases = [dict(p) for p in cursor.fetchall()]
    
    return render_template('admin_requests.html', requests=requests_list, phases=phases, config=APP_CONFIG)


@app.route('/admin/requests/<int:request_id>/action', methods=['POST'])
@admin_required
def admin_request_action(request_id):
    """Handle feature request actions."""
    action = request.form.get('action')
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        if action == 'approve':
            # Get the request
            cursor.execute('SELECT * FROM feature_requests WHERE id = ?', (request_id,))
            req = cursor.fetchone()
            
            if req:
                phase_id = request.form.get('phase_id')
                # Create feature from request
                cursor.execute('''
                    INSERT INTO features (phase_id, title, description, status, priority)
                    VALUES (?, ?, ?, 'planned', 'medium')
                ''', (phase_id, req['title'], req['description']))
                
                # Update request status
                cursor.execute(
                    'UPDATE feature_requests SET status = "approved" WHERE id = ?',
                    (request_id,)
                )
                flash('Feature request approved and added to roadmap.', 'success')
        
        elif action == 'reject':
            cursor.execute(
                'UPDATE feature_requests SET status = "rejected" WHERE id = ?',
                (request_id,)
            )
            flash('Feature request rejected.', 'success')
        
        elif action == 'delete':
            cursor.execute('DELETE FROM feature_requests WHERE id = ?', (request_id,))
            flash('Feature request deleted.', 'success')
        
        conn.commit()
    
    return redirect(url_for('admin_requests'))


# =============================================================================
# API Endpoints (for integration with other apps)
# =============================================================================

@app.route('/api/roadmap')
def api_roadmap():
    """Get roadmap data as JSON."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM phases ORDER BY sort_order')
        phases = []
        for phase in cursor.fetchall():
            phase_dict = dict(phase)
            cursor.execute(
                'SELECT * FROM features WHERE phase_id = ? ORDER BY sort_order',
                (phase['id'],)
            )
            phase_dict['features'] = [dict(f) for f in cursor.fetchall()]
            phases.append(phase_dict)
    
    return jsonify({
        'app_name': APP_CONFIG['app_name'],
        'version': APP_CONFIG['version'],
        'phases': phases
    })


# =============================================================================
# Initialize and Run
# =============================================================================

init_database()

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes')
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    app.run(debug=debug, host=host, port=int(os.environ.get('FLASK_PORT', '5001')))
