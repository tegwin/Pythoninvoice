"""
Invoice Manager - Web Application
A Flask-based web interface for managing invoices, customers, and products.
"""

import os
import sys
import json
import secrets
from functools import wraps
from datetime import datetime, timedelta, date
from decimal import Decimal
from io import BytesIO

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, jsonify, send_file, Response, g, send_from_directory
)
from flask.json.provider import DefaultJSONProvider
from werkzeug.utils import secure_filename

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_core import (
    init_database, create_user, authenticate_user, change_password,
    SettingsManager, CustomerManager, ProductManager, InvoiceManager,
    CURRENCIES, get_currency_symbol, get_db, get_currency_rate
)

from team_management import get_data_user_id, has_permission, ROLES

from api_webhooks import (
    api_key_required, create_api_key, validate_api_key, get_user_api_keys,
    revoke_api_key, delete_api_key as delete_api_key_func,
    create_webhook, get_user_webhooks, get_webhook, update_webhook, delete_webhook,
    trigger_webhooks, test_webhook, WEBHOOK_EVENTS,
    api_success, api_error, serialize_customer, serialize_product,
    serialize_invoice, serialize_invoice_item, serialize_payment
)

from pdf_generator import generate_invoice_pdf, generate_invoice_html, check_dependencies


# Custom JSON provider to handle Decimal and datetime types
class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


# Initialize Flask app
app = Flask(__name__)
app.json = CustomJSONProvider(app)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.permanent_session_lifetime = timedelta(days=7)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def get_effective_user_id():
    """Get the user_id to use for data access. 
    For team members, returns the owner's user_id.
    For owners, returns their own user_id.
    """
    if 'user_id' not in session:
        return None
    
    # Cache the effective user_id in session to avoid repeated DB lookups
    if 'effective_user_id' not in session:
        session['effective_user_id'] = get_data_user_id(session['user_id'])
    
    return session['effective_user_id']


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/uploads/<filename>')
def serve_upload(filename):
    """Serve uploaded files."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ---------------------------------------------------------------------------
# Demo mode
# ---------------------------------------------------------------------------
# A public demo runs the same code as the real app with DEMO_MODE=true. It
# blocks anything that would reach a third party, cost money, or leak the
# host's credentials, and everything is wiped nightly by reset_demo.py.
DEMO_MODE = os.environ.get('DEMO_MODE', '').lower() in ('1', 'true', 'yes')

# Prefixes blocked in demo mode. Matched against request.path, so a prefix
# covers every sub-route - new integration routes are blocked automatically
# rather than needing to be added here.
# Browsable in demo, but read-only: the page renders, saving does not. Lets
# people see what the integrations actually look like.
DEMO_READONLY_PREFIXES = (
    '/settings/integrations',   # Stripe, GoCardless, SumUp, Wise, FX keys
    '/settings/api-keys',       # can view the (empty) list, not mint keys
    '/settings/webhooks',
    '/settings/incoming-webhooks',
    '/settings/email',          # SMTP / Graph config
    '/settings/team',
    '/settings/portal-users',
)

# Hidden entirely - viewing alone would expose the host's own credentials.
DEMO_BLOCKED_PREFIXES = (
    '/settings/database',       # shows the live DB host, user and password
)

# Blocked only as a substring of the path, for per-record actions that sit
# under an otherwise-allowed prefix (e.g. /invoices/3/send-email).
DEMO_BLOCKED_FRAGMENTS = (
    'send-email', 'stripe', 'gocardless', 'sumup', 'wise',
    'submit-tax', 'setup-direct-debit',
)

DEMO_MESSAGE = ('That is disabled in the demo, because it would send real '
                'email or contact a payment provider. Everything else works.')

DEMO_READONLY_MESSAGE = ('Read-only in the demo - have a look around, but '
                         'saving is disabled here.')

# The shared demo account. reset_demo.py recreates it nightly.
DEMO_USERNAME = os.environ.get('DEMO_USERNAME', 'demo')
DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', 'demo')

# Shown in the login footer. Empty by default so a copy handed to another MSP
# carries no one else's company name.
FOOTER_OWNER = os.environ.get('FOOTER_OWNER', '')


def demo_blocks(path):
    """True if this path must not run at all in demo mode."""
    if path.startswith(DEMO_BLOCKED_PREFIXES):
        return True
    return any(fragment in path for fragment in DEMO_BLOCKED_FRAGMENTS)


@app.before_request
def enforce_demo_mode():
    if not DEMO_MODE:
        return
    # Let the webhook receivers 404 naturally rather than flashing at a
    # machine; they are unauthenticated endpoints, not user navigation.
    if request.path.startswith('/webhook'):
        return ('disabled in demo', 403)
    if demo_blocks(request.path):
        flash(DEMO_MESSAGE, 'warning')
        return redirect(url_for('settings'))

    # Read-only areas: let the page render, refuse anything that writes.
    if request.path.startswith(DEMO_READONLY_PREFIXES):
        if request.method == 'GET':
            g.demo_readonly = True
            return
        flash(DEMO_READONLY_MESSAGE, 'warning')
        return redirect(request.referrer or url_for('settings'))


@app.context_processor
def inject_constants():
    return {
        'CURRENCIES': CURRENCIES,
        'get_currency_symbol': get_currency_symbol,
        'DEMO_MODE': DEMO_MODE,
        'DEMO_READONLY': getattr(g, 'demo_readonly', False),
        'DEMO_USERNAME': DEMO_USERNAME,
        'DEMO_PASSWORD': DEMO_PASSWORD,
        'FOOTER_OWNER': FOOTER_OWNER,
    }


@app.before_request
def load_branding():
    """Load branding settings for navbar and footer."""
    g.brand_name = 'Invoice Manager'
    g.brand_logo = None
    g.show_brand_name = True
    g.show_brand_logo = False
    g.show_powered_by = False
    g.show_footer = True
    g.footer_text = 'Powered by Invoice Manager'
    g.tax_rates = '0,5,10,15,20,25'
    
    if 'user_id' in session:
        try:
            effective_id = get_effective_user_id()
            if effective_id:
                settings = SettingsManager(effective_id).get_settings()
                g.brand_name = settings.get('brand_name') or settings.get('company_name') or 'Invoice Manager'
                g.brand_logo = settings.get('brand_logo_path')
                g.show_brand_name = settings.get('show_brand_name', 1)
                g.show_brand_logo = settings.get('show_brand_logo', 0)
                g.show_powered_by = settings.get('show_powered_by', 0)
                g.show_footer = settings.get('show_footer', 1)
                g.footer_text = settings.get('footer_text') or 'Powered by Invoice Manager'
                g.tax_rates = settings.get('tax_rates', '0,5,10,15,20,25')
        except Exception:
            pass


# =============================================================================
# Authentication Routes
# =============================================================================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == '1'
        
        if not username or not password:
            flash('Please enter username and password.', 'error')
            return render_template('login.html')
        
        user = authenticate_user(username, password)
        
        if user:
            # Check if user is active
            if not user.get('active', 1):
                flash('Your account has been deactivated.', 'error')
                return render_template('login.html')
            
            # Check if 2FA is enabled
            if user.get('totp_enabled'):
                return redirect(url_for('verify_2fa_login', user_id=user['id'], remember='1' if remember else '0'))
            
            # Normal login
            session.permanent = remember
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['email'] = user.get('email')
            session['display_name'] = user.get('display_name')
            session['avatar_path'] = user.get('avatar_path')
            session['user_role'] = user.get('role', 'owner')
            
            # Set effective_user_id for data access (team members use owner's data)
            session['effective_user_id'] = get_data_user_id(user['id'])
            
            # Update login count (ignore if column doesn't exist yet)
            try:
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE users SET login_count = COALESCE(login_count, 0) + 1 WHERE id = ?
                    ''', (user['id'],))
                    conn.commit()
            except Exception:
                pass  # Column may not exist in older databases
            
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        email = request.form.get('email', '').strip()
        
        if not username or not password:
            flash('Please enter username and password.', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')
        
        success, message = create_user(username, password, email)
        
        if success:
            flash(message + ' You can now log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash(message, 'error')
    
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# =============================================================================
# User Profile & 2FA
# =============================================================================

@app.route('/profile')
@login_required
def profile():
    """User profile page."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],))
        row = cursor.fetchone()
        # Convert to dict, handling missing columns gracefully
        user = {}
        if row:
            for key in row.keys():
                user[key] = row[key]
        # Set defaults for potentially missing columns
        user.setdefault('display_name', user.get('username', ''))
        user.setdefault('phone', '')
        user.setdefault('timezone', 'Europe/London')
        user.setdefault('bio', '')
        user.setdefault('avatar_path', None)
        user.setdefault('totp_enabled', 0)
        user.setdefault('login_count', 0)
        user.setdefault('role', 'owner')
    
    return render_template('profile.html', user=user)


@app.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    """Update user profile information."""
    display_name = request.form.get('display_name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    timezone = request.form.get('timezone')
    bio = request.form.get('bio')
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users SET display_name = ?, email = ?, phone = ?, timezone = ?, bio = ?
            WHERE id = ?
        ''', (display_name, email, phone, timezone, bio, session['user_id']))
        conn.commit()
    
    session['display_name'] = display_name
    session['email'] = email
    
    flash('Profile updated successfully.', 'success')
    return redirect(url_for('profile'))


@app.route('/profile/avatar', methods=['POST'])
@login_required
def update_avatar():
    """Update user avatar."""
    if 'avatar' not in request.files:
        flash('No file uploaded.', 'error')
        return redirect(url_for('profile'))
    
    file = request.files['avatar']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('profile'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(f"avatar_{session['user_id']}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET avatar_path = ? WHERE id = ?', (filepath, session['user_id']))
            conn.commit()
        
        session['avatar_path'] = filepath
        flash('Avatar updated.', 'success')
    else:
        flash('Invalid file type.', 'error')
    
    return redirect(url_for('profile'))


@app.route('/profile/avatar/remove', methods=['POST'])
@login_required
def remove_avatar():
    """Remove user avatar."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT avatar_path FROM users WHERE id = ?', (session['user_id'],))
        row = cursor.fetchone()
        if row and row['avatar_path']:
            try:
                os.remove(row['avatar_path'])
            except:
                pass
        
        cursor.execute('UPDATE users SET avatar_path = NULL WHERE id = ?', (session['user_id'],))
        conn.commit()
    
    session.pop('avatar_path', None)
    flash('Avatar removed.', 'success')
    return redirect(url_for('profile'))


@app.route('/profile/2fa/setup')
@login_required
def setup_2fa():
    """Setup two-factor authentication."""
    try:
        import pyotp
        import qrcode
        import io
        import base64
    except ImportError:
        flash('2FA requires pyotp and qrcode packages. Install: pip install pyotp qrcode[pil]', 'error')
        return redirect(url_for('profile'))
    
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=session['username'], issuer_name='Invoice Manager')
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    qr_code = base64.b64encode(buffer.getvalue()).decode()
    
    return render_template('setup_2fa.html', secret=secret, qr_code=qr_code)


@app.route('/profile/2fa/verify', methods=['POST'])
@login_required
def verify_2fa_setup():
    """Verify 2FA setup and enable it."""
    try:
        import pyotp
    except ImportError:
        flash('2FA requires pyotp package.', 'error')
        return redirect(url_for('profile'))
    
    secret = request.form.get('secret')
    totp_code = request.form.get('totp_code')
    
    totp = pyotp.TOTP(secret)
    
    if totp.verify(totp_code):
        backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]
        backup_codes_formatted = [f"{code[:4]}-{code[4:]}" for code in backup_codes]
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET totp_secret = ?, totp_enabled = 1, backup_codes = ?
                WHERE id = ?
            ''', (secret, json.dumps(backup_codes_formatted), session['user_id']))
            conn.commit()
        
        flash('Two-factor authentication enabled!', 'success')
        return render_template('backup_codes.html', backup_codes=backup_codes_formatted)
    else:
        flash('Invalid verification code. Please try again.', 'error')
        return redirect(url_for('setup_2fa'))


