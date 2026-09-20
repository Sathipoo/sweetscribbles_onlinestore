import csv
import io
import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, Response
from extensions import db
from models.b2b import B2BClient, B2BClientContact
from models.b2b_crm import B2BLead, B2BEngagementEvent, CRMEmailTemplate, B2BLeadContact
from crm.routes.auth import crm_login_required
from utils.otp_utils import normalize_phone
from utils.email_utils import send_crm_campaign_email, DEFAULT_CC_EMAIL

leads_bp = Blueprint('crm_leads', __name__)

# 11 Marketing Lifecycle Funnel Stages
STAGES = [
    ('fresh_lead', '1. Fresh Lead', 'secondary'),
    ('dnp', '2. DNP (Did Not Pick)', 'warning'),
    ('call_back', '3. Call Back', 'info'),
    ('prospect', '4. Prospect', 'primary'),
    ('meeting_scheduled', '5. Meeting Scheduled', 'dark'),
    ('qualified', '6. Qualified', 'danger'),
    ('converted', '7. Converted to Client', 'success'),
    ('existing_cx', '8. Existing CX', 'info'),
    ('deferred_interest', '9. Deferred Interest', 'secondary'),
    ('not_interested', '10. Not Interested', 'danger'),
    ('invalid', '11. Invalid', 'dark'),
]

