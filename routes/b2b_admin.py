import os
import io
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file, jsonify
from flask_login import login_required, current_user
from extensions import db
from models.b2b import (
    B2BClient, B2BOrder, B2BProduct, B2BProductImage, B2BProductShowcase,
    B2BTestimonial, B2BTestimonialImage, B2BOrderItem, B2BCommunicationLog
)
from utils.otp_utils import send_b2b_sms, normalize_phone
from utils.gcp_storage import upload_file
from utils.quotation_pdf import generate_quotation_pdf
from utils.email_utils import (
    send_welcome_onboarding_email, send_quotation_email,
    send_advance_received_email, send_design_proof_email,
    send_production_eta_email, send_order_delivered_email
)

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


def dispatch_b2b_sms_and_log(order, event_type, flow_key, variables_dict):
    """Dispatches DLT SMS and records in B2BCommunicationLog."""
    if not order.client or not order.client.phone:
        return False
    
    phone = order.client.phone
    sent = send_b2b_sms(phone, flow_key, variables_dict)
    
    preview_parts = [f"{k}: {v}" for k, v in variables_dict.items()]
    preview = f"DLT Flow [{flow_key}] &rarr; " + ", ".join(preview_parts)
    
    log = B2BCommunicationLog(
        order_id=order.id,
        client_id=order.client.id,
        channel='sms',
        event_type=event_type,
        recipient=phone,
        subject=f"DLT SMS: {flow_key}",
        message_preview=preview,
        status='sent' if sent else 'simulated'
    )
    db.session.add(log)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return sent