@app.route('/profile/2fa/disable', methods=['POST'])
@login_required
def disable_2fa():
    """Disable two-factor authentication."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users SET totp_secret = NULL, totp_enabled = 0, backup_codes = NULL
            WHERE id = ?
        ''', (session['user_id'],))
        conn.commit()
    
    flash('Two-factor authentication disabled.', 'success')
    return redirect(url_for('profile'))


@app.route('/profile/2fa/backup-codes', methods=['POST'])
@login_required
def regenerate_backup_codes():
    """Regenerate backup codes."""
    backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]
    backup_codes_formatted = [f"{code[:4]}-{code[4:]}" for code in backup_codes]
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET backup_codes = ? WHERE id = ?', 
                      (json.dumps(backup_codes_formatted), session['user_id']))
        conn.commit()
    
    return render_template('backup_codes.html', backup_codes=backup_codes_formatted)


@app.route('/auth/2fa', methods=['GET', 'POST'])
def verify_2fa_login():
    """Verify 2FA during login."""
    try:
        import pyotp
    except ImportError:
        flash('2FA verification failed.', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        totp_code = request.form.get('totp_code')
        remember = request.form.get('remember') == '1'
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
            user = cursor.fetchone()
            
            if user:
                totp = pyotp.TOTP(user['totp_secret'])
                
                if totp.verify(totp_code):
                    session.permanent = remember
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    session['email'] = user['email']
                    session['display_name'] = user['display_name']
                    session['avatar_path'] = user['avatar_path']
                    session['user_role'] = user['role']
                    session['effective_user_id'] = get_data_user_id(user['id'])
                    
                    cursor.execute('''
                        UPDATE users SET last_login = ?, login_count = COALESCE(login_count, 0) + 1 
                        WHERE id = ?
                    ''', (datetime.now().isoformat(), user['id']))
                    conn.commit()
                    
                    flash(f'Welcome back, {user["username"]}!', 'success')
                    return redirect(url_for('dashboard'))
                else:
                    flash('Invalid verification code.', 'error')
    
    user_id = request.args.get('user_id')
    remember = request.args.get('remember', '0')
    return render_template('verify_2fa.html', user_id=user_id, remember=remember)


@app.route('/auth/backup-code', methods=['POST'])
def verify_backup_code():
    """Verify backup code during login."""
    user_id = request.form.get('user_id')
    backup_code = request.form.get('backup_code', '').upper().replace('-', '')
    remember = request.form.get('remember') == '1'
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        
        if user and user['backup_codes']:
            codes = json.loads(user['backup_codes'])
            formatted_code = f"{backup_code[:4]}-{backup_code[4:]}" if len(backup_code) == 8 else backup_code
            
            if formatted_code in codes:
                codes.remove(formatted_code)
                cursor.execute('UPDATE users SET backup_codes = ? WHERE id = ?', (json.dumps(codes), user_id))
                
                session.permanent = remember
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['email'] = user['email']
                session['display_name'] = user['display_name']
                session['avatar_path'] = user['avatar_path']
                session['user_role'] = user['role']
                session['effective_user_id'] = get_data_user_id(user['id'])
                session['user_role'] = user['role']
                
                cursor.execute('''
                    UPDATE users SET last_login = ?, login_count = COALESCE(login_count, 0) + 1 WHERE id = ?
                ''', (datetime.now().isoformat(), user['id']))
                conn.commit()
                
                flash(f'Welcome back! You have {len(codes)} backup codes remaining.', 'success')
                return redirect(url_for('dashboard'))
    
    flash('Invalid backup code.', 'error')
    return redirect(url_for('verify_2fa_login', user_id=user_id, remember='1' if remember else '0'))


# =============================================================================
# Dashboard
# =============================================================================

@app.route('/dashboard')
@login_required
def dashboard():
    from app_core import get_user_preference, set_user_preference
    
    invoice_manager = InvoiceManager(get_effective_user_id())
    customer_manager = CustomerManager(get_effective_user_id())
    
    stats = invoice_manager.get_statistics()
    
    # Get status filter - check URL param first, then database preference
    status_filter = request.args.get('status')
    if status_filter is not None:
        # Save to database (empty string means "all")
        set_user_preference(get_effective_user_id(), 'dashboard_status_filter', status_filter if status_filter else '')
        status_filter = status_filter if status_filter else None
    else:
        # Load from database preference
        status_filter = get_user_preference(get_effective_user_id(), 'dashboard_status_filter', '')
        status_filter = status_filter if status_filter else None
    
    all_invoices = invoice_manager.get_all()
    
    if status_filter:
        recent_invoices = [inv for inv in all_invoices if inv.get('status') == status_filter][:10]
    else:
        recent_invoices = all_invoices[:10]
    
    customers = customer_manager.get_all()
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    return render_template('dashboard.html',
                         stats=stats,
                         recent_invoices=recent_invoices,
                         customer_count=len(customers),
                         currency_symbol=currency_symbol,
                         status_filter=status_filter)


# =============================================================================
# Customer Routes
# =============================================================================

@app.route('/customers')
@login_required
def customers():
    customer_manager = CustomerManager(get_effective_user_id())
    customers = customer_manager.get_all()
    return render_template('customers.html', customers=customers)


@app.route('/customers/new', methods=['GET', 'POST'])
@login_required
def new_customer():
    settings = SettingsManager(get_effective_user_id()).get_settings()
    
    if request.method == 'POST':
        customer_manager = CustomerManager(get_effective_user_id())
        
        custom_tax = request.form.get('custom_tax_rate')
        custom_tax = float(custom_tax) if custom_tax else None
        
        customer_id = customer_manager.create(
            name=request.form.get('name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            address_line1=request.form.get('address_line1'),
            address_line2=request.form.get('address_line2'),
            city=request.form.get('city'),
            state=request.form.get('state'),
            postal_code=request.form.get('postal_code'),
            country=request.form.get('country'),
            tax_number=request.form.get('tax_number'),
            custom_tax_rate=custom_tax,
            custom_currency=request.form.get('custom_currency') or None,
            notes=request.form.get('notes')
        )
        
        # Update email preferences
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE customers SET 
                    email_invoice_created = ?,
                    email_invoice_reminder = ?,
                    email_payment_received = ?
                WHERE id = ?
            ''', (
                1 if request.form.get('email_invoice_created') else 0,
                1 if request.form.get('email_invoice_reminder') else 0,
                1 if request.form.get('email_payment_received') else 0,
                customer_id
            ))
            conn.commit()
        
        # Trigger webhook
        customer = customer_manager.get(customer_id)
        trigger_webhooks('customer.created', get_effective_user_id(), serialize_customer(customer))
        
        flash('Customer created successfully.', 'success')
        return redirect(url_for('customers'))
    
    return render_template('customer_form.html', customer=None, settings=settings)


@app.route('/customers/<int:customer_id>')
@login_required
def view_customer(customer_id):
    customer_manager = CustomerManager(get_effective_user_id())
    customer = customer_manager.get(customer_id)
    
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('customers'))
    
    # Get customer's invoices
    invoice_manager = InvoiceManager(get_effective_user_id())
    invoices = [inv for inv in invoice_manager.get_all() if inv.get('customer_id') == customer_id]
    
    return render_template('customer_detail.html', customer=customer, invoices=invoices)


@app.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
    customer_manager = CustomerManager(get_effective_user_id())
    customer = customer_manager.get(customer_id)
    settings = SettingsManager(get_effective_user_id()).get_settings()
    
    if not customer:
        flash('Customer not found.', 'error')
        return redirect(url_for('customers'))
    
    if request.method == 'POST':
        custom_tax = request.form.get('custom_tax_rate')
        custom_tax = float(custom_tax) if custom_tax else None
        
        customer_manager.update(customer_id, {
            'name': request.form.get('name'),
            'email': request.form.get('email'),
            'phone': request.form.get('phone'),
            'address_line1': request.form.get('address_line1'),
            'address_line2': request.form.get('address_line2'),
            'city': request.form.get('city'),
            'state': request.form.get('state'),
            'postal_code': request.form.get('postal_code'),
            'country': request.form.get('country'),
            'tax_number': request.form.get('tax_number'),
            'custom_tax_rate': custom_tax,
            'custom_currency': request.form.get('custom_currency') or None,
            'notes': request.form.get('notes')
        })
        
        # Update email preferences
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE customers SET 
                    email_invoice_created = ?,
                    email_invoice_reminder = ?,
                    email_payment_received = ?
                WHERE id = ?
            ''', (
                1 if request.form.get('email_invoice_created') else 0,
                1 if request.form.get('email_invoice_reminder') else 0,
                1 if request.form.get('email_payment_received') else 0,
                customer_id
            ))
            conn.commit()
        
        customer = customer_manager.get(customer_id)
        trigger_webhooks('customer.updated', get_effective_user_id(), serialize_customer(customer))
        
        flash('Customer updated successfully.', 'success')
        return redirect(url_for('view_customer', customer_id=customer_id))
    
    return render_template('customer_form.html', customer=customer, settings=settings)


@app.route('/customers/<int:customer_id>/delete', methods=['POST'])
@login_required
def delete_customer(customer_id):
    customer_manager = CustomerManager(get_effective_user_id())
    customer = customer_manager.get(customer_id)
    
    if customer:
        try:
            trigger_webhooks('customer.deleted', get_effective_user_id(), serialize_customer(customer))
            customer_manager.delete(customer_id)
            flash('Customer deleted.', 'success')
        except ValueError as e:
            flash(str(e), 'error')
    else:
        flash('Customer not found.', 'error')
    
    return redirect(url_for('customers'))


# =============================================================================
# Product/Service Routes
# =============================================================================

@app.route('/products')
@login_required
def products():
    product_manager = ProductManager(get_effective_user_id())
    products = product_manager.get_all(active_only=False)
    return render_template('products.html', products=products)


@app.route('/products/new', methods=['GET', 'POST'])
@login_required
def new_product():
    if request.method == 'POST':
        product_manager = ProductManager(get_effective_user_id())
        
        product_id = product_manager.create(
            name=request.form.get('name'),
            unit_price=float(request.form.get('unit_price', 0)),
            description=request.form.get('description'),
            unit=request.form.get('unit', 'unit'),
            sku=request.form.get('sku'),
            is_service=1 if request.form.get('is_service') else 0,
            billing_term=request.form.get('billing_term') or None,
            taxable=1 if request.form.get('taxable') else 0
        )
        
        # Update COA separately (not in allowed_fields)
        coa_id = request.form.get('coa_id')
        if coa_id:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE products SET coa_id = ? WHERE id = ?', (int(coa_id), product_id))
                conn.commit()
        
        product = product_manager.get(product_id)
        trigger_webhooks('product.created', get_effective_user_id(), serialize_product(product))
        
        flash('Product/Service created successfully.', 'success')
        return redirect(url_for('products'))
    
    # Get COA accounts for dropdown
    from recurring_invoices import ChartOfAccounts
    coa = ChartOfAccounts(get_effective_user_id())
    coa_accounts = coa.get_all(account_type='revenue')
    
    return render_template('product_form.html', product=None, coa_accounts=coa_accounts)


@app.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product_manager = ProductManager(get_effective_user_id())
    product = product_manager.get(product_id)
    
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('products'))
    
    if request.method == 'POST':
        product_manager.update(product_id, {
            'name': request.form.get('name'),
            'unit_price': float(request.form.get('unit_price', 0)),
            'description': request.form.get('description'),
            'unit': request.form.get('unit', 'unit'),
            'sku': request.form.get('sku'),
            'is_service': 1 if request.form.get('is_service') else 0,
            'billing_term': request.form.get('billing_term') or None,
            'taxable': 1 if request.form.get('taxable') else 0,
            'active': 1 if request.form.get('active') else 0
        })
        
        # Update COA separately
        coa_id = request.form.get('coa_id')
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE products SET coa_id = ? WHERE id = ?', 
                          (int(coa_id) if coa_id else None, product_id))
            conn.commit()
        
        product = product_manager.get(product_id)
        trigger_webhooks('product.updated', get_effective_user_id(), serialize_product(product))
        
        flash('Product/Service updated successfully.', 'success')
        return redirect(url_for('products'))
    
    # Get COA accounts for dropdown
    from recurring_invoices import ChartOfAccounts
    coa = ChartOfAccounts(get_effective_user_id())
    coa_accounts = coa.get_all(account_type='revenue')
    
    return render_template('product_form.html', product=product, coa_accounts=coa_accounts)


@app.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
def delete_product(product_id):
    product_manager = ProductManager(get_effective_user_id())
    product = product_manager.get(product_id)
    
    if product:
        trigger_webhooks('product.deleted', get_effective_user_id(), serialize_product(product))
        product_manager.delete(product_id)
        flash('Product/Service deactivated.', 'success')
    else:
        flash('Product not found.', 'error')
    
    return redirect(url_for('products'))


# =============================================================================
# Invoice Routes
# =============================================================================

@app.route('/invoices')
@login_required
def invoices():
    from app_core import get_user_preference, set_user_preference
    
    invoice_manager = InvoiceManager(get_effective_user_id())
    
    # Get status filter - check URL param first, then database preference
    status_filter = request.args.get('status')
    if status_filter is not None:
        # Save to database (empty string means "all")
        set_user_preference(get_effective_user_id(), 'invoices_status_filter', status_filter if status_filter else '')
        status_filter = status_filter if status_filter else None
    else:
        # Load from database preference
        status_filter = get_user_preference(get_effective_user_id(), 'invoices_status_filter', '')
        status_filter = status_filter if status_filter else None
    
    invoices = invoice_manager.get_all(status=status_filter)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    return render_template('invoices.html', invoices=invoices, 
                         status_filter=status_filter, currency_symbol=currency_symbol)


@app.route('/invoices/new', methods=['GET', 'POST'])
@login_required
def new_invoice():
    from recurring_invoices import ChartOfAccounts
    
    customer_manager = CustomerManager(get_effective_user_id())
    product_manager = ProductManager(get_effective_user_id())
    invoice_manager = InvoiceManager(get_effective_user_id())
    settings_manager = SettingsManager(get_effective_user_id())
    
    customers = customer_manager.get_all()
    products = product_manager.get_all()
    settings = settings_manager.get_settings()
    
    # Get COA accounts
    coa = ChartOfAccounts(get_effective_user_id())
    coa_accounts = coa.get_all(active_only=True)
    coa_mandatory = settings.get('coa_mandatory', 0)
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        customer_id = int(customer_id) if customer_id else None
        
        tax_rate = request.form.get('tax_rate')
        tax_rate = float(tax_rate) if tax_rate else settings.get('default_tax_rate', 0)
        
        currency = request.form.get('currency') or settings.get('default_currency', 'GBP')
        
        invoice_id = invoice_manager.create(
            customer_id=customer_id,
            tax_rate=tax_rate,
            currency=currency,
            issue_date=request.form.get('issue_date'),
            due_date=request.form.get('due_date'),
            notes=request.form.get('notes'),
            payment_terms=request.form.get('payment_terms') or settings.get('payment_terms', '')
        )
        
        # Add line items
        descriptions = request.form.getlist('item_description[]')
        quantities = request.form.getlist('item_quantity[]')
        prices = request.form.getlist('item_price[]')
        product_ids = request.form.getlist('item_product_id[]')
        coa_ids = request.form.getlist('item_coa_id[]')
        
        for i in range(len(descriptions)):
            if descriptions[i]:
                prod_id = int(product_ids[i]) if product_ids[i] else None
                coa_id = int(coa_ids[i]) if i < len(coa_ids) and coa_ids[i] else None
                item_id = invoice_manager.add_item(
                    invoice_id=invoice_id,
                    description=descriptions[i],
                    quantity=float(quantities[i]) if quantities[i] else 1,
                    unit_price=float(prices[i]) if prices[i] else 0,
                    product_id=prod_id,
                    tax_rate=tax_rate
                )
                # Update COA on item
                if coa_id:
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute('UPDATE invoice_items SET coa_id = ? WHERE id = ?', (coa_id, item_id))
                        conn.commit()
        
        invoice = invoice_manager.get(invoice_id)
        trigger_webhooks('invoice.created', get_effective_user_id(), serialize_invoice(invoice))
        
        flash('Invoice created successfully.', 'success')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    return render_template('invoice_form.html',
                         customers=customers,
                         products=products,
                         settings=settings,
                         invoice=None,
                         coa_accounts=coa_accounts,
                         coa_mandatory=coa_mandatory)


@app.route('/invoices/<int:invoice_id>')
@login_required
def view_invoice(invoice_id):
    invoice_manager = InvoiceManager(get_effective_user_id())
    invoice = invoice_manager.get(invoice_id)
    
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('invoices'))
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(invoice.get('currency', 'GBP'))
    
    # Auto-verify Stripe payments for unpaid invoices
    # This runs if: returning from Stripe OR invoice is unpaid and has a Stripe session
    payment_status = request.args.get('payment')
    if invoice.get('status') not in ['paid']:
        try:
            from stripe_integration import check_payment_status, StripeManager
            stripe_manager = StripeManager(get_effective_user_id())
            if stripe_manager.is_configured():
                # Check if there's a pending Stripe session for this invoice
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT session_id, status FROM stripe_payment_sessions
                        WHERE user_id = ? AND invoice_id = ? AND status != 'completed'
                        ORDER BY created_at DESC LIMIT 1
                    ''', (get_effective_user_id(), invoice_id))
                    pending_session = cursor.fetchone()
                
                if pending_session or payment_status == 'success':
                    success, message = check_payment_status(get_effective_user_id(), invoice_id)
                    if success and 'recorded' in message.lower():
                        flash(message, 'success')
                        # Reload invoice to get updated status
                        invoice = invoice_manager.get(invoice_id)
                    elif payment_status == 'success' and not success:
                        flash('Payment may still be processing. Try "Verify Payment" in a few seconds.', 'info')
        except Exception as e:
            # Silently handle errors
            print(f"Stripe auto-verify error: {e}")
            pass
    
    if payment_status == 'cancelled':
        flash('Payment was cancelled.', 'warning')
    
    # Check Stripe configuration
    stripe_enabled = False
    stripe_payment_url = None
    try:
        from stripe_integration import StripeManager, get_payment_link
        stripe_manager = StripeManager(get_effective_user_id())
        stripe_enabled = stripe_manager.is_configured()
        if stripe_enabled:
            stripe_payment_url = get_payment_link(get_effective_user_id(), invoice_id)
    except:
        pass
    
    # Check GoCardless configuration
    gocardless_enabled = False
    gocardless_mandate = None
    gocardless_payment = None
    try:
        from gocardless_integration import GoCardlessManager, get_customer_mandate, get_payment_status
        gc_manager = GoCardlessManager(get_effective_user_id())
        gocardless_enabled = gc_manager.is_configured()
        if gocardless_enabled and invoice.get('customer_id'):
            gocardless_mandate = get_customer_mandate(get_effective_user_id(), invoice['customer_id'])
            gocardless_payment = get_payment_status(get_effective_user_id(), invoice_id)
    except:
        pass
    
    return render_template('invoice_detail.html',
                         invoice=invoice,
                         settings=settings,
                         currency_symbol=currency_symbol,
                         stripe_enabled=stripe_enabled,
                         stripe_payment_url=stripe_payment_url,
                         gocardless_enabled=gocardless_enabled,
                         gocardless_mandate=gocardless_mandate,
                         gocardless_payment=gocardless_payment)


@app.route('/invoices/<int:invoice_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_invoice(invoice_id):
    from recurring_invoices import ChartOfAccounts
    
    invoice_manager = InvoiceManager(get_effective_user_id())
    customer_manager = CustomerManager(get_effective_user_id())
    product_manager = ProductManager(get_effective_user_id())
    settings_manager = SettingsManager(get_effective_user_id())
    
    invoice = invoice_manager.get(invoice_id)
    
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('invoices'))
    
    customers = customer_manager.get_all()
    products = product_manager.get_all()
    settings = settings_manager.get_settings()
    
    # Get COA accounts
    coa = ChartOfAccounts(get_effective_user_id())
    coa_accounts = coa.get_all(active_only=True)
    coa_mandatory = settings.get('coa_mandatory', 0)
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        customer_id = int(customer_id) if customer_id else None
        
        tax_rate = request.form.get('tax_rate')
        tax_rate = float(tax_rate) if tax_rate else 0
        
        invoice_manager.update(invoice_id, {
            'customer_id': customer_id,
            'tax_rate': tax_rate,
            'currency': request.form.get('currency'),
            'status': request.form.get('status'),
            'issue_date': request.form.get('issue_date'),
            'due_date': request.form.get('due_date'),
            'notes': request.form.get('notes'),
            'payment_terms': request.form.get('payment_terms')
        })
        
        # Clear existing items and re-add
        for item in invoice.get('items', []):
            invoice_manager.remove_item(item['id'])
        
        descriptions = request.form.getlist('item_description[]')
        quantities = request.form.getlist('item_quantity[]')
        prices = request.form.getlist('item_price[]')
        product_ids = request.form.getlist('item_product_id[]')
        coa_ids = request.form.getlist('item_coa_id[]')
        
        for i in range(len(descriptions)):
            if descriptions[i]:
                prod_id = int(product_ids[i]) if product_ids[i] else None
                coa_id = int(coa_ids[i]) if i < len(coa_ids) and coa_ids[i] else None
                item_id = invoice_manager.add_item(
                    invoice_id=invoice_id,
                    description=descriptions[i],
                    quantity=float(quantities[i]) if quantities[i] else 1,
                    unit_price=float(prices[i]) if prices[i] else 0,
                    product_id=prod_id,
                    tax_rate=tax_rate
                )
                # Update COA on item
                if coa_id:
                    with get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute('UPDATE invoice_items SET coa_id = ? WHERE id = ?', (coa_id, item_id))
                        conn.commit()
        
        invoice = invoice_manager.get(invoice_id)
        trigger_webhooks('invoice.updated', get_effective_user_id(), serialize_invoice(invoice))
        
        flash('Invoice updated successfully.', 'success')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    return render_template('invoice_form.html',
                         customers=customers,
                         products=products,
                         settings=settings,
                         invoice=invoice,
                         coa_accounts=coa_accounts,
                         coa_mandatory=coa_mandatory)


@app.route('/invoices/<int:invoice_id>/delete', methods=['POST'])
@login_required
def delete_invoice(invoice_id):
    invoice_manager = InvoiceManager(get_effective_user_id())
    invoice = invoice_manager.get(invoice_id)
    
    if invoice:
        try:
            trigger_webhooks('invoice.deleted', get_effective_user_id(), serialize_invoice(invoice))
            invoice_manager.delete(invoice_id)
            flash('Invoice deleted.', 'success')
        except ValueError as e:
            flash(str(e), 'error')
    else:
        flash('Invoice not found.', 'error')
    
    return redirect(url_for('invoices'))


@app.route('/invoices/<int:invoice_id>/status', methods=['POST'])
@login_required
def update_invoice_status(invoice_id):
    invoice_manager = InvoiceManager(get_effective_user_id())
    status = request.form.get('status')
    
    if invoice_manager.update(invoice_id, {'status': status}):
        invoice = invoice_manager.get(invoice_id)
        
        if status == 'sent':
            trigger_webhooks('invoice.sent', get_effective_user_id(), serialize_invoice(invoice))
        
        flash(f'Invoice status updated to {status}.', 'success')
    else:
        flash('Failed to update status.', 'error')
    
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


@app.route('/invoices/<int:invoice_id>/pay', methods=['GET', 'POST'])
@login_required
def pay_invoice(invoice_id):
    invoice_manager = InvoiceManager(get_effective_user_id())
    invoice = invoice_manager.get(invoice_id)
    
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('invoices'))
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(invoice.get('currency', 'GBP'))
    amount_due = invoice['total'] - invoice['amount_paid']
    
    if request.method == 'POST':
        amount = float(request.form.get('amount', 0))
        payment_method = request.form.get('payment_method')
        reference = request.form.get('reference')
        notes = request.form.get('notes')
        
        if amount > 0:
            payment_id = invoice_manager.add_payment(
                invoice_id=invoice_id,
                amount=amount,
                payment_method=payment_method,
                reference=reference,
                notes=notes,
                created_via='manual'
            )
            
            invoice = invoice_manager.get(invoice_id)
            
            if invoice['status'] == 'paid':
                trigger_webhooks('invoice.paid', get_effective_user_id(), serialize_invoice(invoice))
            else:
                trigger_webhooks('invoice.partially_paid', get_effective_user_id(), serialize_invoice(invoice))
            
            trigger_webhooks('payment.received', get_effective_user_id(), {
                'invoice': serialize_invoice(invoice),
                'payment': {
                    'amount': amount,
                    'payment_method': payment_method,
                    'reference': reference
                }
            })
            
            flash('Payment recorded successfully.', 'success')
        else:
            flash('Invalid payment amount.', 'error')
        
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    return render_template('payment_form.html',
                         invoice=invoice,
                         amount_due=amount_due,
                         currency_symbol=currency_symbol)


@app.route('/invoices/<int:invoice_id>/mark-paid', methods=['POST'])
@login_required
def mark_invoice_paid(invoice_id):
    invoice_manager = InvoiceManager(get_effective_user_id())
    
    payment_method = request.form.get('payment_method', 'Other')
    reference = request.form.get('reference', '')
    
    if invoice_manager.mark_as_paid(invoice_id, payment_method, reference):
        invoice = invoice_manager.get(invoice_id)
        trigger_webhooks('invoice.paid', get_effective_user_id(), serialize_invoice(invoice))
        flash('Invoice marked as paid.', 'success')
    else:
        flash('Failed to mark invoice as paid.', 'error')
    
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


@app.route('/invoices/<int:invoice_id>/pdf')
@login_required
def invoice_pdf(invoice_id):
    invoice_manager = InvoiceManager(get_effective_user_id())
    invoice = invoice_manager.get(invoice_id)
    
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('invoices'))
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    
    deps = check_dependencies()
    if not deps['ready']:
        flash('PDF generation requires reportlab. Using HTML instead.', 'warning')
        return redirect(url_for('invoice_html', invoice_id=invoice_id))
    
    try:
        pdf_buffer = generate_invoice_pdf(invoice, settings)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{invoice['invoice_number']}.pdf"
        )
    except Exception as e:
        flash(f'Error generating PDF: {str(e)}', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))


@app.route('/invoices/<int:invoice_id>/html')
@login_required
def invoice_html(invoice_id):
    invoice_manager = InvoiceManager(get_effective_user_id())
    invoice = invoice_manager.get(invoice_id)
    
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('invoices'))
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    
    html = generate_invoice_html(invoice, settings)
    return Response(html, mimetype='text/html')


# =============================================================================
# Bulk Operations
# =============================================================================

@app.route('/invoices/bulk')
@login_required
def bulk_invoices():
    """Bulk invoice management page."""
    invoice_manager = InvoiceManager(get_effective_user_id())
    invoices = invoice_manager.get_all()
    return render_template('bulk_invoices.html', invoices=invoices)


@app.route('/invoices/bulk/action', methods=['POST'])
@login_required
def bulk_invoices_action():
    """Process bulk invoice actions."""
    action = request.form.get('action')
    invoice_ids = request.form.getlist('invoice_ids')
    
    if not invoice_ids:
        flash('No invoices selected.', 'error')
        return redirect(url_for('bulk_invoices'))
    
    invoice_manager = InvoiceManager(get_effective_user_id())
    count = 0
    
    for invoice_id in invoice_ids:
        try:
            invoice_id = int(invoice_id)
            
            if action == 'mark_sent':
                if invoice_manager.update_status(invoice_id, 'sent'):
                    count += 1
            
            elif action == 'mark_paid':
                if invoice_manager.mark_as_paid(invoice_id, 'Bulk Action', ''):
                    invoice = invoice_manager.get(invoice_id)
                    trigger_webhooks('invoice.paid', get_effective_user_id(), serialize_invoice(invoice))
                    count += 1
            
            elif action == 'mark_draft':
                if invoice_manager.update_status(invoice_id, 'draft'):
                    count += 1
            
            elif action == 'mark_cancelled':
                if invoice_manager.update_status(invoice_id, 'cancelled'):
                    count += 1
            
            elif action == 'update_tax':
                tax_rate = request.form.get('tax_rate')
                if tax_rate:
                    tax_rate = float(tax_rate)
                    invoice = invoice_manager.get(invoice_id)
                    if invoice:
                        invoice_manager.update(invoice_id, tax_rate=tax_rate)
                        count += 1
            
            elif action == 'delete':
                if invoice_manager.delete(invoice_id):
                    trigger_webhooks('invoice.deleted', get_effective_user_id(), {'id': invoice_id})
                    count += 1
        
        except (ValueError, Exception) as e:
            continue
    
    if action == 'delete':
        flash(f'Deleted {count} invoice(s).', 'success')
    elif action == 'update_tax':
        flash(f'Updated tax rate on {count} invoice(s).', 'success')
    else:
        flash(f'Updated {count} invoice(s).', 'success')
    
    return redirect(url_for('bulk_invoices'))


@app.route('/customers/bulk')
@login_required
def bulk_customers():
    """Bulk customer management page."""
    customer_manager = CustomerManager(get_effective_user_id())
    invoice_manager = InvoiceManager(get_effective_user_id())
    
    customers = customer_manager.get_all()
    
    # Add invoice count for each customer
    for customer in customers:
        invoices = invoice_manager.get_all()
        customer['invoice_count'] = sum(1 for inv in invoices if inv.get('customer_id') == customer['id'])
    
    return render_template('bulk_customers.html', customers=customers)


@app.route('/customers/bulk/action', methods=['POST'])
@login_required
def bulk_customers_action():
    """Process bulk customer actions."""
    action = request.form.get('action')
    customer_ids = request.form.getlist('customer_ids')
    
    if not customer_ids:
        flash('No customers selected.', 'error')
        return redirect(url_for('bulk_customers'))
    
    # Handle export separately
    if action == 'export':
        from import_export import export_customers_csv
        customer_manager = CustomerManager(get_effective_user_id())
        
        # Get only selected customers
        all_customers = customer_manager.get_all()
        selected_ids = [int(cid) for cid in customer_ids]
        selected_customers = [c for c in all_customers if c['id'] in selected_ids]
        
        csv_content = export_customers_csv(selected_customers)
        
        response = Response(
            csv_content,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=customers_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'}
        )
        return response
    
    customer_manager = CustomerManager(get_effective_user_id())
    invoice_manager = InvoiceManager(get_effective_user_id())
    count = 0
    
    for customer_id in customer_ids:
        try:
            customer_id = int(customer_id)
            
            if action == 'update_country':
                country = request.form.get('country')
                if country:
                    if customer_manager.update(customer_id, country=country):
                        count += 1
            
            elif action == 'update_tax':
                tax_rate = request.form.get('tax_rate')
                if tax_rate:
                    tax_rate = float(tax_rate)
                    if customer_manager.update(customer_id, custom_tax_rate=tax_rate):
                        count += 1
            
            elif action == 'update_currency':
                currency = request.form.get('currency')
                if currency:
                    if customer_manager.update(customer_id, custom_currency=currency):
                        count += 1
            
            elif action == 'update_payment_terms':
                payment_terms = request.form.get('payment_terms')
                if payment_terms:
                    if customer_manager.update(customer_id, notes=payment_terms):
                        count += 1
            
            elif action == 'delete':
                # Delete customer's invoices first
                invoices = invoice_manager.get_all()
                for inv in invoices:
                    if inv.get('customer_id') == customer_id:
                        invoice_manager.delete(inv['id'])
                
                if customer_manager.delete(customer_id):
                    trigger_webhooks('customer.deleted', get_effective_user_id(), {'id': customer_id})
                    count += 1
        
        except (ValueError, Exception) as e:
            continue
    
    if action == 'delete':
        flash(f'Deleted {count} customer(s) and their invoices.', 'success')
    else:
        flash(f'Updated {count} customer(s).', 'success')
    
    return redirect(url_for('bulk_customers'))


# =============================================================================
# Import/Export Routes
# =============================================================================

@app.route('/export/customers')
@login_required
def export_customers():
    """Export customers to CSV."""
    from import_export import DataExporter
    
    exporter = DataExporter(get_effective_user_id())
    csv_data = exporter.export_customers()
    
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=customers.csv'}
    )


@app.route('/export/products')
@login_required
def export_products():
    """Export products to CSV."""
    from import_export import DataExporter
    
    exporter = DataExporter(get_effective_user_id())
    csv_data = exporter.export_products()
    
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=products.csv'}
    )


@app.route('/export/invoices')
@login_required
def export_invoices():
    """Export invoices to CSV."""
    from import_export import DataExporter
    
    exporter = DataExporter(get_effective_user_id())
    include_items = request.args.get('include_items', '1') == '1'
    csv_data = exporter.export_invoices(include_items=include_items)
    
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=invoices.csv'}
    )


@app.route('/import/customers', methods=['GET', 'POST'])
@login_required
def import_customers():
    """Import customers from CSV."""
    if request.method == 'POST':
        from import_export import DataImporter
        
        if 'file' not in request.files:
            flash('No file uploaded.', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected.', 'error')
            return redirect(request.url)
        
        if file and file.filename.endswith('.csv'):
            csv_data = file.read().decode('utf-8')
            update_existing = request.form.get('update_existing') == '1'
            
            importer = DataImporter(get_effective_user_id())
            imported, updated, errors = importer.import_customers(csv_data, update_existing)
            
            if errors:
                for error in errors[:5]:  # Show first 5 errors
                    flash(error, 'warning')
                if len(errors) > 5:
                    flash(f'...and {len(errors) - 5} more errors.', 'warning')
            
            flash(f'Imported {imported} customers, updated {updated}.', 'success')
            return redirect(url_for('customers'))
        else:
            flash('Please upload a CSV file.', 'error')
    
    return render_template('import_form.html', 
                          title='Import Customers',
                          description='Upload a CSV file with customer data. Required column: name. Optional: email, phone, address_line1, address_line2, city, state, postal_code, country, tax_number, custom_tax_rate, custom_currency, notes.',
                          back_url=url_for('customers'),
                          template_url=url_for('download_template', template_type='customers'))


@app.route('/import/products', methods=['GET', 'POST'])
@login_required
def import_products():
    """Import products from CSV."""
    if request.method == 'POST':
        from import_export import DataImporter
        
        if 'file' not in request.files:
            flash('No file uploaded.', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected.', 'error')
            return redirect(request.url)
        
        if file and file.filename.endswith('.csv'):
            csv_data = file.read().decode('utf-8')
            update_existing = request.form.get('update_existing') == '1'
            
            importer = DataImporter(get_effective_user_id())
            imported, updated, errors = importer.import_products(csv_data, update_existing)
            
            if errors:
                for error in errors[:5]:
                    flash(error, 'warning')
                if len(errors) > 5:
                    flash(f'...and {len(errors) - 5} more errors.', 'warning')
            
            flash(f'Imported {imported} products, updated {updated}.', 'success')
            return redirect(url_for('products'))
        else:
            flash('Please upload a CSV file.', 'error')
    
    return render_template('import_form.html',
                          title='Import Products',
                          description='Upload a CSV file with product data. Required columns: name, unit_price. Optional: description, unit, sku, is_service (0/1), taxable (0/1), active (0/1).',
                          back_url=url_for('products'),
                          template_url=url_for('download_template', template_type='products'))


@app.route('/import/template/<template_type>')
@login_required
def download_template(template_type):
    """Download CSV template for imports."""
    import io
    import csv
    
    templates = {
        'customers': {
            'filename': 'customer_import_template.csv',
            'headers': ['name', 'email', 'phone', 'address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country', 'tax_number', 'custom_tax_rate', 'custom_currency', 'notes'],
            'sample': ['Acme Corp', 'billing@acme.com', '+44 1234 567890', '123 Business Street', 'Suite 100', 'London', '', 'SW1A 1AA', 'United Kingdom', 'GB123456789', '', 'GBP', 'Important client']
        },
        'products': {
            'filename': 'product_import_template.csv',
            'headers': ['name', 'description', 'unit_price', 'unit', 'sku', 'is_service', 'taxable', 'active'],
            'sample': ['Consulting Hour', 'Professional consulting services', '150.00', 'hour', 'CONS-001', '1', '1', '1']
        },
        'invoices': {
            'filename': 'invoice_import_template.csv',
            'headers': ['customer_email', 'invoice_number', 'issue_date', 'due_date', 'currency', 'tax_rate', 'status', 'notes', 'item_description', 'item_quantity', 'item_unit_price'],
            'sample': ['billing@acme.com', 'INV-1001', '2025-01-01', '2025-01-31', 'GBP', '20', 'sent', 'Thank you for your business', 'Consulting services', '10', '150.00']
        },
        'suppliers': {
            'filename': 'supplier_import_template.csv',
            'headers': ['name', 'email', 'phone', 'address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country', 'tax_number', 'payment_terms', 'default_currency', 'notes'],
            'sample': ['Office Supplies Ltd', 'orders@officesupplies.com', '+44 1234 567890', '456 Industrial Way', '', 'Manchester', '', 'M1 1AA', 'United Kingdom', 'GB987654321', '30', 'GBP', 'Main stationery supplier']
        }
    }
    
    if template_type not in templates:
        flash('Unknown template type.', 'error')
        return redirect(url_for('dashboard'))
    
    template = templates[template_type]
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(template['headers'])
    writer.writerow(template['sample'])
    
    # Return as downloadable file
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={template["filename"]}'}
    )


@app.route('/import/invoices', methods=['GET', 'POST'])
@login_required
def import_invoices():
    """Import invoices from CSV."""
    if request.method == 'POST':
        from import_export import DataImporter
        
        if 'file' not in request.files:
            flash('No file uploaded.', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected.', 'error')
            return redirect(request.url)
        
        if file and file.filename.endswith('.csv'):
            csv_data = file.read().decode('utf-8')
            
            importer = DataImporter(get_effective_user_id())
            imported, errors = importer.import_invoices(csv_data)
            
            if errors:
                for error in errors[:5]:
                    flash(error, 'warning')
                if len(errors) > 5:
                    flash(f'...and {len(errors) - 5} more errors.', 'warning')
            
            flash(f'Imported {imported} invoices.', 'success')
            return redirect(url_for('invoices'))
        else:
            flash('Please upload a CSV file.', 'error')
    
    return render_template('import_form.html',
                          title='Import Invoices',
                          description='Upload a CSV file with invoice data. Columns: customer_id or customer_name, issue_date, due_date, currency, tax_rate, notes, payment_terms, status, items_json (JSON array of items).',
                          back_url=url_for('invoices'),
                          template_url=url_for('download_template', template_type='invoices'))


# =============================================================================
# Settings Routes
# =============================================================================

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    settings_manager = SettingsManager(get_effective_user_id())
    
    if request.method == 'POST':
        tax_rate = request.form.get('default_tax_rate')
        tax_rate = float(tax_rate) if tax_rate else 0
        
        updates = {
            'company_name': request.form.get('company_name'),
            'address_line1': request.form.get('address_line1'),
            'address_line2': request.form.get('address_line2'),
            'city': request.form.get('city'),
            'state': request.form.get('state'),
            'postal_code': request.form.get('postal_code'),
            'country': request.form.get('country'),
            'phone': request.form.get('phone'),
            'email': request.form.get('email'),
            'website': request.form.get('website'),
            'default_tax_rate': tax_rate,
            'default_currency': request.form.get('default_currency'),
            'invoice_prefix': request.form.get('invoice_prefix'),
            'payment_terms': request.form.get('payment_terms'),
            'bank_details': request.form.get('bank_details'),
            # Branding
            'brand_name': request.form.get('brand_name'),
            'show_brand_name': 1 if request.form.get('show_brand_name') else 0,
            'show_brand_logo': 1 if request.form.get('show_brand_logo') else 0,
            'show_powered_by': 1 if request.form.get('show_powered_by') else 0,
            # Footer settings
            'show_footer': 1 if request.form.get('show_footer') else 0,
            'footer_text': request.form.get('footer_text', 'Powered by Invoice Manager'),
            # Tax rates
            'tax_rates': request.form.get('tax_rates', '0,5,10,15,20,25'),
            # Tax Authority
            'tax_authority': request.form.get('tax_authority'),
            'tax_authority_api_key': request.form.get('tax_authority_api_key'),
            'tax_authority_email': request.form.get('tax_authority_email'),
            # Accountant Details
            'accountant_name': request.form.get('accountant_name'),
            'accountant_email': request.form.get('accountant_email'),
            'accountant_phone': request.form.get('accountant_phone'),
        }
        
        # Handle logo upload
        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"logo_{session['user_id']}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                updates['logo_path'] = filepath
        
        # Handle brand logo upload
        if 'brand_logo' in request.files:
            file = request.files['brand_logo']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"brand_{session['user_id']}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                updates['brand_logo_path'] = filepath
        
        settings_manager.update_settings(updates)
        flash('Settings updated successfully.', 'success')
        return redirect(url_for('settings'))
    
    current_settings = settings_manager.get_settings()
    return render_template('settings.html', settings=current_settings)


@app.route('/settings/password', methods=['POST'])
@login_required
def change_password_route():
    current = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm = request.form.get('confirm_password')
    
    if new_password != confirm:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('settings'))
    
    success, message = change_password(session['user_id'], current, new_password)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('settings'))


# =============================================================================
# API Key Management Routes
# =============================================================================

@app.route('/settings/api-keys')
@login_required
def api_keys():
    keys = get_user_api_keys(get_effective_user_id())
    return render_template('api_keys.html', api_keys=keys)


@app.route('/settings/api-keys/create', methods=['POST'])
@login_required
def create_api_key_route():
    name = request.form.get('name', 'API Key')
    permissions = request.form.getlist('permissions') or ['read', 'write']
    
    api_key = create_api_key(get_effective_user_id(), name, permissions)
    
    session['new_api_key'] = api_key
    session['new_api_key_name'] = name
    
    flash('API key created successfully. Copy it now - it won\'t be shown again!', 'success')
    return redirect(url_for('api_keys'))


@app.route('/settings/api-keys/<int:key_id>/revoke', methods=['POST'])
@login_required
def revoke_api_key_route(key_id):
    if revoke_api_key(get_effective_user_id(), key_id):
        flash('API key revoked.', 'success')
    else:
        flash('Failed to revoke API key.', 'error')
    return redirect(url_for('api_keys'))


@app.route('/settings/api-keys/<int:key_id>/delete', methods=['POST'])
@login_required
def delete_api_key_route(key_id):
    if delete_api_key_func(get_effective_user_id(), key_id):
        flash('API key deleted.', 'success')
    else:
        flash('Failed to delete API key.', 'error')
    return redirect(url_for('api_keys'))


# =============================================================================
# Webhook Management Routes
# =============================================================================

@app.route('/settings/webhooks')
@login_required
def webhooks():
    user_webhooks = get_user_webhooks(get_effective_user_id())
    return render_template('webhooks.html', webhooks=user_webhooks, webhook_events=WEBHOOK_EVENTS)


@app.route('/settings/webhooks/create', methods=['POST'])
@login_required
def create_webhook_route():
    name = request.form.get('name')
    url = request.form.get('url')
    events = request.form.getlist('events')
    auth_type = request.form.get('auth_type') or None
    auth_value = request.form.get('auth_value') or None
    
    # Collect custom headers
    header_keys = request.form.getlist('header_key')
    header_values = request.form.getlist('header_value')
    headers = {}
    for k, v in zip(header_keys, header_values):
        if k and v:
            headers[k] = v
    
    if not url or not events:
        flash('URL and at least one event are required.', 'error')
        return redirect(url_for('webhooks'))
    
    webhook = create_webhook(
        user_id=get_effective_user_id(),
        url=url,
        events=events,
        name=name,
        headers=headers,
        auth_type=auth_type,
        auth_value=auth_value
    )
    
    flash(f'Webhook created. Secret: {webhook["secret"]}', 'success')
    return redirect(url_for('webhooks'))


@app.route('/settings/webhooks/<webhook_id>/test', methods=['POST'])
@login_required
def test_webhook_route(webhook_id):
    result = test_webhook(webhook_id, get_effective_user_id())
    
    if result.get('success'):
        flash('Test webhook sent successfully!', 'success')
    else:
        flash(f'Webhook test failed: {result.get("error", "Unknown error")}', 'error')
    
    return redirect(url_for('webhooks'))


@app.route('/settings/webhooks/<webhook_id>/delete', methods=['POST'])
@login_required
def delete_webhook_route(webhook_id):
    if delete_webhook(webhook_id, get_effective_user_id()):
        flash('Webhook deleted.', 'success')
    else:
        flash('Failed to delete webhook.', 'error')
    return redirect(url_for('webhooks'))


@app.route('/settings/webhooks/<webhook_id>/edit', methods=['POST'])
@login_required
def edit_webhook_route(webhook_id):
    name = request.form.get('name')
    url = request.form.get('url')
    events = request.form.getlist('events')
    
    if not url or not events:
        flash('URL and at least one event are required.', 'error')
        return redirect(url_for('webhooks'))
    
    if update_webhook(webhook_id, get_effective_user_id(), name=name, url=url, events=events):
        flash('Webhook updated successfully.', 'success')
    else:
        flash('Failed to update webhook.', 'error')
    
    return redirect(url_for('webhooks'))


# =============================================================================
# Incoming Webhooks Routes
# =============================================================================

@app.route('/settings/incoming-webhooks')
@login_required
def incoming_webhooks():
    """Manage incoming webhook endpoints."""
    from incoming_webhooks import IncomingWebhookManager, WEBHOOK_PROVIDERS
    
    manager = IncomingWebhookManager(get_effective_user_id())
    webhooks = manager.get_all()
    
    return render_template('incoming_webhooks.html', 
                          webhooks=webhooks, 
                          providers=WEBHOOK_PROVIDERS)


@app.route('/settings/incoming-webhooks/create', methods=['POST'])
@login_required
def create_incoming_webhook():
    """Create a new incoming webhook endpoint."""
    from incoming_webhooks import IncomingWebhookManager
    
    manager = IncomingWebhookManager(get_effective_user_id())
    
    name = request.form.get('name')
    provider = request.form.get('provider', 'generic')
    description = request.form.get('description')
    
    if not name:
        flash('Name is required.', 'error')
        return redirect(url_for('incoming_webhooks'))
    
    webhook_id, endpoint_key, secret_key = manager.create(name, provider, description)
    
    flash(f'Webhook endpoint created. Your secret key is: {secret_key}', 'success')
    return redirect(url_for('view_incoming_webhook', webhook_id=webhook_id))


@app.route('/settings/incoming-webhooks/<int:webhook_id>')
@login_required
def view_incoming_webhook(webhook_id):
    """View incoming webhook details and logs."""
    from incoming_webhooks import IncomingWebhookManager, WEBHOOK_PROVIDERS
    
    manager = IncomingWebhookManager(get_effective_user_id())
    webhook = manager.get(webhook_id)
    
    if not webhook:
        flash('Webhook not found.', 'error')
        return redirect(url_for('incoming_webhooks'))
    
    logs = manager.get_logs(webhook_id, limit=50)
    
    return render_template('incoming_webhook_detail.html',
                          webhook=webhook,
                          logs=logs,
                          providers=WEBHOOK_PROVIDERS)


@app.route('/settings/incoming-webhooks/<int:webhook_id>/toggle', methods=['POST'])
@login_required
def toggle_incoming_webhook(webhook_id):
    """Toggle incoming webhook active status."""
    from incoming_webhooks import IncomingWebhookManager
    
    manager = IncomingWebhookManager(get_effective_user_id())
    webhook = manager.get(webhook_id)
    
    if webhook:
        manager.update(webhook_id, {'active': 0 if webhook['active'] else 1})
        status = 'disabled' if webhook['active'] else 'enabled'
        flash(f'Webhook {status}.', 'success')
    
    return redirect(url_for('incoming_webhooks'))


@app.route('/settings/incoming-webhooks/<int:webhook_id>/delete', methods=['POST'])
@login_required
def delete_incoming_webhook(webhook_id):
    """Delete an incoming webhook."""
    from incoming_webhooks import IncomingWebhookManager
    
    manager = IncomingWebhookManager(get_effective_user_id())
    manager.delete(webhook_id)
    
    flash('Webhook deleted.', 'success')
    return redirect(url_for('incoming_webhooks'))


@app.route('/settings/incoming-webhooks/<int:webhook_id>/regenerate', methods=['POST'])
@login_required
def regenerate_webhook_secret(webhook_id):
    """Regenerate the secret key for an incoming webhook."""
    from incoming_webhooks import IncomingWebhookManager
    
    manager = IncomingWebhookManager(get_effective_user_id())
    new_secret = manager.regenerate_secret(webhook_id)
    
    if new_secret:
        flash(f'Secret key regenerated: {new_secret}', 'success')
    else:
        flash('Failed to regenerate secret.', 'error')
    
    return redirect(url_for('view_incoming_webhook', webhook_id=webhook_id))


# Public endpoint for receiving webhooks (no login required)
@app.route('/webhook/incoming/<endpoint_key>', methods=['POST'])
def receive_incoming_webhook(endpoint_key):
    """
    Public endpoint for receiving payment webhooks.
    No authentication required - uses endpoint_key for identification.
    """
    from incoming_webhooks import (
        IncomingWebhookManager, verify_signature, process_payment_webhook
    )
    import json
    
    # Find the webhook by endpoint key
    manager = IncomingWebhookManager(0)  # User ID not needed for lookup
    webhook = manager.get_by_endpoint_key(endpoint_key)
    
    if not webhook:
        return jsonify({'success': False, 'error': 'Invalid endpoint'}), 404
    
    # Get payload and headers
    try:
        payload = request.get_json(force=True) or {}
    except:
        payload = {}
    
    headers = dict(request.headers)
    payload_bytes = request.get_data()
    
    # Verify signature if provider supports it
    provider = webhook.get('provider', 'generic')
    signature_header = None
    
    if provider == 'stripe':
        signature_header = headers.get('Stripe-Signature')
    elif provider == 'generic':
        signature_header = headers.get('X-Webhook-Signature')
    
    if signature_header and webhook.get('secret_key'):
        if not verify_signature(payload_bytes, signature_header, webhook['secret_key'], provider):
            # Log the failed attempt
            manager_for_user = IncomingWebhookManager(webhook['user_id'])
            manager_for_user.log_request(
                webhook['id'],
                json.dumps(payload),
                json.dumps({k: v for k, v in headers.items() if k.lower() != 'authorization'}),
                'error',
                'Signature verification failed'
            )
            return jsonify({'success': False, 'error': 'Invalid signature'}), 401
    
    # Process the webhook
    success, message, invoice_id = process_payment_webhook(webhook, payload, headers)
    
    # Log the request
    manager_for_user = IncomingWebhookManager(webhook['user_id'])
    manager_for_user.log_request(
        webhook['id'],
        json.dumps(payload),
        json.dumps({k: v for k, v in headers.items() if k.lower() not in ['authorization', 'stripe-signature']}),
        'success' if success else 'error',
        message,
        invoice_id
    )
    
    if success:
        return jsonify({'success': True, 'message': message, 'invoice_id': invoice_id})
    else:
        return jsonify({'success': False, 'error': message}), 400


# =============================================================================
# Integrations Routes (Currency API, etc.)
# =============================================================================

@app.route('/settings/integrations')
@login_required
def integrations():
    """Integrations configuration page."""
    from app_core import get_all_currency_rates, get_enabled_currencies
    from incoming_webhooks import IncomingWebhookManager
    from stripe_integration import StripeManager, init_stripe_tables
    from gocardless_integration import GoCardlessManager, init_gocardless_tables
    from sumup_integration import SumUpManager, init_sumup_tables
    from wise_integration import WiseManager, init_wise_tables
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_rates = get_all_currency_rates(get_effective_user_id())
    enabled_currencies = get_enabled_currencies(get_effective_user_id())
    
    # Default enabled currencies to base currency if none set
    if not enabled_currencies:
        enabled_currencies = [settings.get('default_currency', 'GBP')]
    
    # Get webhook counts
    outgoing_webhooks = get_user_webhooks(get_effective_user_id())
    outgoing_webhook_count = len(outgoing_webhooks)
    
    incoming_manager = IncomingWebhookManager(get_effective_user_id())
    incoming_webhooks = incoming_manager.get_all()
    incoming_webhook_count = len(incoming_webhooks)
    
    # Check Stripe configuration
    init_stripe_tables()
    stripe_manager = StripeManager(get_effective_user_id())
    stripe_configured = stripe_manager.is_configured()
    
    # Check GoCardless configuration
    init_gocardless_tables()
    gc_manager = GoCardlessManager(get_effective_user_id())
    gocardless_configured = gc_manager.is_configured()
    
    # Check SumUp configuration
    init_sumup_tables()
    sumup_manager = SumUpManager(get_effective_user_id())
    sumup_configured = sumup_manager.is_configured()
    
    # Auto-fix: If both Stripe and SumUp are enabled, disable SumUp (Stripe takes priority)
    if stripe_configured and sumup_configured:
        sumup_settings = sumup_manager.get_settings()
        sumup_settings['enabled'] = 0
        sumup_manager.save_settings(sumup_settings)
        sumup_configured = False
        flash('SumUp was automatically disabled because Stripe is active. Only one card provider can be enabled at a time.', 'info')
    
    # Check Wise configuration
    init_wise_tables()
    wise_manager = WiseManager(get_effective_user_id())
    wise_configured = wise_manager.is_configured()
    
    return render_template('integrations.html', 
                          settings=settings, 
                          currency_rates=currency_rates,
                          enabled_currencies=enabled_currencies,
                          outgoing_webhook_count=outgoing_webhook_count,
                          incoming_webhook_count=incoming_webhook_count,
                          stripe_configured=stripe_configured,
                          gocardless_configured=gocardless_configured,
                          sumup_configured=sumup_configured,
                          wise_configured=wise_configured)


@app.route('/settings/integrations/currency', methods=['POST'])
@login_required
def save_currency_integration():
    """Save currency API settings."""
    settings_manager = SettingsManager(get_effective_user_id())
    
    updates = {
        'currency_api_key': request.form.get('currency_api_key'),
        'default_currency': request.form.get('base_currency'),
        'auto_update_rates': 1 if request.form.get('auto_update_rates') else 0,
    }
    
    settings_manager.update_settings(updates)
    flash('Currency API settings saved.', 'success')
    return redirect(url_for('integrations'))


@app.route('/settings/integrations/currencies', methods=['POST'])
@login_required
def save_enabled_currencies():
    """Save enabled currencies."""
    from app_core import set_enabled_currencies
    
    currencies = request.form.getlist('currencies')
    set_enabled_currencies(get_effective_user_id(), currencies)
    
    flash('Enabled currencies saved.', 'success')
    return redirect(url_for('integrations'))


@app.route('/settings/integrations/rates/update', methods=['POST'])
@login_required
def update_currency_rates():
    """Fetch and update currency rates from API."""
    from app_core import set_currency_rate, get_enabled_currencies
    import requests as http_requests
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    api_key = settings.get('currency_api_key')
    base_currency = settings.get('default_currency', 'GBP')
    
    if not api_key:
        flash('Please configure your Currency API key first.', 'error')
        return redirect(url_for('integrations'))
    
    try:
        # Get enabled currencies
        enabled = get_enabled_currencies(get_effective_user_id())
        if not enabled:
            enabled = list(CURRENCIES.keys())
        
        # Filter out base currency
        target_currencies = [c for c in enabled if c != base_currency]
        
        if not target_currencies:
            flash('No target currencies to update.', 'warning')
            return redirect(url_for('integrations'))
        
        # Call Currency API
        currencies_param = ','.join(target_currencies)
        url = f"https://api.currencyapi.com/v3/latest?apikey={api_key}&base_currency={base_currency}&currencies={currencies_param}"
        
        response = http_requests.get(url, timeout=10)
        data = response.json()
        
        if 'data' in data:
            count = 0
            for code, info in data['data'].items():
                rate = info.get('value', 1.0)
                set_currency_rate(get_effective_user_id(), base_currency, code, rate)
                count += 1
            
            # Update last updated timestamp
            settings_manager = SettingsManager(get_effective_user_id())
            settings_manager.update_settings({'rates_last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            
            flash(f'Successfully updated {count} exchange rates.', 'success')
        else:
            error_msg = data.get('message', 'Unknown API error')
            flash(f'API error: {error_msg}', 'error')
            
    except Exception as e:
        flash(f'Failed to update rates: {str(e)}', 'error')
    
    return redirect(url_for('integrations'))


@app.route('/settings/integrations/rates/manual', methods=['POST'])
@login_required
def save_manual_rate():
    """Save a manually entered exchange rate."""
    from app_core import set_currency_rate
    
    from_currency = request.form.get('from_currency')
    to_currency = request.form.get('to_currency')
    rate = request.form.get('rate')
    
    if not all([from_currency, to_currency, rate]):
        flash('All fields are required.', 'error')
        return redirect(url_for('integrations'))
    
    try:
        rate = float(rate)
        set_currency_rate(get_effective_user_id(), from_currency, to_currency, rate)
        flash(f'Exchange rate saved: 1 {from_currency} = {rate} {to_currency}', 'success')
    except ValueError:
        flash('Invalid rate value.', 'error')
    
    return redirect(url_for('integrations'))


@app.route('/settings/integrations/test-api', methods=['POST'])
@login_required
def test_currency_api():
    """Test the currency API connection."""
    import requests as http_requests
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    api_key = settings.get('currency_api_key')
    
    if not api_key:
        return jsonify({'success': False, 'error': 'No API key configured'})
    
    try:
        url = f"https://api.currencyapi.com/v3/status?apikey={api_key}"
        response = http_requests.get(url, timeout=10)
        
        if response.status_code == 200:
            return jsonify({'success': True})
        else:
            data = response.json()
            return jsonify({'success': False, 'error': data.get('message', 'API request failed')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# =============================================================================
# Stripe Integration Routes
# =============================================================================

@app.route('/settings/integrations/stripe', methods=['GET', 'POST'])
@login_required
def stripe_settings():
    """Stripe integration settings page."""
    from stripe_integration import StripeManager, init_stripe_tables
    from sumup_integration import SumUpManager, init_sumup_tables
    
    # Ensure tables exist
    init_stripe_tables()
    init_sumup_tables()
    
    stripe_manager = StripeManager(get_effective_user_id())
    sumup_manager = SumUpManager(get_effective_user_id())
    
    if request.method == 'POST':
        enabled = request.form.get('enabled') == '1'
        
        # Check if SumUp is enabled and user wants to enable Stripe
        if enabled and sumup_manager.is_configured():
            # Check if user confirmed to disable SumUp
            if request.form.get('disable_other_provider') == '1':
                # Disable SumUp
                sumup_settings = sumup_manager.get_settings()
                sumup_settings['enabled'] = 0
                sumup_manager.save_settings(sumup_settings)
                flash('SumUp has been disabled.', 'info')
            else:
                # Show confirmation needed
                flash('SumUp is currently enabled. Only one card provider can be active at a time.', 'warning')
                return redirect(url_for('stripe_settings', confirm_disable_sumup=1))
        
        data = {
            'enabled': 1 if enabled else 0,
            'live_mode': 1 if request.form.get('live_mode') == '1' else 0,
            'test_publishable_key': request.form.get('test_publishable_key') or None,
            'test_secret_key': request.form.get('test_secret_key') or None,
            'live_publishable_key': request.form.get('live_publishable_key') or None,
            'live_secret_key': request.form.get('live_secret_key') or None,
            'webhook_secret': request.form.get('webhook_secret') or None,
            'include_in_invoice_pdf': 1 if request.form.get('include_in_invoice_pdf') else 0,
            'include_in_email': 1 if request.form.get('include_in_email') else 0,
            'payment_button_text': request.form.get('payment_button_text') or 'Pay Now with Card',
            'success_url': request.form.get('success_url') or None,
            'cancel_url': request.form.get('cancel_url') or None,
        }
        
        stripe_manager.save_settings(data)
        flash('Stripe settings saved successfully.', 'success')
        return redirect(url_for('stripe_settings'))
    
    stripe_settings_data = stripe_manager.get_settings()
    is_configured = stripe_manager.is_configured()
    sumup_enabled = sumup_manager.is_configured()
    
    # Check if we need to show confirmation dialog
    show_disable_confirmation = request.args.get('confirm_disable_sumup') == '1'
    
    # Get webhook logs
    webhook_logs = []
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM stripe_webhook_logs 
            WHERE user_id = ? 
            ORDER BY received_at DESC 
            LIMIT 20
        ''', (get_effective_user_id(),))
        webhook_logs = [dict(row) for row in cursor.fetchall()]
    
    return render_template('stripe_settings.html',
                          stripe_settings=stripe_settings_data,
                          is_configured=is_configured,
                          sumup_enabled=sumup_enabled,
                          show_disable_confirmation=show_disable_confirmation,
                          webhook_logs=webhook_logs)


@app.route('/invoices/<int:invoice_id>/stripe-payment-link', methods=['POST'])
@login_required
def create_stripe_payment_link(invoice_id):
    """Create a Stripe payment link for an invoice."""
    from stripe_integration import create_payment_link, StripeManager
    
    stripe_manager = StripeManager(get_effective_user_id())
    if not stripe_manager.is_configured():
        flash('Stripe is not configured. Please set up Stripe in Settings → Integrations.', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    base_url = request.host_url.rstrip('/')
    result = create_payment_link(get_effective_user_id(), invoice_id, base_url)
    
    if result:
        flash(f'Payment link created! Amount: {result["currency"]} {result["amount"]:.2f}', 'success')
    else:
        flash('Failed to create payment link. Check your Stripe configuration.', 'error')
    
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


@app.route('/invoices/<int:invoice_id>/send-stripe-link', methods=['POST'])
@login_required
def send_stripe_payment_link(invoice_id):
    """Send existing Stripe payment link to customer via email."""
    from stripe_integration import get_payment_link
    from email_module import EmailManager
    
    user_id = get_effective_user_id()
    invoice_manager = InvoiceManager(user_id)
    settings_manager = SettingsManager(user_id)
    
    invoice = invoice_manager.get(invoice_id)
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('invoices'))
    
    if not invoice.get('customer_email'):
        flash('Customer has no email address.', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    # Get the payment link
    payment_url = get_payment_link(user_id, invoice_id)
    if not payment_url:
        flash('No payment link found. Generate one first.', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    settings = settings_manager.get_settings()
    symbol = get_currency_symbol(invoice.get('currency', 'GBP'))
    amount_due = (invoice.get('total', 0) or 0) - (invoice.get('amount_paid', 0) or 0)
    
    # Send email with payment link
    email_manager = EmailManager(user_id)
    subject = f"Payment Link - Invoice {invoice.get('invoice_number')} from {settings.get('company_name', 'Our Company')}"
    body = f"""Dear {invoice.get('customer_name', 'Customer')},

