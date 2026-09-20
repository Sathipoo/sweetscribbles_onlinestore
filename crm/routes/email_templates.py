import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from extensions import db
from models.b2b_crm import CRMEmailTemplate, B2BLead
from crm.routes.auth import crm_login_required
from utils.email_utils import _render_luxury_email_layout, DEFAULT_CC_EMAIL

templates_bp = Blueprint('crm_templates', __name__, url_prefix='/email-templates')

@templates_bp.route('/')
@crm_login_required
def list_templates():
    """
    Studio Gallery: Lists all saved email templates with category filtering,
    preview modal triggers, and management controls.
    """
    category_filter = request.args.get('category', '').strip()
    search = request.args.get('q', '').strip()

    query = CRMEmailTemplate.query.filter_by(is_active=True)

    if category_filter:
        query = query.filter_by(category=category_filter)

    if search:
        search_fmt = f"%{search}%"
        query = query.filter(
            (CRMEmailTemplate.name.ilike(search_fmt)) |
            (CRMEmailTemplate.subject.ilike(search_fmt))
        )

    templates = query.order_by(CRMEmailTemplate.updated_at.desc()).all()

    # Extract distinct categories
    all_categories = [c[0] for c in db.session.query(CRMEmailTemplate.category).distinct().filter(CRMEmailTemplate.is_active == True).all()]
    if not all_categories:
        all_categories = ['Festive', 'Sample Pitch', 'Follow-up', 'Custom']

    return render_template(
        'crm/email_templates/list.html',
        templates=templates,
        categories=all_categories,
        current_category=category_filter,
        search=search,
        default_cc=DEFAULT_CC_EMAIL
    )

@templates_bp.route('/new')
@crm_login_required
def new_template():
    """
    Opens the visual email builder for a fresh template with pre-configured starter blocks.
    """
    starter_blocks = {
        'banner_tag': 'Diwali & Festive Gifting 2026',
        'headline': 'Exclusive Festive Corporate Hampers for {company_name}',
        'salutation': 'Dear {contact_name},',
        'body_text': (
            'Warm greetings from Sweet Scribbles Artisanal Gifting!\n\n'
            'As festive celebrations approach, we are excited to introduce our 2026 Corporate Gifting Collection, '
            'curated especially for premier organizations like {company_name}.\n\n'
            'From handcrafted confections and luxury dry-fruit assortments to personalized leatherette keepsakes '
            'branded with your corporate insignia, our hampers are designed to leave an unforgettable impression.'
        ),
        'highlight_1': '✨ 100% Customized Logo Sleeves & Gold Foiled Ribbon',
        'highlight_2': '🚚 Pan-India Doorstep Delivery to {city}',
        'highlight_3': '🍫 Artisanal Belgian Truffles & Premium Nuts',
        'cta_text': 'Explore Corporate Gifting Showcase',
        'cta_url': '{outreach_link}',
        'signoff_name': 'Vishnu Govind',
        'signoff_title': 'Corporate Gifting Director, Sweet Scribbles',
        'theme_color': '#b48324'
    }

    return render_template(
        'crm/email_templates/builder.html',
        template=None,
        starter_blocks=starter_blocks,
        default_cc=DEFAULT_CC_EMAIL,
        initial_mode='visual',
        is_new=True
    )

@templates_bp.route('/<int:template_id>/edit')
@crm_login_required
def edit_template(template_id):
    """
    Opens the visual email builder with an existing template loaded.
    Detects whether template was authored with modular blocks or raw HTML.
    """
    tpl = db.session.get(CRMEmailTemplate, template_id)
    if not tpl:
        flash('Email template not found.', 'danger')
        return redirect(url_for('crm_templates.list_templates'))

    blocks = {}
    has_valid_blocks = False
    if tpl.blocks_json:
        try:
            loaded = json.loads(tpl.blocks_json)
            if isinstance(loaded, dict):
                blocks = loaded
                # Template has meaningful modular blocks if body_text or headline is populated
                if blocks.get('body_text') or blocks.get('headline') or blocks.get('salutation'):
                    has_valid_blocks = True
        except Exception:
            blocks = {}

    initial_mode = 'visual' if has_valid_blocks else 'code'

    return render_template(
        'crm/email_templates/builder.html',
        template=tpl,
        starter_blocks=blocks,
        default_cc=tpl.default_cc or DEFAULT_CC_EMAIL,
        initial_mode=initial_mode,
        is_new=False
    )