# =========================================================================
# 1. B2B PIPELINE KANBAN DASHBOARD & ORDERS LIST
# =========================================================================
def get_b2b_product_options():
    """Generate rich edition options for Quotation Builder and Order Creation Modals."""
    boxes = B2BProduct.query.filter_by(is_active=True).order_by(B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    product_options = []
    for b in boxes:
        has_assorted = (b.price_assorted and b.price_assorted > 0 and b.price_assorted != b.price_premium)
        comp_prem = (b.composition_premium or '').replace('\r\n', ', ').replace('\n', ', ').strip()
        comp_assort = (b.composition_assorted or '').replace('\r\n', ', ').replace('\n', ', ').strip()

        if b.id == 12: # Curated Drawer Gift Set — Sixfold
            prem_label = 'Assorted Bliss Bites (6 Jars)'
            assort_label = 'Just Nuts & Dried Fruits (6 Jars)'
            product_options.append({
                'opt_id': f"{b.id}__assorted_bites",
                'product_id': b.id,
                'edition': prem_label,
                'name': f"{b.name} — {prem_label}",
                'box_type': f"{b.name} ({prem_label})",
                'category': b.category,
                'price': b.price_premium,
                'desc': comp_prem if comp_prem else "Mini Signature, Core, Sesame Date, Peanut, Cashew Almond & Dark Choco Bliss Bites",
                'display_label': f"{b.name} — {prem_label} (₹{int(b.price_premium) if b.price_premium.is_integer() else b.price_premium})"
            })
            product_options.append({
                'opt_id': f"{b.id}__just_nuts",
                'product_id': b.id,
                'edition': assort_label,
                'name': f"{b.name} — {assort_label}",
                'box_type': f"{b.name} ({assort_label})",
                'category': b.category,
                'price': b.price_assorted,
                'desc': comp_assort if comp_assort else "Premium Cashews, California Almonds, Roasted Pistachios, Walnut Kernels, Golden Raisins & Dried Figs",
                'display_label': f"{b.name} — {assort_label} (₹{int(b.price_assorted) if b.price_assorted.is_integer() else b.price_assorted})"
            })
        elif has_assorted:
            product_options.append({
                'opt_id': f"{b.id}__premium",
                'product_id': b.id,
                'edition': 'Premium Edition',
                'name': f"{b.name} — Premium Edition",
                'box_type': f"{b.name} (Premium Edition)",
                'category': b.category,
                'price': b.price_premium,
                'desc': comp_prem if comp_prem else f"Premium handcrafted curation ({b.bites_count} bites)",
                'display_label': f"{b.name} — Premium Edition (₹{int(b.price_premium) if b.price_premium.is_integer() else b.price_premium})"
            })
            product_options.append({
                'opt_id': f"{b.id}__assorted",
                'product_id': b.id,
                'edition': 'Assorted Edition',
                'name': f"{b.name} — Assorted Edition",
                'box_type': f"{b.name} (Assorted Edition)",
                'category': b.category,
                'price': b.price_assorted,
                'desc': comp_assort if comp_assort else f"Assorted classic curation ({b.bites_count} bites)",
                'display_label': f"{b.name} — Assorted Edition (₹{int(b.price_assorted) if b.price_assorted.is_integer() else b.price_assorted})"
            })
        else:
            product_options.append({
                'opt_id': f"{b.id}__standard",
                'product_id': b.id,
                'edition': 'Standard',
                'name': b.name,
                'box_type': b.name,
                'category': b.category,
                'price': b.price_premium,
                'desc': comp_prem if comp_prem else (b.description or f"{b.category} curated hamper"),
                'display_label': f"{b.name} (₹{int(b.price_premium) if b.price_premium.is_integer() else b.price_premium})"
            })
    return product_options


@b2b_admin_bp.route('/')
@b2b_admin_bp.route('/dashboard')
@admin_required
def dashboard():
    all_orders = B2BOrder.query.order_by(B2BOrder.updated_at.desc()).all()
    all_clients = B2BClient.query.filter_by(is_archived=False).order_by(B2BClient.company_name.asc()).all()
    all_products = B2BProduct.query.filter_by(is_active=True).all()
    product_options = get_b2b_product_options()

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
        product_options=product_options,
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
    all_clients = B2BClient.query.filter_by(is_archived=False).order_by(B2BClient.company_name.asc()).all()
    product_options = get_b2b_product_options()

    return render_template(
        'admin/b2b/orders.html',
        orders=all_orders,
        current_stage=current_stage,
        search_query=search_query,
        stage_counts=stage_counts,
        boxes=boxes,
        product_options=product_options,
        clients=all_clients
    )


# =========================================================================
# 2. ORDER DETAILS & STAGE ACTION TRANSITIONS
# =========================================================================
@b2b_admin_bp.route('/orders/<int:order_id>')
@admin_required
def order_detail(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    boxes = B2BProduct.query.filter_by(is_active=True).order_by(B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    product_options = get_b2b_product_options()

    gift_box_options = [opt for opt in product_options if opt['category'] != 'Hampers & Gift Sets']
    hamper_options = [opt for opt in product_options if opt['category'] == 'Hampers & Gift Sets']

    # Ensure items exist for existing orders
    if len(order.items) == 0 and (order.box_count > 0 or order.quoted_price_per_box > 0 or order.total_amount > 0):
        matched_prod = next((p for p in boxes if p.name.lower() in (order.box_type or '').lower()), None)
        qty = order.box_count if order.box_count > 0 else 50
        rate = order.quoted_price_per_box if order.quoted_price_per_box > 0 else (order.total_amount / qty if qty else 0.0)
        item = B2BOrderItem(
            order_id=order.id,
            product_id=matched_prod.id if matched_prod else None,
            item_name=order.box_type or "Curated Corporate Hamper",
            item_category=matched_prod.category if matched_prod else "Corporate Gifting",
            description=matched_prod.description if matched_prod else (order.custom_message or "Luxury rigid box with custom festive sleeve branding"),
            quantity=qty,
            unit_price=rate,
            total_price=round(qty * rate, 2)
        )
        db.session.add(item)
        if not order.subtotal_amount:
            order.subtotal_amount = item.total_price
        db.session.commit()

    return render_template('admin/b2b/order_detail.html', order=order, boxes=boxes, available_boxes=boxes, product_options=product_options, gift_box_options=gift_box_options, hamper_options=hamper_options)


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

    # Trigger Omnichannel (SMS + Email) notification if applicable
    if order.client:
        if new_stage == 'advance_paid':
            dispatch_b2b_sms_and_log(order, 'advance_paid', 'confirmed', {
                'client_name': order.client.contact_name or order.client.company_name,
                'order_number': order.order_number,
                'box_count': str(order.box_count)
            })
            if order.client.email:
                send_advance_received_email(order)
        elif new_stage == 'design_review':
            dispatch_b2b_sms_and_log(order, 'design_ready', 'design_ready', {
                'client_name': order.client.contact_name or order.client.company_name,
                'order_number': order.order_number
            })
            if order.client.email:
                send_design_proof_email(order)
        elif new_stage == 'production':
            dispatch_b2b_sms_and_log(order, 'production_eta', 'production', {
                'client_name': order.client.contact_name or order.client.company_name,
                'order_number': order.order_number
            })
            if order.client.email:
                send_production_eta_email(order)
        elif new_stage == 'delivered':
            dispatch_b2b_sms_and_log(order, 'delivered', 'delivered', {
                'client_name': order.client.contact_name or order.client.company_name,
                'order_number': order.order_number
            })
            if order.client.email:
                send_order_delivered_email(order)

    flash(f"Order #{order.order_number} moved to '{order.get_stage_display()}'.", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/mark-advance-paid', methods=['POST'])
@b2b_admin_bp.route('/orders/<int:order_id>/advance', methods=['POST'])
@admin_required
def mark_advance_paid(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    order.advance_paid = True
    order.advance_paid_at = datetime.utcnow()
    
    # Custom advance amount override if provided in modal/form
    adv_input = request.form.get('advance_amount')
    if adv_input:
        try:
            order.advance_amount_required = float(adv_input)
        except (ValueError, TypeError):
            pass

    old_stage = order.stage
    adv_pct = order.advance_percent_calc
    adv_str = f"₹{order.advance_amount_required:,.2f}"

    if order.stage in ('enquiry', 'quotation_sent'):
        order.stage = 'advance_paid'
        order.add_log(
            action_title=f"{adv_pct}% Advance Confirmed & Order Locked",
            from_stage=old_stage,
            to_stage='advance_paid',
            actor=f"{current_user.name} (Admin)",
            details=f"Payment received: {adv_str} ({adv_pct}% advance requirement met)"
        )
    else:
        order.add_log(
            action_title="Advance Payment Marked as Paid",
            actor=f"{current_user.name} (Admin)",
            details=f"Payment received: {adv_str}"
        )

    db.session.commit()

    # Omnichannel Notifications (SMS + Email)
    if order.client and order.client.phone:
        dispatch_b2b_sms_and_log(order, 'advance_paid', 'confirmed', {
            'client_name': order.client.contact_name or order.client.company_name,
            'order_number': order.order_number,
            'box_count': str(order.box_count)
        })

    if order.client and order.client.email:
        send_advance_received_email(order, advance_amount=order.advance_amount_required)

    flash(f"Advance payment ({adv_str}) for #{order.order_number} confirmed! Client notified via SMS & Email.", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/quotation-builder', methods=['POST'])
@b2b_admin_bp.route('/orders/<int:order_id>/update-quote', methods=['POST'])
@admin_required
def update_quotation_builder(order_id):
    order = B2BOrder.query.get_or_404(order_id)

    # 1. Advance Percentage (Dynamic, not hardcoded to 50%)
    try:
        adv_pct = float(request.form.get('advance_percent', order.advance_percent or 50.0))
    except (ValueError, TypeError):
        adv_pct = 50.0
    order.advance_percent = max(0.0, min(100.0, adv_pct))

    # 2. Optional Discount Type & Value
    discount_type = request.form.get('discount_type', 'flat') # 'flat' or 'percent'
    try:
        discount_input = float(request.form.get('discount_value', 0.0))
    except (ValueError, TypeError):
        discount_input = 0.0
    discount_input = max(0.0, discount_input)

    # 3. Occasion, Notes, ETA
    order.custom_occasion = request.form.get('custom_occasion', order.custom_occasion)
    order.custom_message = request.form.get('custom_message', order.custom_message)
    order.internal_notes = request.form.get('internal_notes', order.internal_notes)
    order.eta_date = request.form.get('eta_date', order.eta_date)
    order.payment_link = request.form.get('payment_link', order.payment_link)

    # 4. Multi-Item Line Builder
    item_names = request.form.getlist('item_name[]')
    product_ids = request.form.getlist('product_id[]')
    categories = request.form.getlist('item_category[]')
    descriptions = request.form.getlist('item_description[]')
    quantities = request.form.getlist('item_quantity[]')
    unit_prices = request.form.getlist('item_unit_price[]')

    # If single item from legacy form fields
    if not item_names and request.form.get('box_type'):
        item_names = [request.form.get('box_type')]
        product_ids = ['']
        categories = ['Corporate Gifting']
        descriptions = [order.custom_message or '']
        quantities = [request.form.get('box_count', '50')]
        unit_prices = [request.form.get('quoted_price_per_box', '0.0')]

    # Reset items
    B2BOrderItem.query.filter_by(order_id=order.id).delete()

    subtotal = 0.0
    total_boxes = 0
    primary_box_name = order.box_type

    if item_names and len(item_names) > 0:
        for i in range(len(item_names)):
            name = item_names[i].strip()
            if not name:
                continue

            p_id = None
            if i < len(product_ids) and product_ids[i]:
                raw_pid = str(product_ids[i]).split('__')[0].strip()
                if raw_pid.isdigit():
                    p_id = int(raw_pid)

            cat = categories[i].strip() if i < len(categories) else 'Corporate Gifting'
            desc = descriptions[i].strip() if i < len(descriptions) else ''

            try:
                qty = int(quantities[i]) if i < len(quantities) else 50
            except (ValueError, TypeError):
                qty = 50
            qty = max(1, qty)

            try:
                rate = float(unit_prices[i]) if i < len(unit_prices) else 0.0
            except (ValueError, TypeError):
                rate = 0.0
            rate = max(0.0, rate)

            line_tot = round(qty * rate, 2)
            subtotal += line_tot
            total_boxes += qty

            if i == 0:
                primary_box_name = name

            new_item = B2BOrderItem(
                order_id=order.id,
                product_id=p_id,
                item_name=name,
                item_category=cat,
                description=desc,
                quantity=qty,
                unit_price=rate,
                total_price=line_tot
            )
            db.session.add(new_item)

    # Compute discount
    if discount_type == 'percent':
        order.discount_percent = discount_input
        order.discount_amount = round(subtotal * (discount_input / 100.0), 2)
    else:
        order.discount_amount = min(subtotal, discount_input)
        order.discount_percent = round((order.discount_amount / subtotal * 100.0), 1) if subtotal > 0 else 0.0

    # Strict discount logic: if <= 0, reset to 0 so it DOES NOT appear on PDF
    if order.discount_amount <= 0:
        order.discount_amount = 0.0
        order.discount_percent = 0.0

    order.subtotal_amount = round(subtotal, 2)
    taxable_val = max(0.0, round(subtotal - order.discount_amount, 2))
    total_tax = round(taxable_val * 0.05, 2)
    order.total_amount = round(taxable_val + total_tax, 2)
    order.advance_amount_required = round(order.total_amount * (order.advance_percent / 100.0), 2)

    order.box_type = primary_box_name
    order.box_count = total_boxes
    order.quoted_price_per_box = round(order.total_amount / total_boxes, 2) if total_boxes > 0 else 0.0

    # Auto transition to quotation_sent if in enquiry
    if order.stage == 'enquiry':
        old_stage = order.stage
        order.stage = 'quotation_sent'
        order.add_log(
            action_title="Quotation Configured in Builder",
            from_stage=old_stage,
            to_stage='quotation_sent',
            actor=f"{current_user.name} (Admin)",
            details=f"Subtotal: ₹{order.subtotal_amount:,.2f} | Discount: ₹{order.discount_amount:,.2f} | GST (5%): ₹{total_tax:,.2f} | Total: ₹{order.total_amount:,.2f} | Advance ({order.advance_percent}%): ₹{order.advance_amount_required:,.2f}"
        )
    else:
        order.add_log(
            action_title="Quotation Values Updated via Builder",
            actor=f"{current_user.name} (Admin)",
            details=f"Subtotal: ₹{order.subtotal_amount:,.2f} | Discount: ₹{order.discount_amount:,.2f} | GST (5%): ₹{total_tax:,.2f} | Total: ₹{order.total_amount:,.2f} | Advance ({order.advance_percent}%): ₹{order.advance_amount_required:,.2f}"
        )

    db.session.commit()
    flash(f"Quotation for #{order.order_number} saved successfully! (Total: ₹{order.total_amount:,.2f})", 'success')
    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/quotation-pdf')
@admin_required
def download_quotation_pdf(order_id):
    """Streams or downloads the luxury branded Quotation PDF."""
    order = B2BOrder.query.get_or_404(order_id)
    pdf_bytes = generate_quotation_pdf(order)

    filename = f"Quotation-{order.order_number}.pdf"
    as_attachment = request.args.get('download', '0') == '1'

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=as_attachment,
        download_name=filename
    )


@b2b_admin_bp.route('/orders/<int:order_id>/send-quotation', methods=['POST'])
@admin_required
def send_quotation(order_id):
    """Generates Quotation PDF and dispatches dual Email (with PDF attached) + SMS."""
    order = B2BOrder.query.get_or_404(order_id)
    if not order.client:
        flash("No client associated with this order.", "danger")
        return redirect(url_for('b2b_admin.order_detail', order_id=order.id))

    pdf_bytes = generate_quotation_pdf(order)
    filename = f"Quotation-{order.order_number}.pdf"

    # 1. Send Email with PDF
    email_sent, email_msg = False, "No client email"
    if order.client.email:
        email_sent, email_msg = send_quotation_email(order, pdf_bytes, filename=filename)

    # 2. Send SMS notification
    if order.client.phone:
        dispatch_b2b_sms_and_log(
            order,
            event_type='quotation',
            flow_key='quotation',
            variables_dict={
                'client_name': order.client.contact_name or order.client.company_name,
                'order_number': order.order_number,
                'total_amount': f"₹{order.total_amount:,.2f}"
            }
        )

    # Update stage if in enquiry
    if order.stage == 'enquiry':
        old_stage = order.stage
        order.stage = 'quotation_sent'
        order.add_log(
            action_title="Commercial Quotation Dispatched (Email + SMS)",
            from_stage=old_stage,
            to_stage='quotation_sent',
            actor=f"{current_user.name} (Admin)",
            details=f"Dispatched quotation PDF (₹{order.total_amount:,.2f}) to {order.client.email} & SMS to {order.client.phone}"
        )
    else:
        order.add_log(
            action_title="Commercial Quotation Re-Dispatched (Email + SMS)",
            actor=f"{current_user.name} (Admin)",
            details=f"Re-sent quotation PDF to {order.client.email} & SMS to {order.client.phone}"
        )

    db.session.commit()

    if email_sent:
        flash(f"Quotation PDF successfully emailed to {order.client.email} and SMS dispatched!", 'success')
    else:
        flash(f"Quotation SMS dispatched. Email delivery status: {email_msg}", 'warning')

    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/send-welcome-email', methods=['POST'])
@admin_required
def send_welcome_email(order_id):
    """Sends onboarding welcome email directing client to log into their portal with their phone number."""
    order = B2BOrder.query.get_or_404(order_id)
    if not order.client:
        flash("No client associated with this order.", "danger")
        return redirect(url_for('b2b_admin.order_detail', order_id=order.id))

    success, msg = send_welcome_onboarding_email(order.client, order)
    if success:
        flash(f"Welcome & Portal Access email dispatched to {order.client.email}!", "success")
    else:
        flash(f"Failed to send welcome email: {msg}", "danger")

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
        if order.stage in ('advance_paid', 'enquiry', 'quotation_sent'):
            order.stage = 'design_review'
            order.add_log(
                action_title="Design Proof Uploaded & Ready for Client Review",
                from_stage=old_stage,
                to_stage='design_review',
                actor=f"{current_user.name} (Admin)",
                details="Uploaded high-res sleeve mockup for corporate approval."
            )
            if order.client and order.client.phone:
                dispatch_b2b_sms_and_log(order, 'design_ready', 'design_ready', {
                    'client_name': order.client.contact_name or order.client.company_name,
                    'order_number': order.order_number
                })
            if order.client and order.client.email:
                send_design_proof_email(order)
        else:
            order.add_log(
                action_title="Design Proof Updated",
                actor=f"{current_user.name} (Admin)",
                details="Updated artwork mockup for client portal."
            )

        db.session.commit()
        flash(f"Design proof uploaded for Order #{order.order_number}! Client notified via SMS & Email.", 'success')
    else:
        flash("No design proof file or URL provided.", 'warning')

    return redirect(url_for('b2b_admin.order_detail', order_id=order.id))


@b2b_admin_bp.route('/orders/<int:order_id>/lock-details', methods=['POST'])
@admin_required
def lock_details(order_id):
    order = B2BOrder.query.get_or_404(order_id)
    try:
        order.box_count = int(request.form.get('box_count', order.box_count))
    except (ValueError, TypeError):
        pass
    order.eta_date = request.form.get('eta_date', order.eta_date)

    old_stage = order.stage
    order.stage = 'details_locked'
    order.add_log(
        action_title="Design & Final Quantity Locked for Production",
        from_stage=old_stage,
        to_stage='details_locked',
        actor=f"{current_user.name} (Admin)",
        details=f"Locked at {order.box_count} boxes. Target ETA: {order.eta_date or 'TBD'}."
    )
    db.session.commit()

    if order.client and order.client.phone:
        dispatch_b2b_sms_and_log(order, 'production_eta', 'production', {
            'client_name': order.client.contact_name or order.client.company_name,
            'order_number': order.order_number
        })
    if order.client and order.client.email:
        send_production_eta_email(order)

    flash(f"Order #{order.order_number} locked for production. Client notified via SMS & Email.", 'success')
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
        dispatch_b2b_sms_and_log(order, 'delivered', 'delivered', {
            'client_name': order.client.contact_name or order.client.company_name,
            'order_number': order.order_number
        })
    if order.client and order.client.email:
        send_order_delivered_email(order)

    flash(f"Order #{order.order_number} marked as Delivered! Client notified via SMS & Email.", 'success')
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


@b2b_admin_bp.route('/orders/create', methods=['POST'])
@b2b_admin_bp.route('/orders/new', methods=['POST'])
@admin_required
def create_order():
    client_id = request.form.get('client_id')
    
    # Check if this is an inline client creation or existing client
    if not client_id or client_id == 'new':
        company_name = request.form.get('new_company_name', '').strip()
        contact_name = request.form.get('new_contact_name', '').strip()
        raw_phone = request.form.get('new_phone', '').strip()
        phone = normalize_phone(raw_phone)
        email = request.form.get('new_email', '').strip()
        gst_number = request.form.get('new_gst_number', '').strip()
        shipping_address = request.form.get('new_shipping_address', '').strip()
        industry = request.form.get('new_industry', '').strip()

        if not company_name or not contact_name or not phone or not email:
            flash('To onboard and create an order, Company Name, Contact Name, Mobile Number, and Email are required.', 'danger')
            return redirect(request.referrer or url_for('b2b_admin.orders'))

        client = B2BClient.query.filter_by(phone=phone).first()
        if not client:
            client = B2BClient(
                company_name=company_name,
                contact_name=contact_name,
                phone=phone,
                email=email,
                gst_number=gst_number,
                shipping_address=shipping_address,
                industry=industry
            )
            db.session.add(client)
            db.session.commit()
            if client.email:
                send_welcome_onboarding_email(client)
    else:
        client = B2BClient.query.get_or_404(int(client_id))

    # Parse product & edition selection
    product_option_key = request.form.get('product_option_key', '').strip()
    custom_occasion = request.form.get('custom_occasion', '').strip() or 'Corporate Celebration'
    custom_message = request.form.get('custom_message', '').strip()
    notes = request.form.get('internal_notes', '').strip() or request.form.get('notes', '').strip()
    stage = request.form.get('stage', 'enquiry').strip()
    eta_date = request.form.get('eta_date', '').strip()
    
    valid_stages = ['enquiry', 'quotation_sent', 'advance_paid', 'design_review', 'details_locked', 'production', 'delivered', 'cancelled']
    if stage not in valid_stages:
        stage = 'enquiry'

    try:
        box_count = int(request.form.get('box_count', 50))
        if box_count <= 0:
            box_count = 50
    except (ValueError, TypeError):
        box_count = 50

    try:
        advance_percent = float(request.form.get('advance_percent', 50.0))
        if advance_percent < 0 or advance_percent > 100:
            advance_percent = 50.0
    except (ValueError, TypeError):
        advance_percent = 50.0

    # Look up product option or fallback
    all_options = get_b2b_product_options()
    selected_opt = next((opt for opt in all_options if opt['opt_id'] == product_option_key), None)

    rate_input = request.form.get('quoted_price_per_box', '').strip()
    if rate_input:
        try:
            unit_price = float(rate_input)
        except (ValueError, TypeError):
            unit_price = selected_opt['price'] if selected_opt else 345.0
    else:
        unit_price = selected_opt['price'] if selected_opt else 345.0

    if selected_opt:
        box_type = selected_opt['box_type']
        item_name = selected_opt['name']
        product_id = selected_opt['product_id']
        category = selected_opt['category']
        desc = selected_opt['desc']
    else:
        # Fallback to direct box_type input if specified
        raw_box_type = request.form.get('box_type', '').strip()
        matched_box = B2BProduct.query.filter_by(name=raw_box_type).first() if raw_box_type else None
        if matched_box:
            box_type = matched_box.name
            item_name = matched_box.name
            product_id = matched_box.id
            category = matched_box.category
            desc = matched_box.description or matched_box.composition_premium or 'Curated gift box'
            if not rate_input:
                unit_price = matched_box.price_premium
        else:
            box_type = raw_box_type or 'Curated Corporate Hamper'
            item_name = box_type
            product_id = None
            category = 'Corporate Gift Box'
            desc = notes or 'Handcrafted corporate celebration curation'

    # Compute financials (Subtotal, 5% GST, Advance Amount)
    subtotal = round(unit_price * box_count, 2)
    total_amount = round(subtotal * 1.05, 2)
    advance_amount_required = round(total_amount * (advance_percent / 100.0), 2)

    order = B2BOrder(
        order_number=B2BOrder.generate_order_number(),
        client_id=client.id,
        box_type=box_type,
        box_count=box_count,
        custom_occasion=custom_occasion,
        custom_message=custom_message,
        quoted_price_per_box=unit_price,
        subtotal_amount=subtotal,
        discount_amount=0.0,
        discount_percent=0.0,
        advance_percent=advance_percent,
        total_amount=total_amount,
        advance_amount_required=advance_amount_required,
        stage=stage,
        eta_date=eta_date,
        internal_notes=notes
    )
    db.session.add(order)
    db.session.flush()

    # Create initial line item for Quotation Builder
    line_item = B2BOrderItem(
        order_id=order.id,
        product_id=product_id,
        item_name=item_name,
        item_category=category,
        description=desc,
        quantity=box_count,
        unit_price=unit_price,
        total_price=subtotal
    )
    db.session.add(line_item)

    actor_name = getattr(current_user, 'name', None) or 'Admin'
    order.add_log(
        action_title=f"Order Initiated on Behalf of Client ({order.get_stage_display()})",
        to_stage=stage,
        from_stage=None,
        actor=f"{actor_name} (Admin)",
        details=f"Created order for {client.company_name}: {box_count}x {box_type} @ ₹{unit_price:.2f}/box. Subtotal: ₹{subtotal:,.2f}, Total (incl. 5% GST): ₹{total_amount:,.2f}, Advance ({advance_percent:.1f}%): ₹{advance_amount_required:,.2f}."
    )

    db.session.commit()

    flash(f'Successfully created Order #{order.order_number} on behalf of {client.company_name}! You can now customize or review the quotation.', 'success')
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
    order.advance_amount_required = round(order.total_amount * ((order.advance_percent or 50.0) / 100.0), 2)
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
# 3. CORPORATE CLIENTS DIRECTORY
# =========================================================================
@b2b_admin_bp.route('/clients')
@admin_required
def clients():
    current_status = request.args.get('status', 'active').strip().lower()
    search_query = request.args.get('q', '').strip()

    base_query = B2BClient.query

    if search_query:
        base_query = base_query.filter(
            (B2BClient.company_name.ilike(f'%{search_query}%')) |
            (B2BClient.contact_name.ilike(f'%{search_query}%')) |
            (B2BClient.phone.ilike(f'%{search_query}%')) |
            (B2BClient.email.ilike(f'%{search_query}%')) |
            (B2BClient.gst_number.ilike(f'%{search_query}%'))
        )

    if current_status == 'archived':
        clients_query = base_query.filter_by(is_archived=True)
    elif current_status == 'all':
        clients_query = base_query
    else:
        current_status = 'active'
        clients_query = base_query.filter_by(is_archived=False)

    all_clients = clients_query.order_by(B2BClient.created_at.desc()).all()

    # Calculate status counts across all clients
    all_db_clients = B2BClient.query.all()
    active_count = sum(1 for c in all_db_clients if not c.is_archived)
    archived_count = sum(1 for c in all_db_clients if c.is_archived)
    total_count = len(all_db_clients)

    available_boxes = B2BProduct.query.filter_by(is_active=True).all()

    return render_template(
        'admin/b2b/clients.html',
        clients=all_clients,
        current_status=current_status,
        search_query=search_query,
        active_count=active_count,
        archived_count=archived_count,
        total_count=total_count,
        available_boxes=available_boxes
    )


@b2b_admin_bp.route('/clients/<int:client_id>')
@admin_required
def client_detail(client_id):
    client = B2BClient.query.get_or_404(client_id)
    boxes = B2BProduct.query.filter_by(is_active=True).all()
    product_options = get_b2b_product_options()
    return render_template('admin/b2b/client_detail.html', client=client, boxes=boxes, product_options=product_options)


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

    # Automatically dispatch Welcome & Portal Access email
    if client.email:
        send_welcome_onboarding_email(client)

    # Check if initial batch / order details were provided during onboarding
    box_type = request.form.get('box_type', '').strip()
    raw_count = request.form.get('box_count', '').strip()
    raw_rate = request.form.get('quoted_price_per_box', '').strip()
    try:
        box_count = int(raw_count) if raw_count else 0
    except ValueError:
        box_count = 0
    try:
        quoted_price = float(raw_rate) if raw_rate else 0.0
    except ValueError:
        quoted_price = 0.0

    if box_type or box_count > 0:
        if box_count <= 0:
            box_count = 50
        matched_prod = B2BProduct.query.filter_by(name=box_type).first()
        if not quoted_price and matched_prod:
            quoted_price = matched_prod.price_premium
        subtotal = round(box_count * quoted_price, 2)
        total_amount = round(subtotal * 1.05, 2)
        advance_amount = round(total_amount * 0.5, 2)
        order = B2BOrder(
            order_number=B2BOrder.generate_order_number(),
            client_id=client.id,
            box_type=box_type or (matched_prod.name if matched_prod else "Curated Corporate Hamper"),
            box_count=box_count,
            custom_occasion=request.form.get('custom_occasion', 'Corporate Celebration').strip(),
            quoted_price_per_box=quoted_price,
            subtotal_amount=subtotal,
            advance_percent=50.0,
            total_amount=total_amount,
            advance_amount_required=advance_amount,
            stage='enquiry',
            internal_notes=notes
        )
        db.session.add(order)
        db.session.flush()

        line_item = B2BOrderItem(
            order_id=order.id,
            product_id=matched_prod.id if matched_prod else None,
            item_name=box_type or (matched_prod.name if matched_prod else "Curated Corporate Hamper"),
            item_category=matched_prod.category if matched_prod else "Corporate Gift Box",
            description=matched_prod.description if matched_prod else (notes or "Corporate Gifting Box"),
            quantity=box_count,
            unit_price=quoted_price,
            total_price=subtotal
        )
        db.session.add(line_item)
        actor_name = getattr(current_user, 'name', None) or 'Admin'
        order.add_log(
            action_title="Client Onboarded & Initial Batch Created",
            to_stage='enquiry',
            from_stage='enquiry',
            actor=f"{actor_name} (Admin)",
            details=f"Onboarded client {client.company_name} with initial order: {box_count}x {order.box_type} @ ₹{quoted_price}."
        )
        db.session.commit()
        flash(f'Corporate client "{company_name}" onboarded & order #{order.order_number} created! You can now build the quotation.', 'success')
        return redirect(url_for('b2b_admin.order_detail', order_id=order.id))

    flash(f'Corporate client "{company_name}" onboarded successfully! Welcome email dispatched.', 'success')
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


@b2b_admin_bp.route('/clients/<int:client_id>/archive', methods=['POST'])
@admin_required
def archive_client(client_id):
    client = B2BClient.query.get_or_404(client_id)
    client.is_archived = True
    client.archived_at = datetime.utcnow()
    db.session.commit()
    flash(f'Corporate client "{client.company_name}" has been archived. All order history and tax records remain preserved.', 'info')
    
    referrer = request.referrer or ''
    if f'/clients/{client.id}' in referrer:
        return redirect(url_for('b2b_admin.client_detail', client_id=client.id))
    return redirect(url_for('b2b_admin.clients', status='archived'))


@b2b_admin_bp.route('/clients/<int:client_id>/restore', methods=['POST'])
@admin_required
def restore_client(client_id):
    client = B2BClient.query.get_or_404(client_id)
    client.is_archived = False
    client.archived_at = None
    db.session.commit()
    flash(f'Corporate client "{client.company_name}" has been restored to active status.', 'success')
    
    referrer = request.referrer or ''
    if f'/clients/{client.id}' in referrer:
        return redirect(url_for('b2b_admin.client_detail', client_id=client.id))
    return redirect(url_for('b2b_admin.clients', status='active'))


@b2b_admin_bp.route('/clients/<int:client_id>/delete', methods=['POST'])
@admin_required
def delete_client(client_id):
    client = B2BClient.query.get_or_404(client_id)
    company_name = client.company_name
    order_count = len(client.orders)
    
    db.session.delete(client)
    db.session.commit()
    
    if order_count > 0:
        flash(f'Corporate client "{company_name}" and its {order_count} associated order record(s) have been permanently deleted.', 'warning')
    else:
        flash(f'Corporate client "{company_name}" has been permanently deleted.', 'info')
        
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


# --- Dedicated Product Photos & Galleries Desk ---
@b2b_admin_bp.route('/photos')
@admin_required
def product_photos():
    category_filter = request.args.get('category', '').strip()
    search_q = request.args.get('q', '').strip()
    
    query = B2BProduct.query
    if category_filter:
        query = query.filter_by(category=category_filter)
    if search_q:
        query = query.filter(B2BProduct.name.ilike(f'%{search_q}%'))
        
    products = query.order_by(B2BProduct.category.asc(), B2BProduct.display_order.asc(), B2BProduct.id.asc()).all()
    
    all_categories = [r[0] for r in db.session.query(B2BProduct.category).distinct().all() if r[0]]
    all_products = B2BProduct.query.all()
    total_products = len(all_products)
    total_gallery_photos = sum(len(p.gallery_images) for p in all_products)
    hamper_photos_count = sum(len(p.gallery_images) for p in all_products if p.category == 'Hampers & Gift Sets')
    
    return render_template(
        'admin/b2b/product_photos.html',
        products=products,
        categories=all_categories,
        selected_category=category_filter,
        search_q=search_q,
        total_products=total_products,
        total_gallery_photos=total_gallery_photos,
        hamper_photos_count=hamper_photos_count
    )


@b2b_admin_bp.route('/products/<int:product_id>/cover', methods=['POST'])
@admin_required
def update_product_cover(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    return_to = request.form.get('return_to', 'photos')
    
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
        
    if image_url:
        product.image_url = image_url
        db.session.commit()
        flash(f'Primary cover photo updated for {product.name}!', 'success')
    else:
        flash('No image file or URL was provided.', 'warning')
        
    if return_to == 'photos':
        return redirect(url_for('b2b_admin.product_photos') + f'#product-{product.id}')
    return redirect(url_for('b2b_admin.product_manage', product_id=product.id))


@b2b_admin_bp.route('/products/<int:product_id>/images/add', methods=['POST'])
@admin_required
def add_product_image(product_id):
    product = B2BProduct.query.get_or_404(product_id)
    caption = request.form.get('caption', '').strip()
    return_to = request.form.get('return_to', 'manage')
    
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
        if return_to == 'photos':
            return redirect(url_for('b2b_admin.product_photos') + f'#product-{product.id}')
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
    if return_to == 'photos':
        return redirect(url_for('b2b_admin.product_photos') + f'#product-{product.id}')
    return redirect(url_for('b2b_admin.product_manage', product_id=product.id))


@b2b_admin_bp.route('/products/images/<int:image_id>/delete', methods=['POST'])
@admin_required
def delete_product_image(image_id):
    img = B2BProductImage.query.get_or_404(image_id)
    product_id = img.product_id
    return_to = request.form.get('return_to', request.args.get('return_to', 'manage'))
    db.session.delete(img)
    db.session.commit()
    flash('Gallery image deleted.', 'info')
    if return_to == 'photos':
        return redirect(url_for('b2b_admin.product_photos') + f'#product-{product_id}')
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
