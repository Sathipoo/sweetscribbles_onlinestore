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
    from utils.otp_utils import generate_otp, send_sms_otp, normalize_phone
    from datetime import datetime, timedelta
    from flask import current_app, session
    
    data = request.get_json(silent=True) or {}
    raw_phone = (data.get('phone') or request.form.get('phone', '')).strip()
    phone = normalize_phone(raw_phone)
    
    if not phone:
        return {'success': False, 'message': 'Valid phone number is required.'}, 400
        
    otp = generate_otp()
    expiry = (datetime.utcnow() + timedelta(minutes=5)).timestamp()
    
    session['mobile_otp'] = {
        'phone': phone,
        'otp': otp,
        'expires': expiry
    }
    
    sent_real = send_sms_otp(phone, otp)
    
    return {
        'success': True,
        'message': 'OTP sent successfully.',
        'phone': phone,
        'dev_otp': otp if current_app.debug else None,
        'sent_real': sent_real
    }

@auth_bp.route('/verify-mobile-otp', methods=['POST'])
def verify_mobile_otp():
    from datetime import datetime
    from utils.otp_utils import normalize_phone
    from flask import session
    
    otp_data = session.get('mobile_otp')
    if not otp_data:
        return {'success': False, 'message': 'No OTP has been requested yet. Please request an OTP.'}, 400
        
    data = request.get_json(silent=True) or {}
    entered_otp = (data.get('otp') or request.form.get('otp', '')).strip()
    raw_phone = (data.get('phone') or request.form.get('phone', '')).strip()
    phone = normalize_phone(raw_phone)
    
    if not entered_otp or not phone:
        return {'success': False, 'message': 'OTP and phone number are required.'}, 400
        
    if otp_data['phone'] != phone:
        return {'success': False, 'message': 'Phone number mismatch error. Please request OTP again.'}, 400
        
    if otp_data['otp'] != entered_otp:
        return {'success': False, 'message': 'Incorrect OTP. Please check the code and try again.'}, 400
        
    if datetime.utcnow().timestamp() > otp_data['expires']:
        return {'success': False, 'message': 'OTP has expired. Please request a new one.'}, 400
        
    # User Lookup or Auto-registration
    user = User.query.filter_by(phone=phone).first()
    if not user:
        # Create user
        import uuid
        placeholder_email = f"user_{phone.replace('+', '')}@sweetscribbles.com"
        
        # Check if email is already taken (edge case fallback)
        existing = User.query.filter_by(email=placeholder_email).first()
        if existing:
            placeholder_email = f"user_{phone.replace('+', '')}_{uuid.uuid4().hex[:4]}@sweetscribbles.com"
            
        user = User(
            email=placeholder_email,
            name=f"User {phone[-4:]}" if len(phone) >= 4 else "Guest User",
            phone=phone
        )
        db.session.add(user)
        db.session.commit()
        
    login_user(user)
    session.pop('mobile_otp', None)
    
    return {'success': True, 'message': 'Login successful!'}
