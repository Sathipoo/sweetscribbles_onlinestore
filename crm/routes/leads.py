import csv
import io
import re
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
    stage_filter = request.args.get('stage', '').strip()
    if stage_filter == 'all':
        stage_filter = ''
    source_filter = request.args.get('source')
    search = request.args.get('q', '').strip()
    hot_only = request.args.get('hot') == '1'
    view_mode = request.args.get('view', 'kanban')  # 'kanban' or 'list'
    sort = request.args.get('sort', 'date_modified_desc').strip()

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
            (B2BLead.lead_source.ilike(search_fmt)) |
            (B2BLead.assigned_to.ilike(search_fmt))
        )

    # Lead Sorting Logic (Ascending and Descending for Name, Date Modified, Date Created)
    if sort == 'name_asc':
        query = query.order_by(B2BLead.company_name.asc(), B2BLead.contact_name.asc())
    elif sort == 'name_desc':
        query = query.order_by(B2BLead.company_name.desc(), B2BLead.contact_name.desc())
    elif sort == 'date_created_asc':
        query = query.order_by(B2BLead.created_at.asc())
    elif sort == 'date_created_desc':
        query = query.order_by(B2BLead.created_at.desc())
    elif sort == 'date_modified_asc':
        query = query.order_by(B2BLead.updated_at.asc().nullslast(), B2BLead.created_at.asc())
    elif sort == 'date_modified_desc':
        query = query.order_by(B2BLead.updated_at.desc().nullslast(), B2BLead.created_at.desc())
    else:
        sort = 'date_modified_desc'
        query = query.order_by(B2BLead.updated_at.desc().nullslast(), B2BLead.created_at.desc())

    all_leads = query.all()

    # Bucket leads for Kanban view across all 11 stages
    kanban = {stage[0]: [] for stage in STAGES}
    for lead in all_leads:
        st = lead.stage if lead.stage in kanban else 'fresh_lead'
        kanban[st].append(lead)

    # Calculate stage counts across the whole database for quick-nav badges
    stage_counts_raw = db.session.query(B2BLead.stage, db.func.count(B2BLead.id)).group_by(B2BLead.stage).all()
    stage_counts = {r[0]: r[1] for r in stage_counts_raw if r[0]}
    total_leads_count = B2BLead.query.count()

    # Distinct sources for source filtering
    db_sources = [r[0] for r in db.session.query(B2BLead.lead_source).distinct().all() if r[0]]
    default_sources = [
        'LinkedIn', 'Instagram', 'Cold Calling', 'Inbound Form',
        'Website', 'WhatsApp', 'Referral', 'Event / Exhibition',
        'Outbound Cold List', 'CSV Import'
    ]
    all_sources = sorted(list(set(db_sources + default_sources)))

    # Team members and known lead owners for assignment
    db_owners = [r[0] for r in db.session.query(B2BLead.assigned_to).distinct().all() if r[0]]
    default_owners = ['Vishnu Govind', 'Pooja Sathish', 'Sales Operations', 'Sathish Kumar']
    all_owners = sorted(list(set(default_owners + db_owners)))

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
        sort=sort,
        stage_counts=stage_counts,
        total_leads_count=total_leads_count,
        owners=all_owners,
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

