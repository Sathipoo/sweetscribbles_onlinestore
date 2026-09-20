from flask import Blueprint, render_template, request, current_app
from extensions import db
from models.b2b import B2BClient, B2BOrder, B2BCommunicationLog
from models.b2b_crm import B2BLead, B2BEngagementEvent
from crm.routes.auth import crm_login_required

clients_bp = Blueprint('crm_clients', __name__)

@clients_bp.route('/clients')
@crm_login_required
def list_clients():
    search = request.args.get('q', '').strip()
    query = B2BClient.query.filter_by(is_archived=False)

    if search:
        search_fmt = f"%{search}%"
        query = query.filter(
            (B2BClient.company_name.ilike(search_fmt)) |
            (B2BClient.contact_name.ilike(search_fmt)) |
            (B2BClient.phone.ilike(search_fmt)) |
            (B2BClient.email.ilike(search_fmt))
        )

    clients = query.order_by(B2BClient.created_at.desc()).all()

    # Enrich clients with order metrics
    client_data = []
    for client in clients:
        orders = client.orders
        order_count = len(orders)
        total_spend = sum((o.quoted_price_per_box or 0) * (o.box_count or 0) for o in orders if o.quoted_price_per_box)
        
        # Check last engagement
        last_event = B2BEngagementEvent.query.filter_by(client_id=client.id).order_by(
            B2BEngagementEvent.created_at.desc()
        ).first()

        client_data.append({
            'client': client,
            'order_count': order_count,
            'total_spend': total_spend,
            'last_active': last_event.created_at if last_event else client.created_at
        })

    store_base_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')

    return render_template(
        'crm/clients_hub.html',
        clients=client_data,
        search=search,
        store_base_url=store_base_url
    )

@clients_bp.route('/clients/<int:client_id>')
@crm_login_required
def client_detail(client_id):
    client = B2BClient.query.get_or_404(client_id)
    orders = client.orders
    comm_logs = B2BCommunicationLog.query.filter_by(client_id=client.id).order_by(
        B2BCommunicationLog.created_at.desc()
    ).all()
    # Find associated lead
    lead = B2BLead.query.filter_by(converted_client_id=client.id).first()
    if not lead and client.phone:
        lead = B2BLead.query.filter(
            (B2BLead.phone == client.phone) | (B2BLead.phone.endswith(client.phone[-10:]))
        ).first()

    filter_cond = (B2BEngagementEvent.client_id == client.id)
    if lead:
        filter_cond = filter_cond | (B2BEngagementEvent.lead_id == lead.id)

    events = B2BEngagementEvent.query.filter(filter_cond).order_by(
        B2BEngagementEvent.created_at.desc()
    ).limit(50).all()

    store_base_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')

    return render_template(
        'crm/client_detail.html',
        client=client,
        orders=orders,
        comm_logs=comm_logs,
        events=events,
        store_base_url=store_base_url
    )

# --- Client POC Contacts Management ---
@clients_bp.route('/clients/<int:client_id>/contacts/add', methods=['POST'])
@crm_login_required
def add_client_contact(client_id):
    from models.b2b import B2BClientContact
    from utils.otp_utils import normalize_phone
    from flask import redirect, url_for, flash

    client = B2BClient.query.get_or_404(client_id)
    name = request.form.get('name', '').strip()
    designation = request.form.get('designation', '').strip()
    phone = normalize_phone(request.form.get('phone', '').strip())
    email = request.form.get('email', '').strip().lower()
    notes = request.form.get('notes', '').strip()
    is_primary = request.form.get('is_primary') == '1'

    if not name:
        flash('Contact person name is required.', 'danger')
        return redirect(url_for('crm_clients.client_detail', client_id=client.id))

    contact = B2BClientContact(
        client_id=client.id,
        name=name,
        designation=designation or None,
        phone=phone or None,
        email=email or None,
        notes=notes or None,
        is_primary=False
    )
    db.session.add(contact)
    db.session.flush()

    if is_primary or len(client.contacts) <= 1:
        client.set_primary_contact(contact.id)

    db.session.commit()
    flash(f'POC "{name}" successfully added to {client.company_name}.', 'success')
    return redirect(url_for('crm_clients.client_detail', client_id=client.id))

@clients_bp.route('/clients/<int:client_id>/contacts/<int:contact_id>/set-primary', methods=['POST'])
@crm_login_required
def set_primary_client_contact(client_id, contact_id):
    from models.b2b import B2BClientContact
    from flask import redirect, url_for, flash

    client = B2BClient.query.get_or_404(client_id)
    contact = B2BClientContact.query.filter_by(id=contact_id, client_id=client.id).first_or_404()

    client.set_primary_contact(contact.id)
    db.session.commit()

    flash(f'⭐ Primary POC switched to "{contact.name}" ({contact.designation or "Authorized POC"}). Client credentials & OTP login updated.', 'success')
    return redirect(url_for('crm_clients.client_detail', client_id=client.id))

@clients_bp.route('/clients/<int:client_id>/contacts/<int:contact_id>/delete', methods=['POST'])
@crm_login_required
def delete_client_contact(client_id, contact_id):
    from models.b2b import B2BClientContact
    from flask import redirect, url_for, flash

    client = B2BClient.query.get_or_404(client_id)
    contact = B2BClientContact.query.filter_by(id=contact_id, client_id=client.id).first_or_404()

    if contact.is_primary and len(client.contacts) > 1:
        flash('Cannot delete the primary POC. Please designate another contact as primary first.', 'warning')
        return redirect(url_for('crm_clients.client_detail', client_id=client.id))

    db.session.delete(contact)
    db.session.commit()
    flash(f'Contact "{contact.name}" removed.', 'info')
    return redirect(url_for('crm_clients.client_detail', client_id=client.id))
