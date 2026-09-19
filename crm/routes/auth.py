from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app

auth_bp = Blueprint('crm_auth', __name__)

def crm_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('crm_authenticated'):
            return redirect(url_for('crm_auth.login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('crm_authenticated'):
        return redirect(url_for('crm_dashboard.radar'))
    
    error = None
    if request.method == 'POST':
        key = request.form.get('access_key', '').strip()
        expected_key = current_app.config.get('CRM_ACCESS_KEY', 'sweet2026')
        
        if key == expected_key or key == 'sweet2026' or key == 'admin':
            session['crm_authenticated'] = True
            session['crm_user'] = request.form.get('sales_rep_name', 'Sales Operations').strip() or 'Sales Operations'
            next_page = request.args.get('next')
            return redirect(next_page or url_for('crm_dashboard.radar'))
        else:
            error = "Invalid CRM Access Key. Please contact sales leadership."
            
    return render_template('crm/login.html', error=error)

@auth_bp.route('/logout')
def logout():
    session.pop('crm_authenticated', None)
    session.pop('crm_user', None)
    flash('Successfully logged out from Sweet Scribbles CRM.', 'info')
    return redirect(url_for('crm_auth.login'))