def _clean_import_phone(phone_str, contact_str=""):
    if not phone_str and not contact_str:
        return ""
    combined = f"{phone_str} {contact_str}"
    
    # 1. 5+5 digit mobile pattern e.g. 81405 60627, 99640 04467, 91640 97687
    split5 = re.findall(r'\b([6-9]\d{4}\s*\d{5})\b', combined)
    if split5:
        d = re.sub(r'\D', '', split5[0])
        return f"+91{d}"
    
    # 2. 10-digit mobile starting with 6-9
    c10 = re.findall(r'\b([6-9]\d{9})\b', combined)
    if c10:
        return f"+91{c10[0]}"
    
    # 3. 12-digit mobile starting with 91
    c12 = re.findall(r'\b(91[6-9]\d{9})\b', combined)
    if c12:
        return f"+{c12[0]}"
        
    # 4. Landlines or standard formatting
    first_part = re.split(r'[/,]', phone_str)[0].strip() if phone_str else ""
    digits = "".join(c for c in first_part if c.isdigit())
    if len(digits) == 10:
        return f"+91{digits}"
    elif len(digits) == 12 and digits.startswith('91'):
        return f"+{digits}"
    elif len(digits) == 11 and digits.startswith('0'):
        return f"+91{digits[1:]}"
    elif len(digits) >= 8:
        return f"+91{digits}" if not digits.startswith('91') else f"+{digits}"
    
    return normalize_phone(first_part)

def _clean_import_email(email_str):
    if not email_str:
        return None, []
    emails = [re.sub(r'[^a-zA-Z0-9_.+-@]', '', e).strip().lower() for e in re.split(r'[;,]', email_str) if '@' in e and '.' in e]
    primary_email = emails[0] if emails else None
    extra_emails = emails[1:] if len(emails) > 1 else []
    return primary_email, extra_emails

def _clean_import_contact(contact_str, designation_str=""):
    if not contact_str or contact_str.strip() in ('-', 'NA', 'N/A', '--', '.', 'nil'):
        return "Authorized Representative"
    name = re.sub(r'(?:-|\b)(?:\+?91[\s-]?)?[6-9]\d{9}\b', '', contact_str)
    name = re.sub(r'[©\d:]+', '', name)
    if ',' in name and designation_str:
        name = name.split(',')[0]
    name = name.strip(' -©,').strip()
    return name if name else "Authorized Representative"

def _extract_import_city(address_str):
    if not address_str:
        return "Bangalore"
    addr_lower = address_str.lower()
    cities = [
        'bangalore', 'bengaluru', 'mumbai', 'delhi', 'new delhi', 'hyderabad',
        'chennai', 'pune', 'kolkata', 'ahmedabad', 'gurgaon', 'gurugram',
        'noida', 'mysore', 'mysuru', 'coimbatore', 'kochi', 'jaipur', 'surat'
    ]
    for c in cities:
        if c in addr_lower:
            return 'Bangalore' if c in ('bangalore', 'bengaluru') else c.title()
    return "Bangalore"

