from extensions import db
from datetime import datetime

class Coupon(db.Model):
    __tablename__ = 'coupons'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(db.String(20), default='percent') # 'percent' or 'flat'
    discount_value = db.Column(db.Float, nullable=False)
    max_discount = db.Column(db.Float, nullable=True) # Optional cap on percentage discount e.g. 150.0
    min_order_amount = db.Column(db.Float, default=0.0) # Optional minimum cart subtotal required
    is_active = db.Column(db.Boolean, default=True)
    expiry_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def calculate_discount(self, original_amount):
        if not self.is_active:
            return 0.0
        if self.expiry_date and self.expiry_date < datetime.utcnow():
            return 0.0
        if self.min_order_amount and original_amount < self.min_order_amount:
            return 0.0
            
        if self.discount_type == 'percent':
            raw_discount = original_amount * (self.discount_value / 100.0)
            if self.max_discount is not None and self.max_discount > 0:
                raw_discount = min(raw_discount, self.max_discount)
            return round(raw_discount, 2)
        elif self.discount_type == 'flat':
            return round(min(self.discount_value, original_amount), 2)
        return 0.0
