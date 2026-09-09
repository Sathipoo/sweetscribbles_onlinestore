import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime
from extensions import db
from models.b2b import B2BCommunicationLog

# Gmail SMTP Configuration
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "pooja.sathish@pikachooz.com")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
SENDER_NAME = "Sweet Scribbles B2B Gifting"
PORTAL_URL = "https://sweetscribbles.pikachooz.com/b2b/portal"


def send_b2b_email(to_email, subject, html_content, text_content=None, attachments=None):
    """
    Sends an email via Gmail SMTP with optional file attachments.
    Returns (success: bool, message: str)
    """
    if not to_email:
        return False, "Recipient email is empty"

    if not text_content:
        # Fallback text
        text_content = html_content.replace("<br>", "\n").replace("</p>", "\n\n")

    msg = MIMEMultipart("mixed")
    msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # Alternative body for plain text vs HTML
    alt_body = MIMEMultipart("alternative")
    alt_body.attach(MIMEText(text_content, "plain"))
    alt_body.attach(MIMEText(html_content, "html"))
    msg.attach(alt_body)

    # Attachments list: tuple of (filename, file_bytes, mime_type)
    if attachments:
        for att in attachments:
            if isinstance(att, tuple) and len(att) >= 2:
                filename, file_bytes = att[0], att[1]
                part = MIMEApplication(file_bytes, Name=filename)
                part['Content-Disposition'] = f'attachment; filename="{filename}"'
                msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())
        server.quit()
        return True, "Email dispatched successfully"
    except Exception as e:
        return False, str(e)