@leads_bp.route('/leads/import', methods=['POST'])
@crm_login_required
def import_leads():
    """
    Bulk import leads via CSV file upload or pasted multi-line text.
    Supports marketing template format:
    Company Name, contact_type, Contact Person, Phone, Email, Designation, Address, Lead Stages (Source)
    as well as legacy / flexible formats.
    Automatically links multi-POC rows into Primary and Secondary POC contacts,
    and initializes all leads to 'fresh_lead' stage (ignoring the leadstages column for pipeline stage).
    """
    pasted_data = request.form.get('raw_data', '').strip()
    file = request.files.get('csv_file')
    default_source = request.form.get('lead_source', 'Marketing Import').strip() or 'Marketing Import'

    raw_text = ""
    if file and file.filename:
        try:
            raw_text = file.stream.read().decode("utf-8-sig", errors="ignore")
        except Exception as e:
            flash(f'Error reading CSV file: {e}', 'danger')
            return redirect(url_for('crm_leads.list_leads'))
    elif pasted_data:
        raw_text = pasted_data

    if not raw_text.strip():
        flash('No valid lead data provided for import.', 'warning')
        return redirect(url_for('crm_leads.list_leads'))

    # Detect delimiter: tab or comma
    first_non_empty_line = next((l for l in raw_text.splitlines() if l.strip()), '')
    delimiter = '\t' if '\t' in first_non_empty_line and ',' not in first_non_empty_line else ','

    stream = io.StringIO(raw_text)
    reader = csv.reader(stream, delimiter=delimiter)
    rows = [r for r in reader if r and any(cell.strip() for cell in r)]

    if not rows:
        flash('No valid data rows found to import.', 'warning')
        return redirect(url_for('crm_leads.list_leads'))

    # Inspect first row for column headers
    col_map = {
        'company': 0,
        'contact_type': None,
        'contact': 1,
        'phone': 2,
        'email': 3,
        'designation': 4,
        'address': 5,
        'source': 6
    }

    first_row = [c.strip().lower() for c in rows[0]]
    has_header = any('company' in c for c in first_row)

    if has_header:
        for idx, h in enumerate(first_row):
            if 'company' in h:
                col_map['company'] = idx
            elif 'type' in h or 'poc_type' in h:
                col_map['contact_type'] = idx
            elif 'contact' in h or 'person' in h or 'name' in h:
                if col_map['contact'] is None or 'person' in h or 'contact' in h:
                    col_map['contact'] = idx
            elif 'phone' in h or 'mobile' in h or 'tel' in h:
                col_map['phone'] = idx
            elif 'email' in h or 'mail' in h:
                col_map['email'] = idx
            elif 'designation' in h or 'role' in h:
                col_map['designation'] = idx
            elif 'address' in h or 'location' in h:
                col_map['address'] = idx
            elif 'city' in h:
                col_map['city'] = idx
            elif 'stage' in h or 'stages' in h or 'source' in h:
                col_map['source'] = idx
        data_rows = rows[1:]
    else:
        # If no header, check number of columns
        if len(rows[0]) >= 8:
            col_map = {
                'company': 0,
                'contact_type': 1,
                'contact': 2,
                'phone': 3,
                'email': 4,
                'designation': 5,
                'address': 6,
                'source': 7
            }
        data_rows = rows

    new_leads_count = 0
    added_pocs_count = 0
    batch_companies = {}

    for row in data_rows:
        if not row or not any(row):
            continue

        def get_val(key):
            idx = col_map.get(key)
            if idx is not None and idx < len(row):
                return row[idx].strip()
            return ""

        company = get_val('company')
        if not company or company.upper() in ('NA', 'N/A', '--', 'NONE', 'NIL'):
            continue

        contact_type = get_val('contact_type').lower() if col_map.get('contact_type') is not None else ''
        contact_raw = get_val('contact')
        designation_raw = get_val('designation') or None
        phone_raw = get_val('phone')
        email_raw = get_val('email')
        address_raw = get_val('address') or None
        source_raw = get_val('source')

        contact_name = _clean_import_contact(contact_raw, designation_raw)
        phone = _clean_import_phone(phone_raw, contact_raw)
        email, extra_emails = _clean_import_email(email_raw)
        city = get_val('city') if col_map.get('city') is not None else None
        if not city and address_raw:
            city = _extract_import_city(address_raw)
        elif not city:
            city = "Bangalore"

        # The marketing sheet has list/segment name under "Lead Stages" or "source"
        # User specified: "ignore the leadstages column mentioend in the csv. and we have the primary conetact and poc contact marked with source."
        row_source = source_raw if source_raw else default_source

        comp_key = company.strip().lower()

        # Determine if this row is intended as Primary or Secondary POC
        # If contact_type is specified: 'primary' -> True, 'poc...' -> False
        # If not specified: first occurrence is Primary, subsequent are Secondary
        is_row_primary = (contact_type == 'primary') or (not contact_type and comp_key not in batch_companies)

        # Check if company was already encountered in this batch or in DB
        lead = batch_companies.get(comp_key)
        if not lead:
            lead = B2BLead.query.filter(db.func.lower(B2BLead.company_name) == comp_key).first()
            if lead:
                batch_companies[comp_key] = lead

        if not lead:
            # Create NEW Lead
            lead = B2BLead(
                company_name=company[:150],
                contact_name=contact_name[:100],
                phone=phone[:20] if phone else None,
                email=email[:120] if email else None,
                designation=designation_raw[:100] if designation_raw else None,
                city=city[:100] if city else None,
                location=address_raw[:255] if address_raw else None,
                lead_source=row_source[:50],
                tags=row_source[:255] if row_source else None,
                stage='fresh_lead',  # Always initialize to Fresh Lead as requested
                priority_score=10
            )
            db.session.add(lead)
            db.session.flush()
            batch_companies[comp_key] = lead
            new_leads_count += 1

            # Create Primary Contact
            poc_notes = f"Primary Account Owner | Source: {row_source}"
            if extra_emails:
                poc_notes += f" | Extra emails: {', '.join(extra_emails)}"

            primary_contact = B2BLeadContact(
                lead_id=lead.id,
                name=contact_name[:100],
                designation=designation_raw[:100] if designation_raw else None,
                phone=phone[:20] if phone else None,
                email=email[:120] if email else None,
                is_primary=True,
                notes=poc_notes
            )
            db.session.add(primary_contact)
        else:
            # Existing lead: Add as corporate POC contact
            # Check if this contact (same name & phone) already exists under this lead
            existing_poc = B2BLeadContact.query.filter_by(lead_id=lead.id, name=contact_name[:100], phone=phone[:20] if phone else None).first()
            if not existing_poc:
                type_label = contact_type.upper() if contact_type else "POC"
                poc_notes = f"{type_label} | Source: {row_source}"
                if extra_emails:
                    poc_notes += f" | Extra emails: {', '.join(extra_emails)}"

                poc = B2BLeadContact(
                    lead_id=lead.id,
                    name=contact_name[:100],
                    designation=designation_raw[:100] if designation_raw else None,
                    phone=phone[:20] if phone else None,
                    email=email[:120] if email else None,
                    is_primary=False,
                    notes=poc_notes
                )
                db.session.add(poc)
                added_pocs_count += 1

            # Enrich main lead if it was missing phone, email, or location
            if not lead.phone and phone:
                lead.phone = phone[:20]
            if not lead.email and email:
                lead.email = email[:120]
            if not lead.location and address_raw:
                lead.location = address_raw[:255]
            if row_source and row_source not in (lead.tags or ''):
                new_tags = f"{lead.tags}, {row_source}" if lead.tags else row_source
                lead.tags = new_tags[:255]

    try:
        db.session.commit()
        flash(f"Successfully processed import: Created {new_leads_count} prospect leads and linked {added_pocs_count} corporate POC contacts across company profiles (Default Source: {default_source})!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error saving imported leads: {e}", "danger")

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

