"""
Invoice Manager - Customer Portal Routes
Handles all customer portal web routes.
Copyright (c) 2026 Sondela Consulting Ltd.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file
from datetime import datetime
from functools import wraps

from database import get_db
from customer_portal import (
    CustomerPortalManager, CustomerPortalData,
    authenticate_portal_user, authenticate_with_token,
    get_portal_user_from_session, change_portal_password
)

# Create blueprint
portal_bp = Blueprint('portal', __name__, url_prefix='/portal')


def get_currency_symbol(currency_code):
    """Get currency symbol from code."""
    symbols = {
        'GBP': '£', 'USD': '$', 'EUR': '€', 'CAD': 'C$', 'AUD': 'A$',
        'JPY': '¥', 'CHF': 'CHF', 'INR': '₹', 'ZAR': 'R'
    }
    return symbols.get(currency_code, currency_code + ' ')


# =============================================================================
# Portal Authentication
# =============================================================================

@portal_bp.route('/login', methods=['GET', 'POST'])
def portal_login():
    """Customer portal login."""
    # Check for impersonation token
    token = request.args.get('token')
    if token:
        user = authenticate_with_token(token)
        if user:
            session['portal_user_id'] = user['id']
            session['impersonating'] = True
            flash('You are now viewing the portal as this customer.', 'info')
            return redirect(url_for('portal.portal_dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = authenticate_portal_user(email, password)
        if user:
            session['portal_user_id'] = user['id']
            session.pop('impersonating', None)
            
            if user.get('must_change_password'):
                flash('Please change your password.', 'warning')
                return redirect(url_for('portal.portal_account'))
            
            return redirect(url_for('portal.portal_dashboard'))
        else:
            flash('Invalid email or password.', 'error')
    
    return render_template('portal_login.html')


@portal_bp.route('/logout')
def portal_logout():
    """Customer portal logout."""
    session.pop('portal_user_id', None)
    session.pop('impersonating', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('portal.portal_login'))


# =============================================================================
# Portal Main Routes
# =============================================================================

@portal_bp.route('/')
@portal_bp.route('/dashboard')
def portal_dashboard():
    """Customer portal dashboard."""
    portal_user = get_portal_user_from_session()
    if not portal_user:
        return redirect(url_for('portal.portal_login'))
    
    portal_data = CustomerPortalData(portal_user)
    stats = portal_data.get_dashboard_stats()
    unpaid_invoices = portal_data.get_invoices('unpaid')
    business_info = portal_data.get_business_info()
    currency_symbol = get_currency_symbol(business_info.get('default_currency', 'GBP'))
    
    return render_template('portal_dashboard.html',
                          portal_user=portal_user,
                          stats=stats,
                          unpaid_invoices=unpaid_invoices,
                          business_info=business_info,
                          currency_symbol=currency_symbol,
                          now=datetime.now())


@portal_bp.route('/invoices')
def portal_invoices():
    """Customer portal invoices list."""
    portal_user = get_portal_user_from_session()
    if not portal_user:
        return redirect(url_for('portal.portal_login'))
    
    portal_data = CustomerPortalData(portal_user)
    filter_type = request.args.get('filter')
    
    all_invoices = portal_data.get_invoices(None)
    invoices = portal_data.get_invoices(filter_type)
    stats = portal_data.get_dashboard_stats()
    business_info = portal_data.get_business_info()
    currency_symbol = get_currency_symbol(business_info.get('default_currency', 'GBP'))
    
    # Calculate totals for display
    total_outstanding = sum(
        float(inv['total'] or 0) - float(inv['amount_paid'] or 0)
        for inv in invoices 
        if inv['status'] not in ['paid', 'cancelled']
    )
    
    # Count by status
    paid_count = sum(1 for inv in all_invoices if inv['status'] == 'paid')
    unpaid_count = sum(1 for inv in all_invoices if inv['status'] not in ['paid', 'cancelled', 'draft'])
    overdue_count = sum(1 for inv in all_invoices 
                       if inv['status'] not in ['paid', 'cancelled', 'draft'] 
                       and inv.get('due_date') and inv['due_date'] < datetime.now().date())
    
    return render_template('portal_invoices.html',
                          portal_user=portal_user,
                          invoices=invoices,
                          filter=filter_type,
                          total_count=len(all_invoices),
                          paid_count=paid_count,
                          unpaid_count=unpaid_count,
                          overdue_count=overdue_count,
                          total_outstanding=total_outstanding,
                          business_info=business_info,
                          currency_symbol=currency_symbol,
                          now=datetime.now())


@portal_bp.route('/invoices/<int:invoice_id>')
def portal_invoice_detail(invoice_id):
    """Customer portal invoice detail with payment options."""
    portal_user = get_portal_user_from_session()
    if not portal_user:
        return redirect(url_for('portal.portal_login'))
    
    portal_data = CustomerPortalData(portal_user)
    invoice = portal_data.get_invoice(invoice_id)
    
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('portal.portal_invoices'))
    
    business_info = portal_data.get_business_info()
    payment_options = portal_data.get_payment_options(invoice_id)
    currency_symbol = get_currency_symbol(invoice.get('currency') or business_info.get('default_currency', 'GBP'))
    
    return render_template('portal_invoice_detail.html',
                          portal_user=portal_user,
                          invoice=invoice,
                          payment_options=payment_options,
                          business_info=business_info,
                          currency_symbol=currency_symbol,
                          now=datetime.now())


@portal_bp.route('/invoices/<int:invoice_id>/download')
def portal_download_invoice(invoice_id):
    """Download invoice PDF from portal."""
    portal_user = get_portal_user_from_session()
    if not portal_user:
        return redirect(url_for('portal.portal_login'))
    
    portal_data = CustomerPortalData(portal_user)
    invoice = portal_data.get_invoice(invoice_id)
    
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('portal.portal_invoices'))
    
    # Generate PDF
    try:
        from pdf_generator import generate_invoice_pdf
        from app_core import SettingsManager
        
        settings = SettingsManager(portal_user['user_id']).get_settings()
        
        pdf_buffer = generate_invoice_pdf(invoice, settings)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"Invoice_{invoice['invoice_number']}.pdf"
        )
    except Exception as e:
        flash(f'Error generating PDF: {str(e)}', 'error')
        return redirect(url_for('portal.portal_invoice_detail', invoice_id=invoice_id))


@portal_bp.route('/invoices/<int:invoice_id>/pay', methods=['POST'])
def portal_create_payment(invoice_id):
    """Create a payment for an invoice from the portal."""
    portal_user = get_portal_user_from_session()
    if not portal_user:
        return redirect(url_for('portal.portal_login'))
    
    portal_data = CustomerPortalData(portal_user)
    invoice = portal_data.get_invoice(invoice_id)
    
    if not invoice:
        flash('Invoice not found.', 'error')
        return redirect(url_for('portal.portal_invoices'))
    
    method = request.form.get('method')
    
    if method == 'stripe':
        # Create Stripe payment link
        try:
            from stripe_integration import create_payment_link
            from flask import request as flask_request
            base_url = flask_request.url_root.rstrip('/')
            result = create_payment_link(portal_user['user_id'], invoice_id, base_url)
            if result and result.get('url'):
                return redirect(result['url'])
            else:
                flash('Error creating payment link', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    elif method == 'gocardless':
        # Create GoCardless payment
        try:
            from gocardless_integration import create_payment
            success, message = create_payment(portal_user['user_id'], invoice_id)
            if success:
                flash('Direct Debit payment initiated. You will receive confirmation shortly.', 'success')
            else:
                flash(f'Error: {message}', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    elif method == 'sumup':
        # Create SumUp checkout
        try:
            from sumup_integration import create_checkout
            success, url_or_error = create_checkout(portal_user['user_id'], invoice_id)
            if success:
                return redirect(url_or_error)
            else:
                flash(f'Error: {url_or_error}', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('portal.portal_invoice_detail', invoice_id=invoice_id))


@portal_bp.route('/account')
def portal_account():
    """Customer portal account settings."""
    portal_user = get_portal_user_from_session()
    if not portal_user:
        return redirect(url_for('portal.portal_login'))
    
    portal_data = CustomerPortalData(portal_user)
    stats = portal_data.get_dashboard_stats()
    business_info = portal_data.get_business_info()
    currency_symbol = get_currency_symbol(business_info.get('default_currency', 'GBP'))
    
    return render_template('portal_account.html',
                          portal_user=portal_user,
                          stats=stats,
                          business_info=business_info,
                          currency_symbol=currency_symbol)


@portal_bp.route('/account/change-password', methods=['POST'])
def portal_change_password():
    """Change password for portal user."""
    portal_user = get_portal_user_from_session()
    if not portal_user:
        return redirect(url_for('portal.portal_login'))
    
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if new_password != confirm_password:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('portal.portal_account'))
    
    if len(new_password) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return redirect(url_for('portal.portal_account'))
    
    success, message = change_portal_password(portal_user['id'], current_password, new_password)
    
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    
    return redirect(url_for('portal.portal_account'))


# =============================================================================
# Register Blueprint Function
# =============================================================================

def register_portal_routes(app):
    """Register portal blueprint with Flask app."""
    app.register_blueprint(portal_bp)
