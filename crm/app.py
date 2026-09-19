import os
from flask import Flask, redirect, url_for
from crm.config import CRMConfig
from extensions import db

def create_crm_app(config_class=CRMConfig):
    crm_app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
        static_folder=os.path.join(os.path.dirname(__file__), 'static'),
        static_url_path='/static'
    )
    crm_app.config.from_object(config_class)

    # Initialize shared database
    db.init_app(crm_app)

    # Register CRM Blueprints
    from crm.routes.auth import auth_bp
    from crm.routes.dashboard import dashboard_bp
    from crm.routes.leads import leads_bp
    from crm.routes.campaigns import campaigns_bp
    from crm.routes.clients import clients_bp

    crm_app.register_blueprint(auth_bp, url_prefix='/auth')
    crm_app.register_blueprint(dashboard_bp)
    crm_app.register_blueprint(leads_bp)
    crm_app.register_blueprint(campaigns_bp)
    crm_app.register_blueprint(clients_bp)

    # Template formatting filters
    @crm_app.template_filter('inr')
    def inr_format(val):
        try:
            return f"₹{int(val):,}"
        except (ValueError, TypeError):
            return f"₹{val}"

    @crm_app.template_filter('datetime_fmt')
    def datetime_fmt(dt, fmt="%d %b %Y, %I:%M %p"):
        if not dt:
            return "—"
        return dt.strftime(fmt)

    @crm_app.template_filter('time_ago')
    def time_ago(dt):
        if not dt:
            return "Never"
        from datetime import datetime
        diff = datetime.utcnow() - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "Just now"
        elif seconds < 3600:
            m = seconds // 60
            return f"{m}m ago"
        elif seconds < 86400:
            h = seconds // 3600
            return f"{h}h ago"
        else:
            d = seconds // 86400
            return f"{d}d ago"

    return crm_app