@leads_bp.route('/leads/bulk-action', methods=['POST'])
@crm_login_required
def bulk_action():
    """
    Executes bulk actions across selected leads:
    - 'change_stage': Updates lead.stage, updates updated_at, appends audit note, adjusts priority score.
    - 'change_owner': Updates lead.assigned_to, updates updated_at, appends audit note.
    Returns JSON with updated lead states and stage counts for instant client-side UI reflection without reload.
    """
    data = request.get_json(silent=True) or request.form
    action = (data.get('action') or '').strip()
    raw_ids = data.get('lead_ids', [])

    if isinstance(raw_ids, str):
        try:
            raw_ids = json.loads(raw_ids)
        except Exception:
            raw_ids = [int(i.strip()) for i in raw_ids.split(',') if i.strip().isdigit()]
    elif isinstance(raw_ids, list):
        raw_ids = [int(i) for i in raw_ids if str(i).isdigit()]

    if not raw_ids:
        return jsonify({'success': False, 'message': 'Please select at least one lead.'}), 400

    leads = B2BLead.query.filter(B2BLead.id.in_(raw_ids)).all()
    if not leads:
        return jsonify({'success': False, 'message': 'No matching leads found.'}), 404

    now = datetime.utcnow()
    timestamp_str = now.strftime("%d %b %Y, %I:%M %p")

    if action == 'change_stage':
        new_stage = (data.get('new_stage') or data.get('stage') or '').strip()
        valid_stages = dict([(s[0], s[1]) for s in STAGES])
        if new_stage not in valid_stages:
            return jsonify({'success': False, 'message': f'Invalid stage: {new_stage}'}), 400

        stage_label = valid_stages[new_stage]
        for lead in leads:
            old_stage = lead.stage
            lead.stage = new_stage
            lead.updated_at = now
            if new_stage == 'meeting_scheduled':
                lead.update_score(30, 'Meeting scheduled (bulk)')
            elif new_stage == 'qualified':
                lead.update_score(40, 'Qualified prospect (bulk)')
            elif new_stage == 'prospect':
                lead.update_score(20, 'Prospect engaged (bulk)')
            elif new_stage == 'converted':
                lead.update_score(50, 'Converted to client (bulk)')

            audit_entry = f"[{timestamp_str} - Bulk Action] Stage updated from '{old_stage}' to '{stage_label}'\n"
            lead.notes = audit_entry + (lead.notes or '')

        db.session.commit()

        # Recalculate stage counts across the whole database
        stage_counts_raw = db.session.query(B2BLead.stage, db.func.count(B2BLead.id)).group_by(B2BLead.stage).all()
        stage_counts = {r[0]: r[1] for r in stage_counts_raw if r[0]}

        updated_leads = []
        for l in leads:
            updated_leads.append({
                'id': l.id,
                'stage': l.stage,
                'stage_display': l.stage_display,
                'stage_badge_class': l.stage_badge_class,
                'updated_at_iso': l.updated_at.isoformat() if l.updated_at else now.isoformat(),
                'updated_at_display': 'Just now'
            })

        return jsonify({
            'success': True,
            'action': 'change_stage',
            'count': len(leads),
            'new_stage': new_stage,
            'new_stage_label': stage_label,
            'message': f"Successfully moved {len(leads)} lead{'s' if len(leads) > 1 else ''} to '{stage_label}'.",
            'updated_leads': updated_leads,
            'stage_counts': stage_counts
        })

    elif action == 'change_owner':
        new_owner = (data.get('assigned_to') or data.get('owner') or '').strip()
        display_owner = new_owner or 'Unassigned'
        for lead in leads:
            old_owner = lead.assigned_to or 'Unassigned'
            lead.assigned_to = new_owner or None
            lead.updated_at = now
            audit_entry = f"[{timestamp_str} - Bulk Action] Owner reassigned from '{old_owner}' to '{display_owner}'\n"
            lead.notes = audit_entry + (lead.notes or '')

        db.session.commit()

        updated_leads = []
        for l in leads:
            updated_leads.append({
                'id': l.id,
                'assigned_to': l.assigned_to or 'Unassigned',
                'updated_at_iso': l.updated_at.isoformat() if l.updated_at else now.isoformat(),
                'updated_at_display': 'Just now'
            })

        return jsonify({
            'success': True,
            'action': 'change_owner',
            'count': len(leads),
            'assigned_to': display_owner,
            'message': f"Successfully assigned {len(leads)} lead{'s' if len(leads) > 1 else ''} to '{display_owner}'.",
            'updated_leads': updated_leads
        })

    else:
        return jsonify({'success': False, 'message': f'Unknown action: {action}'}), 400

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
    assigned_to = request.form.get('assigned_to', '').strip()

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
    if 'assigned_to' in request.form:
        lead.assigned_to = assigned_to or None

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

    db_owners = [r[0] for r in db.session.query(B2BLead.assigned_to).distinct().all() if r[0]]
    default_owners = ['Vishnu Govind', 'Pooja Sathish', 'Sales Operations', 'Sathish Kumar']
    all_owners = sorted(list(set(default_owners + db_owners)))

    return render_template(
        'crm/lead_detail.html',
        lead=lead,
        events=events,
        top_products=top_products,
        stages=STAGES,
        sources=all_sources,
        owners=all_owners,
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
