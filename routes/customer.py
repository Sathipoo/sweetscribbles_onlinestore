from flask import Blueprint, render_template, request, redirect, url_for, session, current_app, flash
from flask_login import login_required, current_user
from models.product import Product, Collection
from models.order import Order, OrderItem
from models.coupon import Coupon
from models.banner import Banner
from models.setting import SiteSetting
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
    active_banners = Banner.query.filter_by(is_active=True).order_by(Banner.display_order.asc(), Banner.id.asc()).all()
    featured_products = Product.query.filter_by(category='bites', is_active=True).limit(4).all()
    bites_products = Product.query.filter_by(category='bites', is_active=True).all()
    choco_products = Product.query.filter_by(category='choco', is_active=True).all()
    return render_template('customer/home.html', 
                           banners=active_banners,
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
            
    net_subtotal = max(0.0, total - discount)
    
    # Dynamic Shipping Calculation
    from models.setting import SiteSetting
    shipping_enabled = SiteSetting.get_val('shipping_enabled', 'true') == 'true'
    free_shipping_threshold = float(SiteSetting.get_val('free_shipping_threshold', '999.0'))
    flat_shipping_fee = float(SiteSetting.get_val('flat_shipping_fee', '50.0'))
    
    if not shipping_enabled or net_subtotal >= free_shipping_threshold:
        shipping_fee = 0.0
        amount_needed_for_free = 0.0
        is_free_shipping = True
    else:
        shipping_fee = flat_shipping_fee
        amount_needed_for_free = free_shipping_threshold - net_subtotal
        is_free_shipping = False
        
    grand_total = net_subtotal + shipping_fee
    
    return render_template(
        'customer/cart.html',
        items=items_data,
        total=total,
        discount=discount,
        coupon_code=coupon_code,
        grand_total=grand_total,
        shipping_fee=shipping_fee,
        free_shipping_threshold=free_shipping_threshold,
        amount_needed_for_free=amount_needed_for_free,
        is_free_shipping=is_free_shipping,
        flat_shipping_fee=flat_shipping_fee,
        shipping_enabled=shipping_enabled
    )

@customer_bp.route('/cart/remove/<int:item_index>', methods=['POST'])
def remove_from_cart(item_index):
    cart = session.get('cart', [])
    if 0 <= item_index < len(cart):
        cart.pop(item_index)
        session['cart'] = cart
        session.modified = True
        flash('Item removed from cart.', 'info')
    return redirect(url_for('customer.cart'))

@customer_bp.route('/cart/coupon', methods=['POST'])
def apply_coupon():
    action = request.form.get('action')
    if action == 'remove':
        session.pop('coupon_code', None)
        session.modified = True
        flash('Coupon code removed successfully.', 'info')
        return redirect(url_for('customer.cart'))
    else:
        code = request.form.get('coupon_code', '').strip().upper()
        if not code:
            flash('Please enter a coupon code.', 'warning')
            return redirect(url_for('customer.cart'))
            
        coupon = Coupon.query.filter_by(code=code).first()
        if not coupon:
            flash('Invalid coupon code.', 'danger')
            return redirect(url_for('customer.cart'))
            
        if not coupon.is_active:
            flash('This coupon is currently inactive.', 'danger')
            return redirect(url_for('customer.cart'))
            
        if coupon.expiry_date and coupon.expiry_date < datetime.utcnow():
            flash('This coupon code has expired.', 'danger')
            return redirect(url_for('customer.cart'))
            
        # Calculate current cart subtotal
        cart_items = session.get('cart', [])
        cart_total = 0.0
        for item in cart_items:
            prod = Product.query.get(item['product_id'])
            if prod:
                cart_total += prod.sale_price * item['quantity']
                
        if coupon.min_order_amount and cart_total < coupon.min_order_amount:
            flash(f'Minimum order amount of ₹{coupon.min_order_amount:.2f} is required to use coupon "{coupon.code}".', 'warning')
            return redirect(url_for('customer.cart'))
            
        session['coupon_code'] = coupon.code
        flash(f'Coupon "{coupon.code}" applied successfully!', 'success')
            
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
        
        # Check if we can reuse an existing Pending order for this session to prevent duplicates
        order = None
        pending_order_id = session.get('pending_order_id')
        if pending_order_id:
            existing_order = Order.query.get(pending_order_id)
            if existing_order and existing_order.status == 'Pending':
                order = existing_order
                order.customer_name = customer_name
                order.customer_email = customer_email
                order.customer_phone = customer_phone
                order.shipping_address = shipping_address
                order.customer_id = current_user.id if current_user.is_authenticated else None
                # Clear old items to repopulate cleanly
                OrderItem.query.filter_by(order_id=order.id).delete()

        if not order:
            order_number = f"SS{uuid.uuid4().hex[:6].upper()}"
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
            session['pending_order_id'] = order.id
        
        total_amount = 0
        
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
                order.coupon_code = coupon.code
                order.discount_amount = discount
                session.pop('coupon_code', None) # Clear coupon after use
                
        net_subtotal = max(0.0, total_amount - discount)
        
        # Calculate shipping fee for order
        from models.setting import SiteSetting
        shipping_enabled = SiteSetting.get_val('shipping_enabled', 'true') == 'true'
        free_shipping_threshold = float(SiteSetting.get_val('free_shipping_threshold', '999.0'))
        flat_shipping_fee = float(SiteSetting.get_val('flat_shipping_fee', '50.0'))
        
        if not shipping_enabled or net_subtotal >= free_shipping_threshold:
            shipping_fee = 0.0
        else:
            shipping_fee = flat_shipping_fee
            
        order.shipping_fee = shipping_fee
        order.total_amount = net_subtotal + shipping_fee
        
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
                'amount': order.total_amount,  # Fix: Use final total amount including shipping
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
            session.pop('pending_order_id', None)
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
            session.pop('pending_order_id', None)
            return redirect(simulated_url)
            
    # GET method summary calculation for checkout page
    subtotal = 0.0
    for item in cart_items:
        prod = Product.query.get(item['product_id'])
        if prod:
            subtotal += prod.sale_price * item['quantity']
            
    discount = 0.0
    coupon_code = session.get('coupon_code')
    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code, is_active=True).first()
        if coupon and (not coupon.expiry_date or coupon.expiry_date > datetime.utcnow()):
            discount = coupon.calculate_discount(subtotal)
            
    net_subtotal = max(0.0, subtotal - discount)
    from models.setting import SiteSetting
    shipping_enabled = SiteSetting.get_val('shipping_enabled', 'true') == 'true'
    free_shipping_threshold = float(SiteSetting.get_val('free_shipping_threshold', '999.0'))
    flat_shipping_fee = float(SiteSetting.get_val('flat_shipping_fee', '50.0'))
    
    if not shipping_enabled or net_subtotal >= free_shipping_threshold:
        shipping_fee = 0.0
    else:
        shipping_fee = flat_shipping_fee
        
    grand_total = net_subtotal + shipping_fee
            
    return render_template(
        'customer/checkout.html',
        subtotal=subtotal,
        discount=discount,
        coupon_code=coupon_code,
        shipping_fee=shipping_fee,
        grand_total=grand_total
    )

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

