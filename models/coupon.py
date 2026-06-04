from extensions import db
from datetime import datetime

class Coupon(db.Model):
    __tablename__ = 'coupons'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(db.String(20), default='percent') # 'percent' or 'flat'
    discount_value = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    expiry_date = db.Column(db.DateTime, nullable=True)
    
    def calculate_discount(self, original_amount):
        if not self.is_active:
            return 0.0
        if self.expiry_date and self.expiry_date < datetime.utcnow():
            return 0.0
            
        if self.discount_type == 'percent':
            return round((original_amount * (self.discount_value / 100.0)), 2)
        elif self.discount_type == 'flat':
            return min(self.discount_value, original_amount)
        return 0.0
