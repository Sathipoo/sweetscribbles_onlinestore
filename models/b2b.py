import uuid
from datetime import datetime
from extensions import db

class B2BClient(db.Model):
    __tablename__ = 'b2b_clients'
    
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    contact_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, index=True, nullable=False)
    email = db.Column(db.String(120), nullable=False)
    gst_number = db.Column(db.String(30), nullable=True)
    shipping_address = db.Column(db.Text, nullable=True)
    industry = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    orders = db.relationship('B2BOrder', backref='client', lazy=True, order_by="desc(B2BOrder.created_at)", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<B2BClient {self.company_name} ({self.contact_name})>"

    @property
    def total_spend(self):
        return sum((o.total_amount or 0.0) for o in self.orders if o.stage != 'cancelled')


class B2BOrder(db.Model):
    __tablename__ = 'b2b_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(30), unique=True, index=True, nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('b2b_clients.id'), nullable=False)
    
    # Requirements & Specs
    box_type = db.Column(db.String(100), default='To be decided / Consultation', nullable=False)
    box_count = db.Column(db.Integer, default=0)
    custom_occasion = db.Column(db.String(150), nullable=True)
    custom_message = db.Column(db.Text, nullable=True)
    
    # Financials
    quoted_price_per_box = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)
    advance_amount_required = db.Column(db.Float, default=0.0)
    advance_paid = db.Column(db.Boolean, default=False)
    advance_paid_at = db.Column(db.DateTime, nullable=True)
    payment_link = db.Column(db.String(500), nullable=True)
    
    # Pipeline Workflow Stage
    stage = db.Column(db.String(50), default='enquiry', index=True)
    eta_date = db.Column(db.String(50), nullable=True)
    
    # Design Proofs & Brand Assets
    client_logo_url = db.Column(db.String(500), nullable=True)
    design_proof_url = db.Column(db.String(500), nullable=True)
    design_status = db.Column(db.String(50), default='pending_upload')
    design_feedback = db.Column(db.Text, nullable=True)
    design_approved_at = db.Column(db.DateTime, nullable=True)
    
    # Delivery & Tracking
    courier_name = db.Column(db.String(100), nullable=True)
    tracking_number = db.Column(db.String(100), nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    
    internal_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    logs = db.relationship('B2BOrderLog', backref='order', lazy=True, order_by="desc(B2BOrderLog.created_at)", cascade="all, delete-orphan")

    @classmethod
    def generate_order_number(cls):
        return f"SSB2B-{uuid.uuid4().hex[:6].upper()}"

    def get_stage_display(self):
        stage_map = {
            'enquiry': 'Enquiry Received',
            'quotation_sent': 'Quotation Shared',
            'advance_paid': 'Order Confirmed (Advance Received)',
            'design_review': 'Design Ready for Approval',
            'details_locked': 'Details & Count Locked',
            'production': 'In Handcrafted Production',
            'delivered': 'Delivered Successfully',
            'cancelled': 'Cancelled'
        }
        return stage_map.get(self.stage, self.stage.title())

    def get_stage_badge_class(self):
        badge_map = {
            'enquiry': 'bg-warning text-dark',
            'quotation_sent': 'bg-info text-dark',
            'advance_paid': 'bg-primary text-white',
            'design_review': 'bg-purple text-white',
            'details_locked': 'bg-secondary text-white',
            'production': 'bg-warning text-dark',
            'delivered': 'bg-success text-white',
            'cancelled': 'bg-danger text-white'
        }
        return badge_map.get(self.stage, 'bg-secondary text-white')

    def add_log(self, action_title, to_stage=None, from_stage=None, actor='Admin', details=None):
        if to_stage is None:
            to_stage = self.stage
        if from_stage is None:
            from_stage = self.stage
            
        log = B2BOrderLog(
            order_id=self.id,
            from_stage=from_stage,
            to_stage=to_stage,
            action_title=action_title,
            actor=actor,
            details=details
        )
        db.session.add(log)
        return log


class B2BOrderLog(db.Model):
    __tablename__ = 'b2b_order_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('b2b_orders.id'), nullable=False, index=True)
    from_stage = db.Column(db.String(50), nullable=True)
    to_stage = db.Column(db.String(50), nullable=False)
    action_title = db.Column(db.String(150), nullable=False)
    actor = db.Column(db.String(100), default='Sales Desk (Admin)')
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<B2BOrderLog {self.order_id}: {self.from_stage} -> {self.to_stage} by {self.actor}>"


class B2BProduct(db.Model):
    __tablename__ = 'b2b_products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), default='Corporate Gifting')
    bites_count = db.Column(db.String(50), default='8')
    net_weight = db.Column(db.String(50), default='144 gms')
    gross_weight = db.Column(db.String(100), default='350 gms')
    
    # Pricing Tiers
    price_premium = db.Column(db.Float, default=0.0)
    price_assorted = db.Column(db.Float, default=0.0)
    
    # Compositions
    composition_premium = db.Column(db.Text, nullable=True)
    composition_assorted = db.Column(db.Text, nullable=True)
    
    # Detailed Specs & Sub-page metadata
    description = db.Column(db.Text, nullable=True)
    box_dimensions = db.Column(db.String(100), default='24 cm x 16 cm x 4.5 cm')
    shelf_life = db.Column(db.String(100), default='60 Days from Dispatch')
    lead_time = db.Column(db.String(100), default='5 - 7 Business Days')
    sleeve_specs = db.Column(db.String(255), default='Full 4-Color Offset Sleeve with matte lamination & metallic gold foil stamping')
    
    customization_info = db.Column(db.String(255), default='Includes custom branding & theme printed on box (Min 50 boxes)')
    badge = db.Column(db.String(50), default='Bestseller')
    image_url = db.Column(db.String(500), nullable=True)
    
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)
    min_order_qty = db.Column(db.Integer, default=50)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships for Multi-Image Gallery and Real Client Deliveries Showcase
    gallery_images = db.relationship('B2BProductImage', backref='product', lazy=True, order_by="B2BProductImage.display_order.asc(), B2BProductImage.id.asc()", cascade="all, delete-orphan")
    showcase_items = db.relationship('B2BProductShowcase', backref='product', lazy=True, order_by="B2BProductShowcase.display_order.asc(), B2BProductShowcase.id.desc()", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<B2BProduct {self.name} (₹{self.price_premium})>"

    def get_composition_premium_list(self):
        if not self.composition_premium:
            return []
        return [line.strip() for line in self.composition_premium.replace('\r', '').split('\n') if line.strip()]

    def get_composition_assorted_list(self):
        if not self.composition_assorted:
            return []
        return [line.strip() for line in self.composition_assorted.replace('\r', '').split('\n') if line.strip()]

    def get_all_images(self):
        """Returns primary image plus all secondary gallery images in order."""
        images = []
        if self.image_url:
            images.append(self.image_url)
        for g in self.gallery_images:
            if g.image_url and g.image_url not in images:
                images.append(g.image_url)
        return images


class B2BProductImage(db.Model):
    """Secondary gallery photos for a B2B gift box product page."""
    __tablename__ = 'b2b_product_images'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('b2b_products.id'), nullable=False, index=True)
    image_url = db.Column(db.String(500), nullable=False)
    caption = db.Column(db.String(150), nullable=True)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<B2BProductImage {self.id} for Product {self.product_id}>"


