from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, index=True, nullable=True)
    email = db.Column(db.String(120), index=True, nullable=True)
    password_hash = db.Column(db.String(256))
    is_admin = db.Column(db.Boolean, default=False)
    name = db.Column(db.String(100))

    
    # Structured Shipping / Delivery Address
    street_address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    pincode = db.Column(db.String(20))
    address = db.Column(db.Text) # Combined full address for legacy/general display

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name or '',
            'email': self.email or '',
            'phone': self.phone or '',
            'street_address': self.street_address or '',
            'city': self.city or '',
            'state': self.state or '',
            'pincode': self.pincode or '',
            'address': self.address or ''
        }