Please use the link below to pay invoice {invoice.get('invoice_number')}:

Amount Due: {symbol}{amount_due:.2f}

Pay Now: {payment_url}

This is a secure payment link powered by Stripe.

If you have any questions, please don't hesitate to contact us.

Best regards,
{settings.get('company_name', 'Our Company')}
{settings.get('email', '')}"""
    
    success, message = email_manager.send_email(
        invoice['customer_email'],
        subject,
        body
    )
    
    if success:
        flash(f'Payment link sent to {invoice["customer_email"]}!', 'success')
    else:
        flash(f'Failed to send email: {message}', 'error')
    
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


@app.route('/invoices/<int:invoice_id>/generate-and-send-stripe-link', methods=['POST'])
@login_required
def generate_and_send_stripe_link(invoice_id):
    """Generate Stripe payment link and immediately send to customer."""
    from stripe_integration import create_payment_link, StripeManager
    from email_module import EmailManager
    
    user_id = get_effective_user_id()
    invoice_manager = InvoiceManager(user_id)
    settings_manager = SettingsManager(user_id)
    
    # Check Stripe is configured
    stripe_manager = StripeManager(user_id)
    if not stripe_manager.is_configured():
        flash('Stripe is not configured. Please set up Stripe in Settings → Integrations.', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    invoice = invoice_manager.get(invoice_id)
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('invoices'))
    
    if not invoice.get('customer_email'):
        flash('Customer has no email address.', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    # Generate payment link
    base_url = request.host_url.rstrip('/')
    result = create_payment_link(user_id, invoice_id, base_url)
    
    if not result:
        flash('Failed to create payment link. Check your Stripe configuration.', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    payment_url = f"{base_url}/pay/stripe/{invoice_id}"
    settings = settings_manager.get_settings()
    symbol = get_currency_symbol(invoice.get('currency', 'GBP'))
    amount_due = (invoice.get('total', 0) or 0) - (invoice.get('amount_paid', 0) or 0)
    
    # Send email with payment link
    email_manager = EmailManager(user_id)
    subject = f"Payment Link - Invoice {invoice.get('invoice_number')} from {settings.get('company_name', 'Our Company')}"
    body = f"""Dear {invoice.get('customer_name', 'Customer')},

