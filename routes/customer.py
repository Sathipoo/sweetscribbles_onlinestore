from flask import Blueprint, render_template, request, redirect, url_for, session, current_app, flash
from flask_login import login_required, current_user
from models.product import Product, Collection
from models.order import Order, OrderItem
from models.coupon import Coupon
from extensions import db
from utils.gcp_storage import upload_file
from utils.zoho_utils import ZohoClient
import uuid
import os
from datetime import datetime
from utils.blog_data import BLOGS

customer_bp = Blueprint('customer', __name__)

def deduct_order_stock(order):
    """
    Helper to deduct stock for order items (bites and choco only).
    Ensures that we don't deduct multiple times.
    """
    if order.is_stock_deducted:
        return
        
    for item in order.items:
        product = item.product
        if product and product.category in ('bites', 'choco'):
            product.available_qty = max(0, product.available_qty - item.quantity)
            
    order.is_stock_deducted = True
    db.session.commit()


@customer_bp.route('/')
def home():
    featured_products = Product.query.filter_by(category='bites', is_active=True).limit(4).all()
    bites_products = Product.query.filter_by(category='bites', is_active=True).all()
    choco_products = Product.query.filter_by(category='choco', is_active=True).all()
    return render_template('customer/home.html', 
                           featured=featured_products, 
                           bites=bites_products, 
                           choco=choco_products)

@customer_bp.route('/collections')
def collections():
    all_collections = Collection.query.order_by(Collection.id).all()
    collections_data = []
    for col in all_collections:
        products = Product.query.filter_by(category=col.slug, is_active=True).order_by(Product.id.desc()).all()
        collections_data.append({
            'collection': col,
            'products': products
        })
    return render_template('customer/collections.html', collections=collections_data)

@customer_bp.route('/product/<int:product_id>', methods=['GET', 'POST'])
def product_detail(product_id):
    product = Product.query.filter_by(id=product_id, is_active=True).first_or_404()
    if request.method == 'POST':
        qty = int(request.form.get('quantity', 1))
        
        # Enforce stock checks for bites and choco categories
        if product.category in ('bites', 'choco'):
            if product.available_qty <= 0:
                flash(f'Sorry, "{product.name}" is currently out of stock.', 'danger')
                return redirect(url_for('customer.product_detail', product_id=product.id))
            if qty > product.available_qty:
                flash(f'Sorry, only {product.available_qty} units of "{product.name}" are in stock.', 'warning')
                return redirect(url_for('customer.product_detail', product_id=product.id))
                
        custom_message = request.form.get('custom_message', '')
        
        custom_logo_url = None
        if 'custom_logo' in request.files:
            file = request.files['custom_logo']
            if file.filename != '':
                custom_logo_url = upload_file(file, file.filename, folder="custom_logos")
        
        cart = session.get('cart', [])
        cart.append({
            'product_id': product.id,
            'quantity': qty,
            'custom_message': custom_message,
            'custom_logo_url': custom_logo_url
        })
        session['cart'] = cart
        return redirect(url_for('customer.cart'))
        
    return render_template('customer/product.html', product=product)

@customer_bp.route('/cart')
def cart():
    cart_items = session.get('cart', [])
    items_data = []
    total = 0
    for idx, item in enumerate(cart_items):
        prod = Product.query.get(item['product_id'])
        if prod:
            subtotal = prod.sale_price * item['quantity']
            total += subtotal
            items_data.append({
                'index': idx,
                'product': prod,
                'quantity': item['quantity'],
                'custom_message': item['custom_message'],
                'custom_logo_url': item['custom_logo_url'],
                'subtotal': subtotal
            })
            
    # Coupon Calculation
    discount = 0.0
    coupon_code = session.get('coupon_code')
    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code, is_active=True).first()
        if coupon and (not coupon.expiry_date or coupon.expiry_date > datetime.utcnow()):
            discount = coupon.calculate_discount(total)
        else:
            session.pop('coupon_code', None) # Clean stale coupon
            coupon_code = None
            
    grand_total = max(0.0, total - discount)
    return render_template('customer/cart.html', items=items_data, total=total, discount=discount, coupon_code=coupon_code, grand_total=grand_total)

