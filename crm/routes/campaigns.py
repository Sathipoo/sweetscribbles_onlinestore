import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from extensions import db
from models.b2b import B2BClient, B2BCommunicationLog
from models.b2b_crm import B2BLead, CRMCampaign, CRMCampaignRecipient
from crm.routes.auth import crm_login_required
from utils.email_utils import send_crm_campaign_email, DEFAULT_CC_EMAIL

campaigns_bp = Blueprint('crm_campaigns', __name__)

@campaigns_bp.route('/campaigns')
@crm_login_required
def list_campaigns():
    campaigns = CRMCampaign.query.order_by(CRMCampaign.created_at.desc()).all()

    total_dispatched = sum(c.sent_count for c in campaigns)
    total_logins_generated = sum(c.unique_logins_generated for c in campaigns)
    active_leads_count = B2BLead.query.filter(B2BLead.stage.in_(['new', 'outreach_sent'])).count()
    existing_clients_count = B2BClient.query.filter_by(is_archived=False).count()

    return render_template(
        'crm/campaigns.html',
        campaigns=campaigns,
        total_dispatched=total_dispatched,
        total_logins_generated=total_logins_generated,
        active_leads_count=active_leads_count,
        existing_clients_count=existing_clients_count
    )

@campaigns_bp.route('/campaigns/create', methods=['POST'])
@crm_login_required
def create_campaign():
    name = request.form.get('name', '').strip()
    target_audience = request.form.get('target_audience', 'leads')  # 'leads', 'existing_clients', 'both'
    channel = request.form.get('channel', 'email')
    subject = request.form.get('subject', '').strip()
    content_body = request.form.get('content_body', '').strip()
    cta_text = request.form.get('cta_text', 'Explore Corporate Festive Hampers').strip()
    cta_url = request.form.get('cta_url', 'https://sweetscribbles.pikachooz.com/b2b/hampers').strip()

    if not name or not content_body or not subject:
        flash('Campaign name, email subject, and message content are required.', 'danger')
        return redirect(url_for('crm_campaigns.list_campaigns'))

    campaign = CRMCampaign(
        name=name,
        target_audience=target_audience,
        channel=channel,
        subject=subject,
        content_body=content_body,
        cta_text=cta_text,
        cta_url=cta_url,
        status='draft',
        created_by='Sales Admin'
    )
    db.session.add(campaign)
    db.session.flush()

    recipients_added = 0

    # 1. Target Leads
    if target_audience in ['leads', 'both']:
        target_leads = B2BLead.query.filter(
            B2BLead.email.isnot(None),
            B2BLead.stage != 'converted'
        ).all()
        for lead in target_leads:
            rcp = CRMCampaignRecipient(
                campaign_id=campaign.id,
                lead_id=lead.id,
                recipient_email=lead.email,
                recipient_phone=lead.phone,
                tracking_token=f"rcp_{uuid.uuid4().hex[:12]}",
                status='pending'
            )
            db.session.add(rcp)
            recipients_added += 1

    # 2. Target Existing Corporate Clients
    if target_audience in ['existing_clients', 'both']:
        active_clients = B2BClient.query.filter(
            B2BClient.email.isnot(None),
            B2BClient.is_archived == False
        ).all()
        for client in active_clients:
            rcp = CRMCampaignRecipient(
                campaign_id=campaign.id,
                client_id=client.id,
                recipient_email=client.email,
                recipient_phone=client.phone,
                tracking_token=f"rcp_{uuid.uuid4().hex[:12]}",
                status='pending'
            )
            db.session.add(rcp)
            recipients_added += 1

    campaign.total_recipients = recipients_added
    db.session.commit()

    flash(f'Campaign "{name}" created in draft mode with {recipients_added} target recipients.', 'success')
    return redirect(url_for('crm_campaigns.campaign_detail', campaign_id=campaign.id))

@campaigns_bp.route('/campaigns/<int:campaign_id>')
@crm_login_required
def campaign_detail(campaign_id):
    campaign = CRMCampaign.query.get_or_404(campaign_id)
    recipients = CRMCampaignRecipient.query.filter_by(campaign_id=campaign.id).all()
    store_base_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')

    return render_template(
        'crm/campaign_detail.html',
        campaign=campaign,
        recipients=recipients,
        store_base_url=store_base_url,
        cc_email=DEFAULT_CC_EMAIL
    )

@campaigns_bp.route('/campaigns/<int:campaign_id>/dispatch', methods=['POST'])
@crm_login_required
def dispatch_campaign(campaign_id):
    campaign = CRMCampaign.query.get_or_404(campaign_id)
    recipients = CRMCampaignRecipient.query.filter_by(campaign_id=campaign.id, status='pending').all()

    if not recipients:
        flash('No pending recipients found to dispatch.', 'warning')
        return redirect(url_for('crm_campaigns.campaign_detail', campaign_id=campaign.id))

    store_base_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')
    sent_count = 0
    failed_count = 0

    for rcp in recipients:
        contact_name = rcp.lead.contact_name if rcp.lead else (rcp.client.contact_name if rcp.client else "Valued Partner")
        company_name = rcp.lead.company_name if rcp.lead else (rcp.client.company_name if rcp.client else "Corporate Partner")

        # Tracked URL containing unique token
        separator = '&' if '?' in campaign.cta_url else '?'
        personalized_cta_url = f"{campaign.cta_url}{separator}trk={rcp.tracking_token}"

        # Replace template placeholders
        rendered_body = campaign.content_body.replace('{contact_name}', contact_name)
        rendered_body = rendered_body.replace('{company_name}', company_name)
        rendered_body = rendered_body.replace('{tracking_link}', personalized_cta_url)

        # Dispatch via Gmail SMTP (automatically CC's Vishnu.govind@pikachooz.com)
        success, msg = send_crm_campaign_email(
            to_email=rcp.recipient_email,
            subject=campaign.subject,
            recipient_name=contact_name,
            content_html=rendered_body,
            cta_text=campaign.cta_text,
            cta_url=personalized_cta_url
        )

        if success:
            rcp.status = 'sent'
            rcp.sent_at = datetime.utcnow()
            sent_count += 1

            if rcp.lead:
                rcp.lead.stage = 'outreach_sent'
                rcp.lead.update_score(10, f"Outreach email dispatched: {campaign.name}")

            if rcp.client:
                comm_log = B2BCommunicationLog(
                    client_id=rcp.client.id,
                    channel='email',
                    event_type='promotional_campaign',
                    recipient=rcp.recipient_email,
                    subject=campaign.subject,
                    message_preview=f"Campaign: {campaign.name} [CC: {DEFAULT_CC_EMAIL}]",
                    status='sent'
                )
                db.session.add(comm_log)
        else:
            rcp.status = 'failed'
            failed_count += 1

    campaign.sent_count = (campaign.sent_count or 0) + sent_count
    campaign.failed_count = (campaign.failed_count or 0) + failed_count
    campaign.status = 'sent'
    db.session.commit()

    flash(
        f'Campaign dispatched! Sent: {sent_count}, Failed: {failed_count}. '
        f'All outgoing emails automatically CC’d to {DEFAULT_CC_EMAIL}.',
        'success' if sent_count > 0 else 'danger'
    )
    return redirect(url_for('crm_campaigns.campaign_detail', campaign_id=campaign.id))