@customer_bp.route('/about')
def about():
    return render_template('customer/about.html')

@customer_bp.route('/terms')
def terms():
    return render_template('customer/terms.html')

@customer_bp.route('/refunds')
def refunds():
    return render_template('customer/refunds.html')

@customer_bp.route('/shipping')
def shipping():
    return render_template('customer/shipping.html')

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

@customer_bp.route('/send-email-otp', methods=['POST'])
@login_required
def send_email_otp_route():
    from utils.otp_utils import generate_otp, send_email_otp
    from datetime import datetime, timedelta
    
    otp = generate_otp()
    expiry = (datetime.utcnow() + timedelta(minutes=5)).timestamp()
    
    session['email_otp'] = {
        'email': current_user.email,
        'otp': otp,
        'expires': expiry
    }
    
    sent_real = send_email_otp(current_user.email, otp)
    
    return {
        'success': True,
        'message': 'OTP sent successfully to your email.',
        'dev_otp': otp if current_app.debug else None,
        'sent_real': sent_real
    }

@customer_bp.route('/change-password-otp', methods=['POST'])
@login_required
def change_password_otp_route():
    from datetime import datetime
    
    otp_data = session.get('email_otp')
    if not otp_data:
        return {'success': False, 'message': 'No active OTP verification session. Please request a new OTP.'}, 400
        
    data = request.get_json(silent=True) or {}
    entered_otp = (data.get('otp') or request.form.get('otp', '')).strip()
    new_password = data.get('new_password') or request.form.get('new_password')
    
    if not entered_otp or not new_password:
        return {'success': False, 'message': 'OTP and new password are required.'}, 400
        
    if otp_data['email'] != current_user.email:
        return {'success': False, 'message': 'Session mismatch error.'}, 400
        
    if otp_data['otp'] != entered_otp:
        return {'success': False, 'message': 'Incorrect OTP. Please try again.'}, 400
        
    if datetime.utcnow().timestamp() > otp_data['expires']:
        return {'success': False, 'message': 'OTP has expired. Please request a new one.'}, 400
        
    current_user.set_password(new_password)
    db.session.commit()
    session.pop('email_otp', None)
    
    return {'success': True, 'message': 'Your password has been changed successfully!'}

@customer_bp.route('/products/dark-choco-bliss-bites/329542500000065585')
def old_dark_choco_redirect():
    # 301 Permanent Redirect for the old URL structure to the current product detail URL
    # Look up by SKU "CB-DRK-01" to handle dynamic product ID assignment, fallback to ID 5
    product = Product.query.filter_by(sku='CB-DRK-01').first()
    target_id = product.id if product else 5
    return redirect(url_for('customer.product_detail', product_id=target_id), code=301)

