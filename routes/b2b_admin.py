import os
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from extensions import db
from models.b2b import B2BClient, B2BOrder, B2BProduct, B2BProductImage, B2BProductShowcase, B2BTestimonial, B2BTestimonialImage
from utils.otp_utils import send_b2b_sms, normalize_phone
from utils.gcp_storage import upload_file

b2b_admin_bp = Blueprint('b2b_admin', __name__)

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin authentication required.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


# =========================================================================
# 1. B2B PIPELINE KANBAN DASHBOARD & ORDERS LIST
# =========================================================================
@b2b_admin_bp.route('/')
@b2b_admin_bp.route('/dashboard')
@admin_required
def dashboard():
    all_orders = B2BOrder.query.order_by(B2BOrder.updated_at.desc()).all()
    all_clients = B2BClient.query.order_by(B2BClient.company_name.asc()).all()
    all_products = B2BProduct.query.filter_by(is_active=True).all()

    pipeline_stages = ['enquiry', 'quotation_sent', 'advance_paid', 'design_review', 'details_locked', 'production', 'delivered', 'cancelled']
    pipeline = {s: [] for s in pipeline_stages}

    for order in all_orders:
        if order.stage in pipeline:
            pipeline[order.stage].append(order)

    active_orders = [o for o in all_orders if o.stage not in ('cancelled', 'delivered')]
    total_pipeline_value = sum((o.total_amount or 0.0) for o in active_orders)
    total_boxes_pipeline = sum((o.box_count or 0) for o in active_orders)
    delivered_revenue = sum((o.total_amount or 0.0) for o in all_orders if o.stage == 'delivered')

    return render_template(
        'admin/b2b/dashboard.html',
        pipeline=pipeline,
        all_orders=all_orders,
        all_clients=all_clients,
        all_products=all_products,
        total_pipeline_value=total_pipeline_value,
        total_boxes_pipeline=total_boxes_pipeline,
        delivered_revenue=delivered_revenue,
        boxes=all_products,
        clients=all_clients
    )



@b2b_admin_bp.route('/orders')
@admin_required
def orders():
    current_stage = request.args.get('stage')
    search_query = request.args.get('q', '').strip()

    query = B2BOrder.query

    if current_stage and current_stage in ('enquiry', 'quotation_sent', 'advance_paid', 'design_review', 'details_locked', 'production', 'delivered', 'cancelled'):
        query = query.filter_by(stage=current_stage)

    if search_query:
        query = query.join(B2BClient).filter(
            (B2BOrder.order_number.ilike(f'%{search_query}%')) |
            (B2BClient.company_name.ilike(f'%{search_query}%')) |
            (B2BClient.contact_name.ilike(f'%{search_query}%')) |
            (B2BClient.phone.ilike(f'%{search_query}%'))
        )

    all_orders = query.order_by(B2BOrder.created_at.desc()).all()

    # Stage Counts
    all_db_orders = B2BOrder.query.all()
    stage_counts = {
        'all': len(all_db_orders),
        'enquiry': sum(1 for o in all_db_orders if o.stage == 'enquiry'),
        'quotation_sent': sum(1 for o in all_db_orders if o.stage == 'quotation_sent'),
        'advance_paid': sum(1 for o in all_db_orders if o.stage == 'advance_paid'),
        'design_review': sum(1 for o in all_db_orders if o.stage == 'design_review'),
        'details_locked': sum(1 for o in all_db_orders if o.stage == 'details_locked'),
        'production': sum(1 for o in all_db_orders if o.stage == 'production'),
        'delivered': sum(1 for o in all_db_orders if o.stage == 'delivered'),
        'cancelled': sum(1 for o in all_db_orders if o.stage == 'cancelled'),
    }

    boxes = B2BProduct.query.filter_by(is_active=True).all()
    all_clients = B2BClient.query.order_by(B2BClient.company_name.asc()).all()

    return render_template(
        'admin/b2b/orders.html',
        orders=all_orders,
        current_stage=current_stage,
        search_query=search_query,
        stage_counts=stage_counts,
        boxes=boxes,
        clients=all_clients
    )


