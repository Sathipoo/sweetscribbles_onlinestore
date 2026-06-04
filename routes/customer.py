from flask import Blueprint, render_template, request, redirect, url_for, session, current_app, flash
from flask_login import login_required, current_user
from models.product import Product
from models.order import Order, OrderItem
from models.coupon import Coupon
from extensions import db
from utils.gcp_storage import upload_file
from utils.zoho_utils import ZohoClient
import uuid
from datetime import datetime

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/')
def home():
    featured_products = Product.query.filter_by(category='bites').limit(4).all()
    bites_products = Product.query.filter_by(category='bites').all()
    choco_products = Product.query.filter_by(category='choco').all()
    return render_template('customer/home.html', 
                           featured=featured_products, 
                           bites=bites_products, 
                           choco=choco_products)

@customer_bp.route('/collections')
def collections():
    bites = Product.query.filter_by(category='bites').all()
    choco = Product.query.filter_by(category='choco').all()
    gifting = Product.query.filter_by(category='gifting').all()
    return render_template('customer/collections.html', bites=bites, choco=choco, gifting=gifting)

@customer_bp.route('/product/<int:product_id>', methods=['GET', 'POST'])
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        qty = int(request.form.get('quantity', 1))
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
        payment_link = zoho.create_payment_link({
            'order_id': order.order_number,
            'amount': total_amount,
            'customer_email': customer_email,
            'customer_phone': customer_phone,
            'customer_name': customer_name,
            'package': f"Order {order_number}"
        })
        
        if payment_link:
            order.payment_link = payment_link
            db.session.commit()
            session.pop('cart', None)
            return redirect(payment_link)
        else:
            # Fallback to simulated payment flow for local development / Zoho error
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
            order.status = 'Paid'
            db.session.commit()
    return render_template('customer/order_success.html', order=order)

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
