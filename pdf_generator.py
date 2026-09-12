"""
Invoice Manager - PDF Generation Module
Generates professional PDF invoices using reportlab.
"""

import os
from datetime import datetime
from io import BytesIO

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm, inch
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

from app_core import get_currency_symbol


def check_dependencies():
    """Check if PDF generation dependencies are available."""
    return {
        'reportlab': REPORTLAB_AVAILABLE,
        'ready': REPORTLAB_AVAILABLE
    }


def generate_invoice_pdf(invoice: dict, company_settings: dict) -> BytesIO:
    """Generate a PDF invoice."""
    if not REPORTLAB_AVAILABLE:
        raise ImportError("reportlab is required for PDF generation. Install with: pip install reportlab")
    
    buffer = BytesIO()
    
    # Page setup
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )
    
    # Colors matching the app theme
    primary_color = HexColor('#e94560')  # Red accent
    secondary_color = HexColor('#1a1a35')  # Dark background
    accent_color = HexColor('#f0a500')  # Yellow accent
    text_color = HexColor('#333333')
    muted_color = HexColor('#666666')
    
    # Styles
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'InvoiceTitle',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=primary_color,
        spaceAfter=10,
        fontName='Helvetica-Bold'
    )
    
    heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=secondary_color,
        spaceBefore=15,
        spaceAfter=8,
        fontName='Helvetica-Bold'
    )
    
    normal_style = ParagraphStyle(
        'NormalText',
        parent=styles['Normal'],
        fontSize=10,
        textColor=text_color,
        fontName='Helvetica'
    )
    
    muted_style = ParagraphStyle(
        'MutedText',
        parent=styles['Normal'],
        fontSize=9,
        textColor=muted_color,
        fontName='Helvetica'
    )
    
    # Build document elements
    elements = []
    
    # Get currency symbol
    currency = invoice.get('currency', 'GBP')
    symbol = get_currency_symbol(currency)
    
    # Header section with company logo and invoice title
    header_data = []
    
    # Company info (left side) - may include logo
    company_info = []
    
    # Add logo if available
    logo_path = company_settings.get('logo_path')
    if logo_path and os.path.exists(logo_path):
        try:
            from reportlab.platypus import Image
            # Scale logo to reasonable size (max 50mm width, 25mm height)
            logo = Image(logo_path)
            logo_width = logo.drawWidth
            logo_height = logo.drawHeight
            max_width = 50 * mm
            max_height = 25 * mm
            
            # Scale proportionally
            scale = min(max_width / logo_width, max_height / logo_height, 1.0)
            logo.drawWidth = logo_width * scale
            logo.drawHeight = logo_height * scale
            company_info.append(logo)
            company_info.append(Spacer(1, 5))
        except Exception as e:
            pass  # Skip logo if there's an error
    
    if company_settings.get('company_name'):
        company_info.append(Paragraph(f"<b>{company_settings['company_name']}</b>", normal_style))
    if company_settings.get('address_line1'):
        company_info.append(Paragraph(company_settings['address_line1'], muted_style))
    if company_settings.get('address_line2'):
        company_info.append(Paragraph(company_settings['address_line2'], muted_style))
    
    city_line = []
    if company_settings.get('city'):
        city_line.append(company_settings['city'])
    if company_settings.get('state'):
        city_line.append(company_settings['state'])
    if company_settings.get('postal_code'):
        city_line.append(company_settings['postal_code'])
    if city_line:
        company_info.append(Paragraph(', '.join(city_line), muted_style))
    
    if company_settings.get('country'):
        company_info.append(Paragraph(company_settings['country'], muted_style))
    if company_settings.get('email'):
        company_info.append(Paragraph(company_settings['email'], muted_style))
    if company_settings.get('phone'):
        company_info.append(Paragraph(company_settings['phone'], muted_style))
    
    # Invoice details (right side)
    invoice_info = []
    invoice_info.append(Paragraph("INVOICE", title_style))
    invoice_info.append(Paragraph(f"<b>{invoice.get('invoice_number', '')}</b>", normal_style))
    invoice_info.append(Spacer(1, 10))
    invoice_info.append(Paragraph(f"<b>Date:</b> {invoice.get('issue_date', '')}", muted_style))
    invoice_info.append(Paragraph(f"<b>Due:</b> {invoice.get('due_date', '')}", muted_style))
    
    status = invoice.get('status', 'draft').upper()
    status_color = '#10b981' if status == 'PAID' else '#e94560' if status == 'OVERDUE' else '#3b82f6'
    invoice_info.append(Paragraph(f"<b>Status:</b> <font color='{status_color}'>{status}</font>", muted_style))
    
    # Header table
    header_table = Table([
        [company_info, invoice_info]
    ], colWidths=[90*mm, 80*mm])
    
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    
    elements.append(header_table)
    elements.append(Spacer(1, 20))
    
    # Bill To section
    elements.append(Paragraph("BILL TO", heading_style))
    
    if invoice.get('customer_name'):
        elements.append(Paragraph(f"<b>{invoice['customer_name']}</b>", normal_style))
    if invoice.get('customer_email'):
        elements.append(Paragraph(invoice['customer_email'], muted_style))
    if invoice.get('customer_address1'):
        elements.append(Paragraph(invoice['customer_address1'], muted_style))
    if invoice.get('customer_address2'):
        elements.append(Paragraph(invoice['customer_address2'], muted_style))
    
    customer_city = []
    if invoice.get('customer_city'):
        customer_city.append(invoice['customer_city'])
    if invoice.get('customer_state'):
        customer_city.append(invoice['customer_state'])
    if invoice.get('customer_postal'):
        customer_city.append(invoice['customer_postal'])
    if customer_city:
        elements.append(Paragraph(', '.join(customer_city), muted_style))
    if invoice.get('customer_country'):
        elements.append(Paragraph(invoice['customer_country'], muted_style))
    
    elements.append(Spacer(1, 20))
    
    # Currency and Tax info
    tax_rate = invoice.get('tax_rate', 0)
    elements.append(Paragraph(f"<b>Currency:</b> {currency} ({symbol})  |  <b>Tax Rate:</b> {tax_rate}%", muted_style))
    elements.append(Spacer(1, 15))
    
    # Line Items table
    items = invoice.get('items', [])
    
    # Table header
    table_data = [
        [
            Paragraph('<b>Description</b>', normal_style),
            Paragraph('<b>Qty</b>', normal_style),
            Paragraph('<b>Unit Price</b>', normal_style),
            Paragraph('<b>Tax</b>', normal_style),
            Paragraph('<b>Amount</b>', normal_style),
        ]
    ]
    
    # Table rows
    for item in items:
        qty = item.get('quantity', 1)
        price = item.get('unit_price', 0)
        item_tax = item.get('tax_rate', 0)
        total = item.get('line_total', qty * price)
        
        table_data.append([
            Paragraph(item.get('description', ''), normal_style),
            Paragraph(f"{qty:.2f}" if isinstance(qty, float) and qty % 1 != 0 else str(int(qty)), normal_style),
            Paragraph(f"{symbol}{price:,.2f}", normal_style),
            Paragraph(f"{item_tax}%", normal_style),
            Paragraph(f"{symbol}{total:,.2f}", normal_style),
        ])
    
    # Create items table
    items_table = Table(
        table_data,
        colWidths=[80*mm, 20*mm, 30*mm, 20*mm, 30*mm],
        repeatRows=1
    )
    
    items_table.setStyle(TableStyle([
        # Header styling
        ('BACKGROUND', (0, 0), (-1, 0), secondary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TOPPADDING', (0, 0), (-1, 0), 12),
        
        # Row styling
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        
        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#f8f9fa')]),
        
        # Alignment
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Borders
        ('LINEBELOW', (0, 0), (-1, 0), 1, secondary_color),
        ('LINEBELOW', (0, -1), (-1, -1), 1, HexColor('#e0e0e0')),
    ]))
    
    elements.append(items_table)
    elements.append(Spacer(1, 20))
    
    # Totals section
    subtotal = invoice.get('subtotal', 0)
    tax_amount = invoice.get('tax_amount', 0)
    total = invoice.get('total', 0)
    amount_paid = invoice.get('amount_paid', 0)
    amount_due = total - amount_paid
    
    totals_data = [
        ['Subtotal:', f"{symbol}{subtotal:,.2f}"],
        [f'Tax ({tax_rate}%):', f"{symbol}{tax_amount:,.2f}"],
        ['Total:', f"{symbol}{total:,.2f}"],
    ]
    
    if amount_paid > 0:
        totals_data.append(['Amount Paid:', f"-{symbol}{amount_paid:,.2f}"])
        totals_data.append(['Amount Due:', f"{symbol}{amount_due:,.2f}"])
    
    totals_table = Table(
        totals_data,
        colWidths=[120*mm, 50*mm],
        hAlign='RIGHT'
    )
    
    totals_style = [
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('LINEABOVE', (0, 2), (-1, 2), 1, HexColor('#e0e0e0')),
    ]
    
    # Highlight total/amount due
    total_row = 2 if amount_paid == 0 else 4
    totals_style.extend([
        ('FONTNAME', (0, total_row), (-1, total_row), 'Helvetica-Bold'),
        ('FONTSIZE', (0, total_row), (-1, total_row), 12),
        ('BACKGROUND', (0, total_row), (-1, total_row), HexColor('#f0f0f0')),
    ])
    
    totals_table.setStyle(TableStyle(totals_style))
    
    elements.append(totals_table)
    elements.append(Spacer(1, 30))
    
    # Notes section
    if invoice.get('notes'):
        elements.append(Paragraph("NOTES", heading_style))
        elements.append(Paragraph(invoice['notes'], muted_style))
        elements.append(Spacer(1, 15))
    
    # Payment Terms / Bank Details
    if invoice.get('payment_terms') or company_settings.get('bank_details'):
        elements.append(Paragraph("PAYMENT INFORMATION", heading_style))
        
        if invoice.get('payment_terms'):
            elements.append(Paragraph(f"<b>Terms:</b> {invoice['payment_terms']}", muted_style))
        
        if company_settings.get('bank_details'):
            elements.append(Spacer(1, 5))
            for line in company_settings['bank_details'].split('\n'):
                elements.append(Paragraph(line, muted_style))
    
    elements.append(Spacer(1, 30))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=muted_color,
        alignment=TA_CENTER,
        fontName='Helvetica'
    )
    
    elements.append(Paragraph("Thank you for your business!", footer_style))
    elements.append(Paragraph("Generated by Invoice Manager", footer_style))
    
    # Build PDF with watermark for status
    status = invoice.get('status', 'draft').lower()
    
    def add_watermark(canvas_obj, doc):
        """Add status watermark to the PDF as a diagonal watermark."""
        if status in ('paid', 'cancelled', 'overdue'):
            canvas_obj.saveState()
            
            # Set watermark properties based on status
            if status == 'paid':
                stamp_text = "PAID"
                stamp_color = HexColor('#10b981')
            elif status == 'cancelled':
                stamp_text = "CANCELLED"
                stamp_color = HexColor('#666666')
            else:  # overdue
                stamp_text = "OVERDUE"
                stamp_color = HexColor('#e94560')
            
            # Get page dimensions
            page_width, page_height = A4
            
            # Draw large diagonal watermark across the page
            canvas_obj.setFillColor(stamp_color)
            canvas_obj.setFillAlpha(0.15)  # More visible watermark
            
            # Center of page
            canvas_obj.translate(page_width / 2, page_height / 2)
            canvas_obj.rotate(45)  # Diagonal
            
            # Large text
            canvas_obj.setFont('Helvetica-Bold', 80)
            canvas_obj.drawCentredString(0, 0, stamp_text)
            
            canvas_obj.restoreState()
    
    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    
    buffer.seek(0)
    return buffer