Please use the link below to pay invoice {invoice.get('invoice_number')}:

Amount Due: {symbol}{amount_due:.2f}

Pay Now: {payment_url}

This is a secure payment link powered by Stripe.

If you have any questions, please don't hesitate to contact us.

Best regards,
{settings.get('company_name', 'Our Company')}
{settings.get('email', '')}"""
    
    success, message = email_manager.send_email(
        invoice['customer_email'],
        subject,
        body
    )
    
    if success:
        flash(f'Payment link generated and sent to {invoice["customer_email"]}!', 'success')
    else:
        flash(f'Payment link created but failed to send email: {message}', 'error')
    
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


@app.route('/invoices/<int:invoice_id>/check-stripe-payment', methods=['POST'])
@login_required
def check_stripe_payment(invoice_id):
    """
    Manually check Stripe payment status for an invoice.
    Useful when webhooks are not configured (e.g., local testing).
    """
    from stripe_integration import check_payment_status, StripeManager
    
    stripe_manager = StripeManager(get_effective_user_id())
    if not stripe_manager.is_configured():
        flash('Stripe is not configured.', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    success, message = check_payment_status(get_effective_user_id(), invoice_id)
    
    if success:
        flash(message, 'success')
    else:
        flash(message, 'warning')
    
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


# Public Stripe webhook endpoint (no login required)
@app.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    """
    Stripe webhook endpoint for receiving payment notifications.
    """
    from stripe_integration import (
        verify_stripe_signature, process_stripe_webhook, 
        log_stripe_webhook, StripeManager
    )
    import json
    
    payload = request.get_data()
    signature = request.headers.get('Stripe-Signature', '')
    
    try:
        event = json.loads(payload)
    except:
        return jsonify({'error': 'Invalid JSON'}), 400
    
    event_type = event.get('type', '')
    event_id = event.get('id', '')
    
    # Get user_id from metadata
    data = event.get('data', {}).get('object', {})
    metadata = data.get('metadata', {})
    user_id = metadata.get('user_id')
    
    if not user_id:
        # Try to find from session
        session_id = data.get('id') if event_type.startswith('checkout') else None
        if session_id:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT user_id FROM stripe_payment_sessions WHERE session_id = ?',
                    (session_id,)
                )
                row = cursor.fetchone()
                if row:
                    user_id = row['user_id']
    
    if user_id:
        user_id = int(user_id)
        
        # Verify signature if webhook secret is configured
        stripe_manager = StripeManager(user_id)
        settings = stripe_manager.get_settings()
        webhook_secret = settings.get('webhook_secret')
        
        if webhook_secret and signature:
            if not verify_stripe_signature(payload, signature, webhook_secret):
                log_stripe_webhook(user_id, event_type, event_id, 'error', 'Invalid signature')
                return jsonify({'error': 'Invalid signature'}), 401
        
        # Process the webhook
        success, message, invoice_id = process_stripe_webhook(event, user_id)
        
        # Log the event
        log_stripe_webhook(
            user_id, event_type, event_id,
            'success' if success else 'error',
            message, invoice_id,
            json.dumps(event)[:5000]  # Limit payload size
        )
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'error': message}), 400
    
    # No user_id found - acknowledge but can't process
    return jsonify({'received': True, 'message': 'Event acknowledged, no user context'})


# =============================================================================
# GoCardless Integration Routes
# =============================================================================

@app.route('/settings/integrations/gocardless', methods=['GET', 'POST'])
@login_required
def gocardless_settings():
    """GoCardless integration settings page."""
    from gocardless_integration import GoCardlessManager, init_gocardless_tables
    
    # Ensure tables exist
    init_gocardless_tables()
    
    gc_manager = GoCardlessManager(get_effective_user_id())
    
    if request.method == 'POST':
        data = {
            'enabled': 1 if request.form.get('enabled') else 0,
            'live_mode': 1 if request.form.get('live_mode') == '1' else 0,
            'sandbox_access_token': request.form.get('sandbox_access_token') or None,
            'live_access_token': request.form.get('live_access_token') or None,
            'webhook_secret': request.form.get('webhook_secret') or None,
            'include_in_invoice_pdf': 1 if request.form.get('include_in_invoice_pdf') else 0,
            'include_in_email': 1 if request.form.get('include_in_email') else 0,
            'payment_description': request.form.get('payment_description') or 'Invoice Payment',
            'days_until_collection': int(request.form.get('days_until_collection') or 5),
            'success_redirect_url': request.form.get('success_redirect_url') or None,
        }
        
        gc_manager.save_settings(data)
        flash('GoCardless settings saved successfully.', 'success')
        return redirect(url_for('gocardless_settings'))
    
    gc_settings = gc_manager.get_settings()
    is_configured = gc_manager.is_configured()
    
    # Get mandates with customer names
    mandates = []
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT m.*, c.name as customer_name
            FROM gocardless_mandates m
            LEFT JOIN customers c ON m.customer_id = c.id
            WHERE m.user_id = ?
            ORDER BY m.created_at DESC
            LIMIT 50
        ''', (get_effective_user_id(),))
        mandates = [dict(row) for row in cursor.fetchall()]
    
    # Get webhook logs
    webhook_logs = []
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM gocardless_webhook_logs 
            WHERE user_id = ? 
            ORDER BY received_at DESC 
            LIMIT 20
        ''', (get_effective_user_id(),))
        webhook_logs = [dict(row) for row in cursor.fetchall()]
    
    return render_template('gocardless_settings.html',
                          gc_settings=gc_settings,
                          is_configured=is_configured,
                          mandates=mandates,
                          webhook_logs=webhook_logs)


@app.route('/customers/<int:customer_id>/setup-direct-debit', methods=['GET', 'POST'])
@login_required
def setup_direct_debit(customer_id):
    """Create a GoCardless billing request flow for customer mandate setup."""
    from gocardless_integration import create_billing_request_flow, GoCardlessManager
    
    gc_manager = GoCardlessManager(get_effective_user_id())
    if not gc_manager.is_configured():
        flash('GoCardless is not configured. Please set up GoCardless in Settings → Integrations.', 'error')
        return redirect(url_for('view_customer', customer_id=customer_id))
    
    base_url = request.host_url.rstrip('/')
    result = create_billing_request_flow(get_effective_user_id(), customer_id, base_url)
    
    if result and 'authorisation_url' in result:
        # Redirect customer to GoCardless to complete mandate setup
        return redirect(result['authorisation_url'])
    else:
        flash('Failed to create Direct Debit setup link. Please check your GoCardless configuration.', 'error')
        return redirect(url_for('view_customer', customer_id=customer_id))


@app.route('/settings/integrations/gocardless/mandate-complete')
@login_required
def gocardless_mandate_complete():
    """Redirect page after mandate setup."""
    flash('Direct Debit mandate setup initiated. It may take a few minutes to become active.', 'success')
    return redirect(url_for('customers'))


@app.route('/invoices/<int:invoice_id>/gocardless-payment', methods=['POST'])
@login_required
def create_gocardless_payment(invoice_id):
    """Create a GoCardless payment for an invoice."""
    from gocardless_integration import create_payment, GoCardlessManager
    
    gc_manager = GoCardlessManager(get_effective_user_id())
    if not gc_manager.is_configured():
        flash('GoCardless is not configured. Please set up GoCardless in Settings → Integrations.', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    result = create_payment(get_effective_user_id(), invoice_id)
    
    if result:
        if 'error' in result:
            flash(result['error'], 'error')
        else:
            flash(f'Direct Debit payment requested! Amount: {result["currency"]} {result["amount"]:.2f}. Collection date: {result["charge_date"]}', 'success')
    else:
        flash('Failed to create payment. Check your GoCardless configuration.', 'error')
    
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


# Public GoCardless webhook endpoint (no login required)
@app.route('/webhook/gocardless', methods=['POST'])
def gocardless_webhook():
    """
    GoCardless webhook endpoint for receiving payment notifications.
    """
    from gocardless_integration import (
        verify_gocardless_signature, process_gocardless_webhook,
        log_gocardless_webhook, GoCardlessManager
    )
    import json
    
    payload = request.get_data()
    signature = request.headers.get('Webhook-Signature', '')
    
    try:
        event_data = json.loads(payload)
    except:
        return jsonify({'error': 'Invalid JSON'}), 400
    
    events = event_data.get('events', [])
    
    # Process each event
    for event in events:
        # Try to find user_id from metadata or payment record
        user_id = None
        links = event.get('links', {})
        
        # Try to find from payment
        payment_id = links.get('payment')
        if payment_id:
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT user_id FROM gocardless_payments WHERE gc_payment_id = ?',
                    (payment_id,)
                )
                row = cursor.fetchone()
                if row:
                    user_id = row['user_id']
        
        # Try to find from mandate
        if not user_id:
            mandate_id = links.get('mandate')
            if mandate_id:
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        'SELECT user_id FROM gocardless_mandates WHERE gc_mandate_id = ?',
                        (mandate_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        user_id = row['user_id']
        
        if user_id:
            # Verify signature if webhook secret is configured
            gc_manager = GoCardlessManager(user_id)
            settings = gc_manager.get_settings()
            webhook_secret = settings.get('webhook_secret')
            
            if webhook_secret and signature:
                if not verify_gocardless_signature(payload, signature, webhook_secret):
                    log_gocardless_webhook(user_id, event, 'error', 'Invalid signature')
                    continue
            
            # Process the webhook
            success, message, invoice_id = process_gocardless_webhook(event_data, user_id)
            
            # Log the event
            log_gocardless_webhook(
                user_id, event,
                'success' if success else 'error',
                message, invoice_id,
                json.dumps(event)[:5000]
            )
    
    # Always acknowledge receipt
    return jsonify({'received': True})


# =============================================================================
# SumUp Integration Routes
# =============================================================================

@app.route('/settings/integrations/sumup', methods=['GET', 'POST'])
@login_required
def sumup_settings():
    """SumUp integration settings page."""
    from sumup_integration import SumUpManager, init_sumup_tables
    from stripe_integration import StripeManager, init_stripe_tables
    
    # Ensure tables exist
    init_sumup_tables()
    init_stripe_tables()
    
    sumup_manager = SumUpManager(get_effective_user_id())
    stripe_manager = StripeManager(get_effective_user_id())
    
    if request.method == 'POST':
        enabled = request.form.get('enabled') == '1'
        
        # Check if Stripe is enabled and user wants to enable SumUp
        if enabled and stripe_manager.is_configured():
            # Check if user confirmed to disable Stripe
            if request.form.get('disable_other_provider') == '1':
                # Disable Stripe
                stripe_settings_data = stripe_manager.get_settings()
                stripe_settings_data['enabled'] = 0
                stripe_manager.save_settings(stripe_settings_data)
                flash('Stripe has been disabled.', 'info')
            else:
                # Show confirmation needed
                flash('Stripe is currently enabled. Only one card provider can be active at a time.', 'warning')
                return redirect(url_for('sumup_settings', confirm_disable_stripe=1))
        
        data = {
            'enabled': 1 if enabled else 0,
            'api_key': request.form.get('api_key') or None,
            'merchant_code': request.form.get('merchant_code') or None,
            'include_in_invoice_pdf': 1 if request.form.get('include_in_invoice_pdf') else 0,
            'include_in_email': 1 if request.form.get('include_in_email') else 0,
            'payment_description': request.form.get('payment_description') or 'Invoice Payment',
        }
        
        sumup_manager.save_settings(data)
        flash('SumUp settings saved successfully.', 'success')
        return redirect(url_for('sumup_settings'))
    
    sumup_settings_data = sumup_manager.get_settings()
    is_configured = sumup_manager.is_configured()
    stripe_enabled = stripe_manager.is_configured()
    
    # Check if we need to show confirmation dialog
    show_disable_confirmation = request.args.get('confirm_disable_stripe') == '1'
    
    # Get webhook logs
    webhook_logs = []
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM sumup_webhook_logs 
            WHERE user_id = ? 
            ORDER BY received_at DESC 
            LIMIT 20
        ''', (get_effective_user_id(),))
        webhook_logs = [dict(row) for row in cursor.fetchall()]
    
    return render_template('sumup_settings.html',
                          sumup_settings=sumup_settings_data,
                          is_configured=is_configured,
                          stripe_enabled=stripe_enabled,
                          show_disable_confirmation=show_disable_confirmation,
                          webhook_logs=webhook_logs)


@app.route('/invoices/<int:invoice_id>/sumup-pay')
def sumup_pay_invoice(invoice_id):
    """
    SumUp payment page with Payment Widget.
    This page is public - customers access it via payment link.
    """
    from sumup_integration import get_or_create_checkout, SumUpManager, init_sumup_tables
    
    init_sumup_tables()
    
    # Get invoice
    invoice_manager = InvoiceManager(None)  # We need to find the invoice without user context
    
    # Find the invoice and its user
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM invoices WHERE id = ?', (invoice_id,))
        invoice = cursor.fetchone()
    
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('dashboard'))
    
    invoice = dict(invoice)
    user_id = invoice['user_id']
    
    # Check SumUp is configured for this user
    sumup_manager = SumUpManager(user_id)
    if not sumup_manager.is_configured():
        flash('Online payments are not available for this invoice.', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    # Check invoice is not already paid
    amount_due = invoice.get('total', 0) - invoice.get('amount_paid', 0)
    if amount_due <= 0:
        flash('This invoice has already been paid.', 'info')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    # Create or get existing checkout
    redirect_url = request.host_url.rstrip('/') + url_for('sumup_payment_callback')
    checkout = get_or_create_checkout(user_id, invoice_id, redirect_url)
    
    if 'error' in checkout:
        flash(f'Error creating checkout: {checkout["error"]}', 'error')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    # Get customer info
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM customers WHERE id = ?', (invoice.get('customer_id'),))
        customer = cursor.fetchone()
        if customer:
            invoice['customer_name'] = customer['name']
    
    settings = SettingsManager(user_id).get_settings()
    currency_symbol = get_currency_symbol(invoice.get('currency', 'GBP'))
    
    return render_template('sumup_pay.html',
                          invoice=invoice,
                          checkout_id=checkout['checkout_id'],
                          amount_due=amount_due,
                          currency_symbol=currency_symbol)


@app.route('/sumup/verify/<checkout_id>', methods=['POST'])
def sumup_verify_payment(checkout_id):
    """
    Verify payment with SumUp API after widget reports success.
    Called via AJAX from the payment page.
    """
    from sumup_integration import verify_and_record_payment, log_sumup_event
    
    # Find the checkout to get user_id
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, invoice_id FROM sumup_checkouts WHERE checkout_id = ?', (checkout_id,))
        checkout = cursor.fetchone()
    
    if not checkout:
        return jsonify({'success': False, 'message': 'Checkout not found'})
    
    user_id = checkout['user_id']
    invoice_id = checkout['invoice_id']
    
    # Verify and record payment
    success, message, _ = verify_and_record_payment(user_id, checkout_id)
    
    # Log the event
    log_sumup_event(
        user_id, 'payment_verification', checkout_id,
        'success' if success else 'error',
        message, invoice_id
    )
    
    return jsonify({'success': success, 'message': message})


@app.route('/sumup/callback')
def sumup_payment_callback():
    """
    Callback URL for 3DS redirect.
    SumUp redirects here after 3DS authentication.
    """
    from sumup_integration import handle_sumup_callback
    
    checkout_id = request.args.get('checkout_id') or request.args.get('id')
    
    if not checkout_id:
        flash('Invalid payment callback.', 'error')
        return redirect(url_for('dashboard'))
    
    success, message, invoice_id, user_id = handle_sumup_callback(checkout_id)
    
    if success:
        flash('Payment successful! Thank you.', 'success')
    else:
        flash(f'Payment issue: {message}', 'error')
    
    if invoice_id:
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    
    return redirect(url_for('dashboard'))


# =============================================================================
# Wise Integration Routes
# =============================================================================

@app.route('/settings/integrations/wise', methods=['GET', 'POST'])
@login_required
def wise_settings():
    """Wise integration settings page."""
    from wise_integration import WiseManager, init_wise_tables, get_unmatched_credits
    import json
    
    # Ensure tables exist
    init_wise_tables()
    
    wise_manager = WiseManager(get_effective_user_id())
    
    if request.method == 'POST':
        # Build bank details JSON
        gbp_details = {}
        if request.form.get('gbp_account_name'):
            gbp_details = {
                'account_name': request.form.get('gbp_account_name'),
                'sort_code': request.form.get('gbp_sort_code'),
                'account_number': request.form.get('gbp_account_number')
            }
        
        eur_details = {}
        if request.form.get('eur_account_name'):
            eur_details = {
                'account_name': request.form.get('eur_account_name'),
                'iban': request.form.get('eur_iban'),
                'bic': request.form.get('eur_bic')
            }
        
        usd_details = {}
        if request.form.get('usd_account_name'):
            usd_details = {
                'account_name': request.form.get('usd_account_name'),
                'routing_number': request.form.get('usd_routing_number'),
                'account_number': request.form.get('usd_account_number'),
                'account_type': request.form.get('usd_account_type', 'Checking')
            }
        
        data = {
            'enabled': 1 if request.form.get('enabled') else 0,
            'live_mode': 1 if request.form.get('live_mode') == '1' else 0,
            'sandbox_api_token': request.form.get('sandbox_api_token') or None,
            'live_api_token': request.form.get('live_api_token') or None,
            'profile_id': request.form.get('profile_id') or None,
            'include_in_invoice_pdf': 1 if request.form.get('include_in_invoice_pdf') else 0,
            'include_in_email': 1 if request.form.get('include_in_email') else 0,
            'gbp_account_details': json.dumps(gbp_details) if gbp_details else None,
            'eur_account_details': json.dumps(eur_details) if eur_details else None,
            'usd_account_details': json.dumps(usd_details) if usd_details else None,
        }
        
        wise_manager.save_settings(data)
        flash('Wise settings saved successfully.', 'success')
        return redirect(url_for('wise_settings'))
    
    wise_settings_data = wise_manager.get_settings()
    is_configured = wise_manager.is_configured()
    
    # Parse bank details
    gbp_details = None
    eur_details = None
    usd_details = None
    try:
        if wise_settings_data.get('gbp_account_details'):
            gbp_details = json.loads(wise_settings_data['gbp_account_details'])
        if wise_settings_data.get('eur_account_details'):
            eur_details = json.loads(wise_settings_data['eur_account_details'])
        if wise_settings_data.get('usd_account_details'):
            usd_details = json.loads(wise_settings_data['usd_account_details'])
    except:
        pass
    
    # Get unmatched credits
    unmatched_credits = get_unmatched_credits(get_effective_user_id())
    
    # Get webhook logs
    webhook_logs = []
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM wise_webhook_logs 
            WHERE user_id = ? 
            ORDER BY received_at DESC 
            LIMIT 20
        ''', (get_effective_user_id(),))
        webhook_logs = [dict(row) for row in cursor.fetchall()]
    
    return render_template('wise_settings.html',
                          wise_settings=wise_settings_data,
                          is_configured=is_configured,
                          gbp_details=gbp_details,
                          eur_details=eur_details,
                          usd_details=usd_details,
                          unmatched_credits=unmatched_credits,
                          webhook_logs=webhook_logs)


@app.route('/settings/integrations/wise/match/<int:credit_id>', methods=['GET', 'POST'])
@login_required
def match_wise_credit(credit_id):
    """Manually match a Wise credit to an invoice."""
    from wise_integration import manually_match_credit
    
    if request.method == 'POST':
        invoice_id = request.form.get('invoice_id')
        if invoice_id:
            if manually_match_credit(get_effective_user_id(), credit_id, int(invoice_id)):
                flash('Payment matched to invoice successfully.', 'success')
            else:
                flash('Failed to match payment.', 'error')
        return redirect(url_for('wise_settings'))
    
    # Show form to select invoice
    invoice_manager = InvoiceManager(get_effective_user_id())
    invoices = invoice_manager.get_all()
    unpaid_invoices = [inv for inv in invoices if inv['status'] not in ['paid', 'cancelled']]
    
    # Get credit details
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM wise_credits WHERE id = ? AND user_id = ?', 
                      (credit_id, get_effective_user_id()))
        credit = cursor.fetchone()
    
    if not credit:
        flash('Credit not found.', 'error')
        return redirect(url_for('wise_settings'))
    
    return render_template('wise_match_credit.html', 
                          credit=dict(credit), 
                          invoices=unpaid_invoices)


# Public Wise webhook endpoint (no login required)
@app.route('/webhook/wise', methods=['POST'])
def wise_webhook():
    """Wise webhook endpoint for receiving payment notifications."""
    from wise_integration import (
        verify_wise_signature, process_wise_webhook,
        log_wise_webhook, WiseManager
    )
    import json
    
    payload = request.get_data()
    signature = request.headers.get('x-signature', '')
    
    try:
        event_data = json.loads(payload)
    except:
        return jsonify({'error': 'Invalid JSON'}), 400
    
    event_type = event_data.get('event_type', '')
    subscription_id = event_data.get('subscription_id', '')
    
    # Try to find user_id from profile in the event
    data = event_data.get('data', {})
    resource = data.get('resource', {})
    profile_id = resource.get('profile_id')
    
    user_id = None
    if profile_id:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT user_id FROM wise_settings WHERE profile_id = ?',
                (str(profile_id),)
            )
            row = cursor.fetchone()
            if row:
                user_id = row['user_id']
    
    # If no profile match, try to find any configured user (for simple setups)
    if not user_id:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM wise_settings WHERE enabled = 1 LIMIT 1')
            row = cursor.fetchone()
            if row:
                user_id = row['user_id']
    
    if user_id:
        # Process the webhook
        success, message, invoice_id = process_wise_webhook(event_data, user_id)
        
        # Log the event
        log_wise_webhook(
            user_id, event_type, subscription_id,
            'success' if success else 'error',
            message, invoice_id,
            json.dumps(event_data)[:5000]
        )
        
        return jsonify({'success': True, 'message': message})
    
    return jsonify({'received': True, 'message': 'Event acknowledged, no user context'})


# =============================================================================
# Accounts Payable Routes - Suppliers
# =============================================================================

@app.route('/suppliers')
@login_required
def suppliers():
    """List all suppliers."""
    from accounts_payable import SupplierManager, init_accounts_payable_tables
    
    init_accounts_payable_tables()
    
    supplier_manager = SupplierManager(get_effective_user_id())
    suppliers_list = supplier_manager.get_all()
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    total_outstanding = sum(s.get('outstanding') or 0 for s in suppliers_list)
    
    return render_template('suppliers.html',
                          suppliers=suppliers_list,
                          currency_symbol=currency_symbol,
                          total_outstanding=total_outstanding)


@app.route('/suppliers/export')
@login_required
def export_suppliers():
    """Export suppliers to CSV."""
    from accounts_payable import SupplierManager
    from import_export import export_suppliers_csv
    
    supplier_manager = SupplierManager(get_effective_user_id())
    suppliers_list = supplier_manager.get_all(include_inactive=True)
    
    csv_data = export_suppliers_csv(suppliers_list)
    
    response = make_response(csv_data)
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=suppliers_{datetime.now().strftime("%Y%m%d")}.csv'
    return response


@app.route('/suppliers/import', methods=['GET', 'POST'])
@login_required
def import_suppliers():
    """Import suppliers from CSV."""
    from import_export import import_suppliers_csv, get_supplier_csv_template
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded.', 'error')
            return redirect(url_for('import_suppliers'))
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected.', 'error')
            return redirect(url_for('import_suppliers'))
        
        if not file.filename.endswith('.csv'):
            flash('Please upload a CSV file.', 'error')
            return redirect(url_for('import_suppliers'))
        
        update_existing = request.form.get('update_existing') == '1'
        
        try:
            csv_data = file.read().decode('utf-8')
            imported, updated, errors = import_suppliers_csv(
                get_effective_user_id(), csv_data, update_existing
            )
            
            if imported > 0 or updated > 0:
                flash(f'Import complete: {imported} created, {updated} updated.', 'success')
            
            if errors:
                for error in errors[:5]:  # Show first 5 errors
                    flash(error, 'warning')
                if len(errors) > 5:
                    flash(f'... and {len(errors) - 5} more errors.', 'warning')
            
            return redirect(url_for('suppliers'))
            
        except Exception as e:
            flash(f'Import failed: {str(e)}', 'error')
            return redirect(url_for('import_suppliers'))
    
    return render_template('import_form.html',
                          import_type='suppliers',
                          title='Import Suppliers',
                          description='Upload a CSV file with supplier data.',
                          template_url=url_for('supplier_csv_template'))


@app.route('/suppliers/template.csv')
@login_required
def supplier_csv_template():
    """Download supplier CSV template."""
    from import_export import get_supplier_csv_template
    
    csv_data = get_supplier_csv_template()
    
    response = make_response(csv_data)
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=supplier_template.csv'
    return response


@app.route('/suppliers/new', methods=['GET', 'POST'])
@login_required
def new_supplier():
    """Create a new supplier."""
    from accounts_payable import SupplierManager, init_accounts_payable_tables
    from recurring_invoices import ChartOfAccounts
    
    init_accounts_payable_tables()
    
    if request.method == 'POST':
        data = {
            'name': request.form.get('name'),
            'contact_name': request.form.get('contact_name'),
            'email': request.form.get('email'),
            'phone': request.form.get('phone'),
            'address_line1': request.form.get('address_line1'),
            'address_line2': request.form.get('address_line2'),
            'city': request.form.get('city'),
            'state': request.form.get('state'),
            'postal_code': request.form.get('postal_code'),
            'country': request.form.get('country'),
            'tax_id': request.form.get('tax_id'),
            'payment_terms': request.form.get('payment_terms', 30),
            'default_coa_id': request.form.get('default_coa_id') or None,
            'notes': request.form.get('notes')
        }
        
        supplier_manager = SupplierManager(get_effective_user_id())
        supplier_id = supplier_manager.create(data)
        
        flash('Supplier created successfully.', 'success')
        return redirect(url_for('view_supplier', supplier_id=supplier_id))
    
    coa = ChartOfAccounts(get_effective_user_id())
    coa_accounts = coa.get_all(active_only=True)
    
    return render_template('supplier_form.html', supplier=None, coa_accounts=coa_accounts)


@app.route('/suppliers/<int:supplier_id>')
@login_required
def view_supplier(supplier_id):
    """View supplier details."""
    from accounts_payable import SupplierManager
    
    supplier_manager = SupplierManager(get_effective_user_id())
    supplier = supplier_manager.get(supplier_id)
    
    if not supplier:
        flash('Supplier not found.', 'error')
        return redirect(url_for('suppliers'))
    
    bills = supplier_manager.get_bills(supplier_id)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    outstanding = sum((b.get('total', 0) - b.get('amount_paid', 0)) for b in bills if b.get('status') not in ['paid', 'cancelled'])
    
    return render_template('supplier_detail.html',
                          supplier=supplier,
                          bills=bills,
                          currency_symbol=currency_symbol,
                          outstanding=outstanding)


@app.route('/suppliers/<int:supplier_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_supplier(supplier_id):
    """Edit a supplier."""
    from accounts_payable import SupplierManager
    from recurring_invoices import ChartOfAccounts
    
    supplier_manager = SupplierManager(get_effective_user_id())
    supplier = supplier_manager.get(supplier_id)
    
    if not supplier:
        flash('Supplier not found.', 'error')
        return redirect(url_for('suppliers'))
    
    if request.method == 'POST':
        data = {
            'name': request.form.get('name'),
            'contact_name': request.form.get('contact_name'),
            'email': request.form.get('email'),
            'phone': request.form.get('phone'),
            'address_line1': request.form.get('address_line1'),
            'address_line2': request.form.get('address_line2'),
            'city': request.form.get('city'),
            'state': request.form.get('state'),
            'postal_code': request.form.get('postal_code'),
            'country': request.form.get('country'),
            'tax_id': request.form.get('tax_id'),
            'payment_terms': request.form.get('payment_terms', 30),
            'default_coa_id': request.form.get('default_coa_id') or None,
            'notes': request.form.get('notes'),
            'is_active': request.form.get('is_active') == '1'
        }
        
        supplier_manager.update(supplier_id, data)
        flash('Supplier updated successfully.', 'success')
        return redirect(url_for('view_supplier', supplier_id=supplier_id))
    
    coa = ChartOfAccounts(get_effective_user_id())
    coa_accounts = coa.get_all(active_only=True)
    
    return render_template('supplier_form.html', supplier=supplier, coa_accounts=coa_accounts)


# =============================================================================
# Accounts Payable Routes - Bills
# =============================================================================

@app.route('/bills')
@login_required
def bills():
    """List all bills."""
    from accounts_payable import BillManager, SupplierManager, init_accounts_payable_tables
    from datetime import date
    
    init_accounts_payable_tables()
    
    bill_manager = BillManager(get_effective_user_id())
    supplier_manager = SupplierManager(get_effective_user_id())
    
    status = request.args.get('status')
    supplier_id = request.args.get('supplier_id', type=int)
    
    bills_list = bill_manager.get_all(status=status, supplier_id=supplier_id)
    suppliers_list = supplier_manager.get_all()
    summary = bill_manager.get_summary()
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    return render_template('bills.html',
                          bills=bills_list,
                          suppliers=suppliers_list,
                          summary=summary,
                          currency_symbol=currency_symbol,
                          today=date.today())


@app.route('/bills/new', methods=['GET', 'POST'])
@login_required
def new_bill():
    """Create a new bill."""
    from accounts_payable import BillManager, SupplierManager, init_accounts_payable_tables
    from recurring_invoices import ChartOfAccounts
    from app_core import get_enabled_currencies
    from datetime import date
    
    init_accounts_payable_tables()
    
    if request.method == 'POST':
        data = {
            'supplier_id': request.form.get('supplier_id') or None,
            'bill_number': request.form.get('bill_number') or None,
            'reference': request.form.get('reference'),
            'bill_date': request.form.get('bill_date'),
            'due_date': request.form.get('due_date') or None,
            'currency': request.form.get('currency', 'GBP'),
            'tax_rate': float(request.form.get('tax_rate', 0)),
            'notes': request.form.get('notes')
        }
        
        # Build items
        descriptions = request.form.getlist('item_description[]')
        quantities = request.form.getlist('item_quantity[]')
        prices = request.form.getlist('item_price[]')
        coa_ids = request.form.getlist('item_coa_id[]')
        
        items = []
        for i in range(len(descriptions)):
            if descriptions[i] or (quantities[i] and prices[i]):
                items.append({
                    'description': descriptions[i],
                    'quantity': float(quantities[i]) if quantities[i] else 1,
                    'unit_price': float(prices[i]) if prices[i] else 0,
                    'coa_id': int(coa_ids[i]) if coa_ids[i] else None
                })
        
        bill_manager = BillManager(get_effective_user_id())
        bill_id = bill_manager.create(data, items)
        
        # Handle attachment upload
        attachment_file = request.files.get('attachment')
        if attachment_file and attachment_file.filename:
            try:
                bill_manager.add_attachment(bill_id, attachment_file)
            except ValueError as e:
                flash(f'Bill created but attachment failed: {e}', 'warning')
        
        flash('Bill created successfully.', 'success')
        return redirect(url_for('view_bill', bill_id=bill_id))
    
    supplier_manager = SupplierManager(get_effective_user_id())
    suppliers = supplier_manager.get_all()
    
    coa = ChartOfAccounts(get_effective_user_id())
    coa_accounts = coa.get_all(active_only=True)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    enabled_currencies = get_enabled_currencies(get_effective_user_id())
    
    return render_template('bill_form.html',
                          bill=None,
                          suppliers=suppliers,
                          coa_accounts=coa_accounts,
                          settings=settings,
                          enabled_currencies=enabled_currencies or [settings.get('default_currency', 'GBP')],
                          default_currency=settings.get('default_currency', 'GBP'),
                          today=date.today())


@app.route('/bills/<int:bill_id>')
@login_required
def view_bill(bill_id):
    """View bill details."""
    from accounts_payable import BillManager
    from datetime import date
    
    bill_manager = BillManager(get_effective_user_id())
    bill = bill_manager.get(bill_id)
    
    if not bill:
        flash('Bill not found.', 'error')
        return redirect(url_for('bills'))
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(bill.get('currency', 'GBP'))
    
    return render_template('bill_detail.html',
                          bill=bill,
                          currency_symbol=currency_symbol,
                          today=date.today())


@app.route('/bills/<int:bill_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_bill(bill_id):
    """Edit a bill."""
    from accounts_payable import BillManager, SupplierManager
    from recurring_invoices import ChartOfAccounts
    from app_core import get_enabled_currencies
    from datetime import date
    
    bill_manager = BillManager(get_effective_user_id())
    bill = bill_manager.get(bill_id)
    
    if not bill:
        flash('Bill not found.', 'error')
        return redirect(url_for('bills'))
    
    if request.method == 'POST':
        data = {
            'supplier_id': request.form.get('supplier_id') or None,
            'reference': request.form.get('reference'),
            'bill_date': request.form.get('bill_date'),
            'due_date': request.form.get('due_date') or None,
            'currency': request.form.get('currency', 'GBP'),
            'tax_rate': float(request.form.get('tax_rate', 0)),
            'notes': request.form.get('notes')
        }
        
        # Build items
        descriptions = request.form.getlist('item_description[]')
        quantities = request.form.getlist('item_quantity[]')
        prices = request.form.getlist('item_price[]')
        coa_ids = request.form.getlist('item_coa_id[]')
        
        items = []
        for i in range(len(descriptions)):
            if descriptions[i] or (quantities[i] and prices[i]):
                items.append({
                    'description': descriptions[i],
                    'quantity': float(quantities[i]) if quantities[i] else 1,
                    'unit_price': float(prices[i]) if prices[i] else 0,
                    'coa_id': int(coa_ids[i]) if coa_ids[i] else None
                })
        
        bill_manager.update(bill_id, data, items)
        
        # Handle attachment
        if request.form.get('remove_attachment'):
            bill_manager.remove_attachment(bill_id)
        else:
            attachment_file = request.files.get('attachment')
            if attachment_file and attachment_file.filename:
                try:
                    bill_manager.add_attachment(bill_id, attachment_file)
                except ValueError as e:
                    flash(f'Attachment failed: {e}', 'warning')
        
        flash('Bill updated successfully.', 'success')
        return redirect(url_for('view_bill', bill_id=bill_id))
    
    supplier_manager = SupplierManager(get_effective_user_id())
    suppliers = supplier_manager.get_all()
    
    coa = ChartOfAccounts(get_effective_user_id())
    coa_accounts = coa.get_all(active_only=True)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    enabled_currencies = get_enabled_currencies(get_effective_user_id())
    
    return render_template('bill_form.html',
                          bill=bill,
                          suppliers=suppliers,
                          coa_accounts=coa_accounts,
                          settings=settings,
                          enabled_currencies=enabled_currencies or [settings.get('default_currency', 'GBP')],
                          default_currency=settings.get('default_currency', 'GBP'),
                          today=date.today())


@app.route('/bills/<int:bill_id>/approve', methods=['POST'])
@login_required
def approve_bill(bill_id):
    """Approve a bill."""
    from accounts_payable import BillManager
    
    bill_manager = BillManager(get_effective_user_id())
    bill_manager.update_status(bill_id, 'approved')
    flash('Bill approved.', 'success')
    return redirect(url_for('view_bill', bill_id=bill_id))


@app.route('/bills/<int:bill_id>/attachment')
@login_required
def view_bill_attachment(bill_id):
    """View/download attachment for a bill."""
    from accounts_payable import BillManager
    import os
    
    bill_manager = BillManager(get_effective_user_id())
    bill = bill_manager.get(bill_id)
    
    if not bill or not bill.get('attachment_path'):
        flash('Attachment not found.', 'error')
        return redirect(url_for('bills'))
    
    attachment_path = bill['attachment_path']
    if os.path.exists(attachment_path):
        directory = os.path.dirname(attachment_path)
        filename = os.path.basename(attachment_path)
        return send_from_directory(directory, filename)
    
    flash('Attachment file not found.', 'error')
    return redirect(url_for('view_bill', bill_id=bill_id))


@app.route('/bills/<int:bill_id>/pay', methods=['GET', 'POST'])
@login_required
def pay_bill(bill_id):
    """Record payment for a bill."""
    from accounts_payable import BillManager
    from datetime import date
    
    bill_manager = BillManager(get_effective_user_id())
    bill = bill_manager.get(bill_id)
    
    if not bill:
        flash('Bill not found.', 'error')
        return redirect(url_for('bills'))
    
    if request.method == 'POST':
        amount = float(request.form.get('amount', 0))
        payment_date = request.form.get('payment_date')
        payment_method = request.form.get('payment_method')
        reference = request.form.get('reference')
        notes = request.form.get('notes')
        
        try:
            bill_manager.add_payment(bill_id, amount, payment_date, payment_method, reference, notes)
            flash(f'Payment of {amount:.2f} recorded.', 'success')
        except ValueError as e:
            flash(str(e), 'error')
        
        return redirect(url_for('view_bill', bill_id=bill_id))
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(bill.get('currency', 'GBP'))
    
    return render_template('bill_payment.html',
                          bill=bill,
                          currency_symbol=currency_symbol,
                          today=date.today())


@app.route('/bills/<int:bill_id>/delete', methods=['POST'])
@login_required
def delete_bill(bill_id):
    """Delete a draft bill."""
    from accounts_payable import BillManager
    
    bill_manager = BillManager(get_effective_user_id())
    if bill_manager.delete(bill_id):
        flash('Bill deleted.', 'success')
    else:
        flash('Cannot delete bill. Only draft bills can be deleted.', 'error')
    return redirect(url_for('bills'))


# =============================================================================
# Accounts Payable Routes - Expenses
# =============================================================================

@app.route('/expenses')
@login_required
def expenses():
    """List all expenses."""
    from accounts_payable import ExpenseManager, EXPENSE_CATEGORIES, init_accounts_payable_tables
    
    init_accounts_payable_tables()
    
    expense_manager = ExpenseManager(get_effective_user_id())
    
    category = request.args.get('category')
    status = request.args.get('status')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    expenses_list = expense_manager.get_all(category=category, date_from=date_from, 
                                            date_to=date_to, status=status)
    summary = expense_manager.get_summary(date_from=date_from, date_to=date_to)
    by_category = expense_manager.get_by_category(date_from=date_from, date_to=date_to)
    categories = expense_manager.get_categories()
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    return render_template('expenses.html',
                          expenses=expenses_list,
                          summary=summary,
                          by_category=by_category,
                          categories=categories or EXPENSE_CATEGORIES,
                          currency_symbol=currency_symbol)


@app.route('/expenses/new', methods=['GET', 'POST'])
@login_required
def new_expense():
    """Create a new expense."""
    from accounts_payable import ExpenseManager, SupplierManager, EXPENSE_CATEGORIES, PAYMENT_METHODS, init_accounts_payable_tables
    from recurring_invoices import ChartOfAccounts
    from app_core import get_enabled_currencies
    from datetime import date
    
    init_accounts_payable_tables()
    
    if request.method == 'POST':
        data = {
            'description': request.form.get('description'),
            'expense_date': request.form.get('expense_date'),
            'amount': float(request.form.get('amount', 0)),
            'currency': request.form.get('currency', 'GBP'),
            'tax_rate': float(request.form.get('tax_rate', 0)),
            'amount_includes_tax': request.form.get('amount_includes_tax') == '1',
            'category': request.form.get('category'),
            'supplier_id': request.form.get('supplier_id') or None,
            'coa_id': request.form.get('coa_id') or None,
            'payment_method': request.form.get('payment_method'),
            'reference': request.form.get('reference'),
            'is_billable': request.form.get('is_billable') == '1',
            'is_reimbursable': request.form.get('is_reimbursable') == '1',
            'notes': request.form.get('notes'),
            'status': 'pending'
        }
        
        receipt_file = request.files.get('receipt')
        
        expense_manager = ExpenseManager(get_effective_user_id())
        try:
            expense_id = expense_manager.create(data, receipt_file)
            flash('Expense created successfully.', 'success')
            return redirect(url_for('view_expense', expense_id=expense_id))
        except ValueError as e:
            flash(str(e), 'error')
    
    supplier_manager = SupplierManager(get_effective_user_id())
    suppliers = supplier_manager.get_all()
    
    coa = ChartOfAccounts(get_effective_user_id())
    coa_accounts = coa.get_all(active_only=True)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    enabled_currencies = get_enabled_currencies(get_effective_user_id())
    
    return render_template('expense_form.html',
                          expense=None,
                          suppliers=suppliers,
                          coa_accounts=coa_accounts,
                          expense_categories=EXPENSE_CATEGORIES,
                          payment_methods=PAYMENT_METHODS,
                          enabled_currencies=enabled_currencies or [settings.get('default_currency', 'GBP')],
                          default_currency=settings.get('default_currency', 'GBP'),
                          today=date.today())


@app.route('/expenses/<int:expense_id>')
@login_required
def view_expense(expense_id):
    """View expense details."""
    from accounts_payable import ExpenseManager
    
    expense_manager = ExpenseManager(get_effective_user_id())
    expense = expense_manager.get(expense_id)
    
    if not expense:
        flash('Expense not found.', 'error')
        return redirect(url_for('expenses'))
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(expense.get('currency', 'GBP'))
    
    return render_template('expense_detail.html',
                          expense=expense,
                          currency_symbol=currency_symbol)


@app.route('/expenses/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    """Edit an expense."""
    from accounts_payable import ExpenseManager, SupplierManager, EXPENSE_CATEGORIES, PAYMENT_METHODS
    from recurring_invoices import ChartOfAccounts
    from app_core import get_enabled_currencies
    from datetime import date
    
    expense_manager = ExpenseManager(get_effective_user_id())
    expense = expense_manager.get(expense_id)
    
    if not expense:
        flash('Expense not found.', 'error')
        return redirect(url_for('expenses'))
    
    if request.method == 'POST':
        data = {
            'description': request.form.get('description'),
            'expense_date': request.form.get('expense_date'),
            'amount': float(request.form.get('amount', 0)),
            'currency': request.form.get('currency', 'GBP'),
            'tax_rate': float(request.form.get('tax_rate', 0)),
            'amount_includes_tax': request.form.get('amount_includes_tax') == '1',
            'category': request.form.get('category'),
            'supplier_id': request.form.get('supplier_id') or None,
            'coa_id': request.form.get('coa_id') or None,
            'payment_method': request.form.get('payment_method'),
            'reference': request.form.get('reference'),
            'is_billable': request.form.get('is_billable') == '1',
            'is_reimbursable': request.form.get('is_reimbursable') == '1',
            'notes': request.form.get('notes'),
            'status': request.form.get('status', 'pending'),
            'remove_receipt': request.form.get('remove_receipt') == '1'
        }
        
        receipt_file = request.files.get('receipt')
        
        try:
            expense_manager.update(expense_id, data, receipt_file)
            flash('Expense updated successfully.', 'success')
            return redirect(url_for('view_expense', expense_id=expense_id))
        except ValueError as e:
            flash(str(e), 'error')
    
    supplier_manager = SupplierManager(get_effective_user_id())
    suppliers = supplier_manager.get_all()
    
    coa = ChartOfAccounts(get_effective_user_id())
    coa_accounts = coa.get_all(active_only=True)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    enabled_currencies = get_enabled_currencies(get_effective_user_id())
    
    return render_template('expense_form.html',
                          expense=expense,
                          suppliers=suppliers,
                          coa_accounts=coa_accounts,
                          expense_categories=EXPENSE_CATEGORIES,
                          payment_methods=PAYMENT_METHODS,
                          enabled_currencies=enabled_currencies or [settings.get('default_currency', 'GBP')],
                          default_currency=settings.get('default_currency', 'GBP'),
                          today=date.today())


@app.route('/expenses/<int:expense_id>/receipt')
@login_required
def view_receipt(expense_id):
    """View/download receipt for an expense."""
    from accounts_payable import ExpenseManager
    import os
    
    expense_manager = ExpenseManager(get_effective_user_id())
    expense = expense_manager.get(expense_id)
    
    if not expense or not expense.get('receipt_path'):
        flash('Receipt not found.', 'error')
        return redirect(url_for('expenses'))
    
    receipt_path = expense['receipt_path']
    if os.path.exists(receipt_path):
        directory = os.path.dirname(receipt_path)
        filename = os.path.basename(receipt_path)
        return send_from_directory(directory, filename)
    
    flash('Receipt file not found.', 'error')
    return redirect(url_for('view_expense', expense_id=expense_id))


@app.route('/expenses/<int:expense_id>/approve', methods=['POST'])
@login_required
def approve_expense(expense_id):
    """Approve an expense."""
    from accounts_payable import ExpenseManager
    
    expense_manager = ExpenseManager(get_effective_user_id())
    if expense_manager.approve(expense_id):
        flash('Expense approved.', 'success')
    else:
        flash('Could not approve expense.', 'error')
    return redirect(url_for('view_expense', expense_id=expense_id))


@app.route('/expenses/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete_expense(expense_id):
    """Delete an expense."""
    from accounts_payable import ExpenseManager
    
    expense_manager = ExpenseManager(get_effective_user_id())
    if expense_manager.delete(expense_id):
        flash('Expense deleted.', 'success')
    else:
        flash('Could not delete expense.', 'error')
    return redirect(url_for('expenses'))


# =============================================================================
# Credit Notes Routes
# =============================================================================

@app.route('/credit-notes')
@login_required
def credit_notes():
    """List all credit notes."""
    from credit_notes import CreditNoteManager, init_credit_notes_tables
    
    init_credit_notes_tables()
    
    cn_manager = CreditNoteManager(get_effective_user_id())
    credit_notes_list = cn_manager.get_all()
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    # Calculate totals
    total_issued = sum(cn.get('total') or 0 for cn in credit_notes_list)
    total_used = sum(cn.get('amount_used') or 0 for cn in credit_notes_list)
    total_available = total_issued - total_used
    
    return render_template('credit_notes.html',
                          credit_notes=credit_notes_list,
                          currency_symbol=currency_symbol,
                          total_issued=total_issued,
                          total_used=total_used,
                          total_available=total_available)


@app.route('/credit-notes/new', methods=['GET', 'POST'])
@login_required
def credit_note_new():
    """Create a new credit note."""
    from credit_notes import CreditNoteManager
    from app_core import CustomerManager, InvoiceManager
    
    cn_manager = CreditNoteManager(get_effective_user_id())
    customer_manager = CustomerManager(get_effective_user_id())
    invoice_manager = InvoiceManager(get_effective_user_id())
    
    if request.method == 'POST':
        items = []
        descriptions = request.form.getlist('item_description[]')
        quantities = request.form.getlist('item_quantity[]')
        prices = request.form.getlist('item_price[]')
        
        for i in range(len(descriptions)):
            if descriptions[i].strip():
                items.append({
                    'description': descriptions[i],
                    'quantity': float(quantities[i]) if quantities[i] else 1,
                    'unit_price': float(prices[i]) if prices[i] else 0
                })
        
        data = {
            'customer_id': request.form.get('customer_id') or None,
            'invoice_id': request.form.get('invoice_id') or None,
            'issue_date': request.form.get('issue_date'),
            'currency': request.form.get('currency', 'GBP'),
            'tax_rate': float(request.form.get('tax_rate', 0)),
            'reason': request.form.get('reason'),
            'notes': request.form.get('notes'),
            'items': items
        }
        
        credit_note_id = cn_manager.create(data)
        flash('Credit note created successfully.', 'success')
        return redirect(url_for('credit_note_detail', credit_note_id=credit_note_id))
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    customers = customer_manager.get_all()
    # Include all non-void invoices for credit notes
    all_invoices = invoice_manager.get_all()
    invoices = [inv for inv in all_invoices if inv.get('status') not in ['void', 'cancelled']]
    
    # Check if creating from invoice
    from_invoice_id = request.args.get('from_invoice')
    prefill_data = {}
    if from_invoice_id:
        invoice = invoice_manager.get(int(from_invoice_id))
        if invoice:
            prefill_data = {
                'customer_id': invoice.get('customer_id'),
                'invoice_id': invoice.get('id'),
                'currency': invoice.get('currency'),
                'tax_rate': invoice.get('tax_rate'),
                'items': invoice.get('items', [])
            }
    
    return render_template('credit_note_form.html',
                          credit_note=None,
                          prefill=prefill_data,
                          customers=customers,
                          invoices=invoices,
                          reasons=cn_manager.REASONS,
                          settings=settings,
                          next_number=cn_manager.get_next_number())


@app.route('/credit-notes/invoice-items/<int:invoice_id>')
@login_required
def get_invoice_items_for_credit_note(invoice_id):
    """Get invoice items for credit note form (session authenticated)."""
    from app_core import InvoiceManager
    
    invoice_manager = InvoiceManager(get_effective_user_id())
    invoice = invoice_manager.get(invoice_id)
    
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404
    
    return jsonify({
        'success': True,
        'data': {
            'items': invoice.get('items', []),
            'customer_id': invoice.get('customer_id'),
            'tax_rate': invoice.get('tax_rate'),
            'currency': invoice.get('currency')
        }
    })


@app.route('/credit-notes/<int:credit_note_id>')
@login_required
def credit_note_detail(credit_note_id):
    """View credit note details."""
    from credit_notes import CreditNoteManager
    
    cn_manager = CreditNoteManager(get_effective_user_id())
    credit_note = cn_manager.get(credit_note_id)
    
    if not credit_note:
        flash('Credit note not found.', 'error')
        return redirect(url_for('credit_notes'))
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(credit_note.get('currency', 'GBP'))
    
    return render_template('credit_note_detail.html',
                          credit_note=credit_note,
                          currency_symbol=currency_symbol,
                          settings=settings)


@app.route('/credit-notes/<int:credit_note_id>/edit', methods=['GET', 'POST'])
@login_required
def credit_note_edit(credit_note_id):
    """Edit a credit note."""
    from credit_notes import CreditNoteManager
    from app_core import CustomerManager, InvoiceManager
    
    cn_manager = CreditNoteManager(get_effective_user_id())
    customer_manager = CustomerManager(get_effective_user_id())
    invoice_manager = InvoiceManager(get_effective_user_id())
    
    credit_note = cn_manager.get(credit_note_id)
    if not credit_note:
        flash('Credit note not found.', 'error')
        return redirect(url_for('credit_notes'))
    
    if credit_note['status'] != 'draft':
        flash('Only draft credit notes can be edited.', 'error')
        return redirect(url_for('credit_note_detail', credit_note_id=credit_note_id))
    
    if request.method == 'POST':
        items = []
        descriptions = request.form.getlist('item_description[]')
        quantities = request.form.getlist('item_quantity[]')
        prices = request.form.getlist('item_price[]')
        
        for i in range(len(descriptions)):
            if descriptions[i].strip():
                items.append({
                    'description': descriptions[i],
                    'quantity': float(quantities[i]) if quantities[i] else 1,
                    'unit_price': float(prices[i]) if prices[i] else 0
                })
        
        data = {
            'customer_id': request.form.get('customer_id') or None,
            'invoice_id': request.form.get('invoice_id') or None,
            'issue_date': request.form.get('issue_date'),
            'tax_rate': float(request.form.get('tax_rate', 0)),
            'reason': request.form.get('reason'),
            'notes': request.form.get('notes'),
            'items': items
        }
        
        cn_manager.update(credit_note_id, data)
        flash('Credit note updated.', 'success')
        return redirect(url_for('credit_note_detail', credit_note_id=credit_note_id))
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    customers = customer_manager.get_all()
    invoices = invoice_manager.get_all()
    
    return render_template('credit_note_form.html',
                          credit_note=credit_note,
                          prefill={},
                          customers=customers,
                          invoices=invoices,
                          reasons=cn_manager.REASONS,
                          settings=settings,
                          next_number=None)


@app.route('/credit-notes/<int:credit_note_id>/issue', methods=['POST'])
@login_required
def credit_note_issue(credit_note_id):
    """Issue a credit note."""
    from credit_notes import CreditNoteManager
    
    cn_manager = CreditNoteManager(get_effective_user_id())
    
    if cn_manager.issue(credit_note_id):
        flash('Credit note issued successfully.', 'success')
    else:
        flash('Could not issue credit note.', 'error')
    
    return redirect(url_for('credit_note_detail', credit_note_id=credit_note_id))


@app.route('/credit-notes/<int:credit_note_id>/apply', methods=['POST'])
@login_required
def credit_note_apply(credit_note_id):
    """Apply credit note to an invoice."""
    from credit_notes import CreditNoteManager
    
    cn_manager = CreditNoteManager(get_effective_user_id())
    
    invoice_id = request.form.get('invoice_id')
    amount = float(request.form.get('amount', 0))
    
    if not invoice_id or amount <= 0:
        flash('Please select an invoice and enter a valid amount.', 'error')
        return redirect(url_for('credit_note_detail', credit_note_id=credit_note_id))
    
    result = cn_manager.apply_to_invoice(credit_note_id, int(invoice_id), amount)
    
    if result['success']:
        flash(result['message'], 'success')
    else:
        flash(result['error'], 'error')
    
    return redirect(url_for('credit_note_detail', credit_note_id=credit_note_id))


@app.route('/credit-notes/<int:credit_note_id>/delete', methods=['POST'])
@login_required
def credit_note_delete(credit_note_id):
    """Delete a draft credit note."""
    from credit_notes import CreditNoteManager
    
    cn_manager = CreditNoteManager(get_effective_user_id())
    
    if cn_manager.delete(credit_note_id):
        flash('Credit note deleted.', 'success')
    else:
        flash('Could not delete credit note. Only draft credit notes can be deleted.', 'error')
    
    return redirect(url_for('credit_notes'))


# =============================================================================
# Financial Reports Routes
# =============================================================================

@app.route('/reports')
@login_required
def reports():
    """Reports dashboard."""
    return render_template('reports.html')


@app.route('/reports/profit-loss', methods=['GET', 'POST'])
@login_required
def report_profit_loss():
    """Profit & Loss report."""
    from financial_reports import FinancialReports
    from accounts_payable import init_accounts_payable_tables
    
    # Ensure AP tables exist
    init_accounts_payable_tables()
    
    report = None
    start_date = request.args.get('start_date') or request.form.get('start_date')
    end_date = request.args.get('end_date') or request.form.get('end_date')
    compare = request.args.get('compare') == '1' or request.form.get('compare') == '1'
    
    if start_date and end_date:
        fr = FinancialReports(get_effective_user_id())
        report = fr.get_profit_and_loss(start_date, end_date, compare_previous=compare)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    return render_template('report_profit_loss.html',
                          report=report,
                          start_date=start_date,
                          end_date=end_date,
                          compare=compare,
                          currency_symbol=currency_symbol,
                          settings=settings)


@app.route('/reports/balance-sheet', methods=['GET', 'POST'])
@login_required
def report_balance_sheet():
    """Balance Sheet report."""
    from financial_reports import FinancialReports
    from accounts_payable import init_accounts_payable_tables
    
    # Ensure AP tables exist
    init_accounts_payable_tables()
    
    report = None
    as_of_date = request.args.get('as_of_date') or request.form.get('as_of_date')
    
    if as_of_date:
        fr = FinancialReports(get_effective_user_id())
        report = fr.get_balance_sheet(as_of_date)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    return render_template('report_balance_sheet.html',
                          report=report,
                          as_of_date=as_of_date,
                          currency_symbol=currency_symbol,
                          settings=settings)


@app.route('/reports/vat/pdf')
@login_required
def report_vat_pdf():
    """Generate VAT report as PDF."""
    from financial_reports import FinancialReports
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        flash('Please specify a date range.', 'error')
        return redirect(url_for('report_vat'))
    
    fr = FinancialReports(get_effective_user_id())
    report = fr.get_vat_report(start_date, end_date)
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    # Extract VAT boxes from report
    boxes = report.get('vat_return_boxes', {})
    summary = report.get('summary', {})
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm, leftMargin=20*mm, rightMargin=20*mm)
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=20, spaceAfter=5, alignment=1)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=12, spaceAfter=3, alignment=1, textColor=colors.grey)
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontSize=14, spaceBefore=20, spaceAfter=10)
    
    # Header
    elements.append(Paragraph("VAT Return", title_style))
    elements.append(Paragraph(f"{settings.get('company_name', 'Company')}", subtitle_style))
    if settings.get('tax_number'):
        elements.append(Paragraph(f"VAT Number: {settings.get('tax_number')}", subtitle_style))
    elements.append(Paragraph(f"Period: {start_date} to {end_date}", subtitle_style))
    elements.append(Spacer(1, 20))
    
    # VAT Return Boxes Table
    elements.append(Paragraph("VAT Return Boxes", heading_style))
    
    vat_data = [
        ['Box', 'Description', 'Amount'],
        ['1', boxes.get('box1_description', 'VAT due on sales'), f"{currency_symbol}{boxes.get('box1', 0):.2f}"],
        ['2', boxes.get('box2_description', 'VAT on acquisitions'), f"{currency_symbol}{boxes.get('box2', 0):.2f}"],
        ['3', boxes.get('box3_description', 'Total VAT due'), f"{currency_symbol}{boxes.get('box3', 0):.2f}"],
        ['4', boxes.get('box4_description', 'VAT reclaimed'), f"{currency_symbol}{boxes.get('box4', 0):.2f}"],
        ['5', boxes.get('box5_description', 'Net VAT'), f"{currency_symbol}{abs(boxes.get('box5', 0)):.2f}"],
        ['6', boxes.get('box6_description', 'Total sales excl VAT'), f"{currency_symbol}{boxes.get('box6', 0):,}"],
        ['7', boxes.get('box7_description', 'Total purchases excl VAT'), f"{currency_symbol}{boxes.get('box7', 0):,}"],
        ['8', boxes.get('box8_description', 'EU supplies'), f"{currency_symbol}{boxes.get('box8', 0):,}"],
        ['9', boxes.get('box9_description', 'EU acquisitions'), f"{currency_symbol}{boxes.get('box9', 0):,}"],
    ]
    
    table = Table(vat_data, colWidths=[40, 320, 100])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a2e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
        ('BACKGROUND', (0, 5), (-1, 5), colors.HexColor('#e8f5e9') if boxes.get('box5', 0) <= 0 else colors.HexColor('#ffebee')),
    ]))
    elements.append(table)
    
    # Summary
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Summary", heading_style))
    
    position = summary.get('position', 'No VAT due')
    net_amount = abs(summary.get('net_vat_position', 0))
    
    summary_data = [
        ['VAT Position', f"{currency_symbol}{net_amount:.2f} - {position}"],
        ['VAT Collected on Sales', f"{currency_symbol}{summary.get('vat_collected', 0):.2f}"],
        ['Less: Credit Note VAT', f"({currency_symbol}{summary.get('credit_note_vat', 0):.2f})"],
        ['VAT on Bills', f"({currency_symbol}{summary.get('vat_on_bills', 0):.2f})"],
        ['VAT on Expenses', f"({currency_symbol}{summary.get('vat_on_expenses', 0):.2f})"],
    ]
    
    summary_table = Table(summary_data, colWidths=[200, 260])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#1a1a2e')),
    ]))
    elements.append(summary_table)
    
    # Warning
    elements.append(Spacer(1, 30))
    warning_style = ParagraphStyle('Warning', parent=styles['Normal'], textColor=colors.red, fontSize=10, borderWidth=1, borderColor=colors.red, borderPadding=10)
    elements.append(Paragraph("⚠️ IMPORTANT: This VAT report is provided as a guide only. All figures MUST be verified by a qualified accountant or tax advisor before submission to HMRC. Incorrect VAT returns may result in penalties and interest charges.", warning_style))
    
    # Footer
    elements.append(Spacer(1, 20))
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey, alignment=1)
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Invoice Manager", footer_style))
    
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, mimetype='application/pdf', as_attachment=True, 
                    download_name=f'VAT_Report_{start_date}_to_{end_date}.pdf')


@app.route('/reports/vat/save-checklist', methods=['POST'])
@login_required
def save_vat_checklist():
    """Save VAT verification checklist."""
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    
    # Get checklist values
    checklist = {
        'checklist_sales_verified': 1 if request.form.get('checklist_sales_verified') else 0,
        'checklist_vat_numbers': 1 if request.form.get('checklist_vat_numbers') else 0,
        'checklist_credit_notes': 1 if request.form.get('checklist_credit_notes') else 0,
        'checklist_expenses_receipts': 1 if request.form.get('checklist_expenses_receipts') else 0,
        'checklist_partial_exemption': 1 if request.form.get('checklist_partial_exemption') else 0,
        'checklist_reverse_charge': 1 if request.form.get('checklist_reverse_charge') else 0,
        'checklist_eu_supply': 1 if request.form.get('checklist_eu_supply') else 0,
        'checklist_accountant_reviewed': 1 if request.form.get('checklist_accountant_reviewed') else 0,
    }
    
    user_id = get_effective_user_id()
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Check if submission record exists
        cursor.execute('''
            SELECT id FROM vat_submissions 
            WHERE user_id = ? AND period_start = ? AND period_end = ?
        ''', (user_id, start_date, end_date))
        
        existing = cursor.fetchone()
        
        if existing:
            # Update existing record
            cursor.execute('''
                UPDATE vat_submissions SET
                    checklist_sales_verified = ?,
                    checklist_vat_numbers = ?,
                    checklist_credit_notes = ?,
                    checklist_expenses_receipts = ?,
                    checklist_partial_exemption = ?,
                    checklist_reverse_charge = ?,
                    checklist_eu_supply = ?,
                    checklist_accountant_reviewed = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND period_start = ? AND period_end = ?
            ''', (
                checklist['checklist_sales_verified'],
                checklist['checklist_vat_numbers'],
                checklist['checklist_credit_notes'],
                checklist['checklist_expenses_receipts'],
                checklist['checklist_partial_exemption'],
                checklist['checklist_reverse_charge'],
                checklist['checklist_eu_supply'],
                checklist['checklist_accountant_reviewed'],
                user_id, start_date, end_date
            ))
        else:
            # Create new record
            cursor.execute('''
                INSERT INTO vat_submissions (
                    user_id, period_start, period_end,
                    checklist_sales_verified, checklist_vat_numbers, checklist_credit_notes,
                    checklist_expenses_receipts, checklist_partial_exemption, checklist_reverse_charge,
                    checklist_eu_supply, checklist_accountant_reviewed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, start_date, end_date,
                checklist['checklist_sales_verified'],
                checklist['checklist_vat_numbers'],
                checklist['checklist_credit_notes'],
                checklist['checklist_expenses_receipts'],
                checklist['checklist_partial_exemption'],
                checklist['checklist_reverse_charge'],
                checklist['checklist_eu_supply'],
                checklist['checklist_accountant_reviewed']
            ))
        
        conn.commit()
    
    flash('Checklist saved.', 'success')
    return redirect(url_for('report_vat', start_date=start_date, end_date=end_date))


@app.route('/reports/submit-tax', methods=['POST'])
@login_required
def submit_tax_report():
    """Submit tax report via email to tax authority or accountant."""
    from email_module import EmailManager
    
    report_type = request.form.get('report_type')
    recipient = request.form.get('recipient', 'authority')  # 'authority' or 'accountant'
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    user_id = get_effective_user_id()
    
    # Determine recipient email
    if recipient == 'accountant':
        to_email = settings.get('accountant_email')
        recipient_name = settings.get('accountant_name', 'Accountant')
        if not to_email:
            flash('No accountant email configured. Please update your settings.', 'error')
            return redirect(url_for('report_vat', start_date=start_date, end_date=end_date))
    else:
        to_email = settings.get('tax_authority_email')
        recipient_name = settings.get('tax_authority', 'Tax Authority')
        if not to_email:
            flash('No tax authority email configured. Please update your settings.', 'error')
            return redirect(url_for('report_vat', start_date=start_date, end_date=end_date))
    
    # Generate report data
    from financial_reports import FinancialReports
    fr = FinancialReports(user_id)
    
    if report_type == 'vat':
        report = fr.get_vat_report(start_date, end_date)
        currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
        
        if recipient == 'accountant':
            subject = f"VAT Return for Review - {settings.get('company_name', 'Company')} - {start_date} to {end_date}"
            intro = "Please review the following VAT return figures before submission to the tax authority."
        else:
            subject = f"VAT Return - {settings.get('company_name', 'Company')} - {start_date} to {end_date}"
            intro = "Please find below the VAT return submission."
        
        # Extract boxes from report
        boxes = report.get('vat_return_boxes', {})
        
        body = f"""{intro}

