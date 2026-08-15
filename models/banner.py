from extensions import db
from datetime import datetime

class Banner(db.Model):
    __tablename__ = 'banners'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=True)
    subtitle = db.Column(db.String(255), nullable=True)
    image_url = db.Column(db.String(255), nullable=False)
    mobile_image_url = db.Column(db.String(255), nullable=True)
    link_url = db.Column(db.String(255), nullable=True, default='/collections')
    button_text = db.Column(db.String(100), nullable=True, default='Shop Now')
    promo_code = db.Column(db.String(50), nullable=True)
    display_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Banner {self.id} - {self.title or self.image_url}>'
