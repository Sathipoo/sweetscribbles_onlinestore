from extensions import db

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    sku = db.Column(db.String(50), unique=True)
    description = db.Column(db.Text)
    short_description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    category = db.Column(db.String(50)) # e.g. 'bites', 'gifting', 'custom'

    # Pricing
    mrp = db.Column(db.Float, default=0.0)
    sale_price = db.Column(db.Float, default=0.0)
    corporate_price = db.Column(db.Float, default=0.0)

    # Inventory
    available_qty = db.Column(db.Integer, default=0)
    low_stock_threshold = db.Column(db.Integer, default=10)

    # Nutrition
    calories = db.Column(db.Float)
    protein = db.Column(db.Float)
    fat = db.Column(db.Float)
    carbs = db.Column(db.Float)
    fiber = db.Column(db.Float)

    ingredients = db.Column(db.Text) # Comma-separated or JSON
    
    image_url = db.Column(db.String(255))

class ProductMedia(db.Model):
    __tablename__ = 'product_media'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    media_type = db.Column(db.String(20), default='image') # 'image' or 'video'
    media_url = db.Column(db.String(255), nullable=False)
    display_order = db.Column(db.Integer, default=0)

    product = db.relationship('Product', backref=db.backref('media_items', lazy=True, cascade='all, delete-orphan', order_by='ProductMedia.display_order'))