@templates_bp.route('/save', methods=['POST'])
@crm_login_required
def save_template():
    """
    Handles saving or updating an email template from the visual builder.
    Supports both JSON AJAX requests and standard form submissions.
    """
    is_json = request.is_json
    data = request.get_json(silent=True) or request.form

    template_id = data.get('id')
    name = (data.get('name') or '').strip()
    subject = (data.get('subject') or '').strip()
    category = (data.get('category') or 'Outreach').strip()
    default_cc = (data.get('default_cc') or DEFAULT_CC_EMAIL).strip()
    content_html = (data.get('content_html') or '').strip()
    blocks_json = data.get('blocks_json')
    editor_mode = (data.get('editor_mode') or 'visual').strip()

    if isinstance(blocks_json, dict):
        blocks_json_str = json.dumps(blocks_json)
    elif isinstance(blocks_json, str):
        blocks_json_str = blocks_json
    else:
        blocks_json_str = None

    if not name or not subject:
        if is_json:
            return jsonify({'success': False, 'error': 'Template name and subject line are required.'}), 400
        flash('Template name and subject line are required.', 'danger')
        return redirect(request.referrer or url_for('crm_templates.list_templates'))

    tpl = None
    if template_id:
        try:
            tpl = db.session.get(CRMEmailTemplate, int(template_id))
        except (ValueError, TypeError):
            tpl = None

    if not tpl:
        tpl = CRMEmailTemplate(
            name=name,
            subject=subject,
            category=category,
            default_cc=default_cc,
            content_html=content_html,
            blocks_json=blocks_json_str if editor_mode == 'visual' else None,
            is_active=True
        )
        db.session.add(tpl)
    else:
        tpl.name = name
        tpl.subject = subject
        tpl.category = category
        tpl.default_cc = default_cc
        tpl.content_html = content_html
        if editor_mode == 'visual' and blocks_json_str:
            tpl.blocks_json = blocks_json_str
        tpl.updated_at = datetime.utcnow()

    db.session.commit()

    if is_json:
        return jsonify({
            'success': True,
            'template_id': tpl.id,
            'edit_url': url_for('crm_templates.edit_template', template_id=tpl.id),
            'message': f'Template "{tpl.name}" saved successfully!'
        })

    flash(f'Template "{tpl.name}" saved successfully!', 'success')
    return redirect(url_for('crm_templates.list_templates'))

@templates_bp.route('/<int:template_id>/clone', methods=['POST'])
@crm_login_required
def clone_template(template_id):
    """
    Duplicates an existing template with a 'Copy of' prefix.
    """
    original = CRMEmailTemplate.query.get_or_404(template_id)
    cloned = CRMEmailTemplate(
        name=f"Copy of {original.name}",
        subject=original.subject,
        category=original.category,
        content_html=original.content_html,
        blocks_json=original.blocks_json,
        default_cc=original.default_cc,
        is_active=True
    )
    db.session.add(cloned)
    db.session.commit()
    flash(f'Cloned template created: "{cloned.name}"', 'success')
    return redirect(url_for('crm_templates.edit_template', template_id=cloned.id))

@templates_bp.route('/<int:template_id>/delete', methods=['POST'])
@crm_login_required
def delete_template(template_id):
    """
    Deactivates a template.
    """
    tpl = CRMEmailTemplate.query.get_or_404(template_id)
    tpl.is_active = False
    db.session.commit()
    flash(f'Template "{tpl.name}" has been removed.', 'info')
    return redirect(url_for('crm_templates.list_templates'))

@templates_bp.route('/api/list')
@crm_login_required
def api_list_templates():
    """
    Returns JSON list of active email templates for dynamic dropdowns in modals.
    """
    templates = CRMEmailTemplate.query.filter_by(is_active=True).order_by(CRMEmailTemplate.updated_at.desc()).all()
    res = []
    for t in templates:
        res.append({
            'id': t.id,
            'name': t.name,
            'subject': t.subject,
            'category': t.category,
            'default_cc': t.default_cc or DEFAULT_CC_EMAIL,
            'content_html': t.content_html,
            'blocks_json': t.blocks_json
        })
    return jsonify({'success': True, 'templates': res})

@templates_bp.route('/api/render-preview', methods=['POST'])
@crm_login_required
def api_render_preview():
    """
    Renders the luxury HTML email wrapper for live split-screen preview.
    """
    data = request.get_json(silent=True) or {}
    subject = data.get('subject', 'Exclusive Gifting Catalog')
    body_html = data.get('content_html', '')
    cta_text = data.get('cta_text', 'Explore Corporate Gifting Showcase')
    cta_url = data.get('cta_url', 'https://sweetscribbles.pikachooz.com/b2b')

    sample_lead = {
        'contact_name': data.get('sample_contact', 'Ananya Sharma'),
        'company_name': data.get('sample_company', 'Wipro Technologies'),
        'city': data.get('sample_city', 'Bangalore'),
        'designation': data.get('sample_designation', 'Head of HR'),
        'outreach_link': data.get('sample_link', 'https://sweetscribbles.pikachooz.com/b2b?trk=preview-token')
    }

    # Interpolate variables
    for k, v in sample_lead.items():
        subject = subject.replace(f"{{{k}}}", str(v))
        body_html = body_html.replace(f"{{{k}}}", str(v))
        cta_url = cta_url.replace(f"{{{k}}}", str(v))

    full_html = _render_luxury_email_layout(
        title=subject,
        preheader=subject,
        body_html=body_html,
        cta_text=cta_text,
        cta_url=cta_url
    )

    return jsonify({'success': True, 'html': full_html, 'subject': subject})