@leads_bp.route('/leads')
@crm_login_required
def list_leads():
    stage_filter = request.args.get('stage')
    source_filter = request.args.get('source')
    search = request.args.get('q', '').strip()
    hot_only = request.args.get('hot') == '1'
    view_mode = request.args.get('view', 'kanban')  # 'kanban' or 'list'

    query = B2BLead.query

    if stage_filter:
        query = query.filter(B2BLead.stage == stage_filter)

    if source_filter:
        query = query.filter(B2BLead.lead_source == source_filter)

    if hot_only:
        query = query.filter((B2BLead.is_hot == True) | (B2BLead.priority_score >= 60))

    if search:
        search_fmt = f"%{search}%"
        query = query.filter(
            (B2BLead.company_name.ilike(search_fmt)) |
            (B2BLead.contact_name.ilike(search_fmt)) |
            (B2BLead.phone.ilike(search_fmt)) |
            (B2BLead.email.ilike(search_fmt)) |
            (B2BLead.city.ilike(search_fmt)) |
            (B2BLead.location.ilike(search_fmt)) |
            (B2BLead.lead_source.ilike(search_fmt))
        )

    all_leads = query.order_by(B2BLead.priority_score.desc(), B2BLead.created_at.desc()).all()

    # Bucket leads for Kanban view across all 11 stages
    kanban = {stage[0]: [] for stage in STAGES}
    for lead in all_leads:
        st = lead.stage if lead.stage in kanban else 'fresh_lead'
        kanban[st].append(lead)

    # Distinct sources for source filtering
    db_sources = [r[0] for r in db.session.query(B2BLead.lead_source).distinct().all() if r[0]]
    default_sources = [
        'LinkedIn', 'Instagram', 'Cold Calling', 'Inbound Form',
        'Website', 'WhatsApp', 'Referral', 'Event / Exhibition',
        'Outbound Cold List', 'CSV Import'
    ]
    all_sources = sorted(list(set(db_sources + default_sources)))

    # Fetch active saved email templates for Bulk Email modal
    saved_templates = CRMEmailTemplate.query.filter_by(is_active=True).order_by(CRMEmailTemplate.updated_at.desc()).all()

    return render_template(
        'crm/leads.html',
        leads=all_leads,
        kanban=kanban,
        stages=STAGES,
        sources=all_sources,
        saved_templates=saved_templates,
        current_stage=stage_filter,
        current_source=source_filter,
        search=search,
        hot_only=hot_only,
        view_mode=view_mode,
        default_cc=DEFAULT_CC_EMAIL,
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
    location = request.form.get('location', '').strip()
    industry = request.form.get('industry', '').strip()
    notes = request.form.get('notes', '').strip()
    lead_source = request.form.get('lead_source', 'Direct Outbound').strip()
    stage = request.form.get('stage', 'fresh_lead').strip()
    tags = request.form.get('tags', '').strip()

    if not company_name or not contact_name:
        flash('Company name and contact person are required.', 'danger')
        return redirect(url_for('crm_leads.list_leads'))

    valid_stages = [s[0] for s in STAGES]
    if stage not in valid_stages:
        stage = 'fresh_lead'

    lead = B2BLead(
        company_name=company_name,
        contact_name=contact_name,
        phone=phone or None,
        email=email or None,
        designation=designation or None,
        city=city or None,
        location=location or None,
        industry=industry or None,
        lead_source=lead_source or 'Direct Outbound',
        stage=stage,
        tags=tags or None,
        notes=notes or None,
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
    Format: Company Name, Contact Name, Phone, Email, Designation, City, Source (optional)
    """
    pasted_data = request.form.get('raw_data', '').strip()
    file = request.files.get('csv_file')
    default_source = request.form.get('lead_source', 'CSV Import').strip() or 'CSV Import'

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
        row_source = row[6].strip() if len(row) > 6 and row[6].strip() else default_source

        if not company or not contact:
            continue

        lead = B2BLead(
            company_name=company,
            contact_name=contact,
            phone=phone or None,
            email=email or None,
            designation=designation or None,
            city=city or None,
            lead_source=row_source,
            stage='fresh_lead',
            priority_score=10
        )
        db.session.add(lead)
        imported_count += 1

    db.session.commit()
    flash(f'Successfully imported {imported_count} corporate prospect leads under source "{default_source}"!', 'success')
    return redirect(url_for('crm_leads.list_leads'))

@leads_bp.route('/leads/export')
@crm_login_required
def export_leads():
    """
    Exports entire or filtered lead directory to Excel-compatible CSV with UTF-8 BOM.
    """
    stage_filter = request.args.get('stage')
    source_filter = request.args.get('source')
    search = request.args.get('q', '').strip()
    hot_only = request.args.get('hot') == '1'
    selected_ids = request.args.get('ids', '').strip()

    query = B2BLead.query

    if selected_ids:
        try:
            id_list = [int(i.strip()) for i in selected_ids.split(',') if i.strip()]
            query = query.filter(B2BLead.id.in_(id_list))
        except Exception:
            pass
    else:
        if stage_filter:
            query = query.filter(B2BLead.stage == stage_filter)
        if source_filter:
            query = query.filter(B2BLead.lead_source == source_filter)
        if hot_only:
            query = query.filter((B2BLead.is_hot == True) | (B2BLead.priority_score >= 60))
        if search:
            search_fmt = f"%{search}%"
            query = query.filter(
                (B2BLead.company_name.ilike(search_fmt)) |
                (B2BLead.contact_name.ilike(search_fmt)) |
                (B2BLead.phone.ilike(search_fmt)) |
                (B2BLead.email.ilike(search_fmt)) |
                (B2BLead.city.ilike(search_fmt))
            )

    leads = query.order_by(B2BLead.created_at.desc()).all()

    output = io.StringIO()
    # Write UTF-8 BOM so Excel opens with proper accents and formatting
    output.write('\ufeff')
    writer = csv.writer(output)

    # Header Row
    writer.writerow([
        'Lead ID', 'Company Name', 'Contact Person', 'Phone Number', 'Official Email',
        'Designation', 'City', 'Location / Address', 'Lead Source', 'Stage',
        'Intent Score', 'Is Hot Lead', 'Total Logins', 'First Login Date',
        'Last Login Date', 'Last Active Date', 'Converted Client ID', 'Created Date', 'Sales Notes'
    ])

    for l in leads:
        writer.writerow([
            l.id,
            l.company_name or '',
            l.contact_name or '',
            l.phone or '',
            l.email or '',
            l.designation or '',
            l.city or '',
            l.location or '',
            l.lead_source or '',
            l.stage_display,
            l.priority_score or 0,
            'Yes' if l.is_hot else 'No',
            l.login_count or 0,
            l.first_login_at.strftime('%Y-%m-%d %H:%M:%S') if l.first_login_at else '',
            l.last_login_at.strftime('%Y-%m-%d %H:%M:%S') if l.last_login_at else '',
            l.last_active_at.strftime('%Y-%m-%d %H:%M:%S') if l.last_active_at else '',
            l.converted_client_id or '',
            l.created_at.strftime('%Y-%m-%d %H:%M:%S') if l.created_at else '',
            (l.notes or '').replace('\n', ' -- ')
        ])

    csv_data = output.getvalue()
    filename = f"SweetScribbles_Leads_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"

    return Response(
        csv_data,
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )

@leads_bp.route('/leads/bulk-email', methods=['POST'])
@crm_login_required
def bulk_email():
    """
    Dispatches templated outreach or promotional emails in bulk to selected leads or stage filter.
    Performs live parameter substitution ({contact_name}, {company_name}, {city}, {outreach_link})
    and supports customizable CC recipients (always ensuring Vishnu.govind@pikachooz.com is present).
    """
    data = request.get_json(silent=True) or request.form
    lead_ids = data.get('lead_ids', [])
    if isinstance(lead_ids, str):
        try:
            lead_ids = json.loads(lead_ids)
        except Exception:
            lead_ids = [int(i.strip()) for i in lead_ids.split(',') if i.strip()]

    target_stage = (data.get('stage') or data.get('target_stage') or '').strip()
    target_source = (data.get('source') or data.get('target_source') or '').strip()
    subject = data.get('subject', '').strip()
    content_body = (data.get('body') or data.get('content_body') or '').strip()
    cta_text = data.get('cta_text', 'Explore Corporate Festive Hampers').strip()
    cta_url = data.get('cta_url', '').strip()
    include_outreach_link = str(data.get('include_outreach_link', 'true')).lower() in ['true', '1', 'yes']
    update_stage_to = (data.get('advance_stage') or data.get('update_stage_to') or '').strip()

    # Customizable CC recipients
    raw_cc = (data.get('cc_recipients') or data.get('cc_email') or '').strip()
    cc_list = []
    if raw_cc:
        cc_list = [c.strip() for c in raw_cc.split(',') if c.strip()]
    if DEFAULT_CC_EMAIL not in cc_list:
        cc_list.append(DEFAULT_CC_EMAIL)
    effective_cc = ", ".join(cc_list)

    if not subject or not content_body:
        return jsonify({'success': False, 'message': 'Email subject and message body are required.'}), 400

    query = B2BLead.query.filter(B2BLead.email.isnot(None), B2BLead.email != '')
    if lead_ids:
        query = query.filter(B2BLead.id.in_(lead_ids))
    else:
        if target_stage:
            query = query.filter(B2BLead.stage == target_stage)
        if target_source:
            query = query.filter(B2BLead.lead_source == target_source)

    targets = query.all()
    if not targets:
        return jsonify({'success': False, 'message': 'No leads with valid email addresses found in the selection.'}), 400

    store_base_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')
    fallback_cta_url = cta_url or f"{store_base_url}/b2b/hampers"

    sent_count = 0
    failed_count = 0

    for lead in targets:
        personal_link = f"{store_base_url}/b2b?trk={lead.tracking_token}"
        chosen_cta_url = personal_link if include_outreach_link else fallback_cta_url

        # Substitute variables
        body_rendered = content_body
        body_rendered = body_rendered.replace('{contact_name}', lead.contact_name or 'Corporate Partner')
        body_rendered = body_rendered.replace('{company_name}', lead.company_name or 'your organization')
        body_rendered = body_rendered.replace('{city}', lead.city or '')
        body_rendered = body_rendered.replace('{designation}', lead.designation or '')
        body_rendered = body_rendered.replace('{outreach_link}', personal_link)
        body_rendered = body_rendered.replace('\n', '<br>')

        subj_rendered = subject
        subj_rendered = subj_rendered.replace('{contact_name}', lead.contact_name or 'Corporate Partner')
        subj_rendered = subj_rendered.replace('{company_name}', lead.company_name or 'your organization')

        success, _ = send_crm_campaign_email(
            to_email=lead.email,
            subject=subj_rendered,
            recipient_name=lead.contact_name,
            content_html=body_rendered,
            cta_text=cta_text,
            cta_url=chosen_cta_url,
            cc_email=effective_cc
        )

        if success:
            sent_count += 1
            lead.update_score(15, f"Outreach email dispatched: {subj_rendered[:40]}")
            if update_stage_to and update_stage_to in [s[0] for s in STAGES]:
                lead.stage = update_stage_to
            elif lead.stage == 'fresh_lead':
                lead.stage = 'prospect'

            # Log sales note
            timestamp = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
            log_msg = f"[{timestamp} - Outbound Email Sent]\nSubject: {subj_rendered}\nCC: {effective_cc}\n"
            lead.notes = log_msg + (lead.notes or '')
        else:
            failed_count += 1

    db.session.commit()

    msg = f"Dispatched {sent_count} emails successfully! (Failed/Skipped: {failed_count}). CC recipients: {effective_cc}."
    return jsonify({
        'success': True,
        'sent_count': sent_count,
        'failed_count': failed_count,
        'message': msg
    })

# --- Lead Multiple POC Contacts Management ---
@leads_bp.route('/leads/<int:lead_id>/contacts/add', methods=['POST'])
@crm_login_required
def add_lead_contact(lead_id):
    lead = B2BLead.query.get_or_404(lead_id)
    name = request.form.get('name', '').strip()
    designation = request.form.get('designation', '').strip()
    phone = normalize_phone(request.form.get('phone', '').strip())
    email = request.form.get('email', '').strip().lower()
    notes = request.form.get('notes', '').strip()
    is_primary = request.form.get('is_primary') == '1'

    if not name:
        flash('Contact name is required.', 'danger')
        return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

    contact = B2BLeadContact(
        lead_id=lead.id,
        name=name,
        designation=designation or None,
        phone=phone or None,
        email=email or None,
        notes=notes or None,
        is_primary=False
    )
    db.session.add(contact)
    db.session.flush()

    if is_primary or len(lead.contacts) <= 1:
        lead.set_primary_contact(contact.id)

    db.session.commit()
    flash(f'Corporate contact "{name}" added to {lead.company_name}.', 'success')
    return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

@leads_bp.route('/leads/<int:lead_id>/contacts/<int:contact_id>/set-primary', methods=['POST'])
@crm_login_required
def set_primary_lead_contact(lead_id, contact_id):
    lead = B2BLead.query.get_or_404(lead_id)
    contact = B2BLeadContact.query.filter_by(id=contact_id, lead_id=lead.id).first_or_404()

    lead.set_primary_contact(contact.id)
    db.session.commit()

    flash(f'⭐ Primary POC switched to "{contact.name}" ({contact.designation or "Lead POC"}). Parent lead credentials synchronized.', 'success')
    return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

@leads_bp.route('/leads/<int:lead_id>/contacts/<int:contact_id>/delete', methods=['POST'])
@crm_login_required
def delete_lead_contact(lead_id, contact_id):
    lead = B2BLead.query.get_or_404(lead_id)
    contact = B2BLeadContact.query.filter_by(id=contact_id, lead_id=lead.id).first_or_404()

    if contact.is_primary and len(lead.contacts) > 1:
        flash('Cannot delete the primary POC. Please designate another contact as primary first.', 'warning')
        return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

    db.session.delete(contact)
    db.session.commit()
    flash(f'Contact "{contact.name}" removed.', 'info')
    return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

@leads_bp.route('/leads/<int:lead_id>/update-location', methods=['POST'])
@crm_login_required
def update_location(lead_id):
    lead = B2BLead.query.get_or_404(lead_id)
    location = request.form.get('location', '').strip()
    city = request.form.get('city', '').strip()
    tags = request.form.get('tags', '').strip()

    if location:
        lead.location = location
    if city:
        lead.city = city
    if tags:
        lead.tags = tags

    db.session.commit()
    flash(f'Location and details for "{lead.company_name}" updated!', 'success')
    return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

@leads_bp.route('/leads/<int:lead_id>/edit', methods=['POST'])
@crm_login_required
def edit_lead(lead_id):
    """
    Updates all primary prospect details (Company, Contact, Designation, Phone, Email, City, Location, Source, Tags).
    Synchronizes the primary POC contact record automatically.
    """
    lead = B2BLead.query.get_or_404(lead_id)

    company_name = request.form.get('company_name', '').strip()
    contact_name = request.form.get('contact_name', '').strip()
    designation = request.form.get('designation', '').strip()
    phone_raw = request.form.get('phone', '').strip()
    phone = normalize_phone(phone_raw) if phone_raw else None
    email = request.form.get('email', '').strip().lower()
    city = request.form.get('city', '').strip()
    location = request.form.get('location', '').strip()
    lead_source = request.form.get('lead_source', '').strip()
    tags = request.form.get('tags', '').strip()

    if not company_name or not contact_name:
        flash('Company name and contact person name are required.', 'danger')
        return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

    lead.company_name = company_name
    lead.contact_name = contact_name
    lead.designation = designation or None
    lead.phone = phone
    lead.email = email or None
    lead.city = city or None
    lead.location = location or None
    if lead_source:
        lead.lead_source = lead_source
    if tags is not None:
        lead.tags = tags

    # Synchronize primary contact record if present
    primary = lead.primary_contact
    if primary:
        primary.name = contact_name
        primary.designation = designation or None
        primary.phone = phone
        primary.email = email or None

    db.session.commit()
    flash(f'Prospect details for "{lead.company_name}" updated successfully!', 'success')
    return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))

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

    db_sources = [r[0] for r in db.session.query(B2BLead.lead_source).distinct().all() if r[0]]
    default_sources = [
        'LinkedIn Outreach', 'Instagram / Social', 'Cold Outreach', 'WhatsApp Campaign',
        'Referral / Network', 'Website Storefront / Organic', 'Event / Trade Expo',
        'Cold Calling', 'Inbound Form', 'CSV Import', 'Other'
    ]
    all_sources = sorted(list(set(db_sources + default_sources)))

    return render_template(
        'crm/lead_detail.html',
        lead=lead,
        events=events,
        top_products=top_products,
        stages=STAGES,
        sources=all_sources,
        tracking_link=tracking_link,
        store_base_url=store_url
    )

@leads_bp.route('/leads/<int:lead_id>/update-stage', methods=['POST'])
@crm_login_required
def update_stage(lead_id):
    lead = B2BLead.query.get_or_404(lead_id)
    new_stage = request.form.get('stage')
    call_notes = request.form.get('call_notes', '').strip()

    valid_stage_keys = [s[0] for s in STAGES]
    if new_stage in valid_stage_keys:
        old_stage = lead.stage
        lead.stage = new_stage
        
        if new_stage == 'meeting_scheduled':
            lead.update_score(30, 'Meeting scheduled with client')
        elif new_stage == 'qualified':
            lead.update_score(40, 'Budget and box volume qualified')
        elif new_stage == 'call_back':
            lead.update_score(10, 'Follow-up call back scheduled')
        elif new_stage == 'prospect':
            lead.update_score(20, 'Prospect engaged')
        elif new_stage == 'converted':
            lead.update_score(50, 'Converted to corporate client')

        if call_notes:
            timestamp = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
            lead.notes = f"[{timestamp} - Stage: {lead.stage_display}]\n{call_notes}\n\n" + (lead.notes or '')

        db.session.commit()
        flash(f'Lead status updated to {lead.stage_display}!', 'success')

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

    # Migrate lead POC contacts to client POC contacts
    for lc in lead.contacts:
        existing_cc = B2BClientContact.query.filter_by(client_id=client.id, name=lc.name).first()
        if not existing_cc:
            cc = B2BClientContact(
                client_id=client.id,
                name=lc.name,
                designation=lc.designation,
                phone=lc.phone,
                email=lc.email,
                is_primary=lc.is_primary,
                notes=lc.notes
            )
            db.session.add(cc)

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
    note_category = request.form.get('category', 'Sales Note').strip()
    if note_text:
        timestamp = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
        lead.notes = f"[{timestamp} - {note_category}]\n{note_text}\n\n" + (lead.notes or '')
        lead.last_active_at = datetime.utcnow()
        db.session.commit()
        flash('Sales note added successfully.', 'success')
    return redirect(url_for('crm_leads.lead_detail', lead_id=lead.id))