class B2BProductShowcase(db.Model):
    """Real client orders delivered in this box style with custom sleeve photos and feedback."""
    __tablename__ = 'b2b_product_showcases'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('b2b_products.id'), nullable=False, index=True)
    client_name = db.Column(db.String(150), nullable=False)
    client_logo_url = db.Column(db.String(500), nullable=True)
    box_photo_url = db.Column(db.String(500), nullable=False)
    order_volume = db.Column(db.String(100), default='250 Custom Boxes')
    occasion = db.Column(db.String(150), nullable=True)
    client_feedback = db.Column(db.Text, nullable=True)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<B2BProductShowcase {self.client_name} - Product {self.product_id}>"


class B2BTestimonial(db.Model):
    """Client collaborations, testimonials, and case studies across the B2B portal."""
    __tablename__ = 'b2b_testimonials'
    
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    company_logo_url = db.Column(db.String(500), nullable=True)
    contact_person = db.Column(db.String(100), nullable=True)
    designation = db.Column(db.String(100), nullable=True)
    box_photo_url = db.Column(db.String(500), nullable=True)
    order_details = db.Column(db.String(150), nullable=True)
    rating = db.Column(db.Integer, default=5)
    testimonial_text = db.Column(db.Text, nullable=False)
    is_featured = db.Column(db.Boolean, default=True, index=True)
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Multi-Photo Relationship for Testimonial Carousel
    images = db.relationship('B2BTestimonialImage', backref='testimonial', lazy=True, order_by="B2BTestimonialImage.display_order.asc(), B2BTestimonialImage.id.asc()", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<B2BTestimonial {self.company_name} ({self.contact_person})>"

    def get_photos(self):
        """Returns a list of image URLs attached to this testimonial."""
        if self.images:
            return [img.image_url for img in self.images]
        if self.box_photo_url:
            return [self.box_photo_url]
        return []


class B2BTestimonialImage(db.Model):
    """Multiple photo uploads for a single corporate testimonial / collaboration."""
    __tablename__ = 'b2b_testimonial_images'
    
    id = db.Column(db.Integer, primary_key=True)
    testimonial_id = db.Column(db.Integer, db.ForeignKey('b2b_testimonials.id'), nullable=False, index=True)
    image_url = db.Column(db.String(500), nullable=False)
    caption = db.Column(db.String(150), nullable=True)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<B2BTestimonialImage {self.id} for Testimonial {self.testimonial_id}>"
