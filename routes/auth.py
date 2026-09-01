from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from models.user import User
from extensions import db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            if user.is_admin:
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('customer.profile'))
        else:
            flash('Invalid email or password')
    return render_template('customer/login.html', signup=False)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email address is already registered.')
            return redirect(url_for('auth.register'))
            
        new_user = User(email=email, name=name, phone=phone)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
        return redirect(url_for('customer.profile'))
        
    return render_template('customer/login.html', signup=True)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('customer.home'))

@auth_bp.route('/google-login', methods=['POST'])
def google_login():
    import requests
    from flask import current_app
    
    data = request.get_json(silent=True) or {}
    id_token = data.get('id_token') or request.form.get('id_token')
    
    # Check for Simulation Mode in Development
    is_simulation = data.get('simulation') or request.form.get('simulation')
    if is_simulation and current_app.debug:
        email = (data.get('email') or request.form.get('email', 'google_mock@example.com')).strip().lower()
        name = data.get('name') or request.form.get('name', 'Google Mock User')
        if not email:
            email = 'google_mock@example.com'
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, name=name)
            db.session.add(user)
            db.session.commit()
        login_user(user)
        return {'success': True, 'message': 'Simulated Google Login Successful'}
        
    if not id_token:
        return {'success': False, 'message': 'Google ID token is required.'}, 400
        
    try:
        response = requests.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}", timeout=10)
        if response.status_code != 200:
            return {'success': False, 'message': 'Invalid Google ID token.'}, 400
            
        token_info = response.json()
        
        # Verify client ID matches if configured
        client_id = current_app.config.get('GOOGLE_CLIENT_ID')
        if client_id and token_info.get('aud') != client_id:
            return {'success': False, 'message': 'Token audience mismatch.'}, 400
            
        email = token_info.get('email')
        name = token_info.get('name') or email.split('@')[0]
        
        if not email:
            return {'success': False, 'message': 'Google account email not found in token.'}, 400
            
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, name=name)
            db.session.add(user)
            db.session.commit()
            
        login_user(user)
        return {'success': True, 'message': 'Google Login Successful'}
        
    except Exception as e:
        print(f"[GOOGLE LOGIN ERROR] Exception: {e}")
        return {'success': False, 'message': f'Google verification failed: {e}'}, 500

@auth_bp.route('/send-mobile-otp', methods=['POST'])
def send_mobile_otp():
    import time
    from utils.otp_utils import generate_otp, send_msg91_otp, normalize_phone
    from datetime import datetime, timedelta
    from flask import current_app, session
    
    data = request.get_json(silent=True) or {}
    raw_phone = (data.get('phone') or request.form.get('phone', '')).strip()
    phone = normalize_phone(raw_phone)
    
    # Require at least a valid phone number format with 10 digits
    digits_only = "".join(c for c in phone if c.isdigit())
    if not phone or len(digits_only) < 10:
        return {'success': False, 'message': 'Please enter a valid 10-digit mobile number.'}, 400
        
    current_ts = time.time()
    existing_otp_data = session.get('mobile_otp')
    
    # 30-second rate-limit cooldown
    if existing_otp_data and existing_otp_data.get('phone') == phone:
        last_sent = existing_otp_data.get('last_sent', 0)
        if current_ts - last_sent < 30:
            remaining = int(30 - (current_ts - last_sent))
            return {
                'success': False,
                'message': f'Please wait {remaining} seconds before requesting a new OTP.'
            }, 429
            
    otp = generate_otp(length=4)
    # DLT approved template is valid for 10 minutes
    expiry = (datetime.utcnow() + timedelta(minutes=10)).timestamp()
    
    session['mobile_otp'] = {
        'phone': phone,
        'otp': otp,
        'expires': expiry,
        'last_sent': current_ts
    }
    
    sent_real = send_msg91_otp(phone, otp)
    
    return {
        'success': True,
        'message': 'OTP sent successfully to your mobile number.',
        'phone': phone,
        'dev_otp': otp if (current_app.debug or not sent_real) else None,
        'sent_real': sent_real
    }

@auth_bp.route('/verify-mobile-otp', methods=['POST'])
def verify_mobile_otp():
    from datetime import datetime
    from utils.otp_utils import normalize_phone
    from flask import session
    
    otp_data = session.get('mobile_otp')
    if not otp_data:
        return {'success': False, 'message': 'No OTP requested or session expired. Please request an OTP.'}, 400
        
    data = request.get_json(silent=True) or {}
    entered_otp = (data.get('otp') or request.form.get('otp', '')).strip()
    raw_phone = (data.get('phone') or request.form.get('phone', '')).strip()
    phone = normalize_phone(raw_phone)
    
    if not entered_otp or not phone:
        return {'success': False, 'message': '4-digit OTP and phone number are required.'}, 400
        
    if otp_data.get('phone') != phone:
        return {'success': False, 'message': 'Phone number mismatch. Please request OTP again.'}, 400
        
    if otp_data.get('otp') != entered_otp:
        return {'success': False, 'message': 'Invalid OTP. Please check the 4-digit code and try again.'}, 400
        
    if datetime.utcnow().timestamp() > otp_data.get('expires', 0):
        return {'success': False, 'message': 'OTP has expired. Please request a new one.'}, 400
        
    # User Lookup or Auto-registration
    user = User.query.filter_by(phone=phone).first()
    if not user:
        # Create user
        import uuid
        digits = "".join(c for c in phone if c.isdigit())[-10:]
        placeholder_email = f"user_{digits}@sweetscribbles.com"
        
        # Check if email is already taken (edge case fallback)
        existing = User.query.filter_by(email=placeholder_email).first()
        if existing:
            placeholder_email = f"user_{digits}_{uuid.uuid4().hex[:4]}@sweetscribbles.com"
            
        user = User(
            email=placeholder_email,
            name=f"Customer {digits[-4:]}" if len(digits) >= 4 else "Sweet Scribbles Customer",
            phone=phone
        )
        db.session.add(user)
        db.session.commit()
        
    login_user(user)
    session.pop('mobile_otp', None)
    
    return {'success': True, 'message': 'Login successful! Redirecting...'}

