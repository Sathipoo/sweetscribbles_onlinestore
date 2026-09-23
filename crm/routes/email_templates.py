import os
import json
import uuid
import mimetypes
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from werkzeug.utils import secure_filename
from extensions import db
from models.b2b_crm import CRMEmailTemplate, B2BLead, CRMLeadOwner
from crm.routes.auth import crm_login_required
from utils.email_utils import _render_luxury_email_layout, DEFAULT_CC_EMAIL

templates_bp = Blueprint('crm_templates', __name__, url_prefix='/email-templates')

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'xlsx', 'xls', 'pptx', 'ppt', 'png', 'jpg', 'jpeg', 'csv', 'txt', 'zip'}
MAX_ATTACHMENT_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def format_file_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


@templates_bp.route('/upload-attachment', methods=['POST'])
@crm_login_required
def upload_attachment():
    """
    Accepts an uploaded file attachment for an email template.
    Saves file to static/uploads/email_attachments and returns attachment metadata.
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded.'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected.'}), 400

    if not allowed_file(file.filename):
        exts = ", ".join(sorted(list(ALLOWED_EXTENSIONS)))
        return jsonify({'success': False, 'error': f'Unsupported file type. Allowed: {exts}'}), 400

    # Ensure upload directory exists in project root static
    base_dir = current_app.root_path
    if os.path.basename(base_dir) == 'crm':
        base_dir = os.path.dirname(base_dir)
    upload_dir = os.path.join(base_dir, 'static', 'uploads', 'email_attachments')
    os.makedirs(upload_dir, exist_ok=True)

    original_filename = file.filename
    clean_name = secure_filename(original_filename)
    if not clean_name:
        clean_name = "attachment"

    file_id = f"att_{uuid.uuid4().hex[:10]}"
    saved_filename = f"{file_id}_{clean_name}"
    save_path = os.path.join(upload_dir, saved_filename)

    file.save(save_path)
    file_size = os.path.getsize(save_path)

    if file_size > MAX_ATTACHMENT_SIZE_BYTES:
        try:
            os.remove(save_path)
        except Exception:
            pass
        return jsonify({'success': False, 'error': 'File exceeds maximum 15MB size limit.'}), 400

    mime_type, _ = mimetypes.guess_type(original_filename)
    if not mime_type:
        mime_type = 'application/octet-stream'

    rel_path = f"static/uploads/email_attachments/{saved_filename}"

    attachment_meta = {
        'id': file_id,
        'filename': saved_filename,
        'original_filename': original_filename,
        'file_path': rel_path,
        'file_size': file_size,
        'file_size_formatted': format_file_size(file_size),
        'mime_type': mime_type,
        'uploaded_at': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }

    return jsonify({
        'success': True,
        'attachment': attachment_meta,
        'message': f"Attached '{original_filename}' successfully!"
    })

@templates_bp.route('/')
@crm_login_required
def list_templates():
    """
    Studio Gallery: Lists all saved email templates with category filtering,
    preview modal triggers, and management controls within the CRM Settings workspace.
    """
    category_filter = request.args.get('category', '').strip()
    search = request.args.get('q', '').strip()

    query = CRMEmailTemplate.query.filter_by(is_active=True)

    if category_filter:
        query = query.filter(CRMEmailTemplate.category.ilike(category_filter))

    if search:
        search_fmt = f"%{search}%"
        query = query.filter(
            (CRMEmailTemplate.name.ilike(search_fmt)) |
            (CRMEmailTemplate.subject.ilike(search_fmt))
        )

    templates = query.order_by(CRMEmailTemplate.updated_at.desc()).all()

    # Extract distinct categories deduplicated case-insensitively
    raw_categories = [c[0].strip() for c in db.session.query(CRMEmailTemplate.category).distinct().filter(CRMEmailTemplate.is_active == True).all() if c[0] and c[0].strip()]
    seen = {}
    for c in raw_categories:
        key = c.lower()
        if key not in seen:
            seen[key] = c.title()
    all_categories = sorted(list(seen.values()))
    if not all_categories:
        all_categories = ['Festive', 'Sample Pitch', 'Follow-up', 'Custom']

    total_owners = CRMLeadOwner.query.count()
    total_templates = CRMEmailTemplate.query.filter_by(is_active=True).count()

    return render_template(
        'crm/email_templates/list.html',
        templates=templates,
        categories=all_categories,
        current_category=category_filter,
        search=search,
        default_cc=DEFAULT_CC_EMAIL,
        total_owners=total_owners,
        total_templates=total_templates,
        active_settings_tab='email_templates'
    )

@templates_bp.route('/new')
@crm_login_required
def new_template():
    """
    Opens the visual email builder for a fresh template with pre-configured starter blocks.
    """
    store_base_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')
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
        'include_gif': True,
        'gif_url': f'{store_base_url}/static/gifs/pika_ss_signature.gif',
        'theme_color': '#b48324'
    }

    return render_template(
        'crm/email_templates/builder.html',
        template=None,
        starter_blocks=starter_blocks,
        default_cc=DEFAULT_CC_EMAIL,
        initial_mode='visual',
        is_new=True,
        store_base_url=store_base_url
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
    store_base_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')

    return render_template(
        'crm/email_templates/builder.html',
        template=tpl,
        starter_blocks=blocks,
        default_cc=tpl.default_cc or DEFAULT_CC_EMAIL,
        initial_mode=initial_mode,
        is_new=False,
        store_base_url=store_base_url
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

    attachments = data.get('attachments')
    if isinstance(attachments, str):
        try:
            attachments = json.loads(attachments)
        except Exception:
            attachments = []
    if isinstance(attachments, list):
        attachments_json_str = json.dumps(attachments)
    else:
        attachments_json_str = None

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
            attachments_json=attachments_json_str,
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
        tpl.attachments_json = attachments_json_str
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
    Duplicates an existing template with a 'Copy of' prefix, preserving attachments.
    """
    original = CRMEmailTemplate.query.get_or_404(template_id)
    cloned = CRMEmailTemplate(
        name=f"Copy of {original.name}",
        subject=original.subject,
        category=original.category,
        content_html=original.content_html,
        blocks_json=original.blocks_json,
        attachments_json=original.attachments_json,
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
    Returns JSON list of active email templates with attachments for dynamic dropdowns in modals.
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
            'blocks_json': t.blocks_json,
            'attachments': t.attachments
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
    store_base_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')
    sig_gif_tag = f'<div style="margin-top: 14px;"><img src="{store_base_url}/static/gifs/pika_ss_signature.gif" alt="Sweet Scribbles Signature" style="width: 240px; max-width: 100%; height: auto; display: block; border-radius: 4px;" /></div>'

    for k, v in sample_lead.items():
        subject = subject.replace(f"{{{k}}}", str(v))
        body_html = body_html.replace(f"{{{k}}}", str(v))
        cta_url = cta_url.replace(f"{{{k}}}", str(v))

    body_html = body_html.replace('{signature_gif}', sig_gif_tag)

    full_html = _render_luxury_email_layout(
        title=subject,
        preheader=subject,
        body_html=body_html,
        cta_text=cta_text,
        cta_url=cta_url
    )

    return jsonify({'success': True, 'html': full_html, 'subject': subject})
