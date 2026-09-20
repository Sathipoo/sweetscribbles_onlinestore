import os
import time
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from extensions import db
from models.b2b import B2BClient, B2BOrder, B2BProduct, B2BProductImage, B2BProductShowcase, B2BTestimonial, B2BTestimonialImage
from models.b2b_crm import B2BLead, B2BEngagementEvent, CRMCampaignRecipient
from utils.otp_utils import generate_otp, send_b2b_enquiry_otp, send_msg91_otp, normalize_phone, format_phone_for_msg91
from utils.gcp_storage import upload_file
from utils.email_utils import send_welcome_onboarding_email, send_b2b_login_otp_email

b2b_bp = Blueprint('b2b', __name__)

def b2b_auth_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_id = session.get('b2b_client_id')
        lead_id = session.get('b2b_lead_id')
        
        if client_id:
            client = B2BClient.query.get(client_id)
            if not client or client.is_archived:
                session.pop('b2b_client_id', None)
                flash('This corporate account has been archived. Please contact Sweet Scribbles to reactivate your account.', 'warning')
                return redirect(url_for('b2b.login'))
            return f(client, *args, **kwargs)
        elif lead_id:
            lead = B2BLead.query.get(lead_id)
            if not lead:
                session.pop('b2b_lead_id', None)
                flash('Please log in with your verified contact to access your B2B Workspace.', 'warning')
                return redirect(url_for('b2b.login'))
            return f(lead, *args, **kwargs)
        else:
            flash('Please log in with your verified mobile number or corporate email to access your B2B Workspace.', 'warning')
            return redirect(url_for('b2b.login'))
    return decorated_function