# =========================================================================
# 2. ORDER DETAILS & STAGE ACTION TRANSITIONS
# =========================================================================
@b2b_admin_bp.route('/orders/<int:order_id>')
@admin_required
def order_detail(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    boxes = B2BProduct.query.filter_by(is_active=True).all()
    return render_template('admin/b2b/order_detail.html', order=order, boxes=boxes)


@b2b_admin_bp.route('/orders/<int:order_id>/stage', methods=['POST'])
@admin_required
def update_stage(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    new_stage = request.form.get('stage')
    notes = request.form.get('notes', '').strip()

    valid_stages = ['enquiry', 'quotation_sent', 'advance_paid', 'design_review', 'details_locked', 'production', 'delivered', 'cancelled']
    if new_stage not in valid_stages:
        flash('Invalid stage selected.', 'danger')
        return redirect(url_for('b2b_admin.order_detail', order_id=order.id))

    old_stage = order.stage
    order.stage = new_stage

    if new_stage == 'delivered':
        order.delivered_at = datetime.utcnow()

    order.add_log(
        action_title=f"Stage changed to {order.get_stage_display()}",
        from_stage=old_stage,
        to_stage=new_stage,
        actor=f"{current_user.name} (Admin)",
        details=notes if notes else f"Updated stage via B2B Control Desk"
    )

    db.session.commit()

    # Trigger SMS notification if applicable
    if order.client and order.client.phone:
        if new_stage == 'advance_paid':
            send_b2b_sms(order.client.phone, 'confirmed', {
                'client_name': order.client.contact_name or order.client.company_name,
                'order_number': order.order_number,
                'box_count': str(order.box_count)
            })
        elif new_stage == 'design_review':
            send_b2b_sms(order.client.phone, 'design_ready', {
                'client_name': order.client.contact_name or order.client.company_name,
                'order_number': order.order_number
            })
        elif new_stage == 'production':
            send_b2b_sms(order.client.phone, 'production', {
                'client_name': order.client.contact_name or order.client.company_name,
                'order_number': order.order_number
            })
        elif new_stage == 'delivered':
            send_b2b_sms(order.client.phone, 'delivered', {
                'client_name': order.client.contact_name or order.client.company_name,
                'order_number': order.order_number
            })

    flash(f"Order #{order.order_number} moved to '{order.get_stage_display()}'.", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/mark-advance-paid', methods=['POST'])
@b2b_admin_bp.route('/orders/<int:order_id>/advance', methods=['POST'])
@admin_required
def mark_advance_paid(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    order.advance_paid = True
    order.advance_paid_at = datetime.utcnow()
    
    old_stage = order.stage
    if order.stage in ('enquiry', 'quotation_sent'):
        order.stage = 'advance_paid'
        order.add_log(
            action_title="50% Advance Confirmed & Order Locked",
            from_stage=old_stage,
            to_stage='advance_paid',
            actor=f"{current_user.name} (Admin)",
            details=f"Payment received: ₹{order.advance_amount_required:,.2f}"
        )
        if order.client and order.client.phone:
            send_b2b_sms(order.client.phone, 'confirmed', {
                'client_name': order.client.contact_name or order.client.company_name,
                'order_number': order.order_number,
                'box_count': str(order.box_count)
            })
    else:
        order.add_log(
            action_title="Advance Payment Marked as Paid",
            actor=f"{current_user.name} (Admin)",
            details=f"Payment received: ₹{order.advance_amount_required:,.2f}"
        )

    db.session.commit()
    flash(f"Advance payment for #{order.order_number} confirmed!", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/update-quote', methods=['POST'])
@admin_required
def update_quote(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    
    try:
        order.quoted_price_per_box = float(request.form.get('quoted_price_per_box', order.quoted_price_per_box))
    except (ValueError, TypeError):
        pass

    try:
        order.box_count = int(request.form.get('box_count', order.box_count))
    except (ValueError, TypeError):
        pass

    order.box_type = request.form.get('box_type', order.box_type)
    order.payment_link = request.form.get('payment_link', order.payment_link)
    order.eta_date = request.form.get('eta_date', order.eta_date)
    
    order.total_amount = order.box_count * order.quoted_price_per_box
    order.advance_amount_required = order.total_amount * 0.50

    if order.stage == 'enquiry':
        old_stage = order.stage
        order.stage = 'quotation_sent'
        order.add_log(
            action_title="Quotation Shared with Client",
            from_stage=old_stage,
            to_stage='quotation_sent',
            actor=f"{current_user.name} (Admin)",
            details=f"Quoted: ₹{order.quoted_price_per_box} per box for {order.box_count} boxes (Total: ₹{order.total_amount:,.2f})"
        )
    else:
        order.add_log(
            action_title="Quotation Values Updated",
            actor=f"{current_user.name} (Admin)",
            details=f"Updated Total: ₹{order.total_amount:,.2f}"
        )

    db.session.commit()
    flash(f"Quotation for #{order.order_number} updated successfully.", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/upload-proof', methods=['POST'])
@b2b_admin_bp.route('/orders/<int:order_id>/design-proof', methods=['POST'])
@admin_required
def upload_proof(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    
    proof_url = None
    if 'design_proof' in request.files:
        file = request.files['design_proof']
        if file and file.filename:
            try:
                proof_url = upload_file(file, file.filename, folder="b2b_designs")
            except Exception as e:
                flash(f"Upload error: {str(e)}", 'danger')
                return redirect(url_for('b2b_admin.order_detail', order_id=order.id))

    fallback_url = request.form.get('design_proof_fallback', '').strip()
    if not proof_url and fallback_url:
        proof_url = fallback_url

    if proof_url:
        order.design_proof_url = proof_url
        order.design_status = 'awaiting_approval'
        
        old_stage = order.stage
        if order.stage == 'advance_paid':
            order.stage = 'design_review'
            order.add_log(
                action_title="Design Proof Uploaded & Ready for Client Review",
                from_stage=old_stage,
                to_stage='design_review',
                actor=f"{current_user.name} (Admin)",
                details="Uploaded high-res sleeve mockup for corporate approval."
            )
            if order.client and order.client.phone:
                send_b2b_sms(order.client.phone, 'design_ready', {
                    'client_name': order.client.contact_name or order.client.company_name,
                    'order_number': order.order_number
                })
        else:
            order.add_log(
                action_title="Design Proof Updated",
                actor=f"{current_user.name} (Admin)",
                details="Updated artwork mockup for client portal."
            )

        db.session.commit()
        flash(f"Design proof uploaded for Order #{order.order_number}!", 'success')
    else:
        flash("No design proof file or URL provided.", 'warning')

    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/lock-details', methods=['POST'])
@admin_required
def lock_details(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    order.stage = 'details_locked'
    order.add_log(
        action_title="Design & Final Quantity Locked for Production",
        to_stage='details_locked',
        actor=f"{current_user.name} (Admin)",
        details=f"Locked at {order.box_count} boxes. Moving to handcrafted sweet preparation."
    )
    db.session.commit()
    flash(f"Order #{order.order_number} locked for production.", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/mark-delivered', methods=['POST'])
@admin_required
def mark_delivered(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    order.stage = 'delivered'
    order.delivered_at = datetime.utcnow()
    
    courier = request.form.get('courier_name', '').strip()
    tracking = request.form.get('tracking_number', '').strip()
    if courier:
        order.courier_name = courier
    if tracking:
        order.tracking_number = tracking

    order.add_log(
        action_title="Order Delivered Successfully",
        to_stage='delivered',
        actor=f"{current_user.name} (Admin)",
        details=f"Delivered via {order.courier_name or 'Direct Logistics'} | Tracking: {order.tracking_number or 'N/A'}"
    )

    db.session.commit()

    if order.client and order.client.phone:
        send_b2b_sms(order.client.phone, 'delivered', {
            'client_name': order.client.contact_name or order.client.company_name,
            'order_number': order.order_number
        })

    flash(f"Order #{order.order_number} marked as Delivered!", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/dispatch', methods=['POST'])
@admin_required
def dispatch_order(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    courier = request.form.get('courier_name', '').strip()
    tracking = request.form.get('tracking_number', '').strip()

    order.courier_name = courier
    order.tracking_number = tracking

    order.add_log(
        action_title="Courier Dispatch Details Updated",
        actor=f"{current_user.name} (Admin)",
        details=f"Courier: {courier} | Tracking: {tracking}"
    )
    db.session.commit()
    flash(f"Dispatch info updated for #{order.order_number}.", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/new', methods=['POST'])
@admin_required
def create_order():
    client_id = request.form.get('client_id')
    box_type = request.form.get('box_type', 'Signature DIYA Box')
    
    try:
        box_count = int(request.form.get('box_count', 100))
    except (ValueError, TypeError):
        box_count = 100
        
    try:
        price_per_box = float(request.form.get('quoted_price_per_box', 345.0))
    except (ValueError, TypeError):
        price_per_box = 345.0
        
    custom_occasion = request.form.get('custom_occasion', '').strip()
    custom_message = request.form.get('custom_message', '').strip()
    eta_date = request.form.get('eta_date', '').strip()
    notes = request.form.get('internal_notes', '').strip()

    client = B2BClient.query.get_or_404(client_id)
    total_amount = box_count * price_per_box
    advance_req = total_amount * 0.50

    order = B2BOrder(
        order_number=B2BOrder.generate_order_number(),
        client_id=client.id,
        box_type=box_type,
        box_count=box_count,
        quoted_price_per_box=price_per_box,
        total_amount=total_amount,
        advance_amount_required=advance_req,
        custom_occasion=custom_occasion,
        custom_message=custom_message,
        eta_date=eta_date,
        internal_notes=notes,
        stage='enquiry'
    )
    db.session.add(order)
    db.session.flush()

    order.add_log(
        action_title="B2B Order Initiated",
        from_stage=None,
        to_stage='enquiry',
        actor=f"{current_user.name} (Admin)",
        details=f"Order created for {client.company_name} ({box_count} x {box_type})"
    )

    db.session.commit()
    flash(f"B2B Order #{order.order_number} created for {client.company_name}!", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/edit', methods=['POST'])
@admin_required
def edit_order(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    
    order.box_type = request.form.get('box_type', order.box_type)
    try:
        order.box_count = int(request.form.get('box_count', order.box_count))
    except (ValueError, TypeError):
        pass

    try:
        order.quoted_price_per_box = float(request.form.get('quoted_price_per_box', order.quoted_price_per_box))
    except (ValueError, TypeError):
        pass

    order.total_amount = order.box_count * order.quoted_price_per_box
    order.advance_amount_required = order.total_amount * 0.50
    order.custom_occasion = request.form.get('custom_occasion', order.custom_occasion)
    order.custom_message = request.form.get('custom_message', order.custom_message)
    order.eta_date = request.form.get('eta_date', order.eta_date)
    order.payment_link = request.form.get('payment_link', order.payment_link)
    order.internal_notes = request.form.get('internal_notes', order.internal_notes)

    order.add_log(
        action_title="Order Specifications Updated",
        actor=f"{current_user.name} (Admin)",
        details=f"Updated count: {order.box_count}, Price: ₹{order.quoted_price_per_box}, Total: ₹{order.total_amount:,.2f}"
    )

    db.session.commit()
    flash(f"Order #{order.order_number} updated successfully.", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/delete', methods=['POST'])
@admin_required
def delete_order(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    num = order.order_number
    db.session.delete(order)
    db.session.commit()
    flash(f"Order #{num} deleted.", 'info')
    return redirect(url_for('b2b_admin.orders'))


# =========================================================================
# 3. CLIENT DIRECTORY & CRM
# =========================================================================
@b2b_admin_bp.route('/clients')
@admin_required
def clients():
    all_clients = B2BClient.query.order_by(B2BClient.created_at.desc()).all()
    boxes = B2BProduct.query.filter_by(is_active=True).all()
    return render_template('admin/b2b/clients.html', clients=all_clients, boxes=boxes)


@b2b_admin_bp.route('/clients/<int:client_id>')
@admin_required
def client_detail(client_id):
    client = B2BClient.query.get_or_404(client_id)
    boxes = B2BProduct.query.filter_by(is_active=True).all()
    return render_template('admin/b2b/client_detail.html', client=client, boxes=boxes)


@b2b_admin_bp.route('/clients/onboard', methods=['POST'])
@b2b_admin_bp.route('/clients/new', methods=['POST'])
@admin_required
def onboard_client():
    company_name = request.form.get('company_name', '').strip()
    contact_name = request.form.get('contact_name', '').strip()
    raw_phone = request.form.get('phone', '').strip()
    phone = normalize_phone(raw_phone)
    email = request.form.get('email', '').strip()
    gst_number = request.form.get('gst_number', '').strip()
    shipping_address = request.form.get('shipping_address', '').strip()
    industry = request.form.get('industry', '').strip()
    notes = request.form.get('notes', '').strip()

    if not company_name or not contact_name or not phone or not email:
        flash('Company, Contact, Phone, and Email are required fields.', 'danger')
        return redirect(url_for('b2b_admin.clients'))

    existing = B2BClient.query.filter_by(phone=phone).first()
    if existing:
        flash(f'A client with phone number {phone} already exists ({existing.company_name}).', 'warning')
        return redirect(url_for('b2b_admin.clients'))

    client = B2BClient(
        company_name=company_name,
        contact_name=contact_name,
        phone=phone,
        email=email,
        gst_number=gst_number,
        shipping_address=shipping_address,
        industry=industry,
        notes=notes
    )
    db.session.add(client)
    db.session.commit()
    flash(f'Corporate client "{company_name}" onboarded successfully!', 'success')
    return redirect(url_for('b2b_admin.clients'))


@b2b_admin_bp.route('/clients/<int:client_id>/edit', methods=['POST'])
@admin_required
def edit_client(client_id):
    client = B2BClient.query.get_or_404(client_id)
    
    client.company_name = request.form.get('company_name', client.company_name).strip()
    client.contact_name = request.form.get('contact_name', client.contact_name).strip()
    raw_phone = request.form.get('phone', client.phone).strip()
    client.phone = normalize_phone(raw_phone)
    client.email = request.form.get('email', client.email).strip()
    client.gst_number = request.form.get('gst_number', client.gst_number).strip()
    client.shipping_address = request.form.get('shipping_address', client.shipping_address).strip()
    client.industry = request.form.get('industry', client.industry).strip()
    client.notes = request.form.get('notes', client.notes).strip()

    db.session.commit()
    flash(f'Client details for "{client.company_name}" updated.', 'success')
    return redirect(url_for('b2b_admin.client_detail', client_id=client.id))


@b2b_admin_bp.route('/clients/<int:client_id>/delete', methods=['POST'])
@admin_required
def delete_client(client_id):
    client = B2BClient.query.get_or_404(client_id)
    name = client.company_name
    db.session.delete(client)
    db.session.commit()
    flash(f'Client "{name}" and associated orders removed.', 'info')
    return redirect(url_for('b2b_admin.clients'))


# =========================================================================
# 4. B2B PRODUCT CATALOG MANAGER
# =========================================================================
@b2b_admin_bp.route('/products')
@admin_required
def products():
    all_products = B2BProduct.query.order_by(B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    return render_template('admin/b2b/products.html', products=all_products)


@b2b_admin_bp.route('/products/add', methods=['POST'])
@admin_required
def add_product():
    name = request.form.get('name', '').strip()
    category = request.form.get('category', 'Corporate Gifting').strip()
    bites_count = request.form.get('bites_count', '8').strip()
    net_weight = request.form.get('net_weight', '144 gms').strip()
    gross_weight = request.form.get('gross_weight', '350 gms').strip()
    
    try:
        price_premium = float(request.form.get('price_premium', 0.0))
    except (ValueError, TypeError):
        price_premium = 0.0
        
    try:
        price_assorted = float(request.form.get('price_assorted', 0.0))
    except (ValueError, TypeError):
        price_assorted = 0.0

    composition_premium = request.form.get('composition_premium', '').strip()
    composition_assorted = request.form.get('composition_assorted', '').strip()
    customization_info = request.form.get('customization_info', 'Includes custom branding & theme printed on box (Min 50 boxes)').strip()
    badge = request.form.get('badge', '').strip()
    
    description = request.form.get('description', '').strip()
    box_dimensions = request.form.get('box_dimensions', '24 cm x 16 cm x 4.5 cm').strip()
    shelf_life = request.form.get('shelf_life', '60 Days from Dispatch').strip()
    lead_time = request.form.get('lead_time', '5 - 7 Business Days').strip()
    sleeve_specs = request.form.get('sleeve_specs', 'Full 4-Color Offset Sleeve with matte lamination & metallic gold foil stamping').strip()

    try:
        display_order = int(request.form.get('display_order', 0))
    except (ValueError, TypeError):
        display_order = 0

    image_url = None
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            try:
                image_url = upload_file(file, file.filename, folder="b2b_products")
            except Exception as e:
                pass

    fallback_img = request.form.get('image_url_fallback', '').strip()
    if not image_url and fallback_img:
        image_url = fallback_img

    product = B2BProduct(
        name=name,
        category=category,
        bites_count=bites_count,
        net_weight=net_weight,
        gross_weight=gross_weight,
        price_premium=price_premium,
        price_assorted=price_assorted,
        composition_premium=composition_premium,
        composition_assorted=composition_assorted,
        customization_info=customization_info,
        badge=badge,
        description=description,
        box_dimensions=box_dimensions,
        shelf_life=shelf_life,
        lead_time=lead_time,
        sleeve_specs=sleeve_specs,
        display_order=display_order,
        image_url=image_url,
        is_active=True
    )
    db.session.add(product)
    db.session.commit()
    flash(f'B2B Box "{name}" added to catalog!', 'success')
    return redirect(url_for('b2b_admin.products'))


@b2b_admin_bp.route('/products/<int:product_id>/edit', methods=['POST'])
@admin_required
def edit_product(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    
    product.name = request.form.get('name', product.name).strip()
    product.category = request.form.get('category', product.category).strip()
    product.bites_count = request.form.get('bites_count', product.bites_count).strip()
    product.net_weight = request.form.get('net_weight', product.net_weight).strip()
    product.gross_weight = request.form.get('gross_weight', product.gross_weight or '350 gms').strip()

    
    try:
        product.price_premium = float(request.form.get('price_premium', product.price_premium))
    except (ValueError, TypeError):
        pass
        
    try:
        product.price_assorted = float(request.form.get('price_assorted', product.price_assorted))
    except (ValueError, TypeError):
        pass

    product.composition_premium = request.form.get('composition_premium', product.composition_premium).strip()
    product.composition_assorted = request.form.get('composition_assorted', product.composition_assorted).strip()
    product.customization_info = request.form.get('customization_info', product.customization_info).strip()
    product.badge = request.form.get('badge', product.badge).strip()
    
    product.description = request.form.get('description', product.description or '').strip()
    product.box_dimensions = request.form.get('box_dimensions', product.box_dimensions or '24 cm x 16 cm x 4.5 cm').strip()
    product.shelf_life = request.form.get('shelf_life', product.shelf_life or '60 Days from Dispatch').strip()
    product.lead_time = request.form.get('lead_time', product.lead_time or '5 - 7 Business Days').strip()
    product.sleeve_specs = request.form.get('sleeve_specs', product.sleeve_specs or 'Full 4-Color Offset Sleeve with matte lamination & metallic gold foil stamping').strip()

    try:
        product.display_order = int(request.form.get('display_order', product.display_order))
    except (ValueError, TypeError):
        pass

    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            try:
                product.image_url = upload_file(file, file.filename, folder="b2b_products")
            except Exception:
                pass

    fallback_img = request.form.get('image_url_fallback', '').strip()
    if fallback_img and not request.files.get('image'):
        product.image_url = fallback_img

    db.session.commit()
    flash(f'Box "{product.name}" specifications & configuration saved!', 'success')
    return_to = request.form.get('return_to')
    if return_to == 'manage':
        return redirect(url_for('b2b_admin.product_manage', product_id=product.id))
    return redirect(url_for('b2b_admin.products'))



@b2b_admin_bp.route('/products/<int:product_id>/toggle', methods=['POST'])
@admin_required
def toggle_product(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    product.is_active = not product.is_active
    db.session.commit()
    status = 'activated' if product.is_active else 'hidden'
    flash(f'Product "{product.name}" is now {status}.', 'info')
    return redirect(url_for('b2b_admin.products'))


@b2b_admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@admin_required
def delete_product(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    name = product.name
    db.session.delete(product)
    db.session.commit()
    flash(f'Product "{name}" deleted from catalog.', 'info')
    return redirect(url_for('b2b_admin.products'))


# =========================================================================
# 5. B2B PRODUCT GALLERY & REAL CLIENT DELIVERY SHOWCASE CONTROL ROOM
# =========================================================================
@b2b_admin_bp.route('/products/<int:product_id>/manage')
@admin_required
def product_manage(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    return render_template('admin/b2b/product_manage.html', product=product)


@b2b_admin_bp.route('/products/<int:product_id>/images/add', methods=['POST'])
@admin_required
def add_product_image(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    caption = request.form.get('caption', '').strip()
    
    try:
        display_order = int(request.form.get('display_order', 0) or 0)
    except (ValueError, TypeError):
        display_order = 0
        
    image_url = None
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            try:
                image_url = upload_file(file, file.filename, folder="b2b_product_gallery")
            except Exception as e:
                pass
                
    fallback_img = request.form.get('image_url_fallback', '').strip()
    if not image_url and fallback_img:
        image_url = fallback_img
        
    if not image_url:
        flash('Please upload an image file or provide an image URL.', 'danger')
        return redirect(url_for('b2b_admin.product_manage', product_id=product.id))
        
    img = B2BProductImage(
        product_id=product.id,
        image_url=image_url,
        caption=caption,
        display_order=display_order
    )
    db.session.add(img)
    db.session.commit()
    flash(f'Gallery photo added to {product.name}!', 'success')
    return redirect(url_for('b2b_admin.product_manage', product_id=product.id))


@b2b_admin_bp.route('/products/images/<int:image_id>/delete', methods=['POST'])
@admin_required
def delete_product_image(image_id):
    img = B2BProductImage.query.get_or_404(image_id)
    product_id = img.product_id
    db.session.delete(img)
    db.session.commit()
    flash('Gallery image deleted.', 'info')
    return redirect(url_for('b2b_admin.product_manage', product_id=product_id))


@b2b_admin_bp.route('/products/<int:product_id>/showcases/add', methods=['POST'])
@admin_required
def add_product_showcase(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    client_name = request.form.get('client_name', '').strip()
    order_volume = request.form.get('order_volume', '250 Custom Boxes').strip()
    occasion = request.form.get('occasion', '').strip()
    client_feedback = request.form.get('client_feedback', '').strip()
    
    try:
        display_order = int(request.form.get('display_order', 0) or 0)
    except (ValueError, TypeError):
        display_order = 0
        
    if not client_name:
        flash('Client name is required.', 'danger')
        return redirect(url_for('b2b_admin.product_manage', product_id=product.id))
        
    box_photo_url = None
    if 'box_photo' in request.files:
        file_box = request.files['box_photo']
        if file_box and file_box.filename:
            try:
                box_photo_url = upload_file(file_box, file_box.filename, folder="b2b_client_showcases")
            except Exception as e:
                pass
                
    fallback_box = request.form.get('box_photo_fallback', '').strip()
    if not box_photo_url and fallback_box:
        box_photo_url = fallback_box
        
    if not box_photo_url:
        flash('Delivered box photo is required for the client delivery showcase.', 'danger')
        return redirect(url_for('b2b_admin.product_manage', product_id=product.id))
        
    client_logo_url = None
    if 'client_logo' in request.files:
        file_logo = request.files['client_logo']
        if file_logo and file_logo.filename:
            try:
                client_logo_url = upload_file(file_logo, file_logo.filename, folder="b2b_logos")
            except Exception as e:
                pass
                
    fallback_logo = request.form.get('client_logo_fallback', '').strip()
    if not client_logo_url and fallback_logo:
        client_logo_url = fallback_logo
        
    showcase = B2BProductShowcase(
        product_id=product.id,
        client_name=client_name,
        client_logo_url=client_logo_url,
        box_photo_url=box_photo_url,
        order_volume=order_volume,
        occasion=occasion,
        client_feedback=client_feedback,
        display_order=display_order
    )
    db.session.add(showcase)
    db.session.commit()
    flash(f'Client delivery showcase for "{client_name}" added to {product.name}!', 'success')
    return redirect(url_for('b2b_admin.product_manage', product_id=product.id))


@b2b_admin_bp.route('/products/showcases/<int:showcase_id>/delete', methods=['POST'])
@admin_required
def delete_product_showcase(showcase_id):
    showcase = B2BProductShowcase.query.get_or_404(showcase_id)
    product_id = showcase.product_id
    db.session.delete(showcase)
    db.session.commit()
    flash('Delivery showcase entry removed.', 'info')
    return redirect(url_for('b2b_admin.product_manage', product_id=product_id))


# =========================================================================
# 6. CLIENT TESTIMONIALS & COLLABORATIONS CONTROL ROOM
# =========================================================================
@b2b_admin_bp.route('/testimonials')
@admin_required
def testimonials():
    all_testimonials = B2BTestimonial.query.order_by(B2BTestimonial.display_order.asc(), B2BTestimonial.id.desc()).all()
    return render_template('admin/b2b/testimonials.html', testimonials=all_testimonials)


@b2b_admin_bp.route('/testimonials/add', methods=['POST'])
@admin_required
def add_testimonial():
    company_name = request.form.get('company_name', '').strip()
    contact_person = request.form.get('contact_person', '').strip()
    designation = request.form.get('designation', '').strip()
    order_details = request.form.get('order_details', '').strip()
    testimonial_text = request.form.get('testimonial_text', '').strip()
    
    try:
        rating = int(request.form.get('rating', 5) or 5)
    except (ValueError, TypeError):
        rating = 5
        
    try:
        display_order = int(request.form.get('display_order', 0) or 0)
    except (ValueError, TypeError):
        display_order = 0
        
    is_featured = 'is_featured' in request.form
    
    if not company_name or not testimonial_text:
        flash('Company name and testimonial text are required.', 'danger')
        return redirect(url_for('b2b_admin.testimonials'))
        
    company_logo_url = None
    if 'company_logo' in request.files:
        file = request.files['company_logo']
        if file and file.filename:
            try:
                company_logo_url = upload_file(file, file.filename, folder="b2b_logos")
            except Exception as e:
                pass
                
    fallback_logo = request.form.get('company_logo_fallback', '').strip()
    if not company_logo_url and fallback_logo:
        company_logo_url = fallback_logo
        
    # Handle Multiple Box Photos Upload
    uploaded_photos = []
    if 'box_photos' in request.files:
        files = request.files.getlist('box_photos')
        for file_box in files:
            if file_box and file_box.filename:
                try:
                    url = upload_file(file_box, file_box.filename, folder="b2b_testimonials")
                    if url:
                        uploaded_photos.append(url)
                except Exception as e:
                    pass
                    
    if 'box_photo' in request.files:
        single_file = request.files['box_photo']
        if single_file and single_file.filename:
            try:
                single_url = upload_file(single_file, single_file.filename, folder="b2b_testimonials")
                if single_url and single_url not in uploaded_photos:
                    uploaded_photos.append(single_url)
            except Exception:
                pass
                
    fallback_box = request.form.get('box_photo_fallback', '').strip()
    if fallback_box:
        for line in fallback_box.replace('\r', '').split('\n'):
            line_clean = line.strip()
            if line_clean and line_clean not in uploaded_photos:
                uploaded_photos.append(line_clean)
                
    primary_photo = uploaded_photos[0] if uploaded_photos else None
    
    testi = B2BTestimonial(
        company_name=company_name,
        company_logo_url=company_logo_url,
        contact_person=contact_person,
        designation=designation,
        box_photo_url=primary_photo,
        order_details=order_details,
        rating=rating,
        testimonial_text=testimonial_text,
        is_featured=is_featured,
        is_active=True,
        display_order=display_order
    )
    db.session.add(testi)
    db.session.flush()
    
    for idx, photo_url in enumerate(uploaded_photos):
        img = B2BTestimonialImage(
            testimonial_id=testi.id,
            image_url=photo_url,
            caption=f"{company_name} Batch",
            display_order=idx + 1
        )
        db.session.add(img)
        
    db.session.commit()
    flash(f'Client review from "{company_name}" with {len(uploaded_photos)} photo(s) added successfully!', 'success')
    return redirect(url_for('b2b_admin.testimonials'))


@b2b_admin_bp.route('/testimonials/<int:id>/edit', methods=['POST'])
@admin_required
def edit_testimonial(id):
    testi = B2BTestimonial.query.get_or_404(id)
    
    testi.company_name = request.form.get('company_name', testi.company_name).strip()
    testi.contact_person = request.form.get('contact_person', testi.contact_person or '').strip()
    testi.designation = request.form.get('designation', testi.designation or '').strip()
    testi.order_details = request.form.get('order_details', testi.order_details or '').strip()
    testi.testimonial_text = request.form.get('testimonial_text', testi.testimonial_text).strip()
    
    try:
        testi.rating = int(request.form.get('rating', testi.rating) or 5)
    except (ValueError, TypeError):
        pass
        
    try:
        testi.display_order = int(request.form.get('display_order', testi.display_order) or 0)
    except (ValueError, TypeError):
        pass
        
    testi.is_featured = 'is_featured' in request.form
    testi.is_active = 'is_active' in request.form
    
    if 'company_logo' in request.files:
        file = request.files['company_logo']
        if file and file.filename:
            try:
                testi.company_logo_url = upload_file(file, file.filename, folder="b2b_logos")
            except Exception as e:
                pass
                
    fallback_logo = request.form.get('company_logo_fallback', '').strip()
    if fallback_logo and not request.files.get('company_logo'):
        testi.company_logo_url = fallback_logo
        
    new_photos = []
    if 'box_photos' in request.files:
        files = request.files.getlist('box_photos')
        for file_box in files:
            if file_box and file_box.filename:
                try:
                    url = upload_file(file_box, file_box.filename, folder="b2b_testimonials")
                    if url:
                        new_photos.append(url)
                except Exception as e:
                    pass
                    
    if 'box_photo' in request.files:
        single_file = request.files['box_photo']
        if single_file and single_file.filename:
            try:
                single_url = upload_file(single_file, single_file.filename, folder="b2b_testimonials")
                if single_url and single_url not in new_photos:
                    new_photos.append(single_url)
            except Exception:
                pass
                
    fallback_box = request.form.get('box_photo_fallback', '').strip()
    if fallback_box:
        for line in fallback_box.replace('\r', '').split('\n'):
            line_clean = line.strip()
            if line_clean and line_clean not in new_photos:
                new_photos.append(line_clean)
                
    start_order = len(testi.images) + 1
    for idx, photo_url in enumerate(new_photos):
        img = B2BTestimonialImage(
            testimonial_id=testi.id,
            image_url=photo_url,
            caption=f"{testi.company_name} Photo",
            display_order=start_order + idx
        )
        db.session.add(img)
        
    if new_photos and not testi.box_photo_url:
        testi.box_photo_url = new_photos[0]
        
    db.session.commit()
    flash(f'Testimonial for "{testi.company_name}" updated successfully.', 'success')
    return redirect(url_for('b2b_admin.testimonials'))


@b2b_admin_bp.route('/testimonials/images/<int:image_id>/delete', methods=['POST'])
@admin_required
def delete_testimonial_image(image_id):
    img = B2BTestimonialImage.query.get_or_404(image_id)
    testi_id = img.testimonial_id
    db.session.delete(img)
    db.session.commit()
    flash('Photo removed from testimonial carousel.', 'info')
    return redirect(url_for('b2b_admin.testimonials'))


@b2b_admin_bp.route('/testimonials/<int:id>/toggle-featured', methods=['POST'])
@admin_required
def toggle_testimonial_featured(id):
    testi = B2BTestimonial.query.get_or_404(id)
    testi.is_featured = not testi.is_featured
    db.session.commit()
    status = 'featured on homepage' if testi.is_featured else 'unpinned from homepage'
    flash(f'Testimonial is now {status}.', 'info')
    return redirect(url_for('b2b_admin.testimonials'))


@b2b_admin_bp.route('/testimonials/<int:id>/delete', methods=['POST'])
@admin_required
def delete_testimonial(id):
    testi = B2BTestimonial.query.get_or_404(id)
    name = testi.company_name
    db.session.delete(testi)
    db.session.commit()
    flash(f'Testimonial from "{name}" removed.', 'info')
    return redirect(url_for('b2b_admin.testimonials'))