Company: {settings.get('company_name', 'N/A')}
Tax Number: {settings.get('tax_number', 'N/A')}
Period: {start_date} to {end_date}

VAT RETURN BOXES
================
Box 1 - VAT due on sales: {currency_symbol}{boxes.get('box1', 0):.2f}
Box 2 - VAT due on acquisitions: {currency_symbol}{boxes.get('box2', 0):.2f}
Box 3 - Total VAT due: {currency_symbol}{boxes.get('box3', 0):.2f}
Box 4 - VAT reclaimed on purchases: {currency_symbol}{boxes.get('box4', 0):.2f}
Box 5 - Net VAT to pay/reclaim: {currency_symbol}{abs(boxes.get('box5', 0)):.2f}
Box 6 - Total value of sales (excl VAT): {currency_symbol}{boxes.get('box6', 0):,}
Box 7 - Total value of purchases (excl VAT): {currency_symbol}{boxes.get('box7', 0):,}

This report was generated automatically from Invoice Manager.
{'Please verify all figures and advise on any issues.' if recipient == 'accountant' else 'Please verify all figures before processing.'}

Sent by: {session.get('username', 'Unknown')}
Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        try:
            email_manager = EmailManager(user_id)
            email_manager.send_email(
                to_email=to_email,
                subject=subject,
                body=body
            )
            
            # Update submission tracking
            with get_db() as conn:
                cursor = conn.cursor()
                
                if recipient == 'accountant':
                    cursor.execute('''
                        UPDATE vat_submissions SET 
                            submitted_to_accountant = 1, 
                            submitted_to_accountant_at = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND period_start = ? AND period_end = ?
                    ''', (user_id, start_date, end_date))
                else:
                    cursor.execute('''
                        UPDATE vat_submissions SET 
                            submitted_to_authority = 1, 
                            submitted_to_authority_at = CURRENT_TIMESTAMP
                        WHERE user_id = ? AND period_start = ? AND period_end = ?
                    ''', (user_id, start_date, end_date))
                
                conn.commit()
            
            flash(f'VAT report sent to {recipient_name} ({to_email}).', 'success')
        except Exception as e:
            flash(f'Failed to send report: {str(e)}', 'error')
    else:
        flash('Unknown report type.', 'error')
    
    return redirect(url_for('report_vat', start_date=start_date, end_date=end_date))