def _render_luxury_email_layout(title, preheader, body_html, cta_text=None, cta_url=None):
    """
    Standard branded responsive HTML wrapper matching Sweet Scribbles luxury theme.
    """
    cta_block = ""
    if cta_text and cta_url:
        cta_block = f"""
        <div style="text-align: center; margin: 30px 0 20px 0;">
            <a href="{cta_url}" style="background: linear-gradient(135deg, #1A202C 0%, #2D3748 100%); color: #D4AF37; padding: 14px 30px; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 15px; letter-spacing: 0.5px; display: inline-block; box-shadow: 0 4px 12px rgba(0,0,0,0.15); border: 1px solid #D4AF37;">
                {cta_text} &rarr;
            </a>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #F8FAFC; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #2D3748; line-height: 1.6;">
    <div style="display: none; max-height: 0px; overflow: hidden;">{preheader}</div>
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout: fixed; background-color: #F8FAFC; padding: 30px 10px;">
        <tr>
            <td align="center">
                <!-- Main Container -->
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #FFFFFF; border-radius: 12px; overflow: hidden; box-shadow: 0 8px 30px rgba(0,0,0,0.06); border: 1px solid #E2E8F0;">
                    <!-- Brand Header -->
                    <tr>
                        <td style="background: #1A202C; padding: 28px 30px; text-align: center; border-bottom: 3px solid #D4AF37;">
                            <div style="font-size: 24px; font-weight: 800; letter-spacing: 2px; color: #FFFFFF; text-transform: uppercase;">
                                SWEET SCRIBBLES
                            </div>
                            <div style="font-size: 11px; letter-spacing: 1.5px; color: #D4AF37; margin-top: 4px; font-weight: 600; text-transform: uppercase;">
                                Artisanal Hampers & Corporate Gifting
                            </div>
                        </td>
                    </tr>
                    <!-- Main Content Body -->
                    <tr>
                        <td style="padding: 35px 35px 25px 35px;">
                            {body_html}
                            {cta_block}
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #F7FAFC; padding: 25px 35px; border-top: 1px solid #EDF2F7; font-size: 12px; color: #718096; text-align: center;">
                            <p style="margin: 0 0 8px 0; font-weight: 600; color: #4A5568;">
                                Sweet Scribbles Confectionery & Gifting Desk
                            </p>
                            <p style="margin: 0 0 10px 0;">
                                Pooja Sathish &bull; Bangalore, Karnataka &bull; +91 99000 00000
                            </p>
                            <p style="margin: 0; font-size: 11px; color: #A0AEC0;">
                                Direct Portal: <a href="{PORTAL_URL}" style="color: #B78628; text-decoration: underline;">{PORTAL_URL}</a>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


# =====================================================================
# SPECIFIC B2B DISPATCHERS & LOGGERS
# =====================================================================

def send_welcome_onboarding_email(client, order=None):
    """
    Dispatches onboarding welcome email informing client they can log into
    https://sweetscribbles.pikachooz.com/b2b/portal using their mobile number.
    Logs event in B2BCommunicationLog.
    """
    to_email = client.email
    if not to_email:
        return False, "Client has no email address"

    contact_name = client.contact_name or "Valued Partner"
    company_name = client.company_name or "Your Organization"
    phone_num = client.phone

    subject = f"Welcome to Sweet Scribbles Corporate Gifting — {company_name}"
    preheader = f"Access your custom B2B Gifting Portal using mobile {phone_num}"

    body_html = f"""
    <h2 style="color: #1A202C; margin-top: 0; font-size: 20px; font-weight: 700;">
        Welcome to Sweet Scribbles, {contact_name}!
    </h2>
    <p style="color: #4A5568; font-size: 15px;">
        Thank you for choosing Sweet Scribbles for your corporate and festive gifting requirements. We are delighted to collaborate with <b>{company_name}</b>.
    </p>
    <div style="background-color: #F8FAFC; border-left: 4px solid #D4AF37; padding: 18px 20px; border-radius: 6px; margin: 24px 0;">
        <h4 style="margin: 0 0 8px 0; color: #1A202C; font-size: 15px;">Your B2B Client Portal is Ready</h4>
        <p style="margin: 0 0 10px 0; color: #4A5568; font-size: 14px;">
            You can track your enquiries, review customized design sleeve proofs, inspect commercial quotations, and check dispatch timelines anytime directly in your private client portal.
        </p>
        <p style="margin: 0; color: #1A202C; font-size: 14px; font-weight: 600;">
            <b>Login URL:</b> <a href="{PORTAL_URL}" style="color: #B78628;">{PORTAL_URL}</a><br>
            <b>Registered Mobile:</b> {phone_num} (Instant OTP sign-in)
        </p>
    </div>
    <p style="color: #4A5568; font-size: 14px;">
        Our team is currently preparing tailored hamper recommendations and specifications for your upcoming occasion. Feel free to reach out to us directly for any special dietary, theme, or branding requests.
    </p>
    <p style="color: #718096; font-size: 13px; margin-top: 25px;">
        Warm regards,<br>
        <b>Pooja Sathish</b><br>
        Founder & Gifting Director &bull; Sweet Scribbles
    </p>
    """

    success, msg = send_b2b_email(
        to_email=to_email,
        subject=subject,
        html_content=_render_luxury_email_layout(
            title="Welcome to Sweet Scribbles",
            preheader=preheader,
            body_html=body_html,
            cta_text="Open Your B2B Portal",
            cta_url=PORTAL_URL
        )
    )

    # Log communication
    log = B2BCommunicationLog(
        order_id=order.id if order else None,
        client_id=client.id,
        channel='email',
        event_type='welcome',
        recipient=to_email,
        subject=subject,
        message_preview=f"Client onboarding welcome email with portal link ({PORTAL_URL})",
        status='sent' if success else 'failed'
    )
    db.session.add(log)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return success, msg


def send_quotation_email(order, pdf_bytes, filename=None):
    """
    Sends formal commercial quotation with generated PDF attached.
    Dynamic advance percentage & conditional discount display.
    """
    client = order.client
    to_email = client.email if client else None
    if not to_email:
        return False, "Client has no email address"

    if not filename:
        filename = f"Quotation-{order.order_number}.pdf"

    contact_name = client.contact_name or "Valued Client"
    company_name = client.company_name or ""
    
    quote_ref = f"QT-{order.order_number}"
    total_val = f"₹{order.total_amount:,.2f}"
    
    # Dynamic advance percentage
    adv_pct = order.advance_percent_calc
    adv_val = f"₹{order.advance_amount_required:,.2f}"

    subject = f"Commercial Quotation [{quote_ref}] — Sweet Scribbles Gifting"
    preheader = f"Quotation {quote_ref} for {order.box_count} units ({order.box_type}) is ready for review."

    # Discount note in email body only if discount > 0
    discount_note = ""
    if order.discount_amount and order.discount_amount > 0:
        discount_note = f"""
        <tr>
            <td style="padding: 8px 0; color: #C53030; font-size: 14px;">Special Applied Discount:</td>
            <td style="padding: 8px 0; color: #C53030; font-weight: 700; text-align: right; font-size: 14px;">- ₹{order.discount_amount:,.2f}</td>
        </tr>
        """

    body_html = f"""
    <h2 style="color: #1A202C; margin-top: 0; font-size: 20px; font-weight: 700;">
        Commercial Quotation Prepared for {company_name or contact_name}
    </h2>
    <p style="color: #4A5568; font-size: 15px;">
        Dear {contact_name},<br><br>
        Thank you for discussing your gifting requirements with us. We have prepared your tailored quotation <b>{quote_ref}</b> with specifications, packaging details, and pricing.
    </p>

    <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 20px; margin: 24px 0;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%">
            <tr>
                <td style="padding: 6px 0; color: #718096; font-size: 14px;">Selected Format / Hamper:</td>
                <td style="padding: 6px 0; color: #1A202C; font-weight: 700; text-align: right; font-size: 14px;">{order.box_type}</td>
            </tr>
            <tr>
                <td style="padding: 6px 0; color: #718096; font-size: 14px;">Quantity:</td>
                <td style="padding: 6px 0; color: #1A202C; font-weight: 700; text-align: right; font-size: 14px;">{order.box_count} Units</td>
            </tr>
            <tr>
                <td style="padding: 6px 0; color: #718096; font-size: 14px;">Occasion / Purpose:</td>
                <td style="padding: 6px 0; color: #1A202C; font-weight: 600; text-align: right; font-size: 14px;">{order.custom_occasion or 'Corporate Gifting'}</td>
            </tr>
            {discount_note}
            <tr style="border-top: 1px solid #CBD5E0;">
                <td style="padding: 10px 0 6px 0; color: #1A202C; font-weight: 700; font-size: 16px;">Total Quoted Price:</td>
                <td style="padding: 10px 0 6px 0; color: #1A202C; font-weight: 800; text-align: right; font-size: 16px;">{total_val}</td>
            </tr>
            <tr>
                <td style="padding: 6px 0; color: #B78628; font-weight: 700; font-size: 14px;">Advance Required ({adv_pct}%):</td>
                <td style="padding: 6px 0; color: #B78628; font-weight: 800; text-align: right; font-size: 14px;">{adv_val}</td>
            </tr>
        </table>
    </div>

    <p style="color: #4A5568; font-size: 14px;">
        Please find your complete, itemized formal quotation attached to this email as a PDF document (<b>{filename}</b>).
    </p>
    <p style="color: #4A5568; font-size: 14px;">
        To accept the quotation and confirm your order slot, simply transfer the advance amount to the bank coordinates listed in the quotation and reply with the payment confirmation.
    </p>
    """

    success, msg = send_b2b_email(
        to_email=to_email,
        subject=subject,
        html_content=_render_luxury_email_layout(
            title=f"Quotation {quote_ref}",
            preheader=preheader,
            body_html=body_html,
            cta_text="View Order on B2B Portal",
            cta_url=PORTAL_URL
        ),
        attachments=[(filename, pdf_bytes)]
    )

    # Log communication
    log = B2BCommunicationLog(
        order_id=order.id,
        client_id=client.id,
        channel='email',
        event_type='quotation',
        recipient=to_email,
        subject=subject,
        message_preview=f"Commercial Quotation {quote_ref} for {order.box_count} boxes ({total_val}) with PDF attached",
        attachment_name=filename,
        status='sent' if success else 'failed'
    )
    db.session.add(log)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return success, msg


def send_advance_received_email(order, advance_amount=None):
    """
    Confirms advance payment receipt (dynamically formatted, NOT hardcoded to 50%).
    """
    client = order.client
    to_email = client.email if client else None
    if not to_email:
        return False, "Client has no email address"

    contact_name = client.contact_name or "Valued Client"
    company_name = client.company_name or ""
    
    amount_str = f"₹{advance_amount:,.2f}" if advance_amount else f"₹{order.advance_amount_required:,.2f}"
    adv_pct = order.advance_percent_calc

    subject = f"Advance Received & Order Confirmed [{order.order_number}] — Sweet Scribbles"
    preheader = f"We have received your advance payment of {amount_str} for Order #{order.order_number}."

    body_html = f"""
    <h2 style="color: #1A202C; margin-top: 0; font-size: 20px; font-weight: 700;">
        Advance Payment Confirmed & Order Locked!
    </h2>
    <p style="color: #4A5568; font-size: 15px;">
        Dear {contact_name},<br><br>
        We have successfully received your advance payment of <b>{amount_str}</b> ({adv_pct}% advance) for Order <b>#{order.order_number}</b>. Your order slot has been officially confirmed!
    </p>

    <div style="background-color: #F0FFF4; border: 1px solid #C6F6D5; border-radius: 8px; padding: 18px 20px; margin: 24px 0;">
        <h4 style="margin: 0 0 6px 0; color: #22543D; font-size: 15px;">Next Step: Custom Digital Sleeve Proof</h4>
        <p style="margin: 0; color: #2F855A; font-size: 14px;">
            Our design studio has commenced preparing your custom branding sleeve proof. Once uploaded, you will receive an approval link to review and greenlight production.
        </p>
    </div>

    <p style="color: #4A5568; font-size: 14px;">
        You can monitor your order progress and preview design files anytime on the B2B portal.
    </p>
    """

    success, msg = send_b2b_email(
        to_email=to_email,
        subject=subject,
        html_content=_render_luxury_email_layout(
            title="Advance Payment Confirmed",
            preheader=preheader,
            body_html=body_html,
            cta_text="Track Order on Portal",
            cta_url=PORTAL_URL
        )
    )

    log = B2BCommunicationLog(
        order_id=order.id,
        client_id=client.id,
        channel='email',
        event_type='advance_paid',
        recipient=to_email,
        subject=subject,
        message_preview=f"Advance confirmation receipt ({amount_str}, {adv_pct}%) for order #{order.order_number}",
        status='sent' if success else 'failed'
    )
    db.session.add(log)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return success, msg


def send_design_proof_email(order):
    """
    Alerts client that digital sleeve proof mockup is ready for approval.
    """
    client = order.client
    to_email = client.email if client else None
    if not to_email:
        return False, "Client has no email address"

    contact_name = client.contact_name or "Valued Client"
    subject = f"Action Required: Approve Design Proof for Order #{order.order_number} — Sweet Scribbles"
    preheader = f"Your custom branding sleeve proof for #{order.order_number} is ready for review."

    body_html = f"""
    <h2 style="color: #1A202C; margin-top: 0; font-size: 20px; font-weight: 700;">
        Your Digital Sleeve Mockup is Ready for Approval!
    </h2>
    <p style="color: #4A5568; font-size: 15px;">
        Dear {contact_name},<br><br>
        Our design studio has crafted your personalized packaging sleeve mockup for Order <b>#{order.order_number}</b>.
    </p>

    <div style="background-color: #FAF5FF; border: 1px solid #E9D8FD; border-radius: 8px; padding: 18px 20px; margin: 24px 0;">
        <h4 style="margin: 0 0 6px 0; color: #553C9A; font-size: 15px;">Sleeve Proof Sign-Off</h4>
        <p style="margin: 0; color: #6B46C1; font-size: 14px;">
            Please log into your client portal to review the proof dimensions, logo fidelity, and festive messaging. Once approved, sleeve printing will commence immediately.
        </p>
    </div>
    """

    success, msg = send_b2b_email(
        to_email=to_email,
        subject=subject,
        html_content=_render_luxury_email_layout(
            title="Design Proof Approval Required",
            preheader=preheader,
            body_html=body_html,
            cta_text="Review & Approve Proof",
            cta_url=PORTAL_URL
        )
    )

    log = B2BCommunicationLog(
        order_id=order.id,
        client_id=client.id,
        channel='email',
        event_type='design_ready',
        recipient=to_email,
        subject=subject,
        message_preview=f"Design proof approval request dispatched for order #{order.order_number}",
        status='sent' if success else 'failed'
    )
    db.session.add(log)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return success, msg


def send_production_eta_email(order):
    """
    Notifies client that final box counts & specs are locked into production.
    """
    client = order.client
    to_email = client.email if client else None
    if not to_email:
        return False, "Client has no email address"

    contact_name = client.contact_name or "Valued Client"
    eta_text = order.eta_date or "Within 5-7 business days"

    subject = f"Production Underway & Schedule Confirmed [#{order.order_number}] — Sweet Scribbles"
    preheader = f"Order #{order.order_number} ({order.box_count} units) has entered handcrafted batch production."

    body_html = f"""
    <h2 style="color: #1A202C; margin-top: 0; font-size: 20px; font-weight: 700;">
        Order Details Locked & Production Underway
    </h2>
    <p style="color: #4A5568; font-size: 15px;">
        Dear {contact_name},<br><br>
        Your specifications and final count of <b>{order.box_count} {order.box_type} boxes</b> have been locked into our master production run.
    </p>

    <div style="background-color: #FEFCBF; border: 1px solid #FAF089; border-radius: 8px; padding: 18px 20px; margin: 24px 0;">
        <p style="margin: 0; color: #744210; font-size: 15px; font-weight: 700;">
            Target Dispatch ETA: {eta_text}
        </p>
        <p style="margin: 6px 0 0 0; color: #975A16; font-size: 13px;">
            Fresh artisanal bites are curated in clean temperature-controlled batches right before dispatch to guarantee maximum freshness and shelf-life.
        </p>
    </div>
    """

    success, msg = send_b2b_email(
        to_email=to_email,
        subject=subject,
        html_content=_render_luxury_email_layout(
            title="Production Schedule Confirmed",
            preheader=preheader,
            body_html=body_html,
            cta_text="Check Order Status",
            cta_url=PORTAL_URL
        )
    )

    log = B2BCommunicationLog(
        order_id=order.id,
        client_id=client.id,
        channel='email',
        event_type='production_eta',
        recipient=to_email,
        subject=subject,
        message_preview=f"Production locked notice with ETA ({eta_text}) for order #{order.order_number}",
        status='sent' if success else 'failed'
    )
    db.session.add(log)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return success, msg


def send_order_delivered_email(order):
    """
    Delivered milestone email with dispatch confirmation & appreciation.
    """
    client = order.client
    to_email = client.email if client else None
    if not to_email:
        return False, "Client has no email address"

    contact_name = client.contact_name or "Valued Client"
    tracking_str = f" via {order.courier_name} (AWB: {order.tracking_number})" if order.courier_name or order.tracking_number else ""

    subject = f"Delivered: Your Sweet Scribbles Hampers Have Arrived! [#{order.order_number}]"
    preheader = f"Order #{order.order_number} has been delivered successfully{tracking_str}."

    body_html = f"""
    <h2 style="color: #1A202C; margin-top: 0; font-size: 20px; font-weight: 700;">
        Your Celebration Hampers Have Arrived!
    </h2>
    <p style="color: #4A5568; font-size: 15px;">
        Dear {contact_name},<br><br>
        We are thrilled to confirm that your order <b>#{order.order_number}</b> ({order.box_count} units of {order.box_type}) has been delivered successfully{tracking_str}.
    </p>
    <p style="color: #4A5568; font-size: 14px;">
        Thank you for trusting Sweet Scribbles with your corporate gifting. We hope your recipients cherish the handcrafted flavors and bespoke packaging!
    </p>
    <p style="color: #4A5568; font-size: 14px;">
        We would love to hear your feedback on how the gift boxes were received.
    </p>
    """

    success, msg = send_b2b_email(
        to_email=to_email,
        subject=subject,
        html_content=_render_luxury_email_layout(
            title="Order Delivered Successfully",
            preheader=preheader,
            body_html=body_html,
            cta_text="View Order on B2B Portal",
            cta_url=PORTAL_URL
        )
    )

    log = B2BCommunicationLog(
        order_id=order.id,
        client_id=client.id,
        channel='email',
        event_type='delivered',
        recipient=to_email,
        subject=subject,
        message_preview=f"Delivery confirmation notice for order #{order.order_number}{tracking_str}",
        status='sent' if success else 'failed'
    )
    db.session.add(log)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return success, msg
