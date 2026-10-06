import os
import io
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# -------------------------------------------------------------------------
# FONT REGISTRATION (TrueType NotoSans for native Indian Rupee ₹ U+20B9)
# -------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(BASE_DIR, 'static', 'fonts')
NOTO_REGULAR = os.path.join(FONTS_DIR, 'NotoSans-Regular.ttf')
NOTO_BOLD = os.path.join(FONTS_DIR, 'NotoSans-Bold.ttf')

if os.path.exists(NOTO_REGULAR) and os.path.exists(NOTO_BOLD):
    try:
        pdfmetrics.registerFont(TTFont('NotoSans', NOTO_REGULAR))
        pdfmetrics.registerFont(TTFont('NotoSans-Bold', NOTO_BOLD))
        FONT_NORMAL = 'NotoSans'
        FONT_BOLD = 'NotoSans-Bold'
    except Exception:
        FONT_NORMAL = 'Helvetica'
        FONT_BOLD = 'Helvetica-Bold'
else:
    FONT_NORMAL = 'Helvetica'
    FONT_BOLD = 'Helvetica-Bold'


# -------------------------------------------------------------------------
# NUMBER TO INDIAN WORDS CONVERTER
# -------------------------------------------------------------------------
def number_to_indian_words(n):
    """
    Converts a float/int amount to Indian currency words format.
    Example: 84493.50 -> Indian Rupee Eighty-Four Thousand Four Hundred Ninety-Three and Fifty Paise Only
    """
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
    
    def two_digits(num):
        if num < 20:
            return ones[num]
        else:
            t = tens[num // 10]
            o = ones[num % 10]
            return f"{t}-{o}" if o else t

    def three_digits(num):
        h = num // 100
        rem = num % 100
        res = []
        if h > 0:
            res.append(f"{ones[h]} Hundred")
        if rem > 0:
            res.append(two_digits(rem))
        return ' '.join(res)

    int_part = int(round(n, 2))
    paise_part = int(round((round(n, 2) - int_part) * 100))

    if int_part == 0:
        words = 'Zero'
    else:
        parts = []
        crore = int_part // 10000000
        int_part %= 10000000
        lakh = int_part // 100000
        int_part %= 100000
        thousand = int_part // 1000
        int_part %= 1000
        hundreds = int_part

        if crore > 0:
            parts.append(f"{two_digits(crore)} Crore")
        if lakh > 0:
            parts.append(f"{two_digits(lakh)} Lakh")
        if thousand > 0:
            parts.append(f"{two_digits(thousand)} Thousand")
        if hundreds > 0:
            parts.append(three_digits(hundreds))
        words = ' '.join(parts)

    paise_str = ''
    if paise_part > 0:
        paise_str = f" and {two_digits(paise_part)} Paise"
    return f"Indian Rupee {words}{paise_str} Only"


# -------------------------------------------------------------------------
# NUMBERED CANVAS FOR DYNAMIC MULTI-PAGE NUMBERING
# -------------------------------------------------------------------------
class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and print total page numbers."""
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont(FONT_NORMAL, 7.5)
        self.setFillColor(colors.HexColor("#718096"))
        
        # Professional Footer
        footer_text = "Pikachooz  •  Sweet Scribbles B2B Gifting  •  www.sweetscribbles.pikachooz.com  •  sathishkumar.dm@pikachooz.com  •  +91 90666 11856"
        self.drawString(36, 18, footer_text)
        
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(A4[0] - 36, 18, page_str)
        
        # Footer rule
        self.setStrokeColor(colors.HexColor("#CBD5E0"))
        self.setLineWidth(0.5)
        self.line(36, 28, A4[0] - 36, 28)
        
        self.restoreState()


# -------------------------------------------------------------------------
# MAIN PDF GENERATOR
# -------------------------------------------------------------------------
def generate_quotation_pdf(order, logo_filename=None, doc_type='quotation'):
    """
    Generates a formal, luxury branded PDF for a B2B order supporting:
    - doc_type='quotation'   : Corporate Estimate & Quotation (default)
    - doc_type='proforma'    : Proforma Invoice for advance payment release
    - doc_type='tax_invoice' : Official statutory GST Tax Invoice upon dispatch
    
    Dynamically applies configurable GST %, PO tracking, bank remittance details,
    authorized signatory, and advance adjustment ledger.
    """
    doc_type = (doc_type or 'quotation').lower().strip()
    if doc_type not in ('quotation', 'proforma', 'tax_invoice'):
        doc_type = 'quotation'

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=28,
        bottomMargin=38,
        pageCompression=0
    )

    styles = getSampleStyleSheet()
    
    # Custom Brand Palette
    PRIMARY_COLOR = colors.HexColor("#1A202C")   # Deep Charcoal
    GOLD_COLOR = colors.HexColor("#B78628")      # Warm Artisan Gold
    MUTED_TEXT = colors.HexColor("#4A5568")      # Slate text
    LIGHT_BG = colors.HexColor("#F8FAFC")        # Clean Off-white
    BORDER_COLOR = colors.HexColor("#CBD5E0")    # Crisp soft border
    TABLE_ALT_BG = colors.HexColor("#FFFFFF")

    # Typography Styles using Registered NotoSans
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName=FONT_BOLD,
        fontSize=18,
        leading=22,
        textColor=PRIMARY_COLOR
    )
    
    label_style = ParagraphStyle(
        'FieldLabel',
        parent=styles['Normal'],
        fontName=FONT_BOLD,
        fontSize=8,
        leading=11,
        textColor=PRIMARY_COLOR
    )

    val_style = ParagraphStyle(
        'FieldValue',
        parent=styles['Normal'],
        fontName=FONT_NORMAL,
        fontSize=7.8,
        leading=10.5,
        textColor=MUTED_TEXT
    )
    
    val_bold = ParagraphStyle(
        'FieldValueBold',
        parent=styles['Normal'],
        fontName=FONT_BOLD,
        fontSize=8.2,
        leading=11,
        textColor=PRIMARY_COLOR
    )

    item_title_style = ParagraphStyle(
        'ItemTitle',
        parent=styles['Normal'],
        fontName=FONT_BOLD,
        fontSize=8.5,
        leading=11,
        textColor=PRIMARY_COLOR
    )
    
    item_desc_style = ParagraphStyle(
        'ItemDesc',
        parent=styles['Normal'],
        fontName=FONT_NORMAL,
        fontSize=7.5,
        leading=9.8,
        textColor=MUTED_TEXT
    )

    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName=FONT_BOLD,
        fontSize=8,
        leading=10.5,
        textColor=colors.white
    )

    story = []

    # -------------------------------------------------------------------------
    # 1. HEADER: PIKACHOOZ PARENT COMPANY LOGO & VERIFIED DETAILS
    # -------------------------------------------------------------------------
    logo_path = None
    if logo_filename and os.path.exists(logo_filename):
        logo_path = logo_filename
    elif logo_filename and os.path.exists(os.path.join(BASE_DIR, 'static', 'images', logo_filename)):
        logo_path = os.path.join(BASE_DIR, 'static', 'images', logo_filename)
    else:
        # Default to Pikachooz parent company logo as requested
        bw_cand = os.path.join(BASE_DIR, 'static', 'images', 'pikachooz_bandw_logo.jpeg')
        color_cand = os.path.join(BASE_DIR, 'static', 'images', 'pikachooz_logo.jpeg')
        if os.path.exists(bw_cand):
            logo_path = bw_cand
        elif os.path.exists(color_cand):
            logo_path = color_cand
        else:
            logo_path = os.path.join(BASE_DIR, 'static', 'images', 'official_logo.png')

    brand_flowable = None
    if logo_path and os.path.exists(logo_path):
        try:
            from PIL import Image as PILImage, ImageOps
            with PILImage.open(logo_path) as im:
                # Auto-crop margin whitespace if raw jpeg
                gray = im.convert('L')
                inv = ImageOps.invert(gray)
                bbox = inv.getbbox()
                if bbox:
                    pad = 12
                    left = max(0, bbox[0] - pad)
                    top = max(0, bbox[1] - pad)
                    right = min(im.width, bbox[2] + pad)
                    bottom = min(im.height, bbox[3] + pad)
                    cropped_im = im.crop((left, top, right, bottom))
                else:
                    cropped_im = im
                orig_w, orig_h = cropped_im.size
                
                clean_logo_path = os.path.join(BASE_DIR, 'static', 'images', 'pikachooz_current_logo.png')
                cropped_im.save(clean_logo_path)

            aspect = orig_w / float(orig_h)
            target_h = 0.32 * inch
            target_w = min(2.7 * inch, target_h * aspect)
            target_h = target_w / aspect
            brand_flowable = Image(clean_logo_path, width=target_w, height=target_h)
        except Exception:
            brand_flowable = None
            
    if not brand_flowable:
        brand_flowable = Paragraph("<b>PIKACHOOZ</b>", title_style)

    # Sweet Scribbles brand logo (shorter than Pikachooz parent logo, placed under brand subtitle)
    ss_logo_path = os.path.join(BASE_DIR, 'static', 'images', 'official_logo.png')
    ss_brand_flowable = None
    ss_w = 0.40 * inch
    if os.path.exists(ss_logo_path):
        try:
            from PIL import Image as PILImage
            with PILImage.open(ss_logo_path) as ss_im:
                bbox = ss_im.getbbox()
                ss_crop = ss_im.crop(bbox) if bbox else ss_im
                ss_w_orig, ss_h_orig = ss_crop.size
                ss_aspect = ss_w_orig / float(ss_h_orig)
                clean_ss_path = os.path.join(BASE_DIR, 'static', 'images', 'sweet_scribbles_clean.png')
                ss_crop.save(clean_ss_path)

            ss_h = 0.43 * inch  # Shorter than Pikachooz's 0.32 inch
            ss_w = ss_h * ss_aspect
            ss_brand_flowable = Image(clean_ss_path, width=ss_w, height=ss_h)
        except Exception:
            ss_brand_flowable = None

    if ss_brand_flowable:
        ss_sub_block = Table(
            [[ss_brand_flowable, Paragraph("<font color='#4A5568'><i>A Pikachooz product</i></font>", val_style)]],
            colWidths=[ss_w + 6, 3.4 * inch]
        )
        ss_sub_block.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
    else:
        ss_sub_block = Paragraph("<font color='#4A5568'><i>A Pikachooz product</i></font>", val_style)

    header_left = [
        brand_flowable,
        Spacer(1, 2),
        Paragraph("<b>Pikachooz</b>", ParagraphStyle('ParentComp', parent=val_bold, fontSize=8.5, leading=11, textColor=PRIMARY_COLOR)),
        Paragraph("<font color='#B78628'><b>Sweet Scribbles Confectionery & Gifting</b></font>", ParagraphStyle('BrandSub', parent=val_bold, fontSize=8, leading=10.5, textColor=GOLD_COLOR)),
        Spacer(1, 2),
        ss_sub_block,
        Spacer(1, 2),
        Paragraph("#151, Sangamashree Nilaya, Om Sai Nagar Layout, Kuduregere, Thammenahalli road", val_style),
        Paragraph("Bengaluru, Karnataka 562162, India", val_style),
        Paragraph("<b>GSTIN:</b> 29FJPPP4801M1ZF", val_style),
        Paragraph("<b>Phone:</b> +91 9066611856  •  <b>Email:</b> sathishkumar.dm@pikachooz.com", val_style),
        Paragraph("<b>Web:</b> www.sweetscribbles.pikachooz.com", val_style)
    ]

    issue_date = order.created_at or datetime.utcnow()
    valid_until = issue_date + timedelta(days=15 if doc_type == 'quotation' else 30)

    if doc_type == 'proforma':
        doc_title_text = "PROFORMA INVOICE"
        doc_ref_label = "Proforma Ref:"
        doc_ref_val = order.proforma_invoice_number or f"PI-{order.order_number}"
        doc_subnote = "Advance Payment Authorization & Commercial Budget Approval"
        if order.proforma_date:
            issue_date = order.proforma_date
    elif doc_type == 'tax_invoice':
        doc_title_text = "TAX INVOICE"
        doc_ref_label = "Tax Invoice No:"
        doc_ref_val = order.tax_invoice_number or f"INV-{order.order_number}"
        doc_subnote = "(Issued under Section 31 of CGST Act, 2017 & Rule 46 of CGST Rules)"
        if order.tax_invoice_date:
            issue_date = order.tax_invoice_date
        elif order.delivered_at:
            issue_date = order.delivered_at
    else:
        doc_title_text = "CORPORATE QUOTATION"
        doc_ref_label = "Quotation Ref:"
        doc_ref_val = f"QT-{order.order_number}"
        doc_subnote = "Artisanal Confectionery & Bespoke Corporate Gifting Proposal"
    
    header_right = [
        Paragraph(doc_title_text, ParagraphStyle(
            'QuoteTitle',
            parent=styles['Normal'],
            fontName=FONT_BOLD,
            fontSize=15,
            leading=18,
            alignment=2,
            textColor=GOLD_COLOR
        )),
        Paragraph(f"<font color='#718096' size='6.5'><i>{doc_subnote}</i></font>", ParagraphStyle('RightSub', parent=val_style, alignment=2)),
        Spacer(1, 3),
        Paragraph(f"<b>{doc_ref_label}</b> {doc_ref_val}", ParagraphStyle('RightBold', parent=val_bold, alignment=2)),
        Paragraph(f"<b>Date:</b> {issue_date.strftime('%d %b %Y')}", ParagraphStyle('RightVal', parent=val_style, alignment=2)),
    ]

    if doc_type in ('quotation', 'proforma'):
        header_right.append(Paragraph(f"<b>Valid Until:</b> {valid_until.strftime('%d %b %Y')}", ParagraphStyle('RightVal', parent=val_style, alignment=2)))

    if order.client_po_number:
        po_display = f"<b>Client PO:</b> {order.client_po_number}"
        if order.client_po_date:
            po_display += f" ({order.client_po_date})"
        header_right.append(Paragraph(po_display, ParagraphStyle('RightValPO', parent=val_bold, alignment=2, textColor=PRIMARY_COLOR)))

    pos_label = "Karnataka (29)" if not order.is_interstate else "Inter-State Supply"
    header_right.append(Paragraph(f"<b>Place of Supply:</b> {pos_label}", ParagraphStyle('RightVal', parent=val_style, alignment=2)))
    header_right.append(Paragraph(f"<b>Workflow Status:</b> {order.get_stage_display()}", ParagraphStyle('RightVal', parent=val_style, alignment=2)))

    header_table = Table(
        [[header_left, header_right]],
        colWidths=[4.2 * inch, 3.0 * inch]
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=GOLD_COLOR, spaceBefore=0, spaceAfter=8))

    # -------------------------------------------------------------------------
    # 2. CLIENT INFORMATION BLOCK
    # -------------------------------------------------------------------------
    client = order.client
    company_name = client.company_name if client else "Valued Corporate Client"
    contact_name = client.contact_name if client else "Attention: Gifting Team"
    client_phone = client.phone if client else "—"
    client_email = client.email if client else "—"
    gst_num = (client.gst_number if client and client.gst_number else "Not Provided / Unregistered Consumer")
    shipping_addr = (client.shipping_address if client and client.shipping_address else "To be confirmed prior to dispatch")
    occasion_txt = order.custom_occasion or "Corporate Milestone / Festive Gifting"

    bill_to_content = [
        Paragraph("<b>QUOTED TO (CLIENT DETAILS):</b>", ParagraphStyle('SubHead', parent=label_style, textColor=GOLD_COLOR)),
        Spacer(1, 2),
        Paragraph(f"<b>Company:</b> {company_name}", val_bold),
        Paragraph(f"<b>Contact Person:</b> {contact_name}", val_style),
        Paragraph(f"<b>Phone:</b> {client_phone}  |  <b>Email:</b> {client_email}", val_style),
        Paragraph(f"<b>GSTIN:</b> {gst_num}", val_style),
    ]

    ship_to_content = [
        Paragraph("<b>DELIVERY & EVENT LOGISTICS:</b>", ParagraphStyle('SubHead2', parent=label_style, textColor=GOLD_COLOR)),
        Spacer(1, 2),
        Paragraph(f"<b>Occasion / Purpose:</b> {occasion_txt}", val_style),
        Paragraph(f"<b>Delivery Address:</b> {shipping_addr}", val_style),
        Paragraph(f"<b>Target Dispatch ETA:</b> {order.eta_date or '5 - 7 Business Days post proof approval'}", val_style),
    ]

    client_table = Table(
        [[bill_to_content, ship_to_content]],
        colWidths=[3.6 * inch, 3.6 * inch]
    )
    client_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), LIGHT_BG),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER_COLOR),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(client_table)
    story.append(Spacer(1, 8))

    # -------------------------------------------------------------------------
    # 3. ITEMIZED PRODUCTS & HAMPERS TABLE
    # -------------------------------------------------------------------------
    line_items = []
    if order.items and len(order.items) > 0:
        for idx, itm in enumerate(order.items, start=1):
            line_items.append({
                'idx': idx,
                'name': itm.item_name,
                'desc': itm.description or itm.item_category or "Handcrafted bespoke curation with custom festive branding",
                'qty': itm.quantity,
                'rate': itm.unit_price,
                'amount': itm.total_price
            })
    else:
        qty = order.box_count if order.box_count > 0 else 1
        rate = order.quoted_price_per_box if order.quoted_price_per_box > 0 else (order.total_amount / qty if qty else 0.0)
        line_items.append({
            'idx': 1,
            'name': order.box_type or "Curated Corporate Hamper",
            'desc': order.custom_message or "Custom sleeve branding, artisanal confectionery curation, luxury rigid box packaging",
            'qty': qty,
            'rate': rate,
            'amount': order.total_amount if order.total_amount > 0 else (qty * rate)
        })

    table_data = [
        [
            Paragraph("<b>#</b>", table_header_style),
            Paragraph("<b>Item Description & Specifications</b>", table_header_style),
            Paragraph("<b>Qty</b>", ParagraphStyle('ThC', parent=table_header_style, alignment=1)),
            Paragraph("<b>Unit Rate (₹)</b>", ParagraphStyle('ThR', parent=table_header_style, alignment=2)),
            Paragraph("<b>Amount (₹)</b>", ParagraphStyle('ThR2', parent=table_header_style, alignment=2)),
        ]
    ]

    for item in line_items:
        desc_flowables = [
            Paragraph(f"<b>{item['name']}</b>", item_title_style),
            Paragraph(f"{item['desc']}", item_desc_style)
        ]
        table_data.append([
            Paragraph(str(item['idx']), ParagraphStyle('RowIdx', parent=val_style, alignment=1)),
            desc_flowables,
            Paragraph(str(item['qty']), ParagraphStyle('RowQty', parent=val_style, alignment=1)),
            Paragraph(f"₹{item['rate']:,.2f}", ParagraphStyle('RowRate', parent=val_style, alignment=2)),
            Paragraph(f"₹{item['amount']:,.2f}", ParagraphStyle('RowTotal', parent=val_bold, alignment=2)),
        ])

    items_table = Table(
        table_data,
        colWidths=[0.35 * inch, 3.95 * inch, 0.65 * inch, 1.10 * inch, 1.15 * inch]
    )
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), PRIMARY_COLOR),
        ('ALIGN', (0,0), (-1,0), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
        ('TOPPADDING', (0,0), (-1,-1), 4.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4.5),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 8))

    # -------------------------------------------------------------------------
    # 4. FINANCIAL BREAKDOWN WITH DYNAMIC GST & ADVANCE ADJUSTMENT LEDGER
    # -------------------------------------------------------------------------
    subtotal = order.subtotal_amount if (order.subtotal_amount and order.subtotal_amount > 0) else sum(i['amount'] for i in line_items)
    discount_val = order.discount_amount or 0.0
    taxable_subtotal = max(0.0, round(subtotal - discount_val, 2))
    
    # Dynamic GST calculation based on order.effective_gst_rate
    gst_rate = order.effective_gst_rate
    is_interstate = order.is_interstate
    if is_interstate:
        igst_val = round(taxable_subtotal * (gst_rate / 100.0), 2)
        cgst_val = 0.0
        sgst_val = 0.0
        total_tax = igst_val
    else:
        half_rate = round(gst_rate / 2.0, 2)
        cgst_val = round(taxable_subtotal * (half_rate / 100.0), 2)
        sgst_val = round(taxable_subtotal * (half_rate / 100.0), 2)
        igst_val = 0.0
        total_tax = cgst_val + sgst_val

    grand_total = round(taxable_subtotal + total_tax, 2)
    
    # Dynamic advance calculation
    adv_pct = order.advance_percent_calc
    adv_required = round(grand_total * (adv_pct / 100.0), 2)
    balance_amount = max(0.0, round(grand_total - adv_required, 2))

    summary_rows = []
    
    # Subtotal row
    summary_rows.append([
        Paragraph("Sub Total:", ParagraphStyle('SumLbl', parent=val_style, alignment=2)),
        Paragraph(f"₹{subtotal:,.2f}", ParagraphStyle('SumVal', parent=val_style, alignment=2))
    ])

    # STRICT CONDITIONAL DISCOUNT: ONLY RENDER IF DISCOUNT > 0
    if discount_val > 0:
        disc_label = "Special Discount:"
        if order.discount_percent and order.discount_percent > 0:
            disc_label = f"Special Discount ({order.discount_percent:.1f}%):"
        summary_rows.append([
            Paragraph(f"<font color='#C53030'>{disc_label}</font>", ParagraphStyle('DiscLbl', parent=val_style, alignment=2)),
            Paragraph(f"<font color='#C53030'>(-) ₹{discount_val:,.2f}</font>", ParagraphStyle('DiscVal', parent=val_bold, alignment=2))
        ])
        summary_rows.append([
            Paragraph("Taxable Value:", ParagraphStyle('TaxLbl', parent=val_style, alignment=2)),
            Paragraph(f"₹{taxable_subtotal:,.2f}", ParagraphStyle('TaxVal', parent=val_style, alignment=2))
        ])

    # Dynamic GST Rows
    if gst_rate > 0:
        if is_interstate:
            summary_rows.append([
                Paragraph(f"IGST ({gst_rate:.1f}%):", ParagraphStyle('TaxLbl', parent=val_style, alignment=2)),
                Paragraph(f"₹{igst_val:,.2f}", ParagraphStyle('TaxVal', parent=val_style, alignment=2))
            ])
        else:
            half_rate = round(gst_rate / 2.0, 2)
            summary_rows.append([
                Paragraph(f"CGST ({half_rate:.1f}%):", ParagraphStyle('TaxLbl', parent=val_style, alignment=2)),
                Paragraph(f"₹{cgst_val:,.2f}", ParagraphStyle('TaxVal', parent=val_style, alignment=2))
            ])
            summary_rows.append([
                Paragraph(f"SGST ({half_rate:.1f}%):", ParagraphStyle('TaxLbl', parent=val_style, alignment=2)),
                Paragraph(f"₹{sgst_val:,.2f}", ParagraphStyle('TaxVal', parent=val_style, alignment=2))
            ])
    else:
        summary_rows.append([
            Paragraph("GST (0.0% Exempted):", ParagraphStyle('TaxLbl', parent=val_style, alignment=2)),
            Paragraph("₹0.00", ParagraphStyle('TaxVal', parent=val_style, alignment=2))
        ])

    # Grand Total Quoted Price (Incl. GST)
    summary_rows.append([
        Paragraph("<b>Total (Incl. GST):</b>", ParagraphStyle('TotLbl', parent=val_bold, fontSize=9.5, textColor=PRIMARY_COLOR, alignment=2)),
        Paragraph(f"<b>₹{grand_total:,.2f}</b>", ParagraphStyle('TotVal', parent=val_bold, fontSize=9.5, textColor=PRIMARY_COLOR, alignment=2))
    ])

    # Milestone Rows according to Document Type
    if doc_type == 'tax_invoice':
        if order.advance_paid:
            paid_str = f"Advance Received (PI-{order.order_number}):"
            if order.advance_paid_at:
                paid_str += f"<br/><font size='6.5' color='#718096'>Recd on {order.advance_paid_at.strftime('%d %b %Y')}</font>"
            summary_rows.append([
                Paragraph(paid_str, ParagraphStyle('AdvPaidLbl', parent=val_style, alignment=2)),
                Paragraph(f"<font color='#059669'>(-) ₹{adv_required:,.2f}</font>", ParagraphStyle('AdvPaidVal', parent=val_bold, alignment=2))
            ])
            net_bal = max(0.0, round(grand_total - adv_required, 2))
            if order.balance_paid or net_bal == 0:
                summary_rows.append([
                    Paragraph("<b>Balance Status:</b>", ParagraphStyle('BalLbl', parent=val_bold, fontSize=9, textColor=PRIMARY_COLOR, alignment=2)),
                    Paragraph("<font color='#059669'><b>PAID IN FULL</b></font>", ParagraphStyle('BalVal', parent=val_bold, fontSize=9, alignment=2))
                ])
            else:
                summary_rows.append([
                    Paragraph("<b>Net Balance Due:</b>", ParagraphStyle('BalLbl', parent=val_bold, fontSize=9, textColor=PRIMARY_COLOR, alignment=2)),
                    Paragraph(f"<b>₹{net_bal:,.2f}</b>", ParagraphStyle('BalVal', parent=val_bold, fontSize=9, textColor=PRIMARY_COLOR, alignment=2))
                ])
        else:
            summary_rows.append([
                Paragraph("<b>Total Due:</b>", ParagraphStyle('BalLbl', parent=val_bold, fontSize=9, textColor=PRIMARY_COLOR, alignment=2)),
                Paragraph(f"<b>₹{grand_total:,.2f}</b>", ParagraphStyle('BalVal', parent=val_bold, fontSize=9, textColor=PRIMARY_COLOR, alignment=2))
            ])
    elif doc_type == 'proforma':
        summary_rows.append([
            Paragraph(f"<b>Advance Due Now ({adv_pct}%):</b>", ParagraphStyle('AdvLbl', parent=val_bold, textColor=GOLD_COLOR, alignment=2)),
            Paragraph(f"<b>₹{adv_required:,.2f}</b>", ParagraphStyle('AdvVal', parent=val_bold, textColor=GOLD_COLOR, alignment=2))
        ])
        summary_rows.append([
            Paragraph("Balance Due on Dispatch:", ParagraphStyle('BalLbl', parent=val_style, fontSize=8.5, textColor=MUTED_TEXT, alignment=2)),
            Paragraph(f"₹{balance_amount:,.2f}", ParagraphStyle('BalVal', parent=val_style, fontSize=8.5, textColor=MUTED_TEXT, alignment=2))
        ])
    else:
        # Quotation
        summary_rows.append([
            Paragraph(f"Advance Required ({adv_pct}%):", ParagraphStyle('AdvLbl', parent=val_bold, textColor=GOLD_COLOR, alignment=2)),
            Paragraph(f"(-) ₹{adv_required:,.2f}", ParagraphStyle('AdvVal', parent=val_bold, textColor=GOLD_COLOR, alignment=2))
        ])
        summary_rows.append([
            Paragraph("<b>Balance on Dispatch:</b>", ParagraphStyle('BalLbl', parent=val_bold, fontSize=9, textColor=PRIMARY_COLOR, alignment=2)),
            Paragraph(f"<b>₹{balance_amount:,.2f}</b>", ParagraphStyle('BalVal', parent=val_bold, fontSize=9, textColor=PRIMARY_COLOR, alignment=2))
        ])

    summary_table = Table(
        summary_rows,
        colWidths=[2.2 * inch, 1.4 * inch]
    )
    summary_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('LINEBELOW', (0,-3), (-1,-3), 0.5, BORDER_COLOR),
        ('LINEBELOW', (0,-2), (-1,-2), 0.5, BORDER_COLOR),
        ('LINEBELOW', (0,-1), (-1,-1), 1, PRIMARY_COLOR),
    ]))

    # -------------------------------------------------------------------------
    # 5. BANK & PAYMENT DETAILS TABLE
    # -------------------------------------------------------------------------
    bank_rows = [
        [Paragraph("<b>Bank Name</b>", val_bold), Paragraph("Kotak Mahindra Bank Ltd.", val_style)],
        [Paragraph("<b>Branch</b>", val_bold), Paragraph("Peenya Industrial Estate, Peenya, Bengaluru - 560058, Karnataka", val_style)],
        [Paragraph("<b>Account Name</b>", val_bold), Paragraph("PIKACHOOZ", val_bold)],
        [Paragraph("<b>Account Number</b>", val_bold), Paragraph("<b>6450708114</b>", val_bold)],
        [Paragraph("<b>Account Type</b>", val_bold), Paragraph("Current Account", val_style)],
        [Paragraph("<b>IFSC Code</b>", val_bold), Paragraph("<b>KKBK0008036</b>", val_bold)],
    ]
    bank_table = Table(
        bank_rows,
        colWidths=[1.15 * inch, 2.35 * inch]
    )
    bank_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
        ('BACKGROUND', (0,0), (0,-1), LIGHT_BG),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 2.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))

    bank_header_text = "BANK PAYMENT DETAILS:"
    if doc_type == 'proforma':
        bank_header_text = "BANK REMITTANCE DETAILS (FOR ADVANCE PAYMENT):"
    elif doc_type == 'tax_invoice':
        bank_header_text = "BANK REMITTANCE & NEFT DETAILS:"

    left_block = [
        Paragraph(f"<b>{bank_header_text}</b>", ParagraphStyle('BankHead', parent=label_style, textColor=GOLD_COLOR)),
        Spacer(1, 3),
        bank_table
    ]

    bottom_block = Table(
        [[left_block, summary_table]],
        colWidths=[3.6 * inch, 3.6 * inch]
    )
    bottom_block.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(KeepTogether([bottom_block]))
    story.append(Spacer(1, 4))

    # -------------------------------------------------------------------------
    # 6. TOTAL IN WORDS
    # -------------------------------------------------------------------------
    amount_in_words = grand_total
    if doc_type == 'proforma':
        words_label = f"Advance Amount In Words ({adv_pct}%):"
        amount_in_words = adv_required
    else:
        words_label = "Total In Words:"

    words_str = number_to_indian_words(amount_in_words)
    words_p = Paragraph(f"<b>{words_label}</b> <i>{words_str}</i>", ParagraphStyle(
        'WordsP',
        parent=val_style,
        fontName=FONT_NORMAL,
        fontSize=8,
        leading=10.5,
        textColor=PRIMARY_COLOR
    ))
    story.append(words_p)
    story.append(Spacer(1, 6))

    # -------------------------------------------------------------------------
    # 7. TERMS & AUTHORIZED SIGNATORY (DOCUMENT TAILORED)
    # -------------------------------------------------------------------------
    sig_path = os.path.join(BASE_DIR, 'static', 'images', 'authorized_signature.png')
    sig_flowable = None
    if os.path.exists(sig_path):
        try:
            sig_flowable = Image(sig_path, width=1.3 * inch, height=0.55 * inch)
        except Exception:
            sig_flowable = None

    if doc_type == 'tax_invoice':
        terms_list = [
            Paragraph("<b>STATUTORY TERMS & DECLARATION:</b>", ParagraphStyle('TermsHead', parent=label_style, textColor=GOLD_COLOR)),
            Paragraph("• Certified that the particulars given above are true and correct under the CGST / SGST / IGST Act 2017.", val_style),
            Paragraph("• Supply of goods handcrafted to bespoke corporate purchase order.", val_style),
            Paragraph("• Input Tax Credit (ITC) can be claimed against GSTIN: 29FJPPP4801M1ZF under monthly GSTR filings.", val_style),
            Paragraph(f"• Target Delivery / Fulfillment Date: {order.eta_date or 'Dispatched / Fulfilled'}.", val_style),
        ]
    elif doc_type == 'proforma':
        terms_list = [
            Paragraph("<b>PROFORMA INVOICE TERMS & CONDITIONS:</b>", ParagraphStyle('TermsHead', parent=label_style, textColor=GOLD_COLOR)),
            Paragraph("• This Proforma Invoice is issued solely to facilitate corporate advance payment processing.", val_style),
            Paragraph("• Statutory Tax Invoice will be issued upon physical dispatch of goods as per GST rules.", val_style),
            Paragraph(f"• Please remit advance payment of {adv_pct}% (₹{adv_required:,.2f}) to the Kotak Mahindra Bank account above.", val_style),
            Paragraph(f"• Target Turnaround ETA: {order.eta_date or '5 - 7 Business Days post advance receipt & proof sign-off'}.", val_style),
        ]
    else:
        terms_list = [
            Paragraph("<b>TERMS & SPECIFICATIONS:</b>", ParagraphStyle('TermsHead', parent=label_style, textColor=GOLD_COLOR)),
            Paragraph("• HSN / SAC Code: 21069099 / 1806 / 1905 (Confectionery & Sweet Gift Boxes).", val_style),
            Paragraph("• This quotation is a formal price estimate. Production commences upon receipt of PO and advance payment.", val_style),
            Paragraph(f"• Target Delivery ETA: {order.eta_date or '5 - 7 Business Days post proof sign-off'}.", val_style),
            Paragraph("• Quotation valid for 15 days from issue date. Prices inclusive of custom sleeve & logo printing.", val_style),
        ]

    sig_block = [
        sig_flowable if sig_flowable else Spacer(1, 30),
        Paragraph("<b>Authorized Signature</b>", ParagraphStyle('SigLbl', parent=val_bold, alignment=0)),
        Paragraph("<font color='#718096' size='7'>For Pikachooz / Sweet Scribbles</font>", ParagraphStyle('SigSub', parent=val_style, alignment=0))
    ]

    closing_table = Table(
        [[terms_list, sig_block]],
        colWidths=[5.3 * inch, 1.9 * inch]
    )
    closing_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(KeepTogether([closing_table]))

    # Optional internal notes
    if order.internal_notes:
        story.append(Spacer(1, 6))
        spec_box = [
            Paragraph("<b>SPECIAL INSTRUCTIONS & NOTES:</b>", ParagraphStyle('SpecLbl', parent=label_style, textColor=PRIMARY_COLOR)),
            Paragraph(order.internal_notes, val_style)
        ]
        spec_table = Table([[spec_box]], colWidths=[7.2 * inch])
        spec_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), LIGHT_BG),
            ('BOX', (0,0), (-1,-1), 0.5, BORDER_COLOR),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(KeepTogether([spec_table]))

    # Build PDF with dynamic page numbering
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()