def generate_invoice_html(invoice: dict, company_settings: dict) -> str:
    """Generate HTML version of invoice for printing."""
    
    currency = invoice.get('currency', 'GBP')
    symbol = get_currency_symbol(currency)
    tax_rate = invoice.get('tax_rate', 0)
    
    # Build items HTML
    items_html = ""
    for item in invoice.get('items', []):
        qty = item.get('quantity', 1)
        price = item.get('unit_price', 0)
        item_tax = item.get('tax_rate', 0)
        total = item.get('line_total', qty * price)
        
        # Format quantity - show decimals only if needed
        qty_str = f"{qty:.2f}" if isinstance(qty, float) and qty % 1 != 0 else str(int(qty))
        
        items_html += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #eee;">{item.get('description', '')}</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right;">{qty_str}</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right;">{symbol}{price:,.2f}</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right;">{item_tax}%</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right;">{symbol}{total:,.2f}</td>
        </tr>
        """
    
    # Totals
    subtotal = invoice.get('subtotal', 0)
    tax_amount = invoice.get('tax_amount', 0)
    total = invoice.get('total', 0)
    amount_paid = invoice.get('amount_paid', 0)
    amount_due = total - amount_paid
    
    totals_html = f"""
    <tr>
        <td style="padding: 8px;">Subtotal:</td>
        <td style="padding: 8px; text-align: right;">{symbol}{subtotal:,.2f}</td>
    </tr>
    <tr>
        <td style="padding: 8px;">Tax ({tax_rate}%):</td>
        <td style="padding: 8px; text-align: right;">{symbol}{tax_amount:,.2f}</td>
    </tr>
    <tr style="font-weight: bold; font-size: 16px; background: #f0f0f0;">
        <td style="padding: 10px;">Total:</td>
        <td style="padding: 10px; text-align: right;">{symbol}{total:,.2f}</td>
    </tr>
    """
    
    if amount_paid > 0:
        totals_html += f"""
        <tr>
            <td style="padding: 8px;">Amount Paid:</td>
            <td style="padding: 8px; text-align: right;">-{symbol}{amount_paid:,.2f}</td>
        </tr>
        <tr style="font-weight: bold; font-size: 16px; background: #fff3cd;">
            <td style="padding: 10px;">Amount Due:</td>
            <td style="padding: 10px; text-align: right;">{symbol}{amount_due:,.2f}</td>
        </tr>
        """
    
    # Build company address
    company_address = []
    if company_settings.get('address_line1'):
        company_address.append(company_settings['address_line1'])
    if company_settings.get('address_line2'):
        company_address.append(company_settings['address_line2'])
    city_parts = []
    if company_settings.get('city'):
        city_parts.append(company_settings['city'])
    if company_settings.get('state'):
        city_parts.append(company_settings['state'])
    if company_settings.get('postal_code'):
        city_parts.append(company_settings['postal_code'])
    if city_parts:
        company_address.append(', '.join(city_parts))
    if company_settings.get('country'):
        company_address.append(company_settings['country'])
    
    company_address_html = '<br>'.join(company_address)
    
    # Build logo HTML
    logo_html = ""
    logo_path = company_settings.get('logo_path')
    if logo_path and os.path.exists(logo_path):
        try:
            import base64
            with open(logo_path, 'rb') as f:
                logo_data = base64.b64encode(f.read()).decode('utf-8')
            # Detect mime type from extension
            ext = logo_path.lower().split('.')[-1]
            mime_types = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp'}
            mime_type = mime_types.get(ext, 'image/png')
            logo_html = f'<img src="data:{mime_type};base64,{logo_data}" style="max-width: 150px; max-height: 60px; margin-bottom: 10px;" alt="Company Logo"><br>'
        except Exception:
            pass  # Skip logo if there's an error
    
    # Build customer address
    customer_address = []
    if invoice.get('customer_address1'):
        customer_address.append(invoice['customer_address1'])
    if invoice.get('customer_address2'):
        customer_address.append(invoice['customer_address2'])
    cust_city = []
    if invoice.get('customer_city'):
        cust_city.append(invoice['customer_city'])
    if invoice.get('customer_state'):
        cust_city.append(invoice['customer_state'])
    if invoice.get('customer_postal'):
        cust_city.append(invoice['customer_postal'])
    if cust_city:
        customer_address.append(', '.join(cust_city))
    if invoice.get('customer_country'):
        customer_address.append(invoice['customer_country'])
    
    customer_address_html = '<br>'.join(customer_address)
    
    # Status color
    status = invoice.get('status', 'draft')
    status_colors = {
        'draft': '#6b7280',
        'sent': '#3b82f6',
        'paid': '#10b981',
        'partial': '#f59e0b',
        'overdue': '#ef4444',
        'cancelled': '#6b7280'
    }
    status_color = status_colors.get(status, '#6b7280')
    
    # Watermark settings based on status
    watermark_html = ""
    if status in ('paid', 'cancelled', 'overdue'):
        watermark_colors = {
            'paid': '#10b981',
            'cancelled': '#666666',
            'overdue': '#ef4444'
        }
        watermark_text = status.upper()
        watermark_color = watermark_colors.get(status, '#666666')
        watermark_html = f"""
            .watermark {{
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%) rotate(-45deg);
                font-size: 140px;
                font-weight: bold;
                color: {watermark_color};
                opacity: 0.15;
                pointer-events: none;
                z-index: 1000;
                white-space: nowrap;
                letter-spacing: 8px;
            }}
            @media print {{
                .watermark {{
                    position: fixed;
                    -webkit-print-color-adjust: exact;
                    print-color-adjust: exact;
                }}
            }}
        """
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Invoice {invoice.get('invoice_number', '')}</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                max-width: 800px; 
                margin: 0 auto; 
                padding: 40px;
                color: #333;
                line-height: 1.6;
                position: relative;
            }}
            {watermark_html}
            .header {{ 
                display: flex; 
                justify-content: space-between; 
                margin-bottom: 40px; 
                padding-bottom: 20px;
                border-bottom: 3px solid #e94560;
            }}
            .company-info {{ max-width: 300px; }}
            .company-name {{ 
                font-size: 24px; 
                font-weight: bold; 
                color: #1a1a35;
                margin-bottom: 10px;
            }}
            .company-details {{ font-size: 12px; color: #666; }}
            .invoice-info {{ text-align: right; }}
            .invoice-title {{ 
                font-size: 32px; 
                font-weight: bold;
                color: #e94560;
                margin-bottom: 5px;
            }}
            .invoice-number {{ 
                font-size: 16px; 
                font-weight: bold;
                color: #1a1a35;
                margin-bottom: 15px;
            }}
            .invoice-meta {{ font-size: 12px; color: #666; }}
            .invoice-meta strong {{ color: #333; }}
            .status {{ 
                display: inline-block; 
                padding: 4px 12px; 
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
                color: white;
                background: {status_color};
            }}
            .parties {{ 
                display: flex; 
                gap: 40px;
                margin-bottom: 30px; 
            }}
            .party {{ flex: 1; }}
            .party-label {{ 
                font-size: 11px; 
                font-weight: bold;
                text-transform: uppercase;
                color: #e94560;
                margin-bottom: 8px;
                padding-bottom: 4px;
                border-bottom: 2px solid #e94560;
            }}
            .party-name {{ 
                font-weight: bold; 
                font-size: 14px;
                margin-bottom: 4px;
            }}
            .party-details {{ font-size: 12px; color: #666; }}
            .currency-info {{
                background: #f8f9fa;
                padding: 10px 15px;
                border-radius: 4px;
                margin-bottom: 20px;
                font-size: 12px;
            }}
            table {{ 
                width: 100%; 
                border-collapse: collapse; 
                margin-bottom: 30px; 
            }}
            th {{ 
                background: #1a1a35; 
                color: white; 
                padding: 12px; 
                text-align: left;
                font-size: 12px;
                text-transform: uppercase;
            }}
            th:not(:first-child) {{ text-align: right; }}
            td {{ font-size: 13px; }}
            .totals {{ 
                width: 300px; 
                margin-left: auto;
            }}
            .totals table {{ margin-bottom: 0; }}
            .totals td {{ 
                padding: 8px; 
                font-size: 13px;
            }}
            .notes {{ 
                background: #f8f9fa; 
                padding: 20px; 
                border-radius: 8px; 
                margin-top: 30px;
            }}
            .notes-title {{
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
                color: #e94560;
                margin-bottom: 8px;
            }}
            .notes-content {{ font-size: 12px; color: #666; }}
            .footer {{ 
                margin-top: 40px; 
                text-align: center; 
                color: #999; 
                font-size: 11px;
                padding-top: 20px;
                border-top: 1px solid #eee;
            }}
            @media print {{
                body {{ padding: 20px; }}
                .no-print {{ display: none; }}
            }}
        </style>
    </head>
    <body>
        {'<div class="watermark">' + status.upper() + '</div>' if status in ('paid', 'cancelled', 'overdue') else ''}
        <div class="header">
            <div class="company-info">
                {logo_html}
                <div class="company-name">{company_settings.get('company_name', 'Your Company')}</div>
                <div class="company-details">
                    {company_address_html}
                    {f'<br>{company_settings["email"]}' if company_settings.get('email') else ''}
                    {f'<br>{company_settings["phone"]}' if company_settings.get('phone') else ''}
                </div>
            </div>
            <div class="invoice-info">
                <div class="invoice-title">INVOICE</div>
                <div class="invoice-number">{invoice.get('invoice_number', '')}</div>
                <div class="invoice-meta">
                    <strong>Date:</strong> {invoice.get('issue_date', '')}<br>
                    <strong>Due:</strong> {invoice.get('due_date', '')}<br>
                    <span class="status">{status.upper()}</span>
                </div>
            </div>
        </div>
        
        <div class="parties">
            <div class="party">
                <div class="party-label">Bill To</div>
                <div class="party-name">{invoice.get('customer_name', '')}</div>
                <div class="party-details">
                    {f'{invoice["customer_email"]}<br>' if invoice.get('customer_email') else ''}
                    {customer_address_html}
                </div>
            </div>
        </div>
        
        <div class="currency-info">
            <strong>Currency:</strong> {currency} ({symbol}) &nbsp;|&nbsp; 
            <strong>Tax Rate:</strong> {tax_rate}%
        </div>
        
        <table>
            <thead>
                <tr>
                    <th>Description</th>
                    <th>Qty</th>
                    <th>Unit Price</th>
                    <th>Tax</th>
                    <th>Amount</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
            </tbody>
        </table>
        
        <div class="totals">
            <table>
                {totals_html}
            </table>
        </div>
        
        {f'''
        <div class="notes">
            <div class="notes-title">Notes</div>
            <div class="notes-content">{invoice.get("notes", "")}</div>
        </div>
        ''' if invoice.get('notes') else ''}
        
        {f'''
        <div class="notes">
            <div class="notes-title">Payment Information</div>
            <div class="notes-content">
                {f'<strong>Terms:</strong> {invoice.get("payment_terms")}<br><br>' if invoice.get('payment_terms') else ''}
                {company_settings.get("bank_details", "").replace(chr(10), "<br>")}
            </div>
        </div>
        ''' if invoice.get('payment_terms') or company_settings.get('bank_details') else ''}
        
        <div class="footer">
            <p>Thank you for your business!</p>
            <p>Generated by Invoice Manager</p>
        </div>
    </body>
    </html>
    """
    
    return html