@app.route('/reports/vat', methods=['GET', 'POST'])
@login_required
def report_vat():
    """VAT report."""
    from financial_reports import FinancialReports
    from accounts_payable import init_accounts_payable_tables
    
    # Ensure AP tables exist
    init_accounts_payable_tables()
    
    user_id = get_effective_user_id()
    report = None
    submission = None
    start_date = request.args.get('start_date') or request.form.get('start_date')
    end_date = request.args.get('end_date') or request.form.get('end_date')
    
    if start_date and end_date:
        fr = FinancialReports(user_id)
        report = fr.get_vat_report(start_date, end_date)
        
        # Load submission record if exists
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM vat_submissions 
                WHERE user_id = ? AND period_start = ? AND period_end = ?
            ''', (user_id, start_date, end_date))
            row = cursor.fetchone()
            if row:
                submission = dict(row)
    
    settings = SettingsManager(user_id).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    return render_template('report_vat.html',
                          report=report,
                          submission=submission,
                          start_date=start_date,
                          end_date=end_date,
                          currency_symbol=currency_symbol,
                          settings=settings)


@app.route('/reports/tax-summary', methods=['GET', 'POST'])
@login_required
def report_tax_summary():
    """Income Tax Summary report."""
    from financial_reports import FinancialReports
    from accounts_payable import init_accounts_payable_tables
    
    # Ensure AP tables exist
    init_accounts_payable_tables()
    
    report = None
    start_date = request.args.get('start_date') or request.form.get('start_date')
    end_date = request.args.get('end_date') or request.form.get('end_date')
    
    if start_date and end_date:
        fr = FinancialReports(get_effective_user_id())
        report = fr.get_income_tax_summary(start_date, end_date)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    return render_template('report_tax_summary.html',
                          report=report,
                          start_date=start_date,
                          end_date=end_date,
                          currency_symbol=currency_symbol,
                          settings=settings)


@app.route('/reports/aged-receivables', methods=['GET', 'POST'])
@login_required
def report_aged_receivables():
    """Aged Receivables report."""
    from financial_reports import FinancialReports
    from datetime import date
    
    as_of_date = request.args.get('as_of_date') or request.form.get('as_of_date') or date.today().isoformat()
    
    fr = FinancialReports(get_effective_user_id())
    report = fr.get_aged_receivables(as_of_date)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    return render_template('report_aged_receivables.html',
                          report=report,
                          as_of_date=as_of_date,
                          currency_symbol=currency_symbol,
                          settings=settings)


@app.route('/reports/aged-payables', methods=['GET', 'POST'])
@login_required
def report_aged_payables():
    """Aged Payables report."""
    from financial_reports import FinancialReports
    from accounts_payable import init_accounts_payable_tables
    from datetime import date
    
    # Ensure AP tables exist
    init_accounts_payable_tables()
    
    as_of_date = request.args.get('as_of_date') or request.form.get('as_of_date') or date.today().isoformat()
    
    fr = FinancialReports(get_effective_user_id())
    report = fr.get_aged_payables(as_of_date)
    
    settings = SettingsManager(get_effective_user_id()).get_settings()
    currency_symbol = get_currency_symbol(settings.get('default_currency', 'GBP'))
    
    return render_template('report_aged_payables.html',
                          report=report,
                          as_of_date=as_of_date,
                          currency_symbol=currency_symbol,
                          settings=settings)


# =============================================================================
# Database Settings Routes
# =============================================================================

@app.route('/settings/database', methods=['GET', 'POST'])
@login_required
def database_settings():
    """Database configuration page."""
    from database import get_db_config, save_db_config, get_database_info, migrate_sqlite_to_mysql, MYSQL_AVAILABLE
    
    if request.method == 'POST':
        db_type = request.form.get('db_type', 'sqlite')
        
        config = get_db_config()
        config['type'] = db_type
        
        if db_type == 'sqlite':
            config['sqlite_path'] = request.form.get('sqlite_path', 'data/invoices.db')
        elif db_type == 'mysql':
            config['mysql_host'] = request.form.get('mysql_host', 'localhost')
            config['mysql_port'] = int(request.form.get('mysql_port', 3306))
            config['mysql_user'] = request.form.get('mysql_user', '')
            config['mysql_password'] = request.form.get('mysql_password', '')
            config['mysql_database'] = request.form.get('mysql_database', 'invoice_manager')
            config['mysql_ssl'] = request.form.get('mysql_ssl') == '1'
        
        # Handle migration
        if request.form.get('migrate_data') and db_type == 'mysql':
            result = migrate_sqlite_to_mysql()
            if result['success']:
                flash(f'Data migrated successfully: {result["migrated"]}', 'success')
            else:
                flash(f'Migration failed: {result["error"]}', 'error')
        
        if save_db_config(config):
            flash('Database settings saved. Restart the application for changes to take effect.', 'success')
        else:
            flash('Failed to save database settings.', 'error')
        
        return redirect(url_for('database_settings'))
    
    db_config = get_db_config()
    db_info = get_database_info()
    
    return render_template('database_settings.html',
                          db_config=db_config,
                          db_connected=db_info.get('connected', False),
                          table_count=db_info.get('tables', 0),
                          db_size=db_info.get('size', 'N/A'),
                          mysql_available=MYSQL_AVAILABLE)


@app.route('/settings/database/test-mysql', methods=['POST'])
@login_required
def test_mysql_connection():
    """Test MySQL connection."""
    from database import test_mysql_connection as test_conn
    
    data = request.get_json()
    result = test_conn(
        host=data.get('host', 'localhost'),
        port=int(data.get('port', 3306)),
        user=data.get('user', ''),
        password=data.get('password', ''),
        database=data.get('database', '')
    )
    
    return jsonify(result)


# =============================================================================
# Help / Documentation
# =============================================================================

@app.route('/help/api')
@login_required
def api_help():
    """Display API documentation page."""
    return render_template('api_help.html')


@app.route('/help/about')
@login_required
def about():
    """Display About page with version and roadmap."""
    return render_template('about.html')


# =============================================================================
# Email Routes
# =============================================================================

@app.route('/settings/email', methods=['GET', 'POST'])
@login_required
def email_settings():
    """Email settings page."""
    from email_module import EmailManager
    
    settings_manager = SettingsManager(get_effective_user_id())
    email_manager = EmailManager(session['user_id'])
    
    if request.method == 'POST':
        updates = {
            # Microsoft Graph settings
            'graph_tenant_id': request.form.get('graph_tenant_id'),
            'graph_client_id': request.form.get('graph_client_id'),
            'graph_client_secret': request.form.get('graph_client_secret'),
            'graph_sender_email': request.form.get('graph_sender_email'),
            # Reminder settings
            'reminders_enabled': 1 if request.form.get('reminders_enabled') else 0,
            'reminder_1_days': int(request.form.get('reminder_1_days', 7) or 7),
            'reminder_2_days': int(request.form.get('reminder_2_days', 0) or 0),
            'reminder_3_days': int(request.form.get('reminder_3_days', -7) or -7),
            'max_reminders': int(request.form.get('max_reminders', 3) or 3),
            'send_payment_thanks': 1 if request.form.get('send_payment_thanks') else 0,
        }
        settings_manager.update_settings(updates)
        flash('Email settings updated.', 'success')
        return redirect(url_for('email_settings'))
    
    current_settings = settings_manager.get_settings()
    email_log = email_manager.get_email_log(limit=20)
    
    return render_template('email_settings.html', 
                          settings=current_settings,
                          email_log=email_log)


@app.route('/settings/email/test-graph', methods=['POST'])
@login_required
def test_graph_config():
    """Test Microsoft Graph email configuration."""
    from graph_email import GraphEmailManager
    
    tenant_id = request.form.get('graph_tenant_id')
    client_id = request.form.get('graph_client_id')
    client_secret = request.form.get('graph_client_secret')
    sender_email = request.form.get('graph_sender_email')
    
    if not all([tenant_id, client_id, client_secret, sender_email]):
        return jsonify({'success': False, 'error': 'Please fill in all Microsoft Graph fields'})
    
    try:
        # Save settings first
        settings_manager = SettingsManager(get_effective_user_id())
        settings_manager.update_settings({
            'graph_tenant_id': tenant_id,
            'graph_client_id': client_id,
            'graph_client_secret': client_secret,
            'graph_sender_email': sender_email,
        })
        
        # Test connection
        graph = GraphEmailManager(tenant_id, client_id, client_secret, sender_email)
        result = graph.test_connection()
        
        if result['success']:
            return jsonify({
                'success': True, 
                'message': result['message'],
                'user': result.get('user')
            })
        else:
            return jsonify({'success': False, 'error': result['message']})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/settings/email/templates/<template_type>', methods=['GET', 'POST'])
@login_required
def edit_email_template(template_type):
    """Edit an email template."""
    from email_module import EmailManager, DEFAULT_TEMPLATES
    
    email_manager = EmailManager(session['user_id'])
    
    template_names = {
        'invoice_send': 'Invoice Email',
        'payment_thank_you': 'Payment Thank You',
        'reminder_1': 'First Reminder',
        'reminder_2': 'Second Reminder',
        'reminder_3': 'Third/Final Reminder'
    }
    
    if template_type not in template_names:
        flash('Invalid template type.', 'error')
        return redirect(url_for('email_settings'))
    
    if request.method == 'POST':
        subject = request.form.get('subject', '')
        body = request.form.get('body', '')
        enabled = request.form.get('enabled') == '1'
        
        email_manager.save_template(template_type, subject, body, enabled)
        flash('Template saved.', 'success')
        return redirect(url_for('email_settings'))
    
    template = email_manager.get_template(template_type)
    
    return render_template('email_template_edit.html',
                          template=template,
                          template_type=template_type,
                          template_name=template_names[template_type])


@app.route('/settings/email/templates/<template_type>/reset')
@login_required
def reset_email_template(template_type):
    """Reset an email template to default."""
    from email_module import EmailManager, DEFAULT_TEMPLATES
    
    if template_type in DEFAULT_TEMPLATES:
        email_manager = EmailManager(session['user_id'])
        default = DEFAULT_TEMPLATES[template_type]
        email_manager.save_template(template_type, default['subject'], default['body'], True)
        flash('Template reset to default.', 'success')
    
    return redirect(url_for('edit_email_template', template_type=template_type))


@app.route('/invoices/<int:invoice_id>/send-email', methods=['POST'])
@login_required
def send_invoice_email_route(invoice_id):
    """Send invoice via email."""
    from email_module import send_invoice_email
    from pdf_generator import generate_invoice_pdf
    
    user_id = get_effective_user_id()
    invoice_manager = InvoiceManager(user_id)
    settings_manager = SettingsManager(user_id)
    
    invoice = invoice_manager.get(invoice_id)
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('invoices'))
    
    settings = settings_manager.get_settings()
    
    # Generate PDF
    pdf_path = None
    try:
        pdf_buffer = generate_invoice_pdf(invoice, settings)
        pdf_dir = os.path.join(os.path.dirname(__file__), 'data', 'temp')
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_path = os.path.join(pdf_dir, f"{invoice['invoice_number']}.pdf")
        with open(pdf_path, 'wb') as f:
            f.write(pdf_buffer.getvalue())
    except Exception as e:
        flash(f'Failed to generate PDF: {str(e)}', 'error')
    
    # Get base URL for payment links
    base_url = request.url_root.rstrip('/')
    
    success, message = send_invoice_email(user_id, invoice, settings, pdf_path, base_url)
    
    # Clean up temp PDF
    if pdf_path and os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
        except:
            pass
    
    if success:
        # Update status to sent
        invoice_manager.update_status(invoice_id, 'sent')
        trigger_webhooks('invoice.sent', user_id, serialize_invoice(invoice))
        flash('Invoice sent successfully!', 'success')
    else:
        flash(f'Failed to send email: {message}', 'error')
    
    return redirect(url_for('view_invoice', invoice_id=invoice_id))


# =============================================================================
# Team Management Routes
# =============================================================================

@app.route('/settings/team')
@login_required
def team_management():
    """Team management page."""
    from team_management import TeamManager, ROLES, get_user_role
    
    # Only owners and admins can manage team
    role = get_user_role(session['user_id'])
    if role not in ('owner', 'admin'):
        flash('Only account owners and admins can manage team members.', 'error')
        return redirect(url_for('settings'))
    
    # Use effective_user_id so admins see owner's team
    effective_user_id = get_effective_user_id()
    team_manager = TeamManager(effective_user_id)
    members = team_manager.get_team_members()
    
    # Get owner info
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, email, last_login, login_count, created_at FROM users WHERE id = ?', (effective_user_id,))
        owner = dict(cursor.fetchone())
    
    return render_template('team.html', members=members, roles=ROLES, owner=owner)


@app.route('/settings/team/add', methods=['POST'])
@login_required
def add_team_member():
    """Add a new team member."""
    from team_management import TeamManager, get_user_role
    
    role = get_user_role(session['user_id'])
    if role not in ('owner', 'admin'):
        flash('Only account owners and admins can add team members.', 'error')
        return redirect(url_for('settings'))
    
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    member_role = request.form.get('role')
    
    if not all([username, email, password, member_role]):
        flash('All fields are required.', 'error')
        return redirect(url_for('team_management'))
    
    # Use effective_user_id so admins add to owner's team
    team_manager = TeamManager(get_effective_user_id())
    success, message, member_id = team_manager.invite_member(email, username, password, member_role)
    
    if success:
        flash(f'Team member "{username}" added successfully.', 'success')
    else:
        flash(f'Failed to add team member: {message}', 'error')
    
    return redirect(url_for('team_management'))


@app.route('/settings/team/update-role', methods=['POST'])
@login_required
def update_team_member_role():
    """Update a team member's role."""
    from team_management import TeamManager, get_user_role
    
    role = get_user_role(session['user_id'])
    if role not in ('owner', 'admin'):
        flash('Only account owners and admins can update team roles.', 'error')
        return redirect(url_for('settings'))
    
    member_id = request.form.get('member_id', type=int)
    new_role = request.form.get('role')
    
    if member_id and new_role:
        team_manager = TeamManager(get_effective_user_id())
        if team_manager.update_member_role(member_id, new_role):
            flash('Role updated successfully.', 'success')
        else:
            flash('Failed to update role.', 'error')
    
    return redirect(url_for('team_management'))


@app.route('/settings/team/<int:member_id>/deactivate', methods=['POST'])
@login_required
def deactivate_team_member(member_id):
    """Deactivate a team member."""
    from team_management import TeamManager, get_user_role
    
    role = get_user_role(session['user_id'])
    if role not in ('owner', 'admin'):
        flash('Only account owners and admins can deactivate team members.', 'error')
        return redirect(url_for('settings'))
    
    team_manager = TeamManager(get_effective_user_id())
    if team_manager.deactivate_member(member_id):
        flash('Team member deactivated.', 'success')
    else:
        flash('Failed to deactivate team member.', 'error')
    
    return redirect(url_for('team_management'))


@app.route('/settings/team/<int:member_id>/reactivate', methods=['POST'])
@login_required
def reactivate_team_member(member_id):
    """Reactivate a team member."""
    from team_management import TeamManager, get_user_role
    
    role = get_user_role(session['user_id'])
    if role not in ('owner', 'admin'):
        flash('Only account owners and admins can reactivate team members.', 'error')
        return redirect(url_for('settings'))
    
    team_manager = TeamManager(get_effective_user_id())
    if team_manager.reactivate_member(member_id):
        flash('Team member reactivated.', 'success')
    else:
        flash('Failed to reactivate team member.', 'error')
    
    return redirect(url_for('team_management'))


@app.route('/settings/team/<int:member_id>/delete', methods=['POST'])
@login_required
def delete_team_member(member_id):
    """Delete a team member."""
    from team_management import TeamManager, get_user_role
    
    role = get_user_role(session['user_id'])
    if role not in ('owner', 'admin'):
        flash('Only account owners and admins can delete team members.', 'error')
        return redirect(url_for('settings'))
    
    team_manager = TeamManager(get_effective_user_id())
    if team_manager.delete_member(member_id):
        flash('Team member deleted.', 'success')
    else:
        flash('Failed to delete team member.', 'error')
    
    return redirect(url_for('team_management'))


@app.route('/settings/team/reset-password', methods=['POST'])
@login_required
def reset_team_member_password():
    """Reset a team member's password."""
    from team_management import TeamManager, get_user_role
    
    role = get_user_role(session['user_id'])
    if role not in ('owner', 'admin'):
        flash('Only account owners and admins can reset passwords.', 'error')
        return redirect(url_for('settings'))
    
    member_id = request.form.get('member_id', type=int)
    new_password = request.form.get('new_password')
    
    if member_id and new_password:
        team_manager = TeamManager(get_effective_user_id())
        if team_manager.reset_member_password(member_id, new_password):
            flash('Password reset successfully.', 'success')
        else:
            flash('Failed to reset password.', 'error')
    
    return redirect(url_for('team_management'))


# =============================================================================
# REST API Endpoints
# =============================================================================

# API: Exchange Rate (public for forms)
@app.route('/api/exchange-rate')
@login_required
def api_exchange_rate():
    """Get exchange rate between currencies using CurrencyAPI."""
    from_currency = request.args.get('from', 'USD')
    to_currency = request.args.get('to', 'GBP')
    
    if from_currency == to_currency:
        return jsonify({'rate': 1.0, 'from': from_currency, 'to': to_currency, 'source': 'same'})
    
    # Try to get from CurrencyAPI
    settings = SettingsManager(get_effective_user_id()).get_settings()
    api_key = settings.get('currency_api_key')  # Match the integrations page field name
    
    if api_key:
        try:
            import requests
            response = requests.get(
                'https://api.currencyapi.com/v3/latest',
                params={
                    'apikey': api_key,
                    'base_currency': from_currency,
                    'currencies': to_currency
                },
                timeout=5
            )
            if response.ok:
                data = response.json()
                rate = data.get('data', {}).get(to_currency, {}).get('value')
                if rate:
                    return jsonify({'rate': rate, 'from': from_currency, 'to': to_currency, 'source': 'currencyapi'})
        except Exception as e:
            print(f"CurrencyAPI error: {e}")
    
    # Fallback to stored rate
    rate = get_currency_rate(get_effective_user_id(), from_currency, to_currency)
    
    # If still 1.0, indicate no rate available
    if rate == 1.0:
        return jsonify({
            'rate': 1.0, 
            'from': from_currency, 
            'to': to_currency, 
            'source': 'default',
            'message': 'No CurrencyAPI key configured. Please add your API key in Integrations settings, or enter the exchange rate manually.'
        })
    
    return jsonify({'rate': rate, 'from': from_currency, 'to': to_currency, 'source': 'stored'})


# API: Customers
@app.route('/api/v1/customers', methods=['GET'])
@api_key_required(['read'])
def api_get_customers():
    customers = CustomerManager(g.api_user_id).get_all()
    return api_success([serialize_customer(c) for c in customers])


@app.route('/api/v1/customers/<int:customer_id>', methods=['GET'])
@api_key_required(['read'])
def api_get_customer(customer_id):
    customer = CustomerManager(g.api_user_id).get(customer_id)
    if not customer:
        return api_error('Customer not found', 404)
    return api_success(serialize_customer(customer))


@app.route('/api/v1/customers', methods=['POST'])
@api_key_required(['write'])
def api_create_customer():
    data = request.get_json()
    if not data or not data.get('name'):
        return api_error('Name is required')
    
    manager = CustomerManager(g.api_user_id)
    customer_id = manager.create(
        name=data['name'],
        email=data.get('email'),
        phone=data.get('phone'),
        address_line1=data.get('address', {}).get('line1'),
        address_line2=data.get('address', {}).get('line2'),
        city=data.get('address', {}).get('city'),
        state=data.get('address', {}).get('state'),
        postal_code=data.get('address', {}).get('postal_code'),
        country=data.get('address', {}).get('country'),
        tax_number=data.get('tax_number'),
        custom_tax_rate=data.get('custom_tax_rate'),
        custom_currency=data.get('custom_currency'),
        notes=data.get('notes')
    )
    
    customer = manager.get(customer_id)
    trigger_webhooks('customer.created', g.api_user_id, serialize_customer(customer))
    
    return api_success(serialize_customer(customer), status=201)


@app.route('/api/v1/customers/<int:customer_id>', methods=['PUT'])
@api_key_required(['write'])
def api_update_customer(customer_id):
    data = request.get_json()
    manager = CustomerManager(g.api_user_id)
    
    if not manager.get(customer_id):
        return api_error('Customer not found', 404)
    
    updates = {}
    if 'name' in data:
        updates['name'] = data['name']
    if 'email' in data:
        updates['email'] = data['email']
    if 'phone' in data:
        updates['phone'] = data['phone']
    if 'address' in data:
        updates['address_line1'] = data['address'].get('line1')
        updates['address_line2'] = data['address'].get('line2')
        updates['city'] = data['address'].get('city')
        updates['state'] = data['address'].get('state')
        updates['postal_code'] = data['address'].get('postal_code')
        updates['country'] = data['address'].get('country')
    if 'tax_number' in data:
        updates['tax_number'] = data['tax_number']
    if 'custom_tax_rate' in data:
        updates['custom_tax_rate'] = data['custom_tax_rate']
    if 'custom_currency' in data:
        updates['custom_currency'] = data['custom_currency']
    if 'notes' in data:
        updates['notes'] = data['notes']
    
    manager.update(customer_id, updates)
    customer = manager.get(customer_id)
    trigger_webhooks('customer.updated', g.api_user_id, serialize_customer(customer))
    
    return api_success(serialize_customer(customer))


@app.route('/api/v1/customers/<int:customer_id>', methods=['DELETE'])
@api_key_required(['write'])
def api_delete_customer(customer_id):
    manager = CustomerManager(g.api_user_id)
    customer = manager.get(customer_id)
    
    if not customer:
        return api_error('Customer not found', 404)
    
    trigger_webhooks('customer.deleted', g.api_user_id, serialize_customer(customer))
    manager.delete(customer_id)
    
    return api_success(message='Customer deleted')


# API: Bulk Import Customers
@app.route('/api/v1/customers/bulk', methods=['POST'])
@api_key_required(['write'])
def api_bulk_import_customers():
    """Bulk import customers via API."""
    from import_export import bulk_import_customers_api
    
    data = request.get_json()
    if not data or not isinstance(data.get('customers'), list):
        return api_error('Expected {"customers": [...]}')
    
    update_existing = data.get('update_existing', False)
    result = bulk_import_customers_api(g.api_user_id, data['customers'], update_existing)
    
    return api_success(result, status=201)


# API: Products
@app.route('/api/v1/products', methods=['GET'])
@api_key_required(['read'])
def api_get_products():
    products = ProductManager(g.api_user_id).get_all(active_only=False)
    return api_success([serialize_product(p) for p in products])


@app.route('/api/v1/products/<int:product_id>', methods=['GET'])
@api_key_required(['read'])
def api_get_product(product_id):
    product = ProductManager(g.api_user_id).get(product_id)
    if not product:
        return api_error('Product not found', 404)
    return api_success(serialize_product(product))


@app.route('/api/v1/products', methods=['POST'])
@api_key_required(['write'])
def api_create_product():
    data = request.get_json()
    if not data or not data.get('name'):
        return api_error('Name is required')
    
    manager = ProductManager(g.api_user_id)
    product_id = manager.create(
        name=data['name'],
        unit_price=data.get('unit_price', 0),
        description=data.get('description'),
        unit=data.get('unit', 'unit'),
        sku=data.get('sku'),
        is_service=1 if data.get('is_service') else 0,
        billing_term=data.get('billing_term'),
        taxable=1 if data.get('taxable', True) else 0
    )
    
    # Update COA if provided
    coa_id = data.get('coa_id')
    if coa_id:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE products SET coa_id = ? WHERE id = ?', (int(coa_id), product_id))
            conn.commit()
    
    product = manager.get(product_id)
    trigger_webhooks('product.created', g.api_user_id, serialize_product(product))
    
    return api_success(serialize_product(product), status=201)


@app.route('/api/v1/products/<int:product_id>', methods=['PUT'])
@api_key_required(['write'])
def api_update_product(product_id):
    data = request.get_json()
    manager = ProductManager(g.api_user_id)
    
    if not manager.get(product_id):
        return api_error('Product not found', 404)
    
    updates = {}
    for field in ['name', 'description', 'unit_price', 'unit', 'sku', 'billing_term']:
        if field in data:
            updates[field] = data[field]
    if 'is_service' in data:
        updates['is_service'] = 1 if data['is_service'] else 0
    if 'taxable' in data:
        updates['taxable'] = 1 if data['taxable'] else 0
    if 'active' in data:
        updates['active'] = 1 if data['active'] else 0
    
    manager.update(product_id, updates)
    
    # Update COA if provided
    if 'coa_id' in data:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE products SET coa_id = ? WHERE id = ?', 
                          (int(data['coa_id']) if data['coa_id'] else None, product_id))
            conn.commit()
    
    product = manager.get(product_id)
    trigger_webhooks('product.updated', g.api_user_id, serialize_product(product))
    
    return api_success(serialize_product(product))


@app.route('/api/v1/products/<int:product_id>', methods=['DELETE'])
@api_key_required(['write'])
def api_delete_product(product_id):
    manager = ProductManager(g.api_user_id)
    product = manager.get(product_id)
    
    if not product:
        return api_error('Product not found', 404)
    
    trigger_webhooks('product.deleted', g.api_user_id, serialize_product(product))
    manager.delete(product_id)
    
    return api_success(message='Product deactivated')


# API: Bulk Import Products
@app.route('/api/v1/products/bulk', methods=['POST'])
@api_key_required(['write'])
def api_bulk_import_products():
    """Bulk import products via API."""
    from import_export import bulk_import_products_api
    
    data = request.get_json()
    if not data or not isinstance(data.get('products'), list):
        return api_error('Expected {"products": [...]}')
    
    update_existing = data.get('update_existing', False)
    result = bulk_import_products_api(g.api_user_id, data['products'], update_existing)
    
    return api_success(result, status=201)


# API: Invoices
@app.route('/api/v1/invoices', methods=['GET'])
@api_key_required(['read'])
def api_get_invoices():
    status = request.args.get('status')
    invoices = InvoiceManager(g.api_user_id).get_all(status=status)
    return api_success([serialize_invoice(inv) for inv in invoices])


@app.route('/api/v1/invoices/<int:invoice_id>', methods=['GET'])
@api_key_required(['read'])
def api_get_invoice(invoice_id):
    invoice = InvoiceManager(g.api_user_id).get(invoice_id)
    if not invoice:
        return api_error('Invoice not found', 404)
    return api_success(serialize_invoice(invoice))


@app.route('/api/v1/invoices', methods=['POST'])
@api_key_required(['write'])
def api_create_invoice():
    data = request.get_json()
    manager = InvoiceManager(g.api_user_id)
    
    invoice_id = manager.create(
        customer_id=data.get('customer_id'),
        tax_rate=data.get('tax_rate'),
        currency=data.get('currency'),
        issue_date=data.get('issue_date'),
        due_date=data.get('due_date'),
        notes=data.get('notes'),
        payment_terms=data.get('payment_terms')
    )
    
    # Add items
    for item in data.get('items', []):
        manager.add_item(
            invoice_id=invoice_id,
            description=item.get('description', ''),
            quantity=item.get('quantity', 1),
            unit_price=item.get('unit_price', 0),
            product_id=item.get('product_id'),
            tax_rate=item.get('tax_rate')
        )
    
    invoice = manager.get(invoice_id)
    trigger_webhooks('invoice.created', g.api_user_id, serialize_invoice(invoice))
    
    return api_success(serialize_invoice(invoice), status=201)


@app.route('/api/v1/invoices/<int:invoice_id>', methods=['PUT'])
@api_key_required(['write'])
def api_update_invoice(invoice_id):
    data = request.get_json()
    manager = InvoiceManager(g.api_user_id)
    
    invoice = manager.get(invoice_id)
    if not invoice:
        return api_error('Invoice not found', 404)
    
    updates = {}
    for field in ['customer_id', 'status', 'issue_date', 'due_date', 'currency', 'tax_rate', 'notes', 'payment_terms']:
        if field in data:
            updates[field] = data[field]
    
    if updates:
        manager.update(invoice_id, updates)
    
    # Update items if provided
    if 'items' in data:
        for item in invoice.get('items', []):
            manager.remove_item(item['id'])
        
        for item in data['items']:
            manager.add_item(
                invoice_id=invoice_id,
                description=item.get('description', ''),
                quantity=item.get('quantity', 1),
                unit_price=item.get('unit_price', 0),
                product_id=item.get('product_id'),
                tax_rate=item.get('tax_rate')
            )
    
    invoice = manager.get(invoice_id)
    trigger_webhooks('invoice.updated', g.api_user_id, serialize_invoice(invoice))
    
    return api_success(serialize_invoice(invoice))


@app.route('/api/v1/invoices/<int:invoice_id>', methods=['DELETE'])
@api_key_required(['write'])
def api_delete_invoice(invoice_id):
    manager = InvoiceManager(g.api_user_id)
    invoice = manager.get(invoice_id)
    
    if not invoice:
        return api_error('Invoice not found', 404)
    
    trigger_webhooks('invoice.deleted', g.api_user_id, serialize_invoice(invoice))
    manager.delete(invoice_id)
    
    return api_success(message='Invoice deleted')


# API: Bulk Import Invoices
@app.route('/api/v1/invoices/bulk', methods=['POST'])
@api_key_required(['write'])
def api_bulk_import_invoices():
    """Bulk import invoices via API."""
    from import_export import bulk_import_invoices_api
    
    data = request.get_json()
    if not data or not isinstance(data.get('invoices'), list):
        return api_error('Expected {"invoices": [...]}')
    
    result = bulk_import_invoices_api(g.api_user_id, data['invoices'])
    
    return api_success(result, status=201)


# API: Payments
@app.route('/api/v1/invoices/<int:invoice_id>/payments', methods=['POST'])
@api_key_required(['write'])
def api_add_payment(invoice_id):
    data = request.get_json()
    manager = InvoiceManager(g.api_user_id)
    
    invoice = manager.get(invoice_id)
    if not invoice:
        return api_error('Invoice not found', 404)
    
    amount = data.get('amount')
    if not amount or amount <= 0:
        return api_error('Valid amount is required')
    
    payment_id = manager.add_payment(
        invoice_id=invoice_id,
        amount=amount,
        payment_method=data.get('payment_method'),
        reference=data.get('reference'),
        notes=data.get('notes'),
        created_via='api'
    )
    
    invoice = manager.get(invoice_id)
    
    if invoice['status'] == 'paid':
        trigger_webhooks('invoice.paid', g.api_user_id, serialize_invoice(invoice))
    else:
        trigger_webhooks('invoice.partially_paid', g.api_user_id, serialize_invoice(invoice))
    
    trigger_webhooks('payment.received', g.api_user_id, {
        'invoice_id': invoice_id,
        'payment': {
            'id': payment_id,
            'amount': amount,
            'payment_method': data.get('payment_method'),
            'reference': data.get('reference')
        }
    })
    
    return api_success(serialize_invoice(invoice))


@app.route('/api/v1/invoices/<int:invoice_id>/mark-paid', methods=['POST'])
@api_key_required(['write'])
def api_mark_paid(invoice_id):
    data = request.get_json() or {}
    manager = InvoiceManager(g.api_user_id)
    
    invoice = manager.get(invoice_id)
    if not invoice:
        return api_error('Invoice not found', 404)
    
    manager.mark_as_paid(
        invoice_id=invoice_id,
        payment_method=data.get('payment_method'),
        reference=data.get('reference'),
        notes=data.get('notes')
    )
    
    invoice = manager.get(invoice_id)
    trigger_webhooks('invoice.paid', g.api_user_id, serialize_invoice(invoice))
    
    return api_success(serialize_invoice(invoice))


# API: Webhooks for external payment processors
@app.route('/api/webhook/payment', methods=['POST'])
def api_webhook_payment():
    """
    External payment webhook endpoint.
    Accepts payment notifications from payment processors.
    Requires API key in header.
    """
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        return api_error('API key required', 401)
    
    key_data = validate_api_key(api_key)
    if not key_data:
        return api_error('Invalid API key', 401)
    
    if 'write' not in key_data.get('permissions', []):
        return api_error('Insufficient permissions', 403)
    
    data = request.get_json()
    if not data:
        return api_error('Invalid JSON payload')
    
    invoice_id = data.get('invoice_id')
    invoice_number = data.get('invoice_number')
    amount = data.get('amount')
    
    if not (invoice_id or invoice_number):
        return api_error('invoice_id or invoice_number is required')
    
    if not amount or amount <= 0:
        return api_error('Valid amount is required')
    
    manager = InvoiceManager(key_data['user_id'])
    
    if invoice_number and not invoice_id:
        invoice = manager.get_by_number(invoice_number)
        if invoice:
            invoice_id = invoice['id']
    
    invoice = manager.get(invoice_id) if invoice_id else None
    
    if not invoice:
        return api_error('Invoice not found', 404)
    
    payment_id = manager.add_payment(
        invoice_id=invoice_id,
        amount=amount,
        payment_method=data.get('payment_method', 'External'),
        reference=data.get('reference'),
        notes=data.get('notes'),
        created_via='webhook'
    )
    
    invoice = manager.get(invoice_id)
    
    if invoice['status'] == 'paid':
        trigger_webhooks('invoice.paid', key_data['user_id'], serialize_invoice(invoice))
    else:
        trigger_webhooks('invoice.partially_paid', key_data['user_id'], serialize_invoice(invoice))
    
    trigger_webhooks('payment.received', key_data['user_id'], {
        'invoice_id': invoice_id,
        'payment': {
            'id': payment_id,
            'amount': amount,
            'payment_method': data.get('payment_method'),
            'reference': data.get('reference')
        }
    })
    
    return api_success({
        'invoice': serialize_invoice(invoice),
        'payment_id': payment_id
    })


# =============================================================================
# API: Recurring Invoices
# =============================================================================

@app.route('/api/v1/recurring', methods=['GET'])
@api_key_required(['read'])
def api_get_recurring_invoices():
    """Get all recurring invoice templates."""
    from recurring_invoices import RecurringInvoiceManager
    
    manager = RecurringInvoiceManager(g.api_user_id)
    recurring_list = manager.get_all(active_only=False)
    
    # Add totals
    for ri in recurring_list:
        template = manager.get(ri['id'])
        if template:
            ri['total'] = sum(item.get('line_total', 0) for item in template.get('items', []))
    
    return api_success(recurring_list)


@app.route('/api/v1/recurring/<int:recurring_id>', methods=['GET'])
@api_key_required(['read'])
def api_get_recurring_invoice(recurring_id):
    """Get a specific recurring invoice template with items."""
    from recurring_invoices import RecurringInvoiceManager
    
    manager = RecurringInvoiceManager(g.api_user_id)
    recurring = manager.get(recurring_id)
    
    if not recurring:
        return api_error('Recurring invoice not found', 404)
    
    return api_success(recurring)


@app.route('/api/v1/recurring/due', methods=['GET'])
@api_key_required(['read'])
def api_get_due_recurring_invoices():
    """Get recurring invoices that are due for generation."""
    from recurring_invoices import RecurringInvoiceManager
    
    manager = RecurringInvoiceManager(g.api_user_id)
    due_list = manager.get_due_invoices()
    
    return api_success({
        'count': len(due_list),
        'due_invoices': due_list
    })


@app.route('/api/v1/recurring/generate', methods=['POST'])
@api_key_required(['write'])
def api_generate_due_recurring_invoices():
    """
    Generate all due recurring invoices.
    
    This is the endpoint to call from n8n or other automation tools.
    
    Example n8n HTTP Request node:
    - Method: POST
    - URL: https://your-domain.com/api/v1/recurring/generate
    - Headers: X-API-Key: your-api-key
    
    Returns list of generated invoice IDs.
    """
    from recurring_invoices import RecurringInvoiceManager
    
    manager = RecurringInvoiceManager(g.api_user_id)
    due_invoices = manager.get_due_invoices()
    
    generated = []
    errors = []
    
    for ri in due_invoices:
        try:
            invoice_id = manager.generate_invoice(ri['id'])
            if invoice_id:
                invoice_manager = InvoiceManager(g.api_user_id)
                invoice = invoice_manager.get(invoice_id)
                generated.append({
                    'recurring_id': ri['id'],
                    'invoice_id': invoice_id,
                    'invoice_number': invoice['invoice_number'] if invoice else None,
                    'customer_name': ri.get('customer_name'),
                    'total': invoice['total'] if invoice else 0
                })
                
                # Trigger webhook for generated invoice
                if invoice:
                    trigger_webhooks('invoice.created', g.api_user_id, serialize_invoice(invoice))
        except Exception as e:
            errors.append({
                'recurring_id': ri['id'],
                'customer_name': ri.get('customer_name'),
                'error': str(e)
            })
    
    return api_success({
        'generated_count': len(generated),
        'error_count': len(errors),
        'generated': generated,
        'errors': errors if errors else None
    })


@app.route('/api/v1/recurring/<int:recurring_id>/generate', methods=['POST'])
@api_key_required(['write'])
def api_generate_single_recurring_invoice(recurring_id):
    """Generate a single recurring invoice immediately."""
    from recurring_invoices import RecurringInvoiceManager
    
    manager = RecurringInvoiceManager(g.api_user_id)
    recurring = manager.get(recurring_id)
    
    if not recurring:
        return api_error('Recurring invoice not found', 404)
    
    try:
        invoice_id = manager.generate_invoice(recurring_id)
        
        if invoice_id:
            invoice_manager = InvoiceManager(g.api_user_id)
            invoice = invoice_manager.get(invoice_id)
            
            # Trigger webhook
            if invoice:
                trigger_webhooks('invoice.created', g.api_user_id, serialize_invoice(invoice))
            
            return api_success({
                'invoice_id': invoice_id,
                'invoice_number': invoice['invoice_number'] if invoice else None,
                'invoice': serialize_invoice(invoice) if invoice else None
            })
        else:
            return api_error('Failed to generate invoice')
    except Exception as e:
        return api_error(f'Error generating invoice: {str(e)}')


@app.route('/api/v1/recurring/<int:recurring_id>/toggle', methods=['POST'])
@api_key_required(['write'])
def api_toggle_recurring_invoice(recurring_id):
    """Pause or resume a recurring invoice."""
    from recurring_invoices import RecurringInvoiceManager
    
    manager = RecurringInvoiceManager(g.api_user_id)
    recurring = manager.get(recurring_id)
    
    if not recurring:
        return api_error('Recurring invoice not found', 404)
    
    new_status = 0 if recurring['active'] else 1
    manager.update(recurring_id, {'active': new_status})
    
    return api_success({
        'recurring_id': recurring_id,
        'active': bool(new_status),
        'status': 'activated' if new_status else 'paused'
    })


# =============================================================================
# Accounts Payable API Routes
# =============================================================================

@app.route('/api/v1/suppliers', methods=['GET'])
@api_key_required(['read'])
def api_suppliers_list():
    """List all suppliers."""
    from accounts_payable_api import api_list_suppliers
    return api_list_suppliers(g.api_user_id)


@app.route('/api/v1/suppliers/<int:supplier_id>', methods=['GET'])
@api_key_required(['read'])
def api_suppliers_get(supplier_id):
    """Get a supplier."""
    from accounts_payable_api import api_get_supplier
    return api_get_supplier(g.api_user_id, supplier_id)


@app.route('/api/v1/suppliers', methods=['POST'])
@api_key_required(['write'])
def api_suppliers_create():
    """Create a supplier."""
    from accounts_payable_api import api_create_supplier
    return api_create_supplier(g.api_user_id)


@app.route('/api/v1/suppliers/<int:supplier_id>', methods=['PUT'])
@api_key_required(['write'])
def api_suppliers_update(supplier_id):
    """Update a supplier."""
    from accounts_payable_api import api_update_supplier
    return api_update_supplier(g.api_user_id, supplier_id)


@app.route('/api/v1/suppliers/<int:supplier_id>', methods=['DELETE'])
@api_key_required(['write'])
def api_suppliers_delete(supplier_id):
    """Delete a supplier."""
    from accounts_payable_api import api_delete_supplier
    return api_delete_supplier(g.api_user_id, supplier_id)


@app.route('/api/v1/suppliers/import', methods=['POST'])
@api_key_required(['write'])
def api_suppliers_import():
    """Bulk import suppliers."""
    from accounts_payable_api import api_import_suppliers
    return api_import_suppliers(g.api_user_id)


# Bills API
@app.route('/api/v1/bills', methods=['GET'])
@api_key_required(['read'])
def api_bills_list():
    """List all bills."""
    from accounts_payable_api import api_list_bills
    return api_list_bills(g.api_user_id)


@app.route('/api/v1/bills/<int:bill_id>', methods=['GET'])
@api_key_required(['read'])
def api_bills_get(bill_id):
    """Get a bill."""
    from accounts_payable_api import api_get_bill
    return api_get_bill(g.api_user_id, bill_id)


@app.route('/api/v1/bills', methods=['POST'])
@api_key_required(['write'])
def api_bills_create():
    """Create a bill."""
    from accounts_payable_api import api_create_bill
    return api_create_bill(g.api_user_id)


@app.route('/api/v1/bills/<int:bill_id>', methods=['PUT'])
@api_key_required(['write'])
def api_bills_update(bill_id):
    """Update a bill."""
    from accounts_payable_api import api_update_bill
    return api_update_bill(g.api_user_id, bill_id)


@app.route('/api/v1/bills/<int:bill_id>', methods=['DELETE'])
@api_key_required(['write'])
def api_bills_delete(bill_id):
    """Delete a bill."""
    from accounts_payable_api import api_delete_bill
    return api_delete_bill(g.api_user_id, bill_id)


@app.route('/api/v1/bills/<int:bill_id>/payments', methods=['POST'])
@api_key_required(['write'])
def api_bills_add_payment(bill_id):
    """Add payment to a bill."""
    from accounts_payable_api import api_bill_add_payment
    return api_bill_add_payment(g.api_user_id, bill_id)


@app.route('/api/v1/bills/<int:bill_id>/status', methods=['PATCH'])
@api_key_required(['write'])
def api_bills_update_status(bill_id):
    """Update bill status."""
    from accounts_payable_api import api_bill_update_status
    return api_bill_update_status(g.api_user_id, bill_id)


# Expenses API
@app.route('/api/v1/expenses', methods=['GET'])
@api_key_required(['read'])
def api_expenses_list():
    """List all expenses."""
    from accounts_payable_api import api_list_expenses
    return api_list_expenses(g.api_user_id)


@app.route('/api/v1/expenses/<int:expense_id>', methods=['GET'])
@api_key_required(['read'])
def api_expenses_get(expense_id):
    """Get an expense."""
    from accounts_payable_api import api_get_expense
    return api_get_expense(g.api_user_id, expense_id)


@app.route('/api/v1/expenses', methods=['POST'])
@api_key_required(['write'])
def api_expenses_create():
    """Create an expense."""
    from accounts_payable_api import api_create_expense
    return api_create_expense(g.api_user_id)


@app.route('/api/v1/expenses/<int:expense_id>', methods=['PUT'])
@api_key_required(['write'])
def api_expenses_update(expense_id):
    """Update an expense."""
    from accounts_payable_api import api_update_expense
    return api_update_expense(g.api_user_id, expense_id)


@app.route('/api/v1/expenses/<int:expense_id>', methods=['DELETE'])
@api_key_required(['write'])
def api_expenses_delete(expense_id):
    """Delete an expense."""
    from accounts_payable_api import api_delete_expense
    return api_delete_expense(g.api_user_id, expense_id)


@app.route('/api/v1/expenses/<int:expense_id>/approve', methods=['POST'])
@api_key_required(['write'])
def api_expenses_approve(expense_id):
    """Approve an expense."""
    from accounts_payable_api import api_expense_approve
    return api_expense_approve(g.api_user_id, expense_id)


@app.route('/api/v1/expenses/<int:expense_id>/reject', methods=['POST'])
@api_key_required(['write'])
def api_expenses_reject(expense_id):
    """Reject an expense."""
    from accounts_payable_api import api_expense_reject
    return api_expense_reject(g.api_user_id, expense_id)


@app.route('/api/v1/expenses/categories', methods=['GET'])
@api_key_required(['read'])
def api_expenses_categories():
    """Get expense categories and payment methods."""
    from accounts_payable_api import api_get_expense_categories
    return api_get_expense_categories()


@app.route('/api/v1/accounts-payable/summary', methods=['GET'])
@api_key_required(['read'])
def api_accounts_payable_summary():
    """Get accounts payable summary."""
    from accounts_payable_api import api_get_accounts_payable_summary
    return api_get_accounts_payable_summary(g.api_user_id)


# =============================================================================
# Error Handlers
# =============================================================================

@app.errorhandler(404)
def not_found(error):
    if request.path.startswith('/api/'):
        return api_error('Not found', 404)
    return render_template('error.html', error='Page not found'), 404


@app.errorhandler(500)
def server_error(error):
    if request.path.startswith('/api/'):
        return api_error('Internal server error', 500)
    return render_template('error.html', error='Internal server error'), 500


# =============================================================================
# Recurring Invoices Routes
# =============================================================================

@app.route('/invoices/recurring')
@login_required
def recurring_invoices():
    """List all recurring invoices."""
    from recurring_invoices import RecurringInvoiceManager, RECURRING_FREQUENCIES
    
    manager = RecurringInvoiceManager(get_effective_user_id())
    recurring_list = manager.get_all(active_only=False)
    
    # Calculate totals for each recurring invoice
    for ri in recurring_list:
        template = manager.get(ri['id'])
        if template:
            ri['total'] = sum(item.get('line_total', 0) for item in template.get('items', []))
    
    due_invoices = manager.get_due_invoices()
    
    return render_template('recurring_invoices.html',
                          recurring_invoices=recurring_list,
                          frequencies=RECURRING_FREQUENCIES,
                          due_count=len(due_invoices))


@app.route('/invoices/recurring/new', methods=['GET', 'POST'])
@login_required
def new_recurring_invoice():
    """Create a new recurring invoice."""
    from recurring_invoices import RecurringInvoiceManager, RECURRING_FREQUENCIES
    from datetime import date
    
    customer_manager = CustomerManager(get_effective_user_id())
    product_manager = ProductManager(get_effective_user_id())
    
    if request.method == 'POST':
        manager = RecurringInvoiceManager(get_effective_user_id())
        
        recurring_id = manager.create(
            customer_id=int(request.form.get('customer_id')),
            frequency=request.form.get('frequency'),
            start_date=request.form.get('start_date'),
            end_date=request.form.get('end_date') or None,
            currency=request.form.get('currency', 'GBP'),
            tax_rate=float(request.form.get('tax_rate', 0)),
            notes=request.form.get('notes'),
            payment_terms=request.form.get('payment_terms'),
            auto_send=request.form.get('auto_send'),
            invoice_prefix=request.form.get('invoice_prefix', 'REC-')
        )
        
        # Update next invoice date if provided
        next_date = request.form.get('next_invoice_date')
        if next_date:
            manager.update(recurring_id, {'next_invoice_date': next_date})
        
        # Add items
        item_index = 0
        while f'items[{item_index}][description]' in request.form:
            description = request.form.get(f'items[{item_index}][description]')
            if description:
                manager.add_item(
                    recurring_id=recurring_id,
                    description=description,
                    quantity=float(request.form.get(f'items[{item_index}][quantity]', 1)),
                    unit_price=float(request.form.get(f'items[{item_index}][unit_price]', 0)),
                    product_id=int(request.form.get(f'items[{item_index}][product_id]')) if request.form.get(f'items[{item_index}][product_id]') else None,
                    tax_rate=float(request.form.get(f'items[{item_index}][tax_rate]', 0)),
                    is_recurring_item=request.form.get(f'items[{item_index}][is_recurring]') == '1'
                )
            item_index += 1
        
        flash('Recurring invoice created successfully.', 'success')
        return redirect(url_for('recurring_invoices'))
    
    settings_manager = SettingsManager(get_effective_user_id())
    settings = settings_manager.get_settings()
    
    return render_template('recurring_invoice_form.html',
                          recurring=None,
                          customers=customer_manager.get_all(),
                          products=product_manager.get_all(),
                          frequencies=RECURRING_FREQUENCIES,
                          settings=settings,
                          today=date.today())


@app.route('/invoices/recurring/<int:recurring_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_recurring_invoice(recurring_id):
    """Edit a recurring invoice."""
    from recurring_invoices import RecurringInvoiceManager, RECURRING_FREQUENCIES
    from datetime import date
    
    manager = RecurringInvoiceManager(get_effective_user_id())
    recurring = manager.get(recurring_id)
    
    if not recurring:
        flash('Recurring invoice not found.', 'error')
        return redirect(url_for('recurring_invoices'))
    
    customer_manager = CustomerManager(get_effective_user_id())
    product_manager = ProductManager(get_effective_user_id())
    
    if request.method == 'POST':
        manager.update(recurring_id, {
            'customer_id': int(request.form.get('customer_id')),
            'frequency': request.form.get('frequency'),
            'start_date': request.form.get('start_date'),
            'end_date': request.form.get('end_date') or None,
            'next_invoice_date': request.form.get('next_invoice_date'),
            'currency': request.form.get('currency', 'GBP'),
            'tax_rate': float(request.form.get('tax_rate', 0)),
            'notes': request.form.get('notes'),
            'payment_terms': request.form.get('payment_terms'),
            'auto_send': 1 if request.form.get('auto_send') else 0,
            'invoice_prefix': request.form.get('invoice_prefix', 'REC-')
        })
        
        # Clear and re-add items
        manager.clear_items(recurring_id)
        
        item_index = 0
        while f'items[{item_index}][description]' in request.form:
            description = request.form.get(f'items[{item_index}][description]')
            if description:
                manager.add_item(
                    recurring_id=recurring_id,
                    description=description,
                    quantity=float(request.form.get(f'items[{item_index}][quantity]', 1)),
                    unit_price=float(request.form.get(f'items[{item_index}][unit_price]', 0)),
                    product_id=int(request.form.get(f'items[{item_index}][product_id]')) if request.form.get(f'items[{item_index}][product_id]') else None,
                    tax_rate=float(request.form.get(f'items[{item_index}][tax_rate]', 0)),
                    is_recurring_item=request.form.get(f'items[{item_index}][is_recurring]') == '1'
                )
            item_index += 1
        
        flash('Recurring invoice updated successfully.', 'success')
        return redirect(url_for('recurring_invoices'))
    
    settings_manager = SettingsManager(get_effective_user_id())
    settings = settings_manager.get_settings()
    
    return render_template('recurring_invoice_form.html',
                          recurring=recurring,
                          customers=customer_manager.get_all(),
                          products=product_manager.get_all(),
                          frequencies=RECURRING_FREQUENCIES,
                          settings=settings,
                          today=date.today())


@app.route('/invoices/recurring/<int:recurring_id>/delete', methods=['POST'])
@login_required
def delete_recurring_invoice(recurring_id):
    """Delete a recurring invoice."""
    from recurring_invoices import RecurringInvoiceManager
    
    manager = RecurringInvoiceManager(get_effective_user_id())
    manager.delete(recurring_id)
    
    flash('Recurring invoice deleted.', 'success')
    return redirect(url_for('recurring_invoices'))


@app.route('/invoices/recurring/<int:recurring_id>/toggle', methods=['POST'])
@login_required
def toggle_recurring_invoice(recurring_id):
    """Toggle recurring invoice active status."""
    from recurring_invoices import RecurringInvoiceManager
    
    manager = RecurringInvoiceManager(get_effective_user_id())
    recurring = manager.get(recurring_id)
    
    if recurring:
        manager.update(recurring_id, {'active': 0 if recurring['active'] else 1})
        status = 'paused' if recurring['active'] else 'activated'
        flash(f'Recurring invoice {status}.', 'success')
    
    return redirect(url_for('recurring_invoices'))


@app.route('/invoices/recurring/<int:recurring_id>/generate', methods=['POST'])
@login_required
def generate_recurring_invoice(recurring_id):
    """Generate an invoice from a recurring template."""
    from recurring_invoices import RecurringInvoiceManager
    
    manager = RecurringInvoiceManager(get_effective_user_id())
    invoice_id = manager.generate_invoice(recurring_id)
    
    if invoice_id:
        flash('Invoice generated successfully.', 'success')
        return redirect(url_for('view_invoice', invoice_id=invoice_id))
    else:
        flash('Failed to generate invoice.', 'error')
        return redirect(url_for('recurring_invoices'))


@app.route('/invoices/recurring/generate-due', methods=['POST'])
@login_required
def generate_due_invoices():
    """Generate all due recurring invoices."""
    from recurring_invoices import RecurringInvoiceManager
    
    manager = RecurringInvoiceManager(get_effective_user_id())
    due_invoices = manager.get_due_invoices()
    
    generated = 0
    for ri in due_invoices:
        invoice_id = manager.generate_invoice(ri['id'])
        if invoice_id:
            generated += 1
    
    flash(f'{generated} invoice(s) generated successfully.', 'success')
    return redirect(url_for('recurring_invoices'))


@app.route('/invoices/recurring/settings')
@login_required
def recurring_settings():
    """Recurring invoice settings."""
    settings_manager = SettingsManager(get_effective_user_id())
    settings = settings_manager.get_settings()
    return render_template('recurring_settings.html', settings=settings)


# =============================================================================
# Chart of Accounts Routes
# =============================================================================

@app.route('/settings/chart-of-accounts')
@login_required
def chart_of_accounts():
    """View chart of accounts."""
    from recurring_invoices import ChartOfAccounts, COA_TYPES
    
    coa = ChartOfAccounts(get_effective_user_id())
    accounts = coa.get_all(active_only=False)
    settings = SettingsManager(get_effective_user_id()).get_settings()
    
    # Get product counts per account
    with get_db() as conn:
        cursor = conn.cursor()
        for account in accounts:
            cursor.execute('SELECT COUNT(*) AS cnt FROM products WHERE coa_id = ? AND user_id = ?', 
                          (account['id'], get_effective_user_id()))
            result = cursor.fetchone()
            account['product_count'] = result['cnt'] if isinstance(result, dict) else (result[0] if result else 0) or 0
    
    return render_template('chart_of_accounts.html', accounts=accounts, coa_types=COA_TYPES, settings=settings)


@app.route('/settings/chart-of-accounts/settings', methods=['POST'])
@login_required
def save_coa_settings():
    """Save COA settings."""
    settings_manager = SettingsManager(get_effective_user_id())
    settings_manager.update_settings({
        'coa_mandatory': 1 if request.form.get('coa_mandatory') else 0
    })
    flash('COA settings saved.', 'success')
    return redirect(url_for('chart_of_accounts'))


@app.route('/settings/chart-of-accounts/save', methods=['POST'])
@login_required
def save_coa():
    """Save a chart of accounts entry."""
    from recurring_invoices import ChartOfAccounts
    
    coa = ChartOfAccounts(get_effective_user_id())
    
    account_id = request.form.get('account_id')
    code = request.form.get('code')
    name = request.form.get('name')
    account_type = request.form.get('account_type')
    description = request.form.get('description')
    
    if account_id:
        coa.update(int(account_id), {
            'code': code,
            'name': name,
            'account_type': account_type,
            'description': description
        })
        flash('Account updated.', 'success')
    else:
        coa.create(code, name, account_type, description)
        flash('Account created.', 'success')
    
    return redirect(url_for('chart_of_accounts'))


@app.route('/settings/chart-of-accounts/<int:account_id>/delete', methods=['POST'])
@login_required
def delete_coa(account_id):
    """Delete (deactivate) a chart of accounts entry."""
    from recurring_invoices import ChartOfAccounts
    
    coa = ChartOfAccounts(get_effective_user_id())
    coa.delete(account_id)
    
    flash('Account deactivated.', 'success')
    return redirect(url_for('chart_of_accounts'))


@app.route('/settings/chart-of-accounts/initialize', methods=['POST'])
@login_required
def initialize_coa():
    """Initialize default chart of accounts."""
    from recurring_invoices import ChartOfAccounts
    
    coa = ChartOfAccounts(get_effective_user_id())
    count = coa.initialize_defaults()
    
    flash(f'{count} default accounts created.', 'success')
    return redirect(url_for('chart_of_accounts'))


# Initialize database
init_database()

# Initialize recurring invoice tables
from recurring_invoices import init_recurring_tables
init_recurring_tables()

# Register customer portal routes
from portal_routes import register_portal_routes
register_portal_routes(app)


# =============================================================================
# Customer Portal Admin Routes (for managing portal users)
# =============================================================================

@app.route('/settings/portal-users')
@login_required
def portal_users():
    """Manage customer portal users."""
    from customer_portal import CustomerPortalManager
    
    manager = CustomerPortalManager(get_effective_user_id())
    users = manager.get_portal_users()
    
    return render_template('portal_users.html', portal_users=users)


@app.route('/settings/portal-users/new', methods=['GET', 'POST'])
@login_required
def create_portal_user():
    """Create a new portal user."""
    from customer_portal import CustomerPortalManager
    
    manager = CustomerPortalManager(get_effective_user_id())
    customer_manager = CustomerManager(get_effective_user_id())
    
    if request.method == 'POST':
        customer_id = int(request.form.get('customer_id'))
        email = request.form.get('email')
        send_email = request.form.get('send_email') == '1'
        
        success, message, temp_password = manager.create_portal_user(customer_id, email, send_email)
        
        if success:
            flash(f'{message} Temporary password: {temp_password}', 'success')
            
            # Send email if requested
            if send_email:
                try:
                    from email_module import EmailManager
                    email_manager = EmailManager(get_effective_user_id())
                    customer = customer_manager.get(customer_id)
                    settings = SettingsManager(get_effective_user_id()).get_settings()
                    
                    portal_url = request.url_root + 'portal/login'
                    subject = f"Your Customer Portal Access - {settings.get('company_name', 'Invoice Manager')}"
                    body = f"""Hello {customer['name']},

You now have access to the customer portal where you can view your invoices and make payments online.

Portal URL: {portal_url}
Email: {email}
Temporary Password: {temp_password}

Please log in and change your password immediately.

Best regards,
{settings.get('company_name', 'Invoice Manager')}"""
                    
                    email_manager.send_email(email, subject, body)
                    flash('Welcome email sent.', 'success')
                except Exception as e:
                    flash(f'Portal created but email failed: {str(e)}', 'warning')
            
            return redirect(url_for('portal_users'))
        else:
            flash(message, 'error')
    
    customers = customer_manager.get_all()
    existing_users = manager.get_portal_users()
    existing_customer_ids = [u['customer_id'] for u in existing_users]
    
    return render_template('portal_user_form.html', 
                          customers=customers,
                          existing_customer_ids=existing_customer_ids)


@app.route('/settings/portal-users/<int:portal_user_id>/impersonate', methods=['POST'])
@login_required
def impersonate_portal_user(portal_user_id):
    """Generate impersonation link for a portal user."""
    from customer_portal import CustomerPortalManager
    
    manager = CustomerPortalManager(get_effective_user_id())
    token = manager.generate_impersonation_token(portal_user_id)
    
    if token:
        # Redirect to portal with token
        return redirect(url_for('portal.portal_login', token=token))
    else:
        flash('Could not generate impersonation link.', 'error')
        return redirect(url_for('portal_users'))


@app.route('/settings/portal-users/<int:portal_user_id>/reset-password', methods=['POST'])
@login_required
def reset_portal_password(portal_user_id):
    """Reset password for a portal user."""
    from customer_portal import CustomerPortalManager
    
    manager = CustomerPortalManager(get_effective_user_id())
    success, message, temp_password = manager.reset_password(portal_user_id)
    
    if success:
        flash(f'{message} New temporary password: {temp_password}', 'success')
    else:
        flash(message, 'error')
    
    return redirect(url_for('portal_users'))


@app.route('/settings/portal-users/<int:portal_user_id>/toggle', methods=['POST'])
@login_required
def toggle_portal_access(portal_user_id):
    """Toggle portal access for a user."""
    from customer_portal import CustomerPortalManager
    
    manager = CustomerPortalManager(get_effective_user_id())
    action = request.form.get('action')
    
    if action == 'revoke':
        manager.revoke_access(portal_user_id)
        flash('Portal access revoked.', 'success')
    elif action == 'restore':
        manager.restore_access(portal_user_id)
        flash('Portal access restored.', 'success')
    
    return redirect(url_for('portal_users'))


@app.route('/settings/portal-users/<int:portal_user_id>/delete', methods=['POST'])
@login_required
def delete_portal_user(portal_user_id):
    """Delete a portal user."""
    from customer_portal import CustomerPortalManager
    
    manager = CustomerPortalManager(get_effective_user_id())
    manager.delete_portal_user(portal_user_id)
    
    flash('Portal user deleted.', 'success')
    return redirect(url_for('portal_users'))


@app.route('/end-impersonation')
def end_impersonation():
    """End impersonation and return to admin."""
    session.pop('portal_user_id', None)
    session.pop('impersonating', None)
    return redirect(url_for('portal_users'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
