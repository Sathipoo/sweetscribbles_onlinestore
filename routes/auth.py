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
