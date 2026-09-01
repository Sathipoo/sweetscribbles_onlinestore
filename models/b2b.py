from extensions import db
from datetime import datetime
import uuid

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
    
    # Requirements & Specs (Optional on onboarding)
    box_type = db.Column(db.String(100), default='To be decided / Consultation', nullable=False) # e.g. "Signature DIYA Box", "Small Celebration Box"
    box_count = db.Column(db.Integer, default=0) # 0 if not decided yet
    custom_occasion = db.Column(db.String(150), nullable=True) # e.g. "Diwali Corporate Gifting 2026"
    custom_message = db.Column(db.Text, nullable=True) # Greeting note / sleeve message
    
    # Financials
    quoted_price_per_box = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)
    advance_amount_required = db.Column(db.Float, default=0.0)
    advance_paid = db.Column(db.Boolean, default=False)
    advance_paid_at = db.Column(db.DateTime, nullable=True)
    payment_link = db.Column(db.String(500), nullable=True)
    
    # Pipeline Workflow Stage:
    # 'enquiry' -> 'quotation_sent' -> 'advance_paid' -> 'design_review' -> 'details_locked' -> 'production' -> 'delivered' -> 'cancelled'
    stage = db.Column(db.String(50), default='enquiry', index=True)
    eta_date = db.Column(db.String(50), nullable=True) # e.g. "15 Oct 2026"
    
    # Design Proofs & Brand Assets
    client_logo_url = db.Column(db.String(500), nullable=True)
    design_proof_url = db.Column(db.String(500), nullable=True)
    design_status = db.Column(db.String(50), default='pending_upload') # pending_upload, awaiting_approval, revision_requested, approved
    design_feedback = db.Column(db.Text, nullable=True)
    design_approved_at = db.Column(db.DateTime, nullable=True)
    
    # Delivery & Tracking
    courier_name = db.Column(db.String(100), nullable=True)
    tracking_number = db.Column(db.String(100), nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    
    internal_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Activity & Stage Transition Logs
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
        """Helper to create a stage transition or activity audit log entry."""
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
    action_title = db.Column(db.String(150), nullable=False) # e.g. "Client Onboarded", "Quotation Updated", "50% Advance Confirmed"
    actor = db.Column(db.String(100), default='Sales Desk (Admin)') # e.g. "Sales Desk (Admin)", "Client (Portal)", "System"
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<B2BOrderLog {self.order_id}: {self.from_stage} -> {self.to_stage} by {self.actor}>"


class B2BProduct(db.Model):
    __tablename__ = 'b2b_products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False) # e.g. "Signature DIYA Box"
    category = db.Column(db.String(100), default='Corporate Gifting') # e.g. "Diwali & Festive", "Executive Gifting"
    bites_count = db.Column(db.String(50), default='8') # e.g. "8", "12", "8 Bites + Hex Box"
    net_weight = db.Column(db.String(50), default='144 gms') # e.g. "144 gms", "210 gms"
    
    # Pricing Tiers
    price_premium = db.Column(db.Float, default=0.0) # e.g. 345.0
    price_assorted = db.Column(db.Float, default=0.0) # e.g. 265.0
    
    # Compositions (stored as newline-separated text)
    composition_premium = db.Column(db.Text, nullable=True)
    composition_assorted = db.Column(db.Text, nullable=True)
    
    customization_info = db.Column(db.String(255), default='Includes custom branding & theme printed on box (Min 50 boxes)')
    badge = db.Column(db.String(50), default='Bestseller') # e.g. "Bestseller", "Popular", "Luxury"
    image_url = db.Column(db.String(500), nullable=True)
    
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)
    min_order_qty = db.Column(db.Integer, default=50)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