@customer_bp.route('/cart/coupon', methods=['POST'])
def apply_coupon():
    action = request.form.get('action')
    if action == 'remove':
        session.pop('coupon_code', None)
        flash('Coupon code removed.', 'info')
    else:
        code = request.form.get('coupon_code', '').strip().upper()
        if not code:
            flash('Please enter a coupon code.', 'warning')
            return redirect(url_for('customer.cart'))
            
        coupon = Coupon.query.filter_by(code=code, is_active=True).first()
        if coupon and (not coupon.expiry_date or coupon.expiry_date > datetime.utcnow()):
            session['coupon_code'] = coupon.code
            flash(f'Coupon "{coupon.code}" applied successfully!', 'success')
        else:
            flash('Invalid or expired coupon code.', 'danger')
            
    return redirect(url_for('customer.cart'))

@customer_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart_items = session.get('cart', [])
    if not cart_items:
        return redirect(url_for('customer.home'))
        
    if request.method == 'POST':
        # Check stock levels for bites and choco products in cart
        cart_totals = {}
        for item in cart_items:
            pid = item['product_id']
            cart_totals[pid] = cart_totals.get(pid, 0) + item['quantity']
            
        for pid, total_qty in cart_totals.items():
            prod = Product.query.get(pid)
            if prod and prod.category in ('bites', 'choco'):
                if prod.available_qty <= 0:
                    flash(f'Sorry, "{prod.name}" has run out of stock. Please adjust your cart.', 'danger')
                    return redirect(url_for('customer.cart'))
                if total_qty > prod.available_qty:
                    flash(f'Sorry, only {prod.available_qty} units of "{prod.name}" are in stock, but your cart has {total_qty}.', 'warning')
                    return redirect(url_for('customer.cart'))
                    
        customer_name = request.form.get('name')
        customer_email = request.form.get('email')
        customer_phone = request.form.get('phone')
        shipping_address = request.form.get('shipping_address')
        
        order_number = f"SS{uuid.uuid4().hex[:6].upper()}"
        
        total_amount = 0
        order = Order(
            order_number=order_number,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            shipping_address=shipping_address,
            customer_id=current_user.id if current_user.is_authenticated else None,
            status='Pending',
            total_amount=0.0
        )
        db.session.add(order)
        db.session.flush() # get order id
        
        for item in cart_items:
            prod = Product.query.get(item['product_id'])
            if prod:
                subtotal = prod.sale_price * item['quantity']
                total_amount += subtotal
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=prod.id,
                    quantity=item['quantity'],
                    price_at_purchase=prod.sale_price,
                    custom_message=item['custom_message'],
                    custom_logo_url=item['custom_logo_url']
                )
                db.session.add(order_item)
                
        # Calculate discount for final amount
        discount = 0.0
        coupon_code = session.get('coupon_code')
        if coupon_code:
            coupon = Coupon.query.filter_by(code=coupon_code, is_active=True).first()
            if coupon and (not coupon.expiry_date or coupon.expiry_date > datetime.utcnow()):
                discount = coupon.calculate_discount(total_amount)
                session.pop('coupon_code', None) # Clear coupon after use
                
        order.total_amount = max(0.0, total_amount - discount)
        
        # Save details back to user profile if authenticated
        if current_user.is_authenticated:
            current_user.name = customer_name
            if customer_phone:
                current_user.phone = customer_phone
            if shipping_address:
                current_user.address = shipping_address
                
        db.session.commit()
        
        zoho = ZohoClient()
        try:
            payment_link, zoho_payment_link_id = zoho.create_payment_link({
                'order_id': order.order_number,
                'amount': order.total_amount,  # Fix: Use discounted total amount
                'customer_email': customer_email,
                'customer_phone': customer_phone,
                'customer_name': customer_name,
                'package': f"Order {order.order_number}"
            })
        except Exception as e:
            print("ERROR: Exception calling create_payment_link:", str(e))
            payment_link, zoho_payment_link_id = None, None
            
        if payment_link:
            order.payment_link = payment_link
            order.zoho_payment_link_id = zoho_payment_link_id
            db.session.commit()
            session.pop('cart', None)
            return redirect(payment_link)
        else:
            # Check if running in production
            is_prod = (
                current_app.config.get('ENV') == 'production'
                or os.environ.get('FLASK_ENV') == 'production'
                or ('localhost' not in request.host and '127.0.0.1' not in request.host)
            )
            
            if is_prod:
                flash("We are unable to initiate payment with Zoho Payments at this time. Please try again later.", "danger")
                # We do NOT pop 'cart' from session so the customer's cart is not lost.
                return redirect(url_for('customer.cart'))

            # Fallback to simulated payment flow for local development / Zoho error
            print("INFO: Falling back to simulated payment flow.")
            simulated_url = url_for('customer.simulate_payment', order_number=order.order_number, _external=True)
            order.payment_link = simulated_url
            db.session.commit()
            session.pop('cart', None)
            return redirect(simulated_url)
            
    return render_template('customer/checkout.html')

