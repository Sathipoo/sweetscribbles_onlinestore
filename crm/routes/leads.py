import csv
import io
import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from extensions import db
from models.b2b import B2BClient
from models.b2b_crm import B2BLead, B2BEngagementEvent
from crm.routes.auth import crm_login_required
from utils.otp_utils import normalize_phone

leads_bp = Blueprint('crm_leads', __name__)

STAGES = [
    ('new', '1. New Prospects', 'secondary'),
    ('outreach_sent', '2. Outreach Sent', 'info'),
    ('portal_active', '3. Portal Engaged (Hot)', 'danger'),
    ('contacted', '4. Sales Contacted', 'primary'),
    ('warm_discussion', '5. In Negotiation', 'warning'),
    ('converted', '6. Converted to Client', 'success'),
]

@leads_bp.route('/leads')
@crm_login_required
def list_leads():
    stage_filter = request.args.get('stage')
    search = request.args.get('q', '').strip()
    hot_only = request.args.get('hot') == '1'
    view_mode = request.args.get('view', 'kanban')  # 'kanban' or 'list'

    query = B2BLead.query

    if stage_filter:
        query = query.filter(B2BLead.stage == stage_filter)

    if hot_only:
        query = query.filter((B2BLead.is_hot == True) | (B2BLead.priority_score >= 60))

    if search:
        search_fmt = f"%{search}%"
        query = query.filter(
            (B2BLead.company_name.ilike(search_fmt)) |
            (B2BLead.contact_name.ilike(search_fmt)) |
            (B2BLead.phone.ilike(search_fmt)) |
            (B2BLead.email.ilike(search_fmt))
        )

    all_leads = query.order_by(B2BLead.priority_score.desc(), B2BLead.created_at.desc()).all()

    # Group leads by stage for Kanban board
    kanban = {stage[0]: [] for stage in STAGES}
    for lead in all_leads:
        st = lead.stage if lead.stage in kanban else 'new'
        kanban[st].append(lead)

    return render_template(
        'crm/leads.html',
        leads=all_leads,
        kanban=kanban,
        stages=STAGES,
        current_stage=stage_filter,
        search=search,
        hot_only=hot_only,
        view_mode=view_mode,
        store_base_url=current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')
    )

@leads_bp.route('/leads/add', methods=['POST'])
@crm_login_required
def add_lead():
    company_name = request.form.get('company_name', '').strip()
    contact_name = request.form.get('contact_name', '').strip()
    phone = normalize_phone(request.form.get('phone', ''))
    email = request.form.get('email', '').strip().lower()
    designation = request.form.get('designation', '').strip()
    city = request.form.get('city', '').strip()
    industry = request.form.get('industry', '').strip()
    notes = request.form.get('notes', '').strip()
    lead_source = request.form.get('lead_source', 'Direct Outbound')

    if not company_name or not contact_name:
        flash('Company name and contact person are required.', 'danger')
        return redirect(url_for('crm_leads.list_leads'))

    lead = B2BLead(
        company_name=company_name,
        contact_name=contact_name,
        phone=phone or None,
        email=email or None,
        designation=designation or None,
        city=city or None,
        industry=industry or None,
        lead_source=lead_source,
        notes=notes or None,
        stage='new',
        priority_score=10
    )
    db.session.add(lead)
    db.session.commit()

    flash(f'Prospect lead for "{company_name}" ({contact_name}) created successfully!', 'success')
    return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

@leads_bp.route('/leads/import', methods=['POST'])
@crm_login_required
def import_leads():
    """
    Bulk import leads via CSV file upload or pasted multi-line text.
    Format: Company Name, Contact Name, Phone, Email, Designation, City
    """
    pasted_data = request.form.get('raw_data', '').strip()
    file = request.files.get('csv_file')

    rows = []
    if file and file.filename:
        try:
            stream = io.StringIO(file.stream.read().decode("utf-8", errors="ignore"))
            reader = csv.reader(stream)
            rows = list(reader)
        except Exception as e:
            flash(f'Error reading CSV file: {e}', 'danger')
            return redirect(url_for('crm_leads.list_leads'))
    elif pasted_data:
        stream = io.StringIO(pasted_data)
        reader = csv.reader(stream)
        rows = list(reader)

    if not rows:
        flash('No valid lead rows provided for import.', 'warning')
        return redirect(url_for('crm_leads.list_leads'))

    imported_count = 0
    for idx, row in enumerate(rows):
        if not row or len(row) < 2:
            continue
        
        # Skip header if present
        first_col = row[0].strip().lower()
        if 'company' in first_col and idx == 0:
            continue

        company = row[0].strip() if len(row) > 0 else ""
        contact = row[1].strip() if len(row) > 1 else ""
        phone = normalize_phone(row[2]) if len(row) > 2 else ""
        email = row[3].strip().lower() if len(row) > 3 else ""
        designation = row[4].strip() if len(row) > 4 else ""
        city = row[5].strip() if len(row) > 5 else ""

        if not company or not contact:
            continue

        lead = B2BLead(
            company_name=company,
            contact_name=contact,
            phone=phone or None,
            email=email or None,
            designation=designation or None,
            city=city or None,
            lead_source='CSV Import',
            stage='new',
            priority_score=10
        )
        db.session.add(lead)
        imported_count += 1

    db.session.commit()
    flash(f'Successfully imported {imported_count} corporate prospect leads!', 'success')
    return redirect(url_for('crm_leads.list_leads'))

