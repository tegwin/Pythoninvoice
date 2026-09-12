"""
Invoice Manager - Email Module
Handles sending invoices, payment confirmations, and reminders via Microsoft Graph.
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json

from app_core import get_db, get_currency_symbol

# Default email templates
DEFAULT_TEMPLATES = {
    'invoice_send': {
        'subject': 'Invoice {invoice_number} from {company_name}',
        'body': '''Dear {customer_name},

Please find attached invoice {invoice_number} for {currency_symbol}{total}.

Invoice Date: {issue_date}
Due Date: {due_date}
Amount Due: {currency_symbol}{amount_due}
{payment_link_section}
{payment_terms}

If you have any questions, please don't hesitate to contact us.

Best regards,
{company_name}
{company_email}'''
    },
    'payment_thank_you': {
        'subject': 'Payment Received - Invoice {invoice_number}',
        'body': '''Dear {customer_name},

Thank you for your payment of {currency_symbol}{payment_amount} for invoice {invoice_number}.

{payment_status_message}

We appreciate your business!

Best regards,
{company_name}
{company_email}'''
    },
    'reminder_1': {
        'subject': 'Payment Reminder - Invoice {invoice_number} Due Soon',
        'body': '''Dear {customer_name},

This is a friendly reminder that invoice {invoice_number} for {currency_symbol}{amount_due} is due on {due_date}.

Please ensure payment is made by the due date to avoid any late fees.

If you have already made payment, please disregard this message.

Best regards,
{company_name}
{company_email}'''
    },
    'reminder_2': {
        'subject': 'Second Reminder - Invoice {invoice_number} Now Due',
        'body': '''Dear {customer_name},

This is a second reminder regarding invoice {invoice_number} for {currency_symbol}{amount_due}, which was due on {due_date}.

Please arrange payment at your earliest convenience.

If payment has already been made, please let us know so we can update our records.

Best regards,
{company_name}
{company_email}'''
    },
    'reminder_3': {
        'subject': 'Final Reminder - Invoice {invoice_number} Overdue',
        'body': '''Dear {customer_name},

This is our final reminder regarding invoice {invoice_number} for {currency_symbol}{amount_due}, which was due on {due_date}.

Please arrange payment immediately to avoid further action.

If you are experiencing difficulties with payment, please contact us to discuss options.

Best regards,
{company_name}
{company_email}'''
    }
}


class EmailManager:
    """Manages email sending via Microsoft Graph and templates."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
    
    def get_template(self, template_type: str) -> Dict:
        """Get an email template, creating default if not exists."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM email_templates WHERE user_id = ? AND template_type = ?',
                (self.user_id, template_type)
            )
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            
            # Return default template
            default = DEFAULT_TEMPLATES.get(template_type, {
                'subject': 'Invoice Notification',
                'body': 'Please see the attached invoice.'
            })
            return {
                'template_type': template_type,
                'subject': default['subject'],
                'body': default['body'],
                'enabled': 1
            }
    
    def save_template(self, template_type: str, subject: str, body: str, enabled: bool = True) -> bool:
        """Save or update an email template."""
        with get_db() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO email_templates (user_id, template_type, subject, body, enabled)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, template_type) DO UPDATE SET
                        subject = excluded.subject,
                        body = excluded.body,
                        enabled = excluded.enabled,
                        updated_at = CURRENT_TIMESTAMP
                ''', (self.user_id, template_type, subject, body, 1 if enabled else 0))
                conn.commit()
                return True
            except Exception as e:
                return False
    
    def get_all_templates(self) -> List[Dict]:
        """Get all email templates for the user."""
        templates = []
        for template_type in DEFAULT_TEMPLATES.keys():
            templates.append(self.get_template(template_type))
        return templates
    
    def render_template(self, template_type: str, context: Dict) -> Tuple[str, str]:
        """Render a template with the given context."""
        template = self.get_template(template_type)
        
        subject = template['subject']
        body = template['body']
        
        # Replace placeholders
        for key, value in context.items():
            placeholder = '{' + key + '}'
            subject = subject.replace(placeholder, str(value) if value else '')
            body = body.replace(placeholder, str(value) if value else '')
        
        return subject, body
    
    def send_email(self, to_email: str, subject: str, body: str, 
                   attachment_path: str = None, attachment_name: str = None,
                   html_body: str = None) -> Tuple[bool, str]:
        """
        Send an email using Microsoft Graph API.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            body: Plain text email body
            attachment_path: Path to file to attach
            attachment_name: Display name for attachment
            html_body: Optional HTML body
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        return self._send_via_graph(to_email, subject, body, attachment_path, attachment_name, html_body)
    
    def _send_via_graph(self, to_email: str, subject: str, body: str,
                        attachment_path: str = None, attachment_name: str = None,
                        html_body: str = None) -> Tuple[bool, str]:
        """Send email via Microsoft Graph API."""
        try:
            from graph_email import GraphEmailManager
        except ImportError:
            return False, 'Microsoft Graph module not available'
        
        settings = self._get_settings()
        
        tenant_id = settings.get('graph_tenant_id')
        client_id = settings.get('graph_client_id')
        client_secret = settings.get('graph_client_secret')
        sender_email = settings.get('graph_sender_email')
        
        if not all([tenant_id, client_id, client_secret, sender_email]):
            return False, 'Microsoft Graph not configured. Go to Settings > Email Settings to configure.'
        
        try:
            graph = GraphEmailManager(tenant_id, client_id, client_secret, sender_email)
            
            # Prepare attachments
            attachments = None
            if attachment_path and os.path.exists(attachment_path):
                with open(attachment_path, 'rb') as f:
                    content = f.read()
                attachments = [{
                    'name': attachment_name or os.path.basename(attachment_path),
                    'content_type': 'application/pdf',
                    'content_bytes': content
                }]
            
            # Send email
            if html_body:
                result = graph.send_html_email(to_email, subject, html_body, attachments=attachments)
            else:
                result = graph.send_email(to_email, subject, body, attachments=attachments)
            
            if result['success']:
                return True, 'Email sent successfully via Microsoft Graph'
            else:
                return False, result.get('message', 'Unknown error')
                
        except Exception as e:
            return False, f'Graph API error: {str(e)}'
    
    def _get_settings(self) -> Dict:
        """Get all settings for this user."""
        from app_core import SettingsManager
        return SettingsManager(self.user_id).get_settings()
    
    def log_email(self, invoice_id: int, customer_id: int, email_type: str,
                  to_email: str, subject: str, status: str, error: str = None) -> int:
        """Log an email attempt."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO email_log (user_id, invoice_id, customer_id, email_type,
                                       to_email, subject, status, error_message, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self.user_id, invoice_id, customer_id, email_type,
                to_email, subject, status, error,
                datetime.now().isoformat() if status == 'sent' else None
            ))
            conn.commit()
            return cursor.lastrowid
    
    def get_email_log(self, invoice_id: int = None, limit: int = 50) -> List[Dict]:
        """Get email log entries."""
        with get_db() as conn:
            cursor = conn.cursor()
            
            if invoice_id:
                cursor.execute('''
                    SELECT el.*, c.name as customer_name, i.invoice_number
                    FROM email_log el
                    LEFT JOIN customers c ON el.customer_id = c.id
                    LEFT JOIN invoices i ON el.invoice_id = i.id
                    WHERE el.user_id = ? AND el.invoice_id = ?
                    ORDER BY el.created_at DESC
                    LIMIT ?
                ''', (self.user_id, invoice_id, limit))
            else:
                cursor.execute('''
                    SELECT el.*, c.name as customer_name, i.invoice_number
                    FROM email_log el
                    LEFT JOIN customers c ON el.customer_id = c.id
                    LEFT JOIN invoices i ON el.invoice_id = i.id
                    WHERE el.user_id = ?
                    ORDER BY el.created_at DESC
                    LIMIT ?
                ''', (self.user_id, limit))
            
            return [dict(row) for row in cursor.fetchall()]


class ReminderManager:
    """Manages invoice payment reminders."""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.email_manager = EmailManager(user_id)
    
    def get_reminder_settings(self) -> Dict:
        """Get reminder settings from company settings."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM company_settings WHERE user_id = ?',
                (self.user_id,)
            )
            row = cursor.fetchone()
            if row:
                settings = dict(row)
                return {
                    'enabled': settings.get('reminders_enabled', 0) == 1,
                    'reminder_1_days': int(settings.get('reminder_1_days', 7)),
                    'reminder_2_days': int(settings.get('reminder_2_days', 0)),
                    'reminder_3_days': int(settings.get('reminder_3_days', -7)),
                    'max_reminders': int(settings.get('max_reminders', 3))
                }
            return {
                'enabled': False,
                'reminder_1_days': 7,
                'reminder_2_days': 0,
                'reminder_3_days': -7,
                'max_reminders': 3
            }
    
    def schedule_reminders(self, invoice_id: int, due_date: str) -> List[int]:
        """Schedule reminders for an invoice."""
        settings = self.get_reminder_settings()
        if not settings['enabled']:
            return []
        
        # Handle both string (SQLite) and date object (MySQL)
        if isinstance(due_date, str):
            due = datetime.strptime(due_date, '%Y-%m-%d').date()
        else:
            due = due_date
        reminder_ids = []
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Clear existing pending reminders
            cursor.execute('''
                DELETE FROM invoice_reminders 
                WHERE invoice_id = ? AND status = 'pending'
            ''', (invoice_id,))
            
            # Schedule up to 3 reminders
            for i, days_key in enumerate(['reminder_1_days', 'reminder_2_days', 'reminder_3_days'], 1):
                if i > settings['max_reminders']:
                    break
                
                days = settings[days_key]
                if days != 0 or i == 1:  # Always schedule at least first reminder
                    scheduled_date = due - timedelta(days=days)
                    
                    cursor.execute('''
                        INSERT INTO invoice_reminders (invoice_id, reminder_number, days_before_due, scheduled_date)
                        VALUES (?, ?, ?, ?)
                    ''', (invoice_id, i, days, scheduled_date.isoformat()))
                    reminder_ids.append(cursor.lastrowid)
            
            conn.commit()
        
        return reminder_ids
    
    def get_pending_reminders(self) -> List[Dict]:
        """Get reminders that are due to be sent."""
        today = datetime.now().date().isoformat()
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT r.*, i.invoice_number, i.total, i.amount_paid, i.currency,
                       i.due_date, i.status as invoice_status, i.customer_id,
                       c.name as customer_name, c.email as customer_email
                FROM invoice_reminders r
                JOIN invoices i ON r.invoice_id = i.id
                LEFT JOIN customers c ON i.customer_id = c.id
                WHERE i.user_id = ? 
                  AND r.status = 'pending'
                  AND r.scheduled_date <= ?
                  AND i.status NOT IN ('paid', 'cancelled')
                ORDER BY r.scheduled_date
            ''', (self.user_id, today))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_invoice_reminders(self, invoice_id: int) -> List[Dict]:
        """Get reminders for a specific invoice."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM invoice_reminders
                WHERE invoice_id = ?
                ORDER BY reminder_number
            ''', (invoice_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def send_reminder(self, reminder_id: int) -> Tuple[bool, str]:
        """Send a specific reminder."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT r.*, i.invoice_number, i.total, i.amount_paid, i.currency,
                       i.due_date, i.customer_id, c.name as customer_name, 
                       c.email as customer_email
                FROM invoice_reminders r
                JOIN invoices i ON r.invoice_id = i.id
                LEFT JOIN customers c ON i.customer_id = c.id
                WHERE r.id = ?
            ''', (reminder_id,))
            
            row = cursor.fetchone()
            if not row:
                return False, 'Reminder not found'
            
            reminder = dict(row)
            
            if not reminder.get('customer_email'):
                return False, 'Customer has no email address'
            
            # Get company settings
            cursor.execute(
                'SELECT * FROM company_settings WHERE user_id = ?',
                (self.user_id,)
            )
            company = dict(cursor.fetchone() or {})
            
            # Prepare context
            symbol = get_currency_symbol(reminder.get('currency', 'GBP'))
            amount_due = (reminder.get('total', 0) or 0) - (reminder.get('amount_paid', 0) or 0)
            
            context = {
                'customer_name': reminder.get('customer_name', 'Customer'),
                'invoice_number': reminder.get('invoice_number', ''),
                'total': f"{reminder.get('total', 0):.2f}",
                'amount_due': f"{amount_due:.2f}",
                'currency_symbol': symbol,
                'due_date': reminder.get('due_date', ''),
                'company_name': company.get('company_name', 'Our Company'),
                'company_email': company.get('email', ''),
            }
            
            # Get template based on reminder number
            template_type = f"reminder_{reminder['reminder_number']}"
            subject, body = self.email_manager.render_template(template_type, context)
            
            # Send email
            success, message = self.email_manager.send_email(
                reminder['customer_email'], subject, body
            )
            
            # Update reminder status
            status = 'sent' if success else 'failed'
            cursor.execute('''
                UPDATE invoice_reminders
                SET status = ?, sent_at = ?
                WHERE id = ?
            ''', (status, datetime.now().isoformat() if success else None, reminder_id))
            
            # Log email
            self.email_manager.log_email(
                reminder.get('invoice_id'),
                reminder.get('customer_id'),
                template_type,
                reminder['customer_email'],
                subject,
                status,
                None if success else message
            )
            
            conn.commit()
            
            return success, message
    
    def cancel_reminders(self, invoice_id: int) -> int:
        """Cancel pending reminders for an invoice (e.g., when paid)."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE invoice_reminders
                SET status = 'cancelled'
                WHERE invoice_id = ? AND status = 'pending'
            ''', (invoice_id,))
            conn.commit()
            return cursor.rowcount


def send_invoice_email(user_id: int, invoice: Dict, settings: Dict, 
                       pdf_path: str = None, base_url: str = None) -> Tuple[bool, str]:
    """Send an invoice via email."""
    email_manager = EmailManager(user_id)
    
    if not invoice.get('customer_email'):
        return False, 'Customer has no email address'
    
    # Prepare context
    symbol = get_currency_symbol(invoice.get('currency', 'GBP'))
    amount_due = (invoice.get('total', 0) or 0) - (invoice.get('amount_paid', 0) or 0)
    
    # Build payment link section if Stripe is configured
    payment_link_section = ''
    if settings.get('stripe_publishable_key') and settings.get('stripe_secret_key') and amount_due > 0:
        if base_url:
            payment_url = f"{base_url}/pay/stripe/{invoice.get('id')}"
            payment_link_section = f'''
Pay Online: {payment_url}
'''
    
    context = {
        'customer_name': invoice.get('customer_name', 'Customer'),
        'invoice_number': invoice.get('invoice_number', ''),
        'total': f"{invoice.get('total', 0):.2f}",
        'amount_due': f"{amount_due:.2f}",
        'currency_symbol': symbol,
        'issue_date': invoice.get('issue_date', ''),
        'due_date': invoice.get('due_date', ''),
        'company_name': settings.get('company_name', 'Our Company'),
        'company_email': settings.get('email', ''),
        'payment_terms': settings.get('payment_terms', ''),
        'payment_link_section': payment_link_section,
    }
    
    subject, body = email_manager.render_template('invoice_send', context)
    
    # Send with PDF attachment if available
    attachment_name = f"{invoice.get('invoice_number', 'invoice')}.pdf" if pdf_path else None
    
    success, message = email_manager.send_email(
        invoice['customer_email'],
        subject,
        body,
        pdf_path,
        attachment_name
    )
    
    # Log the email
    email_manager.log_email(
        invoice.get('id'),
        invoice.get('customer_id'),
        'invoice_send',
        invoice['customer_email'],
        subject,
        'sent' if success else 'failed',
        None if success else message
    )
    
    return success, message


def send_payment_thank_you(user_id: int, invoice: Dict, settings: Dict,
                           payment_amount: float) -> Tuple[bool, str]:
    """Send a payment thank you email."""
    email_manager = EmailManager(user_id)
    
    if not invoice.get('customer_email'):
        return False, 'Customer has no email address'
    
    # Prepare context
    symbol = get_currency_symbol(invoice.get('currency', 'GBP'))
    amount_due = (invoice.get('total', 0) or 0) - (invoice.get('amount_paid', 0) or 0)
    
    if amount_due <= 0:
        payment_status_message = 'Your invoice has been paid in full.'
    else:
        payment_status_message = f'Remaining balance: {symbol}{amount_due:.2f}'
    
    context = {
        'customer_name': invoice.get('customer_name', 'Customer'),
        'invoice_number': invoice.get('invoice_number', ''),
        'payment_amount': f"{payment_amount:.2f}",
        'currency_symbol': symbol,
        'payment_status_message': payment_status_message,
        'company_name': settings.get('company_name', 'Our Company'),
        'company_email': settings.get('email', ''),
    }
    
    subject, body = email_manager.render_template('payment_thank_you', context)
    
    success, message = email_manager.send_email(
        invoice['customer_email'],
        subject,
        body
    )
    
    # Log the email
    email_manager.log_email(
        invoice.get('id'),
        invoice.get('customer_id'),
        'payment_thank_you',
        invoice['customer_email'],
        subject,
        'sent' if success else 'failed',
        None if success else message
    )
    
    # Cancel pending reminders if fully paid
    if amount_due <= 0:
        ReminderManager(user_id).cancel_reminders(invoice['id'])
    
    return success, message
