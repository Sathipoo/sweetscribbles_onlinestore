from extensions import db
from datetime import datetime

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Guest / Customer Info
    customer_name = db.Column(db.String(100))
    customer_email = db.Column(db.String(120))
    customer_phone = db.Column(db.String(20))
    shipping_address = db.Column(db.Text)
    
    status = db.Column(db.String(50), default='Pending') # Pending, Packing, Dispatched, Delivered
    total_amount = db.Column(db.Float, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Payment info
    payment_link = db.Column(db.String(500))
    payment_status = db.Column(db.String(50), default='Unpaid')
    
    # Shipping info (Delhivery/Shiprocket)
    tracking_number = db.Column(db.String(100))
    courier_name = db.Column(db.String(100))
    shipping_status = db.Column(db.String(50), default='Unshipped')
    
    items = db.relationship('OrderItem', backref='order', lazy=True)

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price_at_purchase = db.Column(db.Float, nullable=False)
    
    # Customizations
    custom_message = db.Column(db.Text)
    custom_logo_url = db.Column(db.String(255))
    
    product = db.relationship('Product')