@leads_bp.route('/leads/<int:lead_id>')
@crm_login_required
def lead_detail(lead_id):
    lead = B2BLead.query.get_or_404(lead_id)

    # Check if a client exists for this lead (by converted_client_id or matching phone/email)
    client_ids = [lead.converted_client_id] if lead.converted_client_id else []
    if not client_ids:
        match_client = None
        if lead.phone:
            match_client = B2BClient.query.filter(
                (B2BClient.phone == lead.phone) | (B2BClient.phone.endswith(lead.phone[-10:]))
            ).first()
        if not match_client and lead.email:
            match_client = B2BClient.query.filter_by(email=lead.email).first()
        if match_client:
            client_ids.append(match_client.id)
            if not lead.converted_client_id:
                lead.converted_client_id = match_client.id
                if lead.stage != 'converted':
                    lead.stage = 'converted'
                db.session.commit()

    # Clickstream telemetry events across both lead and linked client
    if client_ids:
        events = B2BEngagementEvent.query.filter(
            (B2BEngagementEvent.lead_id == lead.id) | (B2BEngagementEvent.client_id.in_(client_ids))
        ).order_by(B2BEngagementEvent.created_at.desc()).all()
    else:
        events = B2BEngagementEvent.query.filter_by(lead_id=lead.id).order_by(
            B2BEngagementEvent.created_at.desc()
        ).all()

    # Reconcile login count & timestamps from actual events
    login_events = [e for e in events if e.event_type == 'login']
    if len(login_events) > (lead.login_count or 0):
        lead.login_count = len(login_events)
        if not lead.first_login_at and login_events:
            lead.first_login_at = login_events[-1].created_at
        if login_events:
            lead.last_login_at = login_events[0].created_at
            if not lead.last_active_at or lead.last_active_at < login_events[0].created_at:
                lead.last_active_at = login_events[0].created_at
        db.session.commit()

    # Calculate Top Products of Interest from telemetry
    product_views = {}
    for ev in events:
        if ev.event_metadata:
            try:
                meta = json.loads(ev.event_metadata)
                p_name = meta.get('product_name')
                if p_name:
                    product_views[p_name] = product_views.get(p_name, 0) + 1
            except Exception:
                pass
    top_products = sorted(product_views.items(), key=lambda x: x[1], reverse=True)[:5]

    store_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')
    tracking_link = f"{store_url}/b2b?trk={lead.tracking_token}"

    return render_template(
        'crm/lead_detail.html',
        lead=lead,
        events=events,
        top_products=top_products,
        stages=STAGES,
        tracking_link=tracking_link,
        store_base_url=store_url
    )

@leads_bp.route('/leads/<int:lead_id>/update-stage', methods=['POST'])
@crm_login_required
def update_stage(lead_id):
    lead = B2BLead.query.get_or_404(lead_id)
    new_stage = request.form.get('stage')
    call_notes = request.form.get('call_notes', '').strip()

    if new_stage in [s[0] for s in STAGES]:
        old_stage = lead.stage
        lead.stage = new_stage
        
        if new_stage == 'contacted':
            lead.update_score(15, 'Sales phone contact established')
        elif new_stage == 'warm_discussion':
            lead.update_score(25, 'In budget/sampling discussion')

        if call_notes:
            timestamp = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
            lead.notes = f"[{timestamp} - Stage: {new_stage.title()}]\n{call_notes}\n\n" + (lead.notes or '')

        db.session.commit()
        flash(f'Lead status updated to {new_stage.replace("_", " ").title()}!', 'success')

    return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

@leads_bp.route('/leads/<int:lead_id>/convert', methods=['POST'])
@crm_login_required
def convert_to_client(lead_id):
    """
    1-Click Conversion: Transforms a prospect B2BLead into an active corporate B2BClient.
    Immediately makes the client available in the B2B Operations Deck for quotation and order handling.
    """
    lead = B2BLead.query.get_or_404(lead_id)

    if lead.converted_client_id:
        flash('This lead has already been converted to an active corporate client.', 'info')
        return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

    # Check if a client with this phone or email already exists
    existing_client = None
    if lead.phone:
        existing_client = B2BClient.query.filter_by(phone=lead.phone).first()
    if not existing_client and lead.email:
        existing_client = B2BClient.query.filter_by(email=lead.email).first()

    if existing_client:
        client = existing_client
        flash(f'Linked to existing corporate client "{client.company_name}".', 'info')
    else:
        client = B2BClient(
            company_name=lead.company_name,
            contact_name=lead.contact_name,
            phone=lead.phone or "Not Provided",
            email=lead.email
        )
        db.session.add(client)
        db.session.flush()

    lead.converted_client_id = client.id
    lead.stage = 'converted'
    lead.update_score(50, 'Converted to Active Corporate Client')

    timestamp = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
    lead.notes = f"[{timestamp} CONVERTED TO CORPORATE CLIENT]\nTransferred to B2B Operations Deck (Client #{client.id}).\n\n" + (lead.notes or '')

    db.session.commit()

    flash(
        f'🎉 SUCCESS! "{lead.company_name}" has been converted to an active corporate client! '
        f'They are now accessible on the B2B Operations Deck for order quotations.',
        'success'
    )
    return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

@leads_bp.route('/leads/<int:lead_id>/add-note', methods=['POST'])
@crm_login_required
def add_note(lead_id):
    lead = B2BLead.query.get_or_404(lead_id)
    note_text = request.form.get('note', '').strip()
    if note_text:
        timestamp = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
        lead.notes = f"[{timestamp} - Sales Note]\n{note_text}\n\n" + (lead.notes or '')
        lead.last_active_at = datetime.utcnow()
        db.session.commit()
        flash('Sales note added.', 'success')
    return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))
