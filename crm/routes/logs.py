import json
import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, Response, jsonify, url_for
from extensions import db
from models.b2b import B2BClient
from models.b2b_crm import B2BLead, B2BEngagementEvent
from crm.routes.auth import crm_login_required

logs_bp = Blueprint('crm_logs', __name__)

def parse_date_filters(date_preset, start_date_str, end_date_str):
    now = datetime.utcnow()
    start_dt = None
    end_dt = None

    if date_preset == 'today':
        start_dt = datetime(now.year, now.month, now.day, 0, 0, 0)
        end_dt = now
    elif date_preset == 'yesterday':
        yesterday = now - timedelta(days=1)
        start_dt = datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0)
        end_dt = datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59)
    elif date_preset == '7d':
        start_dt = now - timedelta(days=7)
        end_dt = now
    elif date_preset == '30d':
        start_dt = now - timedelta(days=30)
        end_dt = now
    elif date_preset == 'custom':
        if start_date_str:
            try:
                start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
            except ValueError:
                pass
        if end_date_str:
            try:
                end_dt = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1, microseconds=-1)
            except ValueError:
                pass

    return start_dt, end_dt

def build_filtered_query(args):
    date_preset = args.get('date_preset', 'all')
    start_date_str = args.get('start_date', '').strip()
    end_date_str = args.get('end_date', '').strip()
    lead_id = args.get('lead_id', type=int)
    audience = args.get('audience', 'all')
    event_type = args.get('event_type', 'all')
    high_intent = args.get('high_intent', '') == '1'
    search_query = args.get('q', '').strip()

    query = B2BEngagementEvent.query.outerjoin(B2BLead, B2BEngagementEvent.lead_id == B2BLead.id)

    # 1. Date Range Filter
    start_dt, end_dt = parse_date_filters(date_preset, start_date_str, end_date_str)
    if start_dt:
        query = query.filter(B2BEngagementEvent.created_at >= start_dt)
    if end_dt:
        query = query.filter(B2BEngagementEvent.created_at <= end_dt)

    # 2. Lead / Audience Filter
    if lead_id:
        query = query.filter(B2BEngagementEvent.lead_id == lead_id)
    elif audience == 'leads':
        query = query.filter(B2BEngagementEvent.lead_id.isnot(None))
    elif audience == 'anonymous':
        query = query.filter(B2BEngagementEvent.lead_id.is_(None), B2BEngagementEvent.client_id.is_(None))
    elif audience == 'clients':
        query = query.filter(B2BEngagementEvent.client_id.isnot(None))

    # 3. Event Type Filter
    if event_type and event_type != 'all':
        query = query.filter(B2BEngagementEvent.event_type == event_type)

    # 4. High-Intent Filter (Sliders, CTAs, OTP Logins)
    if high_intent:
        query = query.filter(B2BEngagementEvent.event_type.in_(['slider_change', 'cta_click', 'login']))

    # 5. Full-Text Search Filter
    if search_query:
        term = f"%{search_query}%"
        query = query.filter(
            db.or_(
                B2BLead.contact_name.ilike(term),
                B2BLead.company_name.ilike(term),
                B2BLead.phone.ilike(term),
                B2BEngagementEvent.page_url.ilike(term),
                B2BEngagementEvent.page_title.ilike(term),
                B2BEngagementEvent.element_identifier.ilike(term),
                B2BEngagementEvent.event_metadata.ilike(term),
                B2BEngagementEvent.ip_address.ilike(term),
                B2BEngagementEvent.visitor_id.ilike(term)
            )
        )

    return query, date_preset, start_date_str, end_date_str, lead_id, audience, event_type, high_intent, search_query

