"""
Roadmap Module - Integrated into Invoice Manager
Provides roadmap management functionality.
Copyright (c) 2026 Sondela Consulting Ltd.
"""

import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g

from app_core import get_db

# Create Blueprint
roadmap_bp = Blueprint('roadmap', __name__, url_prefix='/roadmap')

# =============================================================================
# Database Functions
# =============================================================================

def init_roadmap_tables():
    """Initialize roadmap tables in the database."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Roadmap phases/milestones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS roadmap_phases (
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
            CREATE TABLE IF NOT EXISTS roadmap_features (
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
                FOREIGN KEY (phase_id) REFERENCES roadmap_phases (id) ON DELETE CASCADE
            )
        ''')
        
        # Feature requests from users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS roadmap_requests (
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
        cursor.execute('SELECT COUNT(*) FROM roadmap_phases')
        if cursor.fetchone()[0] == 0:
            _create_default_roadmap_data(cursor, conn)


def _create_default_roadmap_data(cursor, conn):
    """Create default roadmap phases and features."""
    default_phases = [
        ('Q1 2026 - Current Release', 'Initial release with core features', '2026-03-31', 'completed', '#10b981', 1),
        ('Q2 2026 - Planned', 'Payment integrations and recurring invoices', '2026-06-30', 'in_progress', '#f59e0b', 2),
        ('Q3 2026 - Planned', 'Advanced features and integrations', '2026-09-30', 'planned', '#3b82f6', 3),
        ('Future', 'Long-term roadmap items', None, 'planned', '#6b7280', 4),
    ]
    
    for phase in default_phases:
        cursor.execute('''
            INSERT INTO roadmap_phases (name, description, target_date, status, color, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', phase)
    
    conn.commit()
    
    # Get phase IDs
    cursor.execute('SELECT id FROM roadmap_phases ORDER BY sort_order')
    phase_ids = [row[0] for row in cursor.fetchall()]
    
    default_features = [
        # Q1 2026
        (phase_ids[0], 'Core invoicing functionality', 'Create, edit, send invoices', 'completed', 'high', 1),
        (phase_ids[0], 'Multi-user team management', 'Role-based access control', 'completed', 'high', 2),
        (phase_ids[0], 'Email integration', 'Send invoices via email', 'completed', 'high', 3),
        (phase_ids[0], 'REST API with webhooks', 'Full API access', 'completed', 'medium', 4),
        (phase_ids[0], 'Multi-currency support', 'Multiple currencies with exchange rates', 'completed', 'medium', 5),
        (phase_ids[0], 'PDF generation', 'Professional PDF invoices', 'completed', 'high', 6),
        # Q2 2026
        (phase_ids[1], 'Recurring invoices', 'Automatic invoice generation', 'in_progress', 'high', 1),
        (phase_ids[1], 'Client portal', 'Customer self-service portal', 'planned', 'high', 2),
        (phase_ids[1], 'Online payments (Stripe)', 'Accept card payments', 'planned', 'high', 3),
        (phase_ids[1], 'Online payments (PayPal)', 'Accept PayPal payments', 'planned', 'medium', 4),
        (phase_ids[1], 'Advanced reporting', 'Dashboard with charts and analytics', 'planned', 'medium', 5),
        # Q3 2026
        (phase_ids[2], 'Quotes & Estimates', 'Create quotes that convert to invoices', 'planned', 'high', 1),
        (phase_ids[2], 'Project tracking', 'Track projects and billable work', 'planned', 'medium', 2),
        (phase_ids[2], 'Time tracking', 'Built-in time tracking', 'planned', 'medium', 3),
        (phase_ids[2], 'Expense tracking', 'Track business expenses', 'planned', 'medium', 4),
        # Future
        (phase_ids[3], 'Mobile app', 'iOS and Android apps', 'planned', 'low', 1),
        (phase_ids[3], 'Accounting integrations', 'QuickBooks, Xero, FreshBooks', 'planned', 'medium', 2),
        (phase_ids[3], 'AI-powered insights', 'Smart recommendations and forecasting', 'planned', 'low', 3),
        (phase_ids[3], 'Multi-language support', 'Internationalization', 'planned', 'low', 4),
    ]
    
    for feature in default_features:
        cursor.execute('''
            INSERT INTO roadmap_features (phase_id, title, description, status, priority, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', feature)
    
    conn.commit()


def get_roadmap_data():
    """Get all roadmap phases with features."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM roadmap_phases ORDER BY sort_order')
        phases = []
        for phase in cursor.fetchall():
            phase_dict = dict(phase)
            cursor.execute(
                'SELECT * FROM roadmap_features WHERE phase_id = ? ORDER BY sort_order',
                (phase['id'],)
            )
            phase_dict['features'] = [dict(f) for f in cursor.fetchall()]
            phases.append(phase_dict)
    
    return phases


# =============================================================================
# Public Routes
# =============================================================================

@roadmap_bp.route('/')
def public_roadmap():
    """Public roadmap view - no login required."""
    phases = get_roadmap_data()
    return render_template('roadmap/public.html', phases=phases)


