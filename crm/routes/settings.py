from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from extensions import db
from models.b2b_crm import CRMLeadOwner, B2BLead, CRMEmailTemplate
from crm.routes.auth import crm_login_required

settings_bp = Blueprint('crm_settings', __name__, url_prefix='/settings')


def ensure_lead_owners_seeded():
    """
    Ensures baseline sales team members exist in the CRM database.
    Seeds default owners and any distinct owners already referenced in b2b_leads.
    """
    try:
        # Create table if not already created
        db.create_all()

        existing_count = CRMLeadOwner.query.count()
        if existing_count == 0:
            default_members = [
                {
                    'name': 'Vishnu Govind',
                    'email': 'vishnu.govind@pikachooz.com',
                    'phone': '+91 98450 11223',
                    'role': 'Head of Outreach & Sales'
                },
                {
                    'name': 'Pooja Sathish',
                    'email': 'pooja@sweetscribbles.com',
                    'phone': '+91 80887 83044',
                    'role': 'Artisanal Gifting Director'
                },
                {
                    'name': 'Sales Operations',
                    'email': 'sales@sweetscribbles.com',
                    'phone': '',
                    'role': 'Inbound & SDR Desk'
                },
                {
                    'name': 'Sathish Kumar',
                    'email': 'sathish@pikachooz.com',
                    'phone': '',
                    'role': 'Executive Administrator'
                }
            ]

            seeded_names = set()
            for m in default_members:
                owner = CRMLeadOwner(
                    name=m['name'],
                    email=m['email'],
                    phone=m['phone'],
                    role=m['role'],
                    is_active=True
                )
                db.session.add(owner)
                seeded_names.add(m['name'])

            # Pull any distinct assigned_to values from existing leads
            legacy_owners = [r[0] for r in db.session.query(B2BLead.assigned_to).distinct().all() if r[0]]
            for name in legacy_owners:
                clean_name = name.strip()
                if clean_name and clean_name not in seeded_names:
                    owner = CRMLeadOwner(
                        name=clean_name,
                        role='Sales Representative',
                        is_active=True
                    )
                    db.session.add(owner)
                    seeded_names.add(clean_name)

            db.session.commit()
    except Exception as e:
        db.session.rollback()


@settings_bp.route('/')
@crm_login_required
def index():
    return redirect(url_for('crm_settings.lead_owners'))


@settings_bp.route('/lead-owners')
@crm_login_required
def lead_owners():
    """
    Settings Dashboard: Lead Owners & Team Management.
    Lists team members, assigned lead counts, and allows adding/editing owners.
    """
    ensure_lead_owners_seeded()

    owners = CRMLeadOwner.query.order_by(CRMLeadOwner.is_active.desc(), CRMLeadOwner.name.asc()).all()

    total_owners = len(owners)
    active_owners = sum(1 for o in owners if o.is_active)
    total_assigned_leads = db.session.query(B2BLead).filter(B2BLead.assigned_to.isnot(None), B2BLead.assigned_to != '').count()
    unassigned_leads = db.session.query(B2BLead).filter((B2BLead.assigned_to.is_(None)) | (B2BLead.assigned_to == '')).count()

    total_templates = CRMEmailTemplate.query.filter_by(is_active=True).count()

    # Pre-calculate assigned lead counts per owner for fast template rendering
    lead_counts_raw = db.session.query(B2BLead.assigned_to, db.func.count(B2BLead.id)).group_by(B2BLead.assigned_to).all()
    owner_lead_counts = {r[0]: r[1] for r in lead_counts_raw if r[0]}

    return render_template(
        'crm/settings/lead_owners.html',
        owners=owners,
        owner_lead_counts=owner_lead_counts,
        total_owners=total_owners,
        active_owners=active_owners,
        total_assigned_leads=total_assigned_leads,
        unassigned_leads=unassigned_leads,
        total_templates=total_templates,
        active_settings_tab='lead_owners'
    )


@settings_bp.route('/lead-owners/add', methods=['POST'])
@crm_login_required
def add_lead_owner():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    role = request.form.get('role', 'Sales Representative').strip()

    if not name:
        flash('Please enter the team member / lead owner name.', 'danger')
        return redirect(url_for('crm_settings.lead_owners'))

    existing = CRMLeadOwner.query.filter(db.func.lower(CRMLeadOwner.name) == name.lower()).first()
    if existing:
        flash(f'A lead owner with name "{name}" already exists.', 'warning')
        return redirect(url_for('crm_settings.lead_owners'))

    new_owner = CRMLeadOwner(
        name=name,
        email=email or None,
        phone=phone or None,
        role=role or 'Sales Representative',
        is_active=True
    )
    db.session.add(new_owner)
    db.session.commit()

    flash(f'🎉 Lead Owner "{name}" added successfully and is now available for lead assignments!', 'success')
    return redirect(url_for('crm_settings.lead_owners'))


@settings_bp.route('/lead-owners/<int:owner_id>/edit', methods=['POST'])
@crm_login_required
def edit_lead_owner(owner_id):
    owner = CRMLeadOwner.query.get_or_404(owner_id)
    new_name = request.form.get('name', '').strip()
    new_email = request.form.get('email', '').strip()
    new_phone = request.form.get('phone', '').strip()
    new_role = request.form.get('role', '').strip()
    update_assigned_leads = request.form.get('update_assigned_leads') == '1'

    if not new_name:
        flash('Lead owner name cannot be empty.', 'danger')
        return redirect(url_for('crm_settings.lead_owners'))

    old_name = owner.name
    if new_name.lower() != old_name.lower():
        duplicate = CRMLeadOwner.query.filter(
            db.func.lower(CRMLeadOwner.name) == new_name.lower(),
            CRMLeadOwner.id != owner.id
        ).first()
        if duplicate:
            flash(f'Another lead owner already exists with the name "{new_name}".', 'danger')
            return redirect(url_for('crm_settings.lead_owners'))

    owner.name = new_name
    owner.email = new_email or None
    owner.phone = new_phone or None
    owner.role = new_role or 'Sales Representative'
    owner.updated_at = datetime.utcnow()

    # If name changed, optionally update all existing leads assigned to old name
    if old_name != new_name and update_assigned_leads:
        B2BLead.query.filter_by(assigned_to=old_name).update({'assigned_to': new_name})

    db.session.commit()
    flash(f'Lead owner "{new_name}" details updated successfully.', 'success')
    return redirect(url_for('crm_settings.lead_owners'))


@settings_bp.route('/lead-owners/<int:owner_id>/toggle', methods=['POST'])
@crm_login_required
def toggle_lead_owner(owner_id):
    owner = CRMLeadOwner.query.get_or_404(owner_id)
    owner.is_active = not owner.is_active
    owner.updated_at = datetime.utcnow()
    db.session.commit()

    status_str = 'activated' if owner.is_active else 'deactivated'
    flash(f'Lead owner "{owner.name}" has been {status_str}.', 'info')
    return redirect(url_for('crm_settings.lead_owners'))
