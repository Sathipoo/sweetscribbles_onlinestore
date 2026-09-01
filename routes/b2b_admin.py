import os
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from extensions import db
from models.b2b import B2BClient, B2BOrder, B2BProduct
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

# ==========================================
# 1. B2B PIPELINE DASHBOARD (KANBAN)
# ==========================================
@b2b_admin_bp.route('/')
@admin_required
def dashboard():
    all_orders = B2BOrder.query.order_by(B2BOrder.created_at.desc()).all()
    all_clients = B2BClient.query.order_by(B2BClient.created_at.desc()).all()
    all_products = B2BProduct.query.filter_by(is_active=True).order_by(B2BProduct.display_order.asc()).all()
    
    pipeline = {
        'enquiry': [o for o in all_orders if o.stage == 'enquiry'],
        'quotation_sent': [o for o in all_orders if o.stage == 'quotation_sent'],
        'advance_paid': [o for o in all_orders if o.stage == 'advance_paid'],
        'design_review': [o for o in all_orders if o.stage == 'design_review'],
        'details_locked': [o for o in all_orders if o.stage == 'details_locked'],
        'production': [o for o in all_orders if o.stage == 'production'],
        'delivered': [o for o in all_orders if o.stage == 'delivered'],
        'cancelled': [o for o in all_orders if o.stage == 'cancelled']
    }
    
    total_pipeline_value = sum((o.total_amount or 0.0) for o in all_orders if o.stage not in ('cancelled',))
    total_boxes_pipeline = sum((o.box_count or 0) for o in all_orders if o.stage not in ('cancelled',))
    
    return render_template(
        'admin/b2b/dashboard.html',
        pipeline=pipeline,
        all_orders=all_orders,
        all_clients=all_clients,
        all_products=all_products,
        total_pipeline_value=total_pipeline_value,
        total_boxes_pipeline=total_boxes_pipeline
    )

# ==========================================
# 2. ALL B2B ORDERS (FILTERABLE TABLE)
# ==========================================
@b2b_admin_bp.route('/orders')
@admin_required
def orders():
    stage_filter = request.args.get('stage', '').strip()
    query_str = request.args.get('q', '').strip().lower()
    
    order_query = B2BOrder.query
    if stage_filter:
        order_query = order_query.filter_by(stage=stage_filter)
        
    orders_list = order_query.order_by(B2BOrder.created_at.desc()).all()
    
    if query_str:
        orders_list = [
            o for o in orders_list
            if query_str in o.order_number.lower()
            or query_str in o.client.company_name.lower()
            or query_str in o.client.contact_name.lower()
            or query_str in o.client.phone.lower()
            or query_str in (o.custom_occasion or '').lower()
        ]
        
    all_stages = ['enquiry', 'quotation_sent', 'advance_paid', 'design_review', 'details_locked', 'production', 'delivered', 'cancelled']
    stage_counts = {st: B2BOrder.query.filter_by(stage=st).count() for st in all_stages}
    stage_counts['all'] = B2BOrder.query.count()
    
    return render_template(
        'admin/b2b/orders.html',
        orders=orders_list,
        current_stage=stage_filter,
        query_str=query_str,
        stage_counts=stage_counts
    )