@logs_bp.route('/')
@crm_login_required
def view_logs():
    query, date_preset, start_date_str, end_date_str, lead_id, audience, event_type, high_intent, search_query = build_filtered_query(request.args)

    # Order newest first
    ordered_query = query.order_by(B2BEngagementEvent.created_at.desc())

    # Calculate Intelligence KPIs across the active filtered scope
    total_events_count = query.count()
    
    unique_leads_count = query.filter(B2BEngagementEvent.lead_id.isnot(None))\
                              .with_entities(B2BEngagementEvent.lead_id)\
                              .distinct().count()

    anonymous_count = query.filter(B2BEngagementEvent.lead_id.is_(None), B2BEngagementEvent.client_id.is_(None))\
                           .with_entities(B2BEngagementEvent.visitor_id)\
                           .distinct().count()

    high_intent_count = query.filter(B2BEngagementEvent.event_type.in_(['slider_change', 'cta_click', 'login'])).count()

    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 50
    pagination = ordered_query.paginate(page=page, per_page=per_page, error_out=False)
    events = pagination.items

    # Format events for presentation
    formatted_events = []
    for ev in events:
        lead_ref = ev.lead
        client_ref = ev.client

        # Name resolution
        if lead_ref:
            display_name = lead_ref.contact_name
            company_name = lead_ref.company_name
            phone = lead_ref.phone
            score = lead_ref.priority_score
            is_identified = True
        elif client_ref:
            display_name = client_ref.contact_name
            company_name = client_ref.company_name
            phone = client_ref.phone
            score = None
            is_identified = True
        else:
            display_name = "Anonymous Visitor"
            company_name = f"ID: {ev.visitor_id[:10]}..." if ev.visitor_id else "Guest"
            phone = None
            score = None
            is_identified = False

        # Metadata parsing
        meta = {}
        meta_raw = ev.event_metadata or ''
        if meta_raw:
            try:
                meta = json.loads(meta_raw)
            except Exception:
                meta = {"raw": meta_raw}

        # Human-readable event description and styling tokens
        badge_class = "secondary"
        icon = "bi-record-circle"
        action_summary = ev.event_type

        if ev.event_type == 'login':
            badge_class = "danger"
            icon = "bi-box-arrow-in-right"
            action_summary = "Corporate OTP Login"
        elif ev.event_type == 'product_view':
            badge_class = "primary"
            icon = "bi-gift"
            p_name = meta.get('product_name') or 'Corporate Hamper'
            action_summary = f"Inspected Hamper: {p_name}"
        elif ev.event_type == 'slider_change':
            badge_class = "warning text-dark"
            icon = "bi-sliders"
            qty = meta.get('quantity') or meta.get('value') or '?'
            est = meta.get('budget_estimate') or ''
            action_summary = f"Adjusted Slider: {qty} boxes {f'({est})' if est else ''}"
        elif ev.event_type == 'cta_click':
            badge_class = "danger"
            icon = "bi-lightning-fill"
            label = meta.get('cta_label') or ev.element_identifier or 'CTA Action'
            action_summary = f"Clicked Action: {label}"
        elif ev.event_type == 'page_view':
            badge_class = "info text-dark"
            icon = "bi-eye"
            action_summary = f"Pageview: {ev.page_title or ev.page_url}"

        formatted_events.append({
            'raw': ev,
            'id': ev.id,
            'lead_id': ev.lead_id,
            'client_id': ev.client_id,
            'visitor_id': ev.visitor_id,
            'created_at': ev.created_at,
            'event_type': ev.event_type,
            'display_name': display_name,
            'company_name': company_name,
            'phone': phone,
            'score': score,
            'is_identified': is_identified,
            'page_url': ev.page_url,
            'page_title': ev.page_title,
            'element_identifier': ev.element_identifier,
            'ip_address': ev.ip_address,
            'meta': meta,
            'meta_json_str': json.dumps(meta, indent=2) if meta else "{}",
            'badge_class': badge_class,
            'icon': icon,
            'action_summary': action_summary
        })

    # Load all leads for the quick lead selector dropdown
    all_leads = B2BLead.query.order_by(B2BLead.company_name.asc(), B2BLead.contact_name.asc()).all()

    # If a specific lead is selected, get their full record for the exclusive dossier banner
    selected_lead = None
    if lead_id:
        selected_lead = db.session.get(B2BLead, lead_id)

    return render_template(
        'crm/logs.html',
        events=formatted_events,
        pagination=pagination,
        total_events_count=total_events_count,
        unique_leads_count=unique_leads_count,
        anonymous_count=anonymous_count,
        high_intent_count=high_intent_count,
        all_leads=all_leads,
        selected_lead=selected_lead,
        current_lead_id=lead_id,
        date_preset=date_preset,
        start_date=start_date_str,
        end_date=end_date_str,
        audience=audience,
        event_type=event_type,
        high_intent=high_intent,
        search_query=search_query
    )

@logs_bp.route('/export')
@crm_login_required
def export_logs_csv():
    """Streams a filtered CSV download of storefront telemetry clickstream logs."""
    query, _, _, _, _, _, _, _, _ = build_filtered_query(request.args)
    events = query.order_by(B2BEngagementEvent.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header Row
    writer.writerow([
        'Event ID',
        'Timestamp (UTC)',
        'Event Type',
        'Lead ID',
        'Contact Name',
        'Company Name',
        'Phone',
        'Stage',
        'Intent Score',
        'Page URL',
        'Page Title',
        'Element Identifier',
        'Metadata JSON',
        'IP Address',
        'Visitor ID'
    ])

    for ev in events:
        lead = ev.lead
        writer.writerow([
            ev.id,
            ev.created_at.strftime('%Y-%m-%d %H:%M:%S') if ev.created_at else '',
            ev.event_type,
            ev.lead_id or '',
            lead.contact_name if lead else (ev.client.contact_name if ev.client else 'Anonymous'),
            lead.company_name if lead else (ev.client.company_name if ev.client else ''),
            lead.phone if lead else (ev.client.phone if ev.client else ''),
            lead.stage if lead else '',
            lead.priority_score if lead else '',
            ev.page_url or '',
            ev.page_title or '',
            ev.element_identifier or '',
            ev.event_metadata or '',
            ev.ip_address or '',
            ev.visitor_id or ''
        ])

    output.seek(0)
    filename = f"sweetscribbles_clickstream_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )
