import os
import time
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from extensions import db
from models.b2b import B2BClient, B2BOrder
from utils.otp_utils import generate_otp, send_b2b_enquiry_otp, send_msg91_otp, normalize_phone, format_phone_for_msg91
from utils.gcp_storage import upload_file

b2b_bp = Blueprint('b2b', __name__)

def b2b_auth_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_id = session.get('b2b_client_id')
        if not client_id:
            flash('Please log in with your verified mobile number to access your B2B Client Portal.', 'warning')
            return redirect(url_for('b2b.login'))
        client = B2BClient.query.get(client_id)
        if not client:
            session.pop('b2b_client_id', None)
            flash('B2B Client profile not found. Please log in again.', 'warning')
            return redirect(url_for('b2b.login'))
        return f(client, *args, **kwargs)
    return decorated_function

from models.b2b import B2BClient, B2BOrder, B2BProduct

# --- Public B2B Catalogue & Landing Page ---
@b2b_bp.route('/')
def index():
    # Load dynamic boxes from database
    catalog_boxes = B2BProduct.query.filter_by(is_active=True).order_by(B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    return render_template('b2b/index.html', boxes=catalog_boxes)

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
    
    # Authenticate Client in Session
    session['b2b_client_id'] = client.id
    session.pop('b2b_enquiry_otp', None)
    
    print(f"[B2B ENQUIRY CREATED] Order #{order.order_number} for {client.company_name} ({client.phone})")
    
    return {
        'success': True,
        'message': f'Thank you {contact_name}! Your corporate gifting enquiry (#{order.order_number}) has been registered.',
        'redirect_url': url_for('b2b.portal')
    }

# --- B2B Client Login (OTP-based) ---
@b2b_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('b2b_client_id'):
        return redirect(url_for('b2b.portal'))
    return render_template('b2b/login.html')

@b2b_bp.route('/send-login-otp', methods=['POST'])
def send_login_otp():
    data = request.get_json(silent=True) or {}
    raw_phone = (data.get('phone') or request.form.get('phone', '')).strip()
    phone = normalize_phone(raw_phone)
    
    if not phone:
        return {'success': False, 'message': 'Valid mobile number is required.'}, 400
        
    client = B2BClient.query.filter_by(phone=phone).first()
    if not client:
        return {'success': False, 'message': 'No corporate client found with this phone number. Please submit an enquiry first.'}, 404
        
    current_ts = time.time()
    existing_otp = session.get('b2b_login_otp')
    if existing_otp and existing_otp.get('phone') == phone:
        last_sent = existing_otp.get('last_sent', 0)
        if current_ts - last_sent < 30:
            remaining = int(30 - (current_ts - last_sent))
            return {'success': False, 'message': f'Please wait {remaining}s before requesting a new OTP.'}, 429
            
    otp = generate_otp(length=4)
    expiry = (datetime.utcnow() + timedelta(minutes=10)).timestamp()
    
    session['b2b_login_otp'] = {
        'phone': phone,
        'otp': otp,
        'expires': expiry,
        'last_sent': current_ts
    }
    
    sent_real = send_msg91_otp(phone, otp)
    
    return {
        'success': True,
        'message': 'Login OTP sent successfully.',
        'dev_otp': otp if (current_app.debug or not sent_real) else None,
        'sent_real': sent_real
    }

@b2b_bp.route('/verify-login-otp', methods=['POST'])
def verify_login_otp():
    data = request.get_json(silent=True) or {}
    raw_phone = (data.get('phone') or request.form.get('phone', '')).strip()
    entered_otp = (data.get('otp') or request.form.get('otp', '')).strip()
    phone = normalize_phone(raw_phone)
    
    otp_data = session.get('b2b_login_otp')
    if not otp_data or otp_data.get('phone') != phone:
        return {'success': False, 'message': 'Please request an OTP first.'}, 400
        
    if otp_data.get('otp') != entered_otp:
        return {'success': False, 'message': 'Invalid 4-digit code.'}, 400
        
    if datetime.utcnow().timestamp() > otp_data.get('expires', 0):
        return {'success': False, 'message': 'OTP expired.'}, 400
        
    client = B2BClient.query.filter_by(phone=phone).first()
    if not client:
        return {'success': False, 'message': 'Client profile not found.'}, 404
        
    session['b2b_client_id'] = client.id
    session.pop('b2b_login_otp', None)
    
    return {'success': True, 'message': f'Welcome back, {client.contact_name}!', 'redirect_url': url_for('b2b.portal')}

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
        action_title="Repeat Festive Batch Requested via Portal",
        to_stage='enquiry',
        actor=f"Client ({client.contact_name})",
        details=f"Occasion: {custom_occasion}, Box: {box_type}, Qty: {box_count}"
    )
    
    db.session.commit()
    
    flash(f'New corporate gifting enquiry (#{order.order_number}) submitted successfully!', 'success')
    return redirect(url_for('b2b.portal'))


# --- Logout B2B Client ---
@b2b_bp.route('/logout')
def logout():
    session.pop('b2b_client_id', None)
    flash('You have been logged out of your B2B Client Portal.', 'info')
    return redirect(url_for('b2b.index'))
