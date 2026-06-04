from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required, current_user
from functools import wraps
from models.product import Product, ProductMedia
from models.order import Order
from extensions import db
from utils.gcp_storage import upload_file

admin_bp = Blueprint('admin', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/')
@admin_required
def dashboard():
    today_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='Pending').count()
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(5).all()
    return render_template('admin/dashboard.html', today_orders=today_orders, pending_orders=pending_orders, recent_orders=recent_orders)

@admin_bp.route('/products', methods=['GET', 'POST'])
@admin_required
def products():
    if request.method == 'POST':
        name = request.form.get('name')
        sku = request.form.get('sku')
        category = request.form.get('category')
        sale_price = request.form.get('sale_price', 0.0)
        
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file.filename != '':
                image_url = upload_file(file, file.filename, folder="products")
                
        new_product = Product(
            name=name, sku=sku, category=category, sale_price=float(sale_price), image_url=image_url
        )
        db.session.add(new_product)
        db.session.flush() # Get product ID
        
        # Add main image to ProductMedia gallery too
        display_order = 1
        if image_url:
            main_media = ProductMedia(
                product_id=new_product.id,
                media_type='image',
                media_url=image_url,
                display_order=display_order
            )
            db.session.add(main_media)
            display_order += 1

        # Handle multiple uploaded media files
        new_media_files = request.files.getlist('new_media')
        for file in new_media_files:
            if file and file.filename != '':
                filename = file.filename.lower()
                is_video = (file.content_type and file.content_type.startswith('video/')) or \
                           filename.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm', '.3gp', '.ogg'))
                media_type = 'video' if is_video else 'image'
                media_url = upload_file(file, file.filename, folder="products")
                
                new_media = ProductMedia(
                    product_id=new_product.id,
                    media_type=media_type,
                    media_url=media_url,
                    display_order=display_order
                )
                db.session.add(new_media)
                display_order += 1
                
        db.session.commit()
        return redirect(url_for('admin.products'))
        
    all_products = Product.query.all()
    return render_template('admin/products.html', products=all_products)

@admin_bp.route('/product/<int:product_id>/edit', methods=['POST'])
@admin_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    product.name = request.form.get('name')
    product.sku = request.form.get('sku')
    product.category = request.form.get('category')
    product.sale_price = float(request.form.get('sale_price', 0.0))
    
    # Handle main image replacement
    if 'image' in request.files:
        file = request.files['image']
        if file.filename != '':
            image_url = upload_file(file, file.filename, folder="products")
            product.image_url = image_url
            
            # Also add to media gallery if not already present
            # We can set display order as 1 or max_order + 1
            max_order = max([m.display_order for m in product.media_items] + [0])
            main_media = ProductMedia(
                product_id=product.id,
                media_type='image',
                media_url=image_url,
                display_order=max_order + 1
            )
            db.session.add(main_media)
            
    # Handle display order updates
    for media in product.media_items:
        order_val = request.form.get(f'display_order_{media.id}')
        if order_val is not None:
            try:
                media.display_order = int(order_val)
            except ValueError:
                pass
                
    # Handle media deletion
    delete_ids = request.form.getlist('delete_media')
    if delete_ids:
        delete_ids = [int(x) for x in delete_ids if x.isdigit()]
        medias_to_delete = ProductMedia.query.filter(
            ProductMedia.id.in_(delete_ids), 
            ProductMedia.product_id == product.id
        ).all()
        for media in medias_to_delete:
            db.session.delete(media)
            
    # Handle new media uploads
    if 'new_media' in request.files:
        new_media_files = request.files.getlist('new_media')
        # Refresh current media items display order max
        max_order = max([m.display_order for m in product.media_items if m.id not in delete_ids] + [0])
        for file in new_media_files:
            if file and file.filename != '':
                filename = file.filename.lower()
                is_video = (file.content_type and file.content_type.startswith('video/')) or \
                           filename.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm', '.3gp', '.ogg'))
                media_type = 'video' if is_video else 'image'
                media_url = upload_file(file, file.filename, folder="products")
                
                max_order += 1
                new_media = ProductMedia(
                    product_id=product.id,
                    media_type=media_type,
                    media_url=media_url,
                    display_order=max_order
                )
                db.session.add(new_media)
                
    db.session.commit()
    return redirect(url_for('admin.products'))

@admin_bp.route('/orders')
@admin_required
def orders():
    all_orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin/orders.html', orders=all_orders)
    
@admin_bp.route('/order/<int:order_id>/status', methods=['POST'])
@admin_required
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    if new_status:
        order.status = new_status
        db.session.commit()
    # Check where we came from, to redirect back appropriately
    referrer = request.referrer
    if referrer and 'customers' in referrer:
        return redirect(url_for('admin.customers'))
    return redirect(url_for('admin.orders'))

@admin_bp.route('/customers')
@admin_required
def customers():
    from sqlalchemy import func
    customer_records = db.session.query(
        Order.customer_email.label('email'),
        func.max(Order.customer_name).label('name'),
        func.max(Order.customer_phone).label('phone'),
        func.max(Order.shipping_address).label('address'),
        func.count(Order.id).label('order_count'),
        func.sum(Order.total_amount).label('total_spent')
    ).group_by(Order.customer_email).all()
    
    customer_profiles = []
    for row in customer_records:
        if not row.email:
            continue
        customer_orders = Order.query.filter_by(customer_email=row.email).order_by(Order.created_at.desc()).all()
        customer_profiles.append({
            'email': row.email,
            'name': row.name,
            'phone': row.phone,
            'address': row.address,
            'order_count': row.order_count,
            'total_spent': row.total_spent,
            'orders': customer_orders
        })
        
    return render_template('admin/customers.html', customers=customer_profiles)

@admin_bp.route('/order/<int:order_id>/tracking', methods=['POST'])
@admin_required
def update_order_tracking(order_id):
    order = Order.query.get_or_404(order_id)
    order.tracking_number = request.form.get('tracking_number')
    order.courier_name = request.form.get('courier_name')
    order.shipping_status = request.form.get('shipping_status')
    
    # Auto-align main order status with shipping steps
    if order.shipping_status == 'Packed' and order.status == 'Pending':
        order.status = 'Packing'
    elif order.shipping_status == 'In Transit':
        order.status = 'Dispatched'
    elif order.shipping_status == 'Delivered':
        order.status = 'Delivered'
        
    db.session.commit()
    
    referrer = request.referrer
    if referrer and 'customers' in referrer:
        return redirect(url_for('admin.customers'))
    return redirect(url_for('admin.orders'))