@customer_bp.route('/pay/simulate/<order_number>', methods=['GET', 'POST'])
def simulate_payment(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'success':
            order.status = 'Paid'
            deduct_order_stock(order)
            db.session.commit()
            return redirect(url_for('customer.pay_return', order_number=order.order_number))
        else:
            order.status = 'Failed'
            db.session.commit()
            return redirect(url_for('customer.home'))
            
    return render_template('customer/simulate_payment.html', order=order)

@customer_bp.route('/pay/return')
def pay_return():
    order_number = request.args.get('order_number')
    order = None
    if order_number:
        order = Order.query.filter_by(order_number=order_number).first()
        if order and order.status == 'Pending':
            if order.zoho_payment_link_id:
                zoho = ZohoClient()
                zoho_status = zoho.check_payment_link_status(order.zoho_payment_link_id)
                zoho_status_lower = zoho_status.lower() if zoho_status else ""
                print(f"DEBUG: check_payment_link_status returned '{zoho_status}' for order {order.order_number}")
                # Zoho payment link statuses typically include: 'paid', 'generated', 'expired', 'partially_paid', etc.
                # Payment transaction status can also be 'succeeded' or 'completed'.
                if zoho_status_lower in ('paid', 'succeeded', 'completed', 'success'):
                    order.status = 'Paid'
                    order.payment_status = 'Paid'
                    deduct_order_stock(order)
                    db.session.commit()
                    print(f"SUCCESS: Order {order.order_number} verified and marked as Paid.")
                else:
                    print(f"INFO: Return URL hit, but payment status from Zoho is '{zoho_status}' for order {order.order_number}.")
            else:
                # Fallback for simulated checkout
                order.status = 'Paid'
                order.payment_status = 'Paid'
                deduct_order_stock(order)
                db.session.commit()
                print(f"SUCCESS: Simulated payment marked as Paid for order {order.order_number}.")
                
    return render_template('customer/order_success.html', order=order)

@customer_bp.route('/api/order/status/<order_number>')
def order_status_api(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    
    if order.status == 'Pending':
        if order.zoho_payment_link_id:
            zoho = ZohoClient()
            zoho_status = zoho.check_payment_link_status(order.zoho_payment_link_id)
            zoho_status_lower = zoho_status.lower() if zoho_status else ""
            print(f"DEBUG: API check_payment_link_status returned '{zoho_status}' for order {order.order_number}")
            if zoho_status_lower in ('paid', 'succeeded', 'completed', 'success'):
                order.status = 'Paid'
                order.payment_status = 'Paid'
                deduct_order_stock(order)
                db.session.commit()
                print(f"SUCCESS: API verified and marked order {order.order_number} as Paid.")
                
    return {
        "status": order.status,
        "payment_status": order.payment_status or "Unpaid"
    }


@customer_bp.route('/pay/webhook', methods=['POST'])
def pay_webhook():
    import json
    print("DEBUG: Webhook headers:", dict(request.headers))
    try:
        # force=True parses request body as JSON even if the content type is missing
        payload = request.get_json(force=True) or {}
        print("DEBUG: Webhook payload:", json.dumps(payload, indent=2))
    except Exception as e:
        print("ERROR: Failed to parse webhook JSON payload:", str(e))
        return "Invalid JSON", 400

    # Verify signature
    zoho = ZohoClient()
    if not zoho.verify_webhook(payload, request.headers):
        print("ERROR: Webhook signature mismatch")
        return "Invalid Signature", 401

    event_type = payload.get("event_type")
    event_obj = payload.get("event_object", {})
    
    # Extract order number recursively or via common payload patterns
    order_number = (
        event_obj.get("payment", {}).get("reference_number")
        or event_obj.get("payment", {}).get("reference_id")
        or event_obj.get("payment_link", {}).get("reference_id")
        or event_obj.get("payment_link", {}).get("reference_number")
        or payload.get("reference_id")
    )
    
    print(f"DEBUG: Webhook Event: {event_type}, Extracted Order Number: {order_number}")

    if event_type in ("payment.succeeded", "payment_link.paid"):
        if order_number:
            order = Order.query.filter_by(order_number=order_number).first()
            if order:
                if order.status == 'Pending':
                    order.status = 'Paid'
                    order.payment_status = 'Paid'
                    deduct_order_stock(order)
                    db.session.commit()
                    print(f"SUCCESS: Webhook confirmed payment for order {order_number}.")
                    return "Success", 200
                else:
                    print(f"INFO: Webhook event ignored, order {order_number} is already '{order.status}'.")
                    return "Already Processed", 200
            else:
                print(f"INFO: Webhook reference order {order_number} not found in this storefront. Acknowledging event to prevent retries.")
                return "Order Not Found in Storefront", 200
        else:
            print("ERROR: No reference_id/order_number found in webhook payload.")
            return "No Reference Found", 400

    return "Event Ignored", 200

@customer_bp.route('/cart/restore/<order_number>')
def restore_cart(order_number):
    order = Order.query.filter_by(order_number=order_number, status='Pending').first()
    if not order:
        flash("Order not found, or it has already been paid.", "warning")
        return redirect(url_for('customer.cart'))
        
    # Rebuild cart from OrderItems
    cart = []
    for item in order.items:
        cart.append({
            'product_id': item.product_id,
            'quantity': item.quantity,
            'custom_message': item.custom_message or '',
            'custom_logo_url': item.custom_logo_url
        })
    session['cart'] = cart
    flash("Your shopping cart has been restored from the pending order.", "success")
    return redirect(url_for('customer.cart'))

@customer_bp.route('/terms')
def terms():
    return render_template('customer/terms.html')

@customer_bp.route('/refunds')
def refunds():
    return render_template('customer/refunds.html')

@customer_bp.route('/privacy')
def privacy():
    return render_template('customer/privacy.html')

@customer_bp.route('/choco-world')
def choco_world():
    return render_template('customer/choco_world.html')

@customer_bp.route('/profile')
@login_required
def profile():
    # Retrieve all orders matching the logged-in customer's email address
    user_orders = Order.query.filter_by(customer_email=current_user.email).order_by(Order.created_at.desc()).all()
    return render_template('customer/profile.html', orders=user_orders)

@customer_bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    current_user.name = request.form.get('name')
    current_user.phone = request.form.get('phone')
    current_user.address = request.form.get('address')
    db.session.commit()
    return redirect(url_for('customer.profile'))

@customer_bp.route('/blog/<slug>')
def blog_detail(slug):
    blog = BLOGS.get(slug)
    if not blog:
        flash("Blog post not found.", "warning")
        return redirect(url_for('customer.home'))
    return render_template('customer/blog.html', blog=blog)
