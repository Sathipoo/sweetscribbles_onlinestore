import uuid
from datetime import datetime
from extensions import db

class B2BLead(db.Model):
    """
    Corporate lead/prospect identified prior to becoming an active B2B client.
    Tracks prospecting stage, priority score, login counts, and clickstream engagement.
    """
    __tablename__ = 'b2b_leads'

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    contact_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), index=True, nullable=True)
    email = db.Column(db.String(120), index=True, nullable=True)
    designation = db.Column(db.String(100), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    industry = db.Column(db.String(100), nullable=True)
    estimated_budget = db.Column(db.Float, default=0.0)
    estimated_box_count = db.Column(db.Integer, default=0)
    lead_source = db.Column(db.String(50), default='Outbound Cold List')

    # Lifecycle Stage
    # 'new' -> 'outreach_sent' -> 'portal_active' -> 'contacted' -> 'warm_discussion' -> 'converted' -> 'disqualified'
    stage = db.Column(db.String(50), default='new', index=True)

    # Lead Intent Scoring
    priority_score = db.Column(db.Integer, default=10)
    is_hot = db.Column(db.Boolean, default=False, index=True)

    # Authentication & Visit Telemetry
    login_count = db.Column(db.Integer, default=0)
    first_login_at = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_active_at = db.Column(db.DateTime, nullable=True)

    # Unique tracking token embedded in cold outreach links (?trk=...)
    tracking_token = db.Column(db.String(64), unique=True, index=True, nullable=False, default=lambda: f"trk_{uuid.uuid4().hex[:12]}")

    # Conversion Linkage
    converted_client_id = db.Column(db.Integer, db.ForeignKey('b2b_clients.id'), nullable=True)
    assigned_to = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    events = db.relationship('B2BEngagementEvent', backref='lead', lazy=True, order_by="desc(B2BEngagementEvent.created_at)", cascade="all, delete-orphan")
    converted_client = db.relationship('B2BClient', foreign_keys=[converted_client_id], backref='source_lead', lazy=True)

    def __repr__(self):
        return f"<B2BLead {self.company_name} ({self.contact_name}) - Stage: {self.stage} (Score: {self.priority_score})>"

    def update_score(self, points, reason=None):
        """Dynamically increments score and evaluates hot prospect status."""
        self.priority_score = max(0, (self.priority_score or 0) + points)
        if self.priority_score >= 60 or self.stage == 'portal_active':
            self.is_hot = True
        self.last_active_at = datetime.utcnow()

    @property
    def is_archived(self):
        return False

    @property
    def orders(self):
        if self.converted_client:
            return self.converted_client.orders
        return []

    @property
    def priority_label(self):
        if self.is_hot or (self.priority_score and self.priority_score >= 60):
            return "HOT PROSPECT"
        elif self.priority_score and self.priority_score >= 30:
            return "WARM"
        return "COLD"

    @property
    def priority_badge_class(self):
        if self.is_hot or (self.priority_score and self.priority_score >= 60):
            return "bg-danger text-white shadow-sm"
        elif self.priority_score and self.priority_score >= 30:
            return "bg-warning text-dark"
        return "bg-secondary text-light"

    @property
    def stage_display(self):
        stage_map = {
            'new': '1. New / Uncontacted',
            'outreach_sent': '2. Outreach Dispatched',
            'portal_active': '3. Portal Active (Engaged)',
            'contacted': '4. Phone Contacted',
            'warm_discussion': '5. In Negotiation',
            'converted': '6. Converted to Client',
            'disqualified': 'Disqualified'
        }
        return stage_map.get(self.stage, (self.stage or 'new').title())


class B2BEngagementEvent(db.Model):
    """
    Clickstream telemetry event recording visitor interactions across B2B storefront pages.
    Tracks product views, slider interactions, CTA clicks, logins, and timestamps.
    """
    __tablename__ = 'b2b_engagement_events'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('b2b_leads.id'), nullable=True, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('b2b_clients.id'), nullable=True, index=True)
    visitor_id = db.Column(db.String(64), nullable=True, index=True)

    # Event types: 'login', 'page_view', 'product_view', 'slider_change', 'cta_click', 'edition_switch', 'portal_visit'
    event_type = db.Column(db.String(50), nullable=False, index=True)
    page_url = db.Column(db.String(255), nullable=True)
    page_title = db.Column(db.String(150), nullable=True)
    element_identifier = db.Column(db.String(100), nullable=True)

    # Event metadata (e.g. JSON string with product_id, product_name, qty, budget)
    event_metadata = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationship to B2BClient
    client = db.relationship('B2BClient', backref=db.backref('engagement_events', lazy=True, order_by="desc(B2BEngagementEvent.created_at)"))

    def __repr__(self):
        target = f"Lead #{self.lead_id}" if self.lead_id else (f"Client #{self.client_id}" if self.client_id else f"Anon {self.visitor_id}")
        return f"<B2BEngagementEvent [{self.event_type}] by {target} on {self.page_url} at {self.created_at}>"


class CRMCampaign(db.Model):
    """
    Outbound outreach and promotional campaign (Email / SMS)
    targeting prospective leads or re-engaging existing corporate clients.
    """
    __tablename__ = 'crm_campaigns'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    channel = db.Column(db.String(20), default='email')  # 'email', 'sms', 'both'
    target_audience = db.Column(db.String(50), default='leads')  # 'leads', 'existing_clients', 'both'
    subject = db.Column(db.String(200), nullable=True)
    content_body = db.Column(db.Text, nullable=False)
    cta_text = db.Column(db.String(100), default='Explore Corporate Hampers')
    cta_url = db.Column(db.String(255), default='https://sweetscribbles.pikachooz.com/b2b')

    status = db.Column(db.String(30), default='draft')  # 'draft', 'sending', 'sent'
    total_recipients = db.Column(db.Integer, default=0)
    sent_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    unique_logins_generated = db.Column(db.Integer, default=0)

    created_by = db.Column(db.String(100), default='Sales Admin')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    recipients = db.relationship('CRMCampaignRecipient', backref='campaign', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<CRMCampaign '{self.name}' ({self.channel}) - Status: {self.status}>"


class CRMCampaignRecipient(db.Model):
    """
    Individual recipient tracking for an outreach or promotional campaign.
    """
    __tablename__ = 'crm_campaign_recipients'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('crm_campaigns.id'), nullable=False, index=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('b2b_leads.id'), nullable=True, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('b2b_clients.id'), nullable=True, index=True)

    recipient_email = db.Column(db.String(120), nullable=True)
    recipient_phone = db.Column(db.String(20), nullable=True)
    tracking_token = db.Column(db.String(64), unique=True, index=True, nullable=False, default=lambda: f"rcp_{uuid.uuid4().hex[:12]}")

    status = db.Column(db.String(30), default='pending')  # 'pending', 'sent', 'delivered', 'failed', 'clicked', 'logged_in'
    sent_at = db.Column(db.DateTime, nullable=True)
    clicked_at = db.Column(db.DateTime, nullable=True)
    logged_in_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    lead = db.relationship('B2BLead', backref=db.backref('campaign_deliveries', lazy=True))
    client = db.relationship('B2BClient', backref=db.backref('campaign_deliveries', lazy=True))

    def __repr__(self):
        return f"<CRMCampaignRecipient {self.recipient_email or self.recipient_phone} ({self.status})>"
