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
    location = db.Column(db.String(255), nullable=True)
    tags = db.Column(db.String(255), nullable=True)

    # Lifecycle Stage
    # 'fresh_lead', 'dnp', 'call_back', 'prospect', 'meeting_scheduled', 'qualified',
    # 'converted', 'existing_cx', 'deferred_interest', 'not_interested', 'invalid'
    stage = db.Column(db.String(50), default='fresh_lead', index=True)

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
    contacts = db.relationship('B2BLeadContact', backref='lead', lazy=True, order_by="desc(B2BLeadContact.is_primary)", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<B2BLead {self.company_name} ({self.contact_name}) - Stage: {self.stage} (Score: {self.priority_score})>"

    @property
    def primary_contact(self):
        for c in self.contacts:
            if c.is_primary:
                return c
        return self.contacts[0] if self.contacts else None

    def set_primary_contact(self, contact_id):
        """Designates a contact as the primary POC and syncs parent lead credentials."""
        chosen = None
        for c in self.contacts:
            if c.id == contact_id:
                c.is_primary = True
                chosen = c
            else:
                c.is_primary = False
        if chosen:
            self.contact_name = chosen.name
            if chosen.phone:
                self.phone = chosen.phone
            if chosen.email:
                self.email = chosen.email
            if chosen.designation:
                self.designation = chosen.designation
        return chosen

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
            'fresh_lead': '1. Fresh Lead',
            'dnp': '2. DNP (Did Not Pick)',
            'call_back': '3. Call Back',
            'prospect': '4. Prospect',
            'meeting_scheduled': '5. Meeting Scheduled',
            'qualified': '6. Qualified',
            'converted': '7. Converted to Client',
            'existing_cx': '8. Existing CX',
            'deferred_interest': '9. Deferred Interest',
            'not_interested': '10. Not Interested',
            'invalid': '11. Invalid',
            # Legacy fallbacks
            'new': '1. Fresh Lead',
            'outreach_sent': '4. Prospect',
            'portal_active': '4. Prospect',
            'contacted': '3. Call Back',
            'warm_discussion': '6. Qualified',
            'disqualified': '10. Not Interested'
        }
        return stage_map.get(self.stage, (self.stage or 'fresh_lead').replace('_', ' ').title())

    @property
    def stage_badge_class(self):
        badge_map = {
            'fresh_lead': 'stage-badge-fresh_lead',
            'dnp': 'stage-badge-dnp',
            'call_back': 'stage-badge-call_back',
            'prospect': 'stage-badge-prospect',
            'meeting_scheduled': 'stage-badge-meeting_scheduled',
            'qualified': 'stage-badge-qualified',
            'converted': 'stage-badge-converted',
            'existing_cx': 'stage-badge-existing_cx',
            'deferred_interest': 'stage-badge-deferred_interest',
            'not_interested': 'stage-badge-not_interested',
            'invalid': 'stage-badge-invalid',
            # Legacy fallbacks
            'new': 'stage-badge-fresh_lead',
            'outreach_sent': 'stage-badge-prospect',
            'portal_active': 'stage-badge-prospect',
            'contacted': 'stage-badge-call_back',
            'warm_discussion': 'stage-badge-qualified',
            'disqualified': 'stage-badge-not_interested',
        }
        return badge_map.get(self.stage, 'stage-badge-fresh_lead')

    @property
    def google_maps_url(self):
        query = (self.location or self.city or '').strip()
        if not query:
            return None
        import urllib.parse
        return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(query)}"


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


class B2BLeadContact(db.Model):
    __tablename__ = 'b2b_lead_contacts'

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('b2b_leads.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    designation = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    is_primary = db.Column(db.Boolean, default=False, nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<B2BLeadContact {self.name} ({self.designation}) for Lead #{self.lead_id}>"


class CRMEmailTemplate(db.Model):
    __tablename__ = 'crm_email_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(50), default='Outreach', nullable=False)  # 'Diwali & Festive', 'Sample Pitch', 'Follow-up', 'Custom'
    content_html = db.Column(db.Text, nullable=False)
    blocks_json = db.Column(db.Text, nullable=True)  # Serialized modular builder blocks
    default_cc = db.Column(db.String(255), default='Vishnu.govind@pikachooz.com')
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<CRMEmailTemplate '{self.name}' ({self.category})>"

    def render_subject(self, lead_dict):
        """Interpolates dynamic tokens into the subject line."""
        res = self.subject or ""
        for k, v in lead_dict.items():
            res = res.replace(f"{{{k}}}", str(v or ''))
        return res

    def render_body(self, lead_dict):
        """Interpolates dynamic tokens into the template HTML."""
        res = self.content_html or ""
        for k, v in lead_dict.items():
            res = res.replace(f"{{{k}}}", str(v or ''))
        return res

    @property
    def is_visual_builder(self):
        """Returns True if template was designed using the visual block builder."""
        return bool(self.blocks_json and self.blocks_json.strip() and self.blocks_json != '[]')


class CRMLeadOwner(db.Model):
    """
    Sales representative or corporate team member who owns B2B leads.
    Managed via CRM Settings, available for lead assignment and pipeline filtering.
    """
    __tablename__ = 'crm_lead_owners'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(100), default='Sales Representative')
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<CRMLeadOwner '{self.name}' ({self.role}) - Active: {self.is_active}>"

    @property
    def assigned_leads_count(self):
        return B2BLead.query.filter_by(assigned_to=self.name).count()

