import json
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request
from extensions import db
from models.b2b import B2BClient, B2BProduct
from models.b2b_crm import B2BLead, B2BEngagementEvent, CRMCampaign
from crm.routes.auth import crm_login_required

dashboard_bp = Blueprint('crm_dashboard', __name__)

@dashboard_bp.route('/')
@crm_login_required
def index():
    return render_template('crm/radar.html')

@dashboard_bp.route('/radar')
@crm_login_required
def radar():
    now = datetime.utcnow()
    past_24h = now - timedelta(hours=24)

    # Core Intelligence Metrics
    total_leads = B2BLead.query.count()
    hot_leads_count = B2BLead.query.filter((B2BLead.is_hot == True) | (B2BLead.priority_score >= 60)).count()
    portal_engaged_count = B2BLead.query.filter(B2BLead.stage == 'portal_active').count()
    events_24h_count = B2BEngagementEvent.query.filter(B2BEngagementEvent.created_at >= past_24h).count()
    logins_today_count = B2BEngagementEvent.query.filter(
        B2BEngagementEvent.event_type == 'login',
        B2BEngagementEvent.created_at >= past_24h
    ).count()

    # Hot Leads Queue (Ranked by Score and Activity)
    hot_leads = B2BLead.query.filter(
        (B2BLead.is_hot == True) | (B2BLead.priority_score >= 50)
    ).order_by(B2BLead.priority_score.desc(), B2BLead.last_active_at.desc()).limit(15).all()

    # Recent Live Engagement Activity Stream
    recent_events = B2BEngagementEvent.query.order_by(
        B2BEngagementEvent.created_at.desc()
    ).limit(35).all()

    # Format human-friendly activity cards
    activity_stream = []
    for ev in recent_events:
        lead_name = ev.lead.contact_name if ev.lead else (ev.client.contact_name if ev.client else "Anonymous Prospect")
        company = ev.lead.company_name if ev.lead else (ev.client.company_name if ev.client else "")
        score = ev.lead.priority_score if ev.lead else None
        phone = ev.lead.phone if ev.lead else (ev.client.phone if ev.client else None)
        lead_id = ev.lead.id if ev.lead else None

        meta = {}
        if ev.event_metadata:
            try:
                meta = json.loads(ev.event_metadata)
            except Exception:
                meta = {"raw": ev.event_metadata}

        description = ""
        badge_type = "info"
        icon = "bi-eye"

        if ev.event_type == 'login':
            icon = "bi-box-arrow-in-right"
            badge_type = "danger"
            description = f"🔑 Logged into Corporate Workspace via OTP."
        elif ev.event_type == 'slider_change':
            icon = "bi-sliders"
            badge_type = "warning"
            qty = meta.get('quantity') or meta.get('value') or '?'
            est = meta.get('budget_estimate') or ''
            est_txt = f" (Estimated: {est})" if est else ""
            description = f"📊 Adjusted bulk volume slider to {qty} units{est_txt}."
        elif ev.event_type == 'product_view':
            icon = "bi-gift"
            badge_type = "primary"
            p_name = meta.get('product_name') or 'Catalogue Hamper'
            description = f"🎁 Inspected product details for '{p_name}'."
        elif ev.event_type == 'cta_click':
            icon = "bi-lightning-fill"
            badge_type = "danger"
            label = meta.get('cta_label') or 'Enquiry CTA'
            description = f"⚡ Clicked action button: '{label}'."
        else:
            description = f"Visited {ev.page_title or ev.page_url}."

        activity_stream.append({
            'id': ev.id,
            'lead_id': lead_id,
            'contact_name': lead_name,
            'company_name': company,
            'phone': phone,
            'score': score,
            'event_type': ev.event_type,
            'description': description,
            'badge_type': badge_type,
            'icon': icon,
            'page_url': ev.page_url,
            'created_at': ev.created_at
        })

    return render_template(
        'crm/radar.html',
        total_leads=total_leads,
        hot_leads_count=hot_leads_count,
        portal_engaged_count=portal_engaged_count,
        events_24h_count=events_24h_count,
        logins_today_count=logins_today_count,
        hot_leads=hot_leads,
        activity_stream=activity_stream
    )

@dashboard_bp.route('/api/radar-feed')
@crm_login_required
def api_radar_feed():
    """Returns JSON payload of recent clickstream events for live polling."""
    recent_events = B2BEngagementEvent.query.order_by(
        B2BEngagementEvent.created_at.desc()
    ).limit(20).all()

    items = []
    for ev in recent_events:
        lead_name = ev.lead.contact_name if ev.lead else (ev.client.contact_name if ev.client else "Anonymous Prospect")
        company = ev.lead.company_name if ev.lead else (ev.client.company_name if ev.client else "")
        items.append({
            'id': ev.id,
            'lead_id': ev.lead_id,
            'contact_name': lead_name,
            'company_name': company,
            'event_type': ev.event_type,
            'created_at': ev.created_at.strftime("%H:%M:%S") if ev.created_at else "",
            'time_ago': ev.created_at.strftime("%I:%M %p") if ev.created_at else ""
        })

    return jsonify({'success': True, 'events': items})