# ==========================================
# 3. B2B ORDER DETAIL CONTROL ROOM
# ==========================================
@b2b_admin_bp.route('/order/<int:order_id>')
@admin_required
def order_detail(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    available_boxes = B2BProduct.query.filter_by(is_active=True).order_by(B2BProduct.display_order.asc()).all()
    return render_template('admin/b2b/order_detail.html', order=order, available_boxes=available_boxes)

# ==========================================
# 4. CORPORATE CLIENTS DIRECTORY
# ==========================================
@b2b_admin_bp.route('/clients')
@admin_required
def clients():
    query_str = request.args.get('q', '').strip().lower()
    clients_list = B2BClient.query.order_by(B2BClient.created_at.desc()).all()
    
    if query_str:
        clients_list = [
            c for c in clients_list
            if query_str in c.company_name.lower()
            or query_str in c.contact_name.lower()
            or query_str in c.phone.lower()
            or query_str in c.email.lower()
            or query_str in (c.gst_number or '').lower()
        ]
        
    available_boxes = B2BProduct.query.filter_by(is_active=True).order_by(B2BProduct.display_order.asc()).all()
    return render_template('admin/b2b/clients.html', clients=clients_list, query_str=query_str, available_boxes=available_boxes)

@b2b_admin_bp.route('/client/<int:client_id>')
@admin_required
def client_detail(client_id):
    client = B2BClient.query.get_or_404(client_id)
    return render_template('admin/b2b/client_detail.html', client=client)

@b2b_admin_bp.route('/client/<int:client_id>/edit', methods=['POST'])
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
    flash(f'Corporate profile for "{client.company_name}" updated successfully.', 'success')
    return redirect(url_for('b2b_admin.client_detail', client_id=client.id))

# ==========================================
# 5. B2B PRODUCTS & CATALOGUE MANAGER
# ==========================================
@b2b_admin_bp.route('/products')
@admin_required
def products():
    products_list = B2BProduct.query.order_by(B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    return render_template('admin/b2b/products.html', products=products_list)

@b2b_admin_bp.route('/products/add', methods=['POST'])
@admin_required
def add_product():
    name = request.form.get('name', '').strip()
    category = request.form.get('category', 'Corporate Gifting').strip()
    bites_count = request.form.get('bites_count', '8 Bites').strip()
    net_weight = request.form.get('net_weight', '144 gms').strip()
    
    try:
        price_premium = float(request.form.get('price_premium', 0.0) or 0.0)
    except (ValueError, TypeError):
        price_premium = 0.0
        
    try:
        price_assorted = float(request.form.get('price_assorted', 0.0) or 0.0)
    except (ValueError, TypeError):
        price_assorted = 0.0
        
    try:
        display_order = int(request.form.get('display_order', 0) or 0)
    except (ValueError, TypeError):
        display_order = 0
        
    try:
        min_order_qty = int(request.form.get('min_order_qty', 50) or 50)
    except (ValueError, TypeError):
        min_order_qty = 50
        
    badge = request.form.get('badge', 'Bestseller').strip()
    customization_info = request.form.get('customization_info', 'Includes custom branding & theme printed on box (Min 50 boxes)').strip()
    composition_premium = request.form.get('composition_premium', '').strip()
    composition_assorted = request.form.get('composition_assorted', '').strip()
    
    # Handle Photo upload
    image_url = None
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            try:
                image_url = upload_file(file, file.filename, folder="b2b_products")
            except Exception as e:
                flash(f'Note on photo upload: {e}', 'warning')
                
    if not image_url and request.form.get('image_url_fallback'):
        image_url = request.form.get('image_url_fallback').strip()
        
    new_product = B2BProduct(
        name=name,
        category=category,
        bites_count=bites_count,
        net_weight=net_weight,
        price_premium=price_premium,
        price_assorted=price_assorted,
        composition_premium=composition_premium,
        composition_assorted=composition_assorted,
        customization_info=customization_info,
        badge=badge,
        image_url=image_url,
        display_order=display_order,
        min_order_qty=min_order_qty,
        is_active=True
    )
    db.session.add(new_product)
    db.session.commit()
    
    flash(f'B2B Box "{name}" added to catalogue successfully!', 'success')
    return redirect(url_for('b2b_admin.products'))

@b2b_admin_bp.route('/products/<int:product_id>/edit', methods=['POST'])
@admin_required
def edit_product(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    
    product.name = request.form.get('name', product.name).strip()
    product.category = request.form.get('category', product.category).strip()
    product.bites_count = request.form.get('bites_count', product.bites_count).strip()
    product.net_weight = request.form.get('net_weight', product.net_weight).strip()
    
    try:
        product.price_premium = float(request.form.get('price_premium', product.price_premium) or 0.0)
    except (ValueError, TypeError):
        pass
        
    try:
        product.price_assorted = float(request.form.get('price_assorted', product.price_assorted) or 0.0)
    except (ValueError, TypeError):
        pass
        
    try:
        product.display_order = int(request.form.get('display_order', product.display_order) or 0)
    except (ValueError, TypeError):
        pass
        
    try:
        product.min_order_qty = int(request.form.get('min_order_qty', product.min_order_qty) or 50)
    except (ValueError, TypeError):
        pass
        
    product.badge = request.form.get('badge', product.badge).strip()
    product.customization_info = request.form.get('customization_info', product.customization_info).strip()
    product.composition_premium = request.form.get('composition_premium', product.composition_premium).strip()
    product.composition_assorted = request.form.get('composition_assorted', product.composition_assorted).strip()
    
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename:
            try:
                product.image_url = upload_file(file, file.filename, folder="b2b_products")
            except Exception as e:
                flash(f'Photo upload note: {e}', 'warning')
                
    fallback_url = request.form.get('image_url_fallback', '').strip()
    if fallback_url and not request.files.get('image'):
        product.image_url = fallback_url
        
    db.session.commit()
    flash(f'B2B Box "{product.name}" updated successfully.', 'success')
    return redirect(url_for('b2b_admin.products'))

@b2b_admin_bp.route('/products/<int:product_id>/toggle', methods=['POST'])
@admin_required
def toggle_product(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    product.is_active = not product.is_active
    db.session.commit()
    status_str = "activated" if product.is_active else "deactivated"
    flash(f'Box "{product.name}" {status_str} on the live B2B catalogue.', 'info')
    return redirect(url_for('b2b_admin.products'))

@b2b_admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@admin_required
def delete_product(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    box_name = product.name
    db.session.delete(product)
    db.session.commit()
    flash(f'Box "{box_name}" deleted from catalogue.', 'info')
    return redirect(url_for('b2b_admin.products'))

# ==========================================
# 6. DIRECT SALES ONBOARDING (NO OTP - OPTIONAL BOX & COUNT)
# ==========================================
@b2b_admin_bp.route('/onboard-client', methods=['POST'])
@admin_required
def onboard_client():
    company_name = request.form.get('company_name', '').strip()
    contact_name = request.form.get('contact_name', '').strip()
    email = request.form.get('email', '').strip()
    raw_phone = request.form.get('phone', '').strip()
    gst_number = request.form.get('gst_number', '').strip()
    shipping_address = request.form.get('shipping_address', '').strip()
    
    # Optional Box and Quantity during onboarding
    raw_box_type = request.form.get('box_type', '').strip()
    box_type = raw_box_type if raw_box_type else 'To be decided / Consultation'
    
    try:
        raw_box_count = request.form.get('box_count', '').strip()
        box_count = int(raw_box_count) if raw_box_count else 0
    except (ValueError, TypeError):
        box_count = 0
        
    try:
        raw_price = request.form.get('quoted_price_per_box', '').strip()
        quoted_price_per_box = float(raw_price) if raw_price else 0.0
    except (ValueError, TypeError):
        quoted_price_per_box = 0.0
        
    custom_occasion = request.form.get('custom_occasion', 'Corporate Gifting Consultation').strip()
    custom_message = request.form.get('custom_message', '').strip()
    notes = request.form.get('notes', '').strip()
    
    phone = normalize_phone(raw_phone)
    if not phone or not company_name or not contact_name:
        flash('Company Name, Contact Name, and Mobile Number are required.', 'danger')
        return redirect(url_for('b2b_admin.dashboard'))
        
    client = B2BClient.query.filter_by(phone=phone).first()
    if not client:
        client = B2BClient(
            company_name=company_name,
            contact_name=contact_name,
            phone=phone,
            email=email,
            gst_number=gst_number,
            shipping_address=shipping_address,
            notes=notes
        )
        db.session.add(client)
        db.session.flush()
    else:
        client.company_name = company_name
        client.contact_name = contact_name
        if email: client.email = email
        if gst_number: client.gst_number = gst_number
        if shipping_address: client.shipping_address = shipping_address
        
    total_amount = quoted_price_per_box * box_count
    advance_amount_required = total_amount * 0.5
    
    stage = 'quotation_sent' if (quoted_price_per_box > 0 and box_count > 0) else 'enquiry'
    
    order = B2BOrder(
        order_number=B2BOrder.generate_order_number(),
        client_id=client.id,
        box_type=box_type,
        box_count=box_count,
        quoted_price_per_box=quoted_price_per_box,
        total_amount=total_amount,
        advance_amount_required=advance_amount_required,
        custom_occasion=custom_occasion,
        custom_message=custom_message,
        stage=stage,
        internal_notes=notes
    )
    db.session.add(order)
    db.session.flush()
    
    # Create Initial Audit Log
    admin_name = current_user.email if hasattr(current_user, 'email') else 'Admin'
    log_details = f"Box: {box_type}, Qty: {box_count if box_count > 0 else 'Undecided'}"
    if quoted_price_per_box > 0:
        log_details += f", Quoted: ₹{quoted_price_per_box}/box"
    order.add_log(
        action_title="Client Onboarded (Sales Desk)",
        to_stage=order.stage,
        actor=f"Sales Desk ({admin_name})",
        details=log_details
    )
    
    db.session.commit()
    
    flash(f'Client "{company_name}" onboarded successfully with Order #{order.order_number}!', 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))

# ==========================================
# 7. WORKFLOW STAGE ACTIONS & DLT TRIGGERS
# ==========================================
@b2b_admin_bp.route('/order/<int:order_id>/update-quote', methods=['POST'])
@admin_required
def update_quote(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    prev_stage = order.stage
    
    try:
        box_count = int(request.form.get('box_count', order.box_count) or 0)
        price_per_box = float(request.form.get('quoted_price_per_box', order.quoted_price_per_box) or 0.0)
        advance_percent = float(request.form.get('advance_percent', 50.0) or 50.0)
    except (ValueError, TypeError):
        flash('Invalid numerical values entered.', 'danger')
        return redirect(url_for('b2b_admin.order_detail', order_id=order.id))
        
    order.box_count = box_count
    order.quoted_price_per_box = price_per_box
    order.total_amount = box_count * price_per_box
    order.advance_amount_required = order.total_amount * (advance_percent / 100.0)
    order.box_type = request.form.get('box_type', order.box_type)
    order.custom_occasion = request.form.get('custom_occasion', order.custom_occasion)
    order.internal_notes = request.form.get('internal_notes', order.internal_notes)
    
    if order.stage == 'enquiry' and price_per_box > 0 and box_count > 0:
        order.stage = 'quotation_sent'
        
    admin_name = current_user.email if hasattr(current_user, 'email') else 'Admin'
    order.add_log(
        action_title="Quotation & Terms Updated",
        from_stage=prev_stage,
        to_stage=order.stage,
        actor=f"Sales Desk ({admin_name})",
        details=f"Box: {order.box_type}, Qty: {order.box_count}, Rate: ₹{order.quoted_price_per_box}/box, Total: ₹{order.total_amount:,.2f}"
    )
    
    db.session.commit()
    flash('Quotation details updated successfully!', 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))

@b2b_admin_bp.route('/order/<int:order_id>/mark-advance-paid', methods=['POST'])
@admin_required
def mark_advance_paid(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    prev_stage = order.stage
    
    order.advance_paid = True
    order.advance_paid_at = datetime.utcnow()
    order.stage = 'advance_paid'
    
    admin_name = current_user.email if hasattr(current_user, 'email') else 'Admin'
    order.add_log(
        action_title="50% Advance Payment Received (Order Confirmed)",
        from_stage=prev_stage,
        to_stage='advance_paid',
        actor=f"Finance Desk ({admin_name})",
        details=f"Advance received: ₹{order.advance_amount_required:,.2f}. DLT confirmation SMS dispatched."
    )
    
    db.session.commit()
    
    tracking_url = url_for('b2b.portal', _external=True)
    send_b2b_sms(
        phone=order.client.phone,
        flow_key='MSG91_FLOW_B2B_CONFIRMED',
        variables_dict={
            'order_id': order.order_number,
            'tracking_url': tracking_url
        }
    )
    
    flash(f'Advance payment marked as received. Order confirmed & SMS alert dispatched to client!', 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))

@b2b_admin_bp.route('/order/<int:order_id>/upload-proof', methods=['POST'])
@admin_required
def upload_proof(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    prev_stage = order.stage
    
    file = request.files.get('design_proof')
    if file and file.filename:
        try:
            proof_url = upload_file(file, file.filename, folder="b2b_proofs")
            order.design_proof_url = proof_url
            order.design_status = 'awaiting_approval'
            order.stage = 'design_review'
            
            admin_name = current_user.email if hasattr(current_user, 'email') else 'Admin'
            order.add_log(
                action_title="Artwork Proof Uploaded & Shared with Client",
                from_stage=prev_stage,
                to_stage='design_review',
                actor=f"Design Team ({admin_name})",
                details="Mockup uploaded to cloud storage. DLT SMS approval link sent to client."
            )
            
            db.session.commit()
            
            approval_url = url_for('b2b.portal', _external=True)
            send_b2b_sms(
                phone=order.client.phone,
                flow_key='MSG91_FLOW_B2B_DESIGN_READY',
                variables_dict={
                    'order_id': order.order_number,
                    'approval_url': approval_url
                }
            )
            flash('Design proof uploaded successfully & notification SMS sent to client!', 'success')
        except Exception as e:
            flash(f'Proof upload failed: {e}', 'danger')
    else:
        flash('Please select an image/PDF proof file to upload.', 'warning')
        
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))

@b2b_admin_bp.route('/order/<int:order_id>/lock-details', methods=['POST'])
@admin_required
def lock_details(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    prev_stage = order.stage
    
    eta_date = request.form.get('eta_date', '').strip()
    try:
        box_count = int(request.form.get('box_count', order.box_count))
    except (ValueError, TypeError):
        box_count = order.box_count
        
    if not eta_date:
        flash('Please specify the Expected Delivery Date (ETA).', 'danger')
        return redirect(url_for('b2b_admin.order_detail', order_id=order.id))
        
    order.eta_date = eta_date
    order.box_count = box_count
    order.stage = 'production'
    order.design_status = 'approved'
    
    admin_name = current_user.email if hasattr(current_user, 'email') else 'Admin'
    order.add_log(
        action_title="Details Locked & Handcrafted Production Commenced",
        from_stage=prev_stage,
        to_stage='production',
        actor=f"Production Operations ({admin_name})",
        details=f"Locked box count: {order.box_count} units, ETA: {order.eta_date}. DLT SMS sent."
    )
    
    db.session.commit()
    
    order_url = url_for('b2b.portal', _external=True)
    send_b2b_sms(
        phone=order.client.phone,
        flow_key='MSG91_FLOW_B2B_PRODUCTION',
        variables_dict={
            'box_count': str(order.box_count),
            'eta_date': order.eta_date,
            'order_url': order_url
        }
    )
    
    flash('Order locked & production started! SMS notification dispatched.', 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))

@b2b_admin_bp.route('/order/<int:order_id>/mark-delivered', methods=['POST'])
@admin_required
def mark_delivered(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    prev_stage = order.stage
    
    order.courier_name = request.form.get('courier_name', 'Pikachooz Direct Delivery').strip()
    order.tracking_number = request.form.get('tracking_number', '').strip()
    order.delivered_at = datetime.utcnow()
    order.stage = 'delivered'
    
    admin_name = current_user.email if hasattr(current_user, 'email') else 'Admin'
    order.add_log(
        action_title="Delivery Completed & Order Handover Finished",
        from_stage=prev_stage,
        to_stage='delivered',
        actor=f"Logistics Desk ({admin_name})",
        details=f"Partner: {order.courier_name}, Pod/Tracking: {order.tracking_number or 'Direct Handover'}. DLT SMS sent."
    )
    
    db.session.commit()
    
    order_url = url_for('b2b.portal', _external=True)
    send_b2b_sms(
        phone=order.client.phone,
        flow_key='MSG91_FLOW_B2B_DELIVERED',
        variables_dict={
            'order_id': order.order_number,
            'order_url': order_url
        }
    )
    
    flash('Order marked as delivered! Completion SMS sent to client.', 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/order/<int:order_id>/delete', methods=['POST'])
@admin_required
def delete_order(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    order_num = order.order_number
    db.session.delete(order)
    db.session.commit()
    flash(f'Order #{order_num} has been deleted.', 'info')
    return redirect(url_for('b2b_admin.dashboard'))