@roadmap_bp.route('/request', methods=['GET', 'POST'])
def feature_request():
    """Submit a feature request - no login required."""
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        name = request.form.get('name')
        email = request.form.get('email')
        
        if not title:
            flash('Please provide a title for your feature request.', 'error')
            return redirect(url_for('roadmap.feature_request'))
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO roadmap_requests (title, description, submitted_by, email)
                VALUES (?, ?, ?, ?)
            ''', (title, description, name, email))
            conn.commit()
        
        flash('Thank you! Your feature request has been submitted.', 'success')
        return redirect(url_for('roadmap.public_roadmap'))
    
    return render_template('roadmap/request.html')


@roadmap_bp.route('/vote/<int:feature_id>', methods=['POST'])
def vote_feature(feature_id):
    """Vote for a feature."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE roadmap_features SET votes = votes + 1 WHERE id = ?', (feature_id,))
        conn.commit()
    return jsonify({'success': True})


# =============================================================================
# Admin Routes (require login)
# =============================================================================

def admin_required(f):
    """Decorator to require admin/owner login."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        
        # Check if user is admin or owner
        from team_management import get_user_role
        role = get_user_role(session['user_id'])
        if role not in ('owner', 'admin'):
            flash('Only administrators can manage the roadmap.', 'error')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function


@roadmap_bp.route('/admin')
@admin_required
def admin_dashboard():
    """Admin roadmap dashboard."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM roadmap_phases ORDER BY sort_order')
        phases = [dict(p) for p in cursor.fetchall()]
        
        cursor.execute('SELECT COUNT(*) as count FROM roadmap_features')
        feature_count = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM roadmap_requests WHERE status = "pending"')
        pending_requests = cursor.fetchone()['count']
    
    return render_template('roadmap/admin_dashboard.html', 
                          phases=phases, 
                          feature_count=feature_count,
                          pending_requests=pending_requests)


@roadmap_bp.route('/admin/phases', methods=['GET', 'POST'])
@admin_required
def admin_phases():
    """Manage roadmap phases."""
    if request.method == 'POST':
        action = request.form.get('action')
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            if action == 'add':
                cursor.execute('''
                    INSERT INTO roadmap_phases (name, description, target_date, status, color, sort_order)
                    VALUES (?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM roadmap_phases))
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
                    UPDATE roadmap_phases SET name = ?, description = ?, target_date = ?, 
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
                cursor.execute('DELETE FROM roadmap_phases WHERE id = ?', (request.form.get('phase_id'),))
                flash('Phase deleted.', 'success')
            
            conn.commit()
        
        return redirect(url_for('roadmap.admin_phases'))
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM roadmap_phases ORDER BY sort_order')
        phases = [dict(p) for p in cursor.fetchall()]
    
    return render_template('roadmap/admin_phases.html', phases=phases)


@roadmap_bp.route('/admin/features', methods=['GET', 'POST'])
@admin_required
def admin_features():
    """Manage roadmap features."""
    if request.method == 'POST':
        action = request.form.get('action')
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            if action == 'add':
                cursor.execute('''
                    INSERT INTO roadmap_features (phase_id, title, description, status, priority, sort_order)
                    VALUES (?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM roadmap_features WHERE phase_id = ?))
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
                    UPDATE roadmap_features SET phase_id = ?, title = ?, description = ?, 
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
                cursor.execute('DELETE FROM roadmap_features WHERE id = ?', (request.form.get('feature_id'),))
                flash('Feature deleted.', 'success')
            
            conn.commit()
        
        return redirect(url_for('roadmap.admin_features'))
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM roadmap_phases ORDER BY sort_order')
        phases = [dict(p) for p in cursor.fetchall()]
        
        cursor.execute('''
            SELECT f.*, p.name as phase_name 
            FROM roadmap_features f 
            JOIN roadmap_phases p ON f.phase_id = p.id 
            ORDER BY p.sort_order, f.sort_order
        ''')
        features = [dict(f) for f in cursor.fetchall()]
    
    return render_template('roadmap/admin_features.html', phases=phases, features=features)


@roadmap_bp.route('/admin/requests')
@admin_required
def admin_requests():
    """View feature requests."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM roadmap_requests ORDER BY created_at DESC')
        requests_list = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute('SELECT * FROM roadmap_phases ORDER BY sort_order')
        phases = [dict(p) for p in cursor.fetchall()]
    
    return render_template('roadmap/admin_requests.html', requests=requests_list, phases=phases)


@roadmap_bp.route('/admin/requests/<int:request_id>/action', methods=['POST'])
@admin_required
def admin_request_action(request_id):
    """Handle feature request actions."""
    action = request.form.get('action')
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        if action == 'approve':
            cursor.execute('SELECT * FROM roadmap_requests WHERE id = ?', (request_id,))
            req = cursor.fetchone()
            
            if req:
                phase_id = request.form.get('phase_id')
                cursor.execute('''
                    INSERT INTO roadmap_features (phase_id, title, description, status, priority)
                    VALUES (?, ?, ?, 'planned', 'medium')
                ''', (phase_id, req['title'], req['description']))
                
                cursor.execute(
                    'UPDATE roadmap_requests SET status = "approved" WHERE id = ?',
                    (request_id,)
                )
                flash('Feature request approved and added to roadmap.', 'success')
        
        elif action == 'reject':
            cursor.execute(
                'UPDATE roadmap_requests SET status = "rejected" WHERE id = ?',
                (request_id,)
            )
            flash('Feature request rejected.', 'success')
        
        elif action == 'delete':
            cursor.execute('DELETE FROM roadmap_requests WHERE id = ?', (request_id,))
            flash('Feature request deleted.', 'success')
        
        conn.commit()
    
    return redirect(url_for('roadmap.admin_requests'))


# =============================================================================
# API Endpoint
# =============================================================================

@roadmap_bp.route('/api')
def api_roadmap():
    """Get roadmap data as JSON."""
    phases = get_roadmap_data()
    return jsonify({
        'app_name': 'Invoice Manager',
        'version': '1.0.0',
        'phases': phases
    })