# --- Public B2B Catalogue & Landing Page ---
@b2b_bp.route('/')
def index():
    # Load dynamic boxes and featured client testimonials from database
    catalog_boxes = B2BProduct.query.filter_by(is_active=True).order_by(B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    featured_testimonials = B2BTestimonial.query.filter_by(is_active=True, is_featured=True).order_by(B2BTestimonial.display_order.asc(), B2BTestimonial.id.asc()).all()
    return render_template('b2b/index.html', boxes=catalog_boxes, testimonials=featured_testimonials)

# --- Dedicated Product Sub-Page with Multi-Image Gallery & Delivered Showcase ---
@b2b_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    all_boxes = B2BProduct.query.filter_by(is_active=True).order_by(B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    return render_template('b2b/product_detail.html', product=product, boxes=all_boxes)

# --- Dedicated Corporate Client Stories & Testimonials Page ---
@b2b_bp.route('/testimonials')
def testimonials():
    all_testimonials = B2BTestimonial.query.filter_by(is_active=True).order_by(B2BTestimonial.display_order.asc(), B2BTestimonial.id.desc()).all()
    all_boxes = B2BProduct.query.filter_by(is_active=True).order_by(B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    return render_template('b2b/testimonials.html', testimonials=all_testimonials, boxes=all_boxes)

# --- Dedicated Hampers & Luxury Gift Sets Page ---
@b2b_bp.route('/hampers')
def hampers():
    hamper_products = B2BProduct.query.filter_by(category='Hampers & Gift Sets', is_active=True).order_by(B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    all_boxes = B2BProduct.query.filter_by(is_active=True).order_by(B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    hamper_map = {h.name: h for h in hamper_products}
    return render_template('b2b/hampers.html', hampers=hamper_products, boxes=all_boxes, hamper_map=hamper_map)


# --- Send OTP for B2B Enquiry Verification ---
@b2b_bp.route('/send-enquiry-otp', methods=['POST'])
def send_enquiry_otp():
    data = request.get_json(silent=True) or {}
    raw_phone = (data.get('phone') or request.form.get('phone', '')).strip()
    phone = normalize_phone(raw_phone)
    
    digits_only = "".join(c for c in phone if c.isdigit())
    if not phone or len(digits_only) < 10:
        return {'success': False, 'message': 'Please enter a valid 10-digit mobile number.'}, 400
        
    current_ts = time.time()
    existing_otp = session.get('b2b_enquiry_otp')
    if existing_otp and existing_otp.get('phone') == phone:
        last_sent = existing_otp.get('last_sent', 0)
        if current_ts - last_sent < 30:
            remaining = int(30 - (current_ts - last_sent))
            return {'success': False, 'message': f'Please wait {remaining}s before requesting a new OTP.'}, 429
            
    otp = generate_otp(length=4)
    expiry = (datetime.utcnow() + timedelta(minutes=10)).timestamp()
    
    session['b2b_enquiry_otp'] = {
        'phone': phone,
        'otp': otp,
        'expires': expiry,
        'last_sent': current_ts
    }
    
    sent_real = send_b2b_enquiry_otp(phone, otp)
    
    return {
        'success': True,
        'message': 'OTP sent successfully to your mobile number.',
        'phone': phone,
        'dev_otp': otp if (current_app.debug or not sent_real) else None,
        'sent_real': sent_real
    }

# --- Submit B2B Enquiry with Verified OTP ---
@b2b_bp.route('/submit-enquiry', methods=['POST'])
def submit_enquiry():
    data = request.get_json(silent=True) or {}
    
    company_name = (data.get('company_name') or request.form.get('company_name', '')).strip()
    contact_name = (data.get('contact_name') or request.form.get('contact_name', '')).strip()
    email = (data.get('email') or request.form.get('email', '')).strip()
    raw_phone = (data.get('phone') or request.form.get('phone', '')).strip()
    entered_otp = (data.get('otp') or request.form.get('otp', '')).strip()
    
    box_type = data.get('box_type') or request.form.get('box_type', 'Signature DIYA Box')
    try:
        box_count = int(data.get('box_count') or request.form.get('box_count', 50))
    except (ValueError, TypeError):
        box_count = 50
    custom_occasion = (data.get('custom_occasion') or request.form.get('custom_occasion', 'Corporate Gifting')).strip()
    custom_message = (data.get('custom_message') or request.form.get('custom_message', '')).strip()
    
    phone = normalize_phone(raw_phone)
    if not phone or not company_name or not contact_name or not email:
        return {'success': False, 'message': 'Company name, contact name, email, and mobile number are required.'}, 400
        
    otp_data = session.get('b2b_enquiry_otp')
    if not otp_data or otp_data.get('phone') != phone:
        return {'success': False, 'message': 'Please request an OTP for this mobile number first.'}, 400
        
    if otp_data.get('otp') != entered_otp:
        return {'success': False, 'message': 'Invalid 4-digit OTP. Please check and try again.'}, 400
        
    if datetime.utcnow().timestamp() > otp_data.get('expires', 0):
        return {'success': False, 'message': 'OTP has expired. Please request a new code.'}, 400
        
    # Find or create B2B Client
    client = B2BClient.query.filter_by(phone=phone).first()
    if not client:
        client = B2BClient(
            company_name=company_name,
            contact_name=contact_name,
            phone=phone,
            email=email
        )
        db.session.add(client)
        db.session.flush()
    else:
        # Update details
        client.company_name = company_name
        client.contact_name = contact_name
        client.email = email
        
    # Create B2B Order in 'enquiry' stage
    order_number = B2BOrder.generate_order_number()
    order = B2BOrder(
        order_number=order_number,
        client_id=client.id,
        box_type=box_type,
        box_count=max(10, box_count),
        custom_occasion=custom_occasion,
        custom_message=custom_message,
        stage='enquiry'
    )
    db.session.add(order)
    db.session.flush()
    
    # Audit Log
    order.add_log(
        action_title="Enquiry Registered via Mobile OTP",
        to_stage='enquiry',
        actor=f"Client ({client.contact_name})",
        details=f"Box: {order.box_type}, Count: {order.box_count} units, Occasion: {order.custom_occasion}"
    )
    
    db.session.commit()
    
    # Auto-dispatch welcome email with portal link
    if client.email:
        send_welcome_onboarding_email(client, order)

    # Authenticate Client in Session
    session['b2b_client_id'] = client.id
    session.pop('b2b_enquiry_otp', None)
    
    print(f"[B2B ENQUIRY CREATED] Order #{order.order_number} for {client.company_name} ({client.phone})")
    
    return {
        'success': True,
        'message': f'Thank you {contact_name}! Your corporate gifting enquiry (#{order.order_number}) has been registered.',
        'redirect_url': url_for('b2b.portal')
    }

# Server-side cache for active OTPs to protect against session cookie race conditions or dropouts
_B2B_ACTIVE_OTPS = {}

# --- B2B Client & Prospect Login (Dual Mobile / Email OTP) ---
@b2b_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('b2b_client_id') or session.get('b2b_lead_id'):
        return redirect(url_for('b2b.portal'))
    return render_template('b2b/login.html')

@b2b_bp.route('/send-login-otp', methods=['POST'])
def send_login_otp():
    data = request.get_json(silent=True) or {}
    raw_identifier = (data.get('identifier') or data.get('phone') or data.get('email') or request.form.get('identifier') or request.form.get('phone', '')).strip()
    
    if not raw_identifier:
        return {'success': False, 'message': 'Valid mobile number or corporate email is required.'}, 400

    is_email = '@' in raw_identifier
    if is_email:
        identifier = raw_identifier.lower().strip()
        client = B2BClient.query.filter(B2BClient.email.ilike(identifier)).first()
        lead = None
        if not client:
            lead = B2BLead.query.filter(B2BLead.email.ilike(identifier)).first()
        display_target = identifier
        digits = None
    else:
        digits = "".join(c for c in raw_identifier if c.isdigit())
        if len(digits) == 11 and digits.startswith('0'):
            digits = digits[1:]
        elif len(digits) > 10 and digits.startswith('91'):
            digits = digits[2:]
        if len(digits) != 10:
            return {'success': False, 'message': 'Please enter a valid 10-digit Indian mobile number.'}, 400

        phone_normalized = f"+91{digits}"
        identifier = phone_normalized
        display_target = f"+91 {digits[:5]} {digits[5:]}"

        client = B2BClient.query.filter(
            (B2BClient.phone == phone_normalized) | (B2BClient.phone == digits) | (B2BClient.phone.endswith(digits))
        ).first()
        lead = None
        if not client:
            lead = B2BLead.query.filter(
                (B2BLead.phone == phone_normalized) | (B2BLead.phone == digits) | (B2BLead.phone.endswith(digits))
            ).first()

    if not client and not lead:
        return {
            'success': False,
            'message': 'No registered corporate client or invited prospect found with this contact. Please submit an enquiry to get started.'
        }, 404

    if client and client.is_archived:
        return {
            'success': False,
            'message': 'This corporate account has been archived. Please contact your Sweet Scribbles account manager to reactivate.'
        }, 403

    entity_type = 'client' if client else 'lead'
    entity_id = client.id if client else lead.id
    contact_name = client.contact_name if client else lead.contact_name

    current_ts = time.time()
    existing_otp = session.get('b2b_login_otp') or _B2B_ACTIVE_OTPS.get(identifier)
    if existing_otp and existing_otp.get('identifier') == identifier:
        last_sent = existing_otp.get('last_sent', 0)
        if current_ts - last_sent < 30:
            remaining = int(30 - (current_ts - last_sent))
            return {'success': False, 'message': f'Please wait {remaining}s before requesting a new OTP.'}, 429

    otp = generate_otp(length=4)
    expiry = (datetime.utcnow() + timedelta(minutes=10)).timestamp()

    otp_record = {
        'identifier': identifier,
        'raw_identifier': raw_identifier,
        'digits': digits,
        'is_email': is_email,
        'entity_type': entity_type,
        'entity_id': entity_id,
        'contact_name': contact_name,
        'otp': otp,
        'expires': expiry,
        'last_sent': current_ts
    }

    session['b2b_login_otp'] = otp_record
    session.modified = True

    # Store in server memory cache for resilience against session cookie clobbering
    _B2B_ACTIVE_OTPS[identifier] = otp_record
    _B2B_ACTIVE_OTPS[raw_identifier] = otp_record
    if digits:
        _B2B_ACTIVE_OTPS[digits] = otp_record
        _B2B_ACTIVE_OTPS[f"+91{digits}"] = otp_record

    if is_email:
        sent_real, _ = send_b2b_login_otp_email(to_email=identifier, otp=otp, contact_name=contact_name)
        msg_text = f"4-digit OTP sent to {identifier}."
    else:
        sent_real = send_msg91_otp(identifier, otp)
        msg_text = f"4-digit OTP sent to {display_target}."

    print(f"[B2B LOGIN OTP] Generated OTP {otp} for {identifier} (entity: {entity_type} #{entity_id}). Real sent: {sent_real}")

    return {
        'success': True,
        'message': msg_text,
        'identifier': identifier,
        'is_email': is_email,
        'target_display': display_target,
        'dev_otp': otp if (current_app.debug or not sent_real) else None,
        'sent_real': sent_real
    }

@b2b_bp.route('/verify-login-otp', methods=['POST'])
def verify_login_otp():
    data = request.get_json(silent=True) or {}
    raw_identifier = (data.get('identifier') or data.get('phone') or data.get('email') or request.form.get('identifier') or request.form.get('phone', '')).strip()
    entered_otp = (data.get('otp') or request.form.get('otp', '')).strip()

    if not raw_identifier:
        return {'success': False, 'message': 'Contact identifier is required.'}, 400

    is_email = '@' in raw_identifier
    digits = "".join(c for c in raw_identifier if c.isdigit())
    if is_email:
        identifier = raw_identifier.lower().strip()
    else:
        if len(digits) == 11 and digits.startswith('0'):
            digits = digits[1:]
        elif len(digits) > 10 and digits.startswith('91'):
            digits = digits[2:]
        identifier = f"+91{digits}" if digits else raw_identifier

    # Retrieve OTP data from session or server memory cache fallback
    otp_data = session.get('b2b_login_otp')
    if not otp_data:
        otp_data = _B2B_ACTIVE_OTPS.get(identifier) or _B2B_ACTIVE_OTPS.get(raw_identifier)
        if not otp_data and digits:
            otp_data = _B2B_ACTIVE_OTPS.get(digits) or _B2B_ACTIVE_OTPS.get(f"+91{digits}")

    print(f"[B2B VERIFY OTP] Raw ID: '{raw_identifier}', Parsed: '{identifier}', Entered OTP: '{entered_otp}', Found OTP Data: {bool(otp_data)}")

    if not otp_data:
        return {'success': False, 'message': 'Please request an OTP first.'}, 400

    # Match identifier against stored record
    stored_id = otp_data.get('identifier', '')
    match = (stored_id.lower() == identifier.lower()) or (stored_id.lower() == raw_identifier.lower())
    if not match and not is_email:
        stored_digits = "".join(c for c in stored_id if c.isdigit())[-10:]
        input_digits = digits[-10:] if digits else ""
        if stored_digits and input_digits and stored_digits == input_digits:
            match = True

    if not match:
        print(f"[B2B VERIFY OTP MISMATCH] Stored ID: '{stored_id}' != Input ID: '{identifier}'")
        return {'success': False, 'message': 'Contact identifier mismatch. Please request a new OTP.'}, 400

    if otp_data.get('otp') != entered_otp:
        return {'success': False, 'message': 'Invalid 4-digit code. Please check and try again.'}, 400

    if datetime.utcnow().timestamp() > otp_data.get('expires', 0):
        return {'success': False, 'message': 'OTP has expired. Please request a new one.'}, 400

    entity_type = otp_data.get('entity_type')
    entity_id = otp_data.get('entity_id')
    ip_addr = request.headers.get('X-Forwarded-For', request.remote_addr)
    user_agent_str = request.user_agent.string if request.user_agent else None

    if entity_type == 'client':
        client = B2BClient.query.get(entity_id)
        if not client or client.is_archived:
            return {'success': False, 'message': 'Corporate client account not found or archived.'}, 403
        
        session['b2b_client_id'] = client.id
        session.pop('b2b_lead_id', None)
        session.modified = True

        login_event = B2BEngagementEvent(
            client_id=client.id,
            event_type='login',
            page_url='/b2b/login',
            page_title='Client Portal Login',
            ip_address=ip_addr,
            user_agent=user_agent_str
        )
        db.session.add(login_event)
        db.session.commit()
        welcome_name = client.contact_name

    else:
        lead = B2BLead.query.get(entity_id)
        if not lead:
            return {'success': False, 'message': 'Prospect profile not found.'}, 404
        
        session['b2b_lead_id'] = lead.id
        session.pop('b2b_client_id', None)
        session.modified = True

        lead.login_count = (lead.login_count or 0) + 1
        if not lead.first_login_at:
            lead.first_login_at = datetime.utcnow()
        lead.last_login_at = datetime.utcnow()
        lead.stage = 'portal_active'
        lead.update_score(50, 'Logged in via OTP')
        lead.is_hot = True

        # Link campaign recipient if tracked
        trk_token = session.get('b2b_trk_token')
        if trk_token:
            rcp = CRMCampaignRecipient.query.filter_by(tracking_token=trk_token).first()
            if rcp and not rcp.logged_in_at:
                rcp.logged_in_at = datetime.utcnow()
                rcp.status = 'logged_in'
                if rcp.campaign:
                    rcp.campaign.unique_logins_generated = (rcp.campaign.unique_logins_generated or 0) + 1

        login_event = B2BEngagementEvent(
            lead_id=lead.id,
            event_type='login',
            page_url='/b2b/login',
            page_title='Prospect Portal Login',
            ip_address=ip_addr,
            user_agent=user_agent_str
        )
        db.session.add(login_event)
        db.session.commit()
        welcome_name = lead.contact_name

    # Clear OTP state from session and server memory cache
    session.pop('b2b_login_otp', None)
    session.modified = True
    _B2B_ACTIVE_OTPS.pop(identifier, None)
    _B2B_ACTIVE_OTPS.pop(raw_identifier, None)
    if digits:
        _B2B_ACTIVE_OTPS.pop(digits, None)
        _B2B_ACTIVE_OTPS.pop(f"+91{digits}", None)

    return {
        'success': True,
        'message': f'Welcome back, {welcome_name}!',
        'redirect_url': url_for('b2b.portal')
    }

# --- Storefront Telemetry Receiver API ---
@b2b_bp.route('/api/telemetry', methods=['POST'])
def record_telemetry():
    data = request.get_json(silent=True) or {}
    event_type = data.get('event_type', 'page_view')
    page_url = data.get('page_url', request.referrer or '')
    page_title = data.get('page_title', '')
    element_identifier = data.get('element_identifier')
    event_metadata = data.get('event_metadata')
    tracking_token = data.get('tracking_token') or request.args.get('trk')
    visitor_id = data.get('visitor_id')

    if tracking_token and session.get('b2b_trk_token') != tracking_token:
        session['b2b_trk_token'] = tracking_token
        session.modified = True

    client_id = session.get('b2b_client_id')
    lead_id = session.get('b2b_lead_id')

    # If identity is anonymous, resolve via tracking_token if present
    if not client_id and not lead_id and tracking_token:
        lead_match = B2BLead.query.filter_by(tracking_token=tracking_token).first()
        if lead_match:
            lead_id = lead_match.id
        else:
            rcp_match = CRMCampaignRecipient.query.filter_by(tracking_token=tracking_token).first()
            if rcp_match:
                if rcp_match.lead_id:
                    lead_id = rcp_match.lead_id
                elif rcp_match.client_id:
                    client_id = rcp_match.client_id
                if not rcp_match.clicked_at:
                    rcp_match.clicked_at = datetime.utcnow()
                    if rcp_match.status != 'logged_in':
                        rcp_match.status = 'clicked'

    meta_str = None
    if event_metadata:
        import json
        if isinstance(event_metadata, (dict, list)):
            meta_str = json.dumps(event_metadata)
        else:
            meta_str = str(event_metadata)

    ip_addr = request.headers.get('X-Forwarded-For', request.remote_addr)
    user_agent_str = request.user_agent.string if request.user_agent else None

    event = B2BEngagementEvent(
        lead_id=lead_id,
        client_id=client_id,
        visitor_id=visitor_id,
        event_type=event_type,
        page_url=page_url[:255] if page_url else None,
        page_title=page_title[:150] if page_title else None,
        element_identifier=element_identifier[:100] if element_identifier else None,
        event_metadata=meta_str,
        ip_address=ip_addr,
        user_agent=user_agent_str
    )
    db.session.add(event)

    if lead_id:
        lead = B2BLead.query.get(lead_id)
        if lead:
            if event_type == 'product_view':
                lead.update_score(5, 'Viewed product details')
            elif event_type == 'slider_change':
                lead.update_score(15, 'Adjusted quantity/budget range slider')
            elif event_type == 'cta_click':
                lead.update_score(25, 'Clicked high-intent CTA')
            elif event_type == 'page_view':
                lead.update_score(2, 'Browsed storefront page')

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

    return jsonify({'status': 'ok', 'event_id': event.id})

# --- B2B Client Self-Service Portal ---
@b2b_bp.route('/portal')
@b2b_auth_required
def portal(client):
    orders = client.orders
    active_order = orders[0] if orders else None
    return render_template('b2b/portal.html', client=client, orders=orders, active_order=active_order)

# --- Upload Brand Logo or Message in Portal ---
@b2b_bp.route('/portal/upload-asset', methods=['POST'])
@b2b_auth_required
def upload_asset(client):
    order_id = request.form.get('order_id')
    order = B2BOrder.query.filter_by(id=order_id, client_id=client.id).first()
    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('b2b.portal'))
        
    custom_message = request.form.get('custom_message')
    if custom_message is not None:
        order.custom_message = custom_message.strip()
        
    file = request.files.get('client_logo')
    if file and file.filename:
        try:
            logo_url = upload_file(file, file.filename, folder="b2b_logos")
            order.client_logo_url = logo_url
            flash('Brand logo and custom message saved successfully!', 'success')
            order.add_log(
                action_title="Brand Logo & Greeting Message Uploaded",
                actor=f"Client ({client.contact_name})",
                details="Vector logo and customized sleeve greeting note saved."
            )
        except Exception as e:
            flash(f'Logo upload note: Saved locally. Error connecting to storage: {e}', 'warning')
    else:
        flash('Order preferences updated!', 'success')
        order.add_log(
            action_title="Custom Greeting Note Updated",
            actor=f"Client ({client.contact_name})",
            details=f"Updated sleeve note: {order.custom_message[:60]}..." if order.custom_message else "Cleared note."
        )
        
    db.session.commit()
    return redirect(url_for('b2b.portal'))

# --- Client Approves Design Proof ---
@b2b_bp.route('/portal/approve-design/<int:order_id>', methods=['POST'])
@b2b_auth_required
def approve_design(client, order_id):
    order = B2BOrder.query.filter_by(id=order_id, client_id=client.id).first()
    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('b2b.portal'))
        
    prev_stage = order.stage
    order.design_status = 'approved'
    order.design_approved_at = datetime.utcnow()
    order.stage = 'details_locked'
    
    order.add_log(
        action_title="Design Proof Approved by Client",
        from_stage=prev_stage,
        to_stage='details_locked',
        actor=f"Client ({client.contact_name})",
        details="Client approved the box artwork mockup. Production locked."
    )
    
    db.session.commit()
    
    flash('Design proof approved! Our production team has been notified and will begin handcrafting your batch.', 'success')
    return redirect(url_for('b2b.portal'))

# --- Client Requests Design Revision ---
@b2b_bp.route('/portal/request-revision/<int:order_id>', methods=['POST'])
@b2b_auth_required
def request_revision(client, order_id):
    order = B2BOrder.query.filter_by(id=order_id, client_id=client.id).first()
    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('b2b.portal'))
        
    feedback = request.form.get('design_feedback', '').strip()
    if feedback:
        order.design_status = 'revision_requested'
        order.design_feedback = feedback
        
        order.add_log(
            action_title="Design Revision Requested by Client",
            from_stage=order.stage,
            to_stage=order.stage,
            actor=f"Client ({client.contact_name})",
            details=f"Client feedback: {feedback}"
        )
        
        db.session.commit()
        flash('Revision feedback sent to our design team. We will share an updated proof shortly!', 'info')
    else:
        flash('Please provide your revision comments.', 'warning')
        
    return redirect(url_for('b2b.portal'))

# --- 1-Click Repeat Enquiry from Client Portal ---
@b2b_bp.route('/portal/new-enquiry', methods=['POST'])
@b2b_auth_required
def new_portal_enquiry(client):
    # If the user is a prospect lead, convert to active client automatically
    if isinstance(client, B2BLead):
        lead = client
        if lead.converted_client:
            actual_client = lead.converted_client
        else:
            actual_client = B2BClient(
                company_name=lead.company_name,
                contact_name=lead.contact_name,
                phone=lead.phone or "9999999999",
                email=lead.email
            )
            db.session.add(actual_client)
            db.session.flush()
            lead.converted_client_id = actual_client.id
            lead.stage = 'converted'
            lead.update_score(50, 'Converted to Client via Portal Enquiry')

        session['b2b_client_id'] = actual_client.id
        session.pop('b2b_lead_id', None)
        client = actual_client

    box_type = request.form.get('box_type', 'Signature DIYA Box')
    try:
        box_count = int(request.form.get('box_count', 50))
    except (ValueError, TypeError):
        box_count = 50
    custom_occasion = request.form.get('custom_occasion', 'Festive Gifting').strip()
    custom_message = request.form.get('custom_message', '').strip()
    
    order = B2BOrder(
        order_number=B2BOrder.generate_order_number(),
        client_id=client.id,
        box_type=box_type,
        box_count=max(10, box_count),
        custom_occasion=custom_occasion,
        custom_message=custom_message,
        stage='enquiry'
    )
    db.session.add(order)
    db.session.flush()
    
    order.add_log(
        action_title="Festive Batch Requested via Portal",
        to_stage='enquiry',
        actor=f"Client ({client.contact_name})",
        details=f"Occasion: {custom_occasion}, Box: {box_type}, Qty: {box_count}"
    )
    
    db.session.commit()
    
    flash(f'New corporate gifting enquiry (#{order.order_number}) submitted successfully!', 'success')
    return redirect(url_for('b2b.portal'))


# --- Logout B2B Client / Prospect ---
@b2b_bp.route('/logout')
def logout():
    session.pop('b2b_client_id', None)
    session.pop('b2b_lead_id', None)
    session.pop('b2b_login_otp', None)
    flash('You have been logged out of your corporate workspace.', 'info')
    return redirect(url_for('b2b.index'))

