# Frequently Asked Questions

Find answers to common questions about Invoice Manager.

## General

??? question "What is Invoice Manager?"
    Invoice Manager is a professional invoicing solution designed for small businesses, freelancers, and consultants. It helps you create invoices, manage customers, track payments, and more.

??? question "Is my data secure?"
    Yes! Your data is stored locally in an encrypted database. We recommend regular backups and using HTTPS in production.

??? question "Can I use Invoice Manager offline?"
    Yes, Invoice Manager runs locally on your machine and doesn't require an internet connection for basic operations. However, email sending and currency rate updates require internet access.

## Invoicing

??? question "Can I customize invoice numbers?"
    Yes! Go to Settings → Company and change the Invoice Prefix. Numbers are auto-incremented.

??? question "How do I add discounts?"
    Add a line item with a negative amount, or adjust the unit price of existing items.

??? question "Can I send invoices by email?"
    Yes! Configure your SMTP settings in Settings → Email, then use the "Send Email" button on any invoice.

??? question "What currencies are supported?"
    Invoice Manager supports 20+ currencies including GBP, USD, EUR, ZAR, CAD, AUD, and more. You can enable additional currencies in Settings → Integrations.

## Technical

??? question "What database does Invoice Manager use?"
    SQLite by default (no setup required). You can also use MySQL/MariaDB for larger deployments.

??? question "Is there an API?"
    Yes! Invoice Manager has a full REST API. Go to Settings → API Keys to generate keys. See the [API Documentation](api/overview.md).

??? question "I forgot my password"
    If you're the only user, you'll need to reset the database or contact support. For team members, an admin can reset your password from Settings → Team.

??? question "Emails aren't sending"
    Check your SMTP settings in Settings → Email. Common issues:
    
    - Incorrect server address or port
    - Wrong username/password
    - SSL/TLS setting mismatch
    - Firewall blocking outbound connections
    
    Use the "Test Connection" button to verify settings.

??? question "PDF generation fails"
    Ensure all required Python packages are installed:
    ```bash
    pip install reportlab
    ```

??? question "The application won't start"
    Check for common issues:
    
    1. Port already in use: Try `python run.py --port 8080`
    2. Missing dependencies: Run `pip install -r requirements.txt`
    3. Database locked: Close other instances

## Billing & Licensing

??? question "How much does Invoice Manager cost?"
    Contact [helpdesk@sondelaconsulting.com](mailto:helpdesk@sondelaconsulting.com) for pricing information.

??? question "Is there a free trial?"
    Contact us for trial options.

??? question "Can I get a refund?"
    Please review our terms of service or contact support.

## Still Have Questions?

Can't find what you're looking for?

- 📧 **Email**: [helpdesk@sondelaconsulting.com](mailto:helpdesk@sondelaconsulting.com)
- 🌐 **Website**: [sondelaconsulting.com](https://sondelaconsulting.com)
- 🗺️ **Feature Requests**: [Submit a feature request](https://roadmap.sondelaconsulting.com/request) password"
    If you're the only user, you'll need to reset the database or contact support. For team members, an admin can reset your password.

## Still Need Help?

- 📧 **Email**: [helpdesk@sondelaconsulting.com](mailto:helpdesk@sondelaconsulting.com)
- 🗺️ **Roadmap**: [View planned features](https://roadmap.sondelaconsulting.com)
