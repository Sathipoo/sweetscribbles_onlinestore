import json
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response, current_app, session
from extensions import db
from models.b2b_crm import CRMCalendarEvent, B2BLead, CRMLeadOwner
from models.b2b import B2BOrder
from crm.routes.auth import crm_login_required
from utils.calendar_utils import (
    generate_ics_calendar,
    generate_google_calendar_link,
    dispatch_calendar_invitations_and_sync,
    generate_live_webcal_feed,
    DEFAULT_TEAM_AUTO_SYNC
)

calendar_bp = Blueprint('crm_calendar', __name__)


@calendar_bp.route('/calendar')
@crm_login_required
def view_calendar():
    """
    Main CRM Calendar Workspace.
    Provides Month, Week, and Agenda views for Client Meetings,
    Order Delivery Deadlines, Sampling Dispatches, and Office Events.
    """
    now = datetime.utcnow()
    # Summary KPI counts
    total_events = CRMCalendarEvent.query.filter(CRMCalendarEvent.status != 'cancelled').count()
    upcoming_meetings = CRMCalendarEvent.query.filter(
        CRMCalendarEvent.event_type == 'client_meeting',
        CRMCalendarEvent.start_time >= now - timedelta(days=1),
        CRMCalendarEvent.status != 'cancelled'
    ).count()
    delivery_deadlines = CRMCalendarEvent.query.filter(
        CRMCalendarEvent.event_type == 'delivery_deadline',
        CRMCalendarEvent.start_time >= now - timedelta(days=1),
        CRMCalendarEvent.status != 'cancelled'
    ).count()
    samplings_count = CRMCalendarEvent.query.filter(
        CRMCalendarEvent.event_type == 'sampling_delivery',
        CRMCalendarEvent.start_time >= now - timedelta(days=1),
        CRMCalendarEvent.status != 'cancelled'
    ).count()
    office_events = CRMCalendarEvent.query.filter(
        CRMCalendarEvent.event_type == 'office_event',
        CRMCalendarEvent.start_time >= now - timedelta(days=1),
        CRMCalendarEvent.status != 'cancelled'
    ).count()

    # Active leads for linking dropdown in Add Event modal
    leads = B2BLead.query.order_by(B2BLead.company_name.asc()).all()
    # Registered owners for owner filter and assignment
    owners = CRMLeadOwner.query.filter_by(is_active=True).order_by(CRMLeadOwner.name.asc()).all()

    # Store base URL for feed link and lead links
    store_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')
    feed_url = f"{request.host_url.rstrip('/')}/crm/calendar/feed.ics"

    return render_template(
        'crm/calendar.html',
        total_events=total_events,
        upcoming_meetings=upcoming_meetings,
        delivery_deadlines=delivery_deadlines,
        samplings_count=samplings_count,
        office_events=office_events,
        leads=leads,
        owners=owners,
        feed_url=feed_url,
        default_team_sync=DEFAULT_TEAM_AUTO_SYNC,
        current_user=session.get('crm_user', 'Sales Operations')
    )


@calendar_bp.route('/calendar/events-json')
@crm_login_required
def get_events_json():
    """
    JSON API returning filtered events for the interactive calendar (Month, Week, Agenda).
    Supports category filtering, owner filtering, and keyword search.
    """
    event_type = request.args.get('type', 'all').strip()
    owner = request.args.get('owner', '').strip()
    search = request.args.get('q', '').strip().lower()

    query = CRMCalendarEvent.query

    if event_type and event_type != 'all':
        query = query.filter(CRMCalendarEvent.event_type == event_type)

    if owner:
        if owner == '__unassigned__':
            query = query.filter((CRMCalendarEvent.assigned_to.is_(None)) | (CRMCalendarEvent.assigned_to == ''))
        else:
            query = query.filter(CRMCalendarEvent.assigned_to == owner)

    events = query.order_by(CRMCalendarEvent.start_time.asc()).all()

    result = []
    for ev in events:
        if search:
            match = (
                search in ev.title.lower() or
                (ev.meeting_notes and search in ev.meeting_notes.lower()) or
                (ev.lead and search in ev.lead.company_name.lower()) or
                (ev.attendee_emails and search in ev.attendee_emails.lower())
            )
            if not match:
                continue

        lead_info = None
        if ev.lead:
            lead_info = {
                'id': ev.lead.id,
                'company_name': ev.lead.company_name,
                'contact_name': ev.lead.contact_name,
                'phone': ev.lead.phone,
                'email': ev.lead.email,
                'stage': ev.lead.stage,
                'stage_display': ev.lead.stage_display,
                'url': url_for('crm_leads.lead_detail', lead_id=ev.lead.id)
            }

        gcal_url = generate_google_calendar_link(ev)

        result.append({
            'id': ev.id,
            'title': ev.title,
            'event_type': ev.event_type,
            'event_type_display': ev.event_type_display,
            'badge_class': ev.event_badge_class,
            'status_badge_class': ev.status_badge_class,
            'is_all_day': ev.is_all_day,
            'start': ev.start_time.isoformat(),
            'end': ev.end_time.isoformat(),
            'date_str': ev.start_time.strftime("%Y-%m-%d"),
            'start_time_str': ev.start_time.strftime("%I:%M %p") if not ev.is_all_day else 'All Day',
            'end_time_str': ev.end_time.strftime("%I:%M %p") if not ev.is_all_day else 'All Day',
            'duration_minutes': ev.duration_minutes,
            'location_type': ev.location_type,
            'location_details': ev.location_details or '',
            'notes': ev.meeting_notes or '',
            'organizer_name': ev.organizer_name,
            'organizer_email': ev.organizer_email,
            'assigned_to': ev.assigned_to or 'Unassigned',
            'attendee_emails': ev.attendee_emails or '',
            'status': ev.status,
            'priority': ev.priority,
            'lead': lead_info,
            'google_calendar_url': gcal_url
        })

    return jsonify({'success': True, 'events': result, 'count': len(result)})


@calendar_bp.route('/calendar/events/add', methods=['POST'])
@crm_login_required
def add_event():
    """
    Creates a new calendar event, client meeting, or delivery deadline.
    Auto-syncs into vishnu.govind@pikachooz.com and sathishkumar.dm@pikachooz.com.
    """
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    data = request.get_json(silent=True) or request.form

    title = data.get('title', '').strip()
    event_type = data.get('event_type', 'client_meeting').strip()
    is_all_day = bool(data.get('is_all_day') in [True, '1', 'true', 'on', 'y', 'yes'])

    event_date_str = (data.get('event_date') or data.get('start_date') or '').strip()
    start_time_str = data.get('start_time', '11:00').strip()
    duration_minutes = int(data.get('duration_minutes', 45) or 45)

    lead_id = data.get('lead_id')
    if lead_id and str(lead_id).isdigit():
        lead_id = int(lead_id)
    else:
        lead_id = None

    if not title:
        msg = "Event title is required."
        return jsonify({'success': False, 'message': msg}), 400 if is_ajax else flash(msg, 'danger')

    if not event_date_str:
        msg = "Event date is required."
        return jsonify({'success': False, 'message': msg}), 400 if is_ajax else flash(msg, 'danger')

    try:
        if is_all_day:
            start_dt = datetime.strptime(event_date_str, "%Y-%m-%d")
            end_dt = start_dt.replace(hour=23, minute=59, second=59)
        else:
            dt_combined = f"{event_date_str} {start_time_str}"
            start_dt = datetime.strptime(dt_combined, "%Y-%m-%d %H:%M")
            end_dt = start_dt + timedelta(minutes=duration_minutes)
    except Exception as e:
        msg = f"Invalid date/time format: {str(e)}"
        return jsonify({'success': False, 'message': msg}), 400 if is_ajax else flash(msg, 'danger')

    location_type = data.get('location_type', 'google_meet').strip()
    location_details = data.get('location_details', '').strip()
    meeting_notes = data.get('meeting_notes', '').strip()
    assigned_to = data.get('assigned_to', '').strip() or session.get('crm_user', 'Sales Operations')
    priority = data.get('priority', 'normal').strip()

    # Collect attendees: team auto-sync + custom attendees + client POC
    team_sync_selected = []
    if hasattr(data, 'getlist'):
        team_sync_selected = data.getlist('team_sync[]') or data.getlist('team_sync')
    elif isinstance(data.get('team_sync'), list):
        team_sync_selected = data.get('team_sync')

    if not team_sync_selected and not data.get('team_sync_custom_off'):
        # Default auto-sync core team
        team_sync_selected = list(DEFAULT_TEAM_AUTO_SYNC)

    client_emails = []
    lead = B2BLead.query.get(lead_id) if lead_id else None
    if lead:
        if lead.email:
            client_emails.append(lead.email)
        # Check secondary POCs if submitted
        if hasattr(data, 'getlist'):
            extra_poc_emails = data.getlist('poc_emails[]') or data.getlist('poc_emails')
            client_emails.extend(extra_poc_emails)

    additional_attendees_raw = data.get('additional_attendees', '')
    if additional_attendees_raw:
        client_emails.extend([e.strip() for e in additional_attendees_raw.split(',') if '@' in e])

    all_attendees = list(set([e.strip() for e in (team_sync_selected + client_emails) if e and e.strip()]))

    # Instantiate event
    event = CRMCalendarEvent(
        title=title,
        event_type=event_type,
        is_all_day=is_all_day,
        start_time=start_dt,
        end_time=end_dt,
        duration_minutes=duration_minutes,
        lead_id=lead_id,
        location_type=location_type,
        location_details=location_details,
        meeting_notes=meeting_notes,
        organizer_name=session.get('crm_user', 'Sweet Scribbles Corporate'),
        organizer_email=current_app.config.get('SENDER_EMAIL', 'pooja.sathish@pikachooz.com'),
        assigned_to=assigned_to,
        attendee_emails=", ".join(all_attendees) if all_attendees else None,
        status='scheduled',
        priority=priority
    )

    db.session.add(event)

    # If linked to lead and event is client meeting, advance lead stage to meeting_scheduled
    if lead and event_type == 'client_meeting':
        old_stage = lead.stage
        lead.stage = 'meeting_scheduled'
        lead.update_score(30, f"Meeting scheduled: '{title}' on {start_dt.strftime('%d %b %Y, %I:%M %p')}")
        timestamp = datetime.utcnow().strftime("%d %b %Y, %I:%M %p")
        lead.notes = f"[{timestamp} - Meeting Scheduled]\n{title} ({start_dt.strftime('%d %b %Y, %I:%M %p')})\nNotes: {meeting_notes}\n\n" + (lead.notes or '')

    db.session.commit()

    # Dispatch calendar invitations & auto-sync if requested
    send_invites = data.get('send_invites') in [True, '1', 'true', 'on', None]
    if send_invites and all_attendees:
        try:
            store_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')
            success_count, total_count, errors = dispatch_calendar_invitations_and_sync(
                event=event,
                team_emails=team_sync_selected,
                client_emails=client_emails,
                store_base_url=store_url
            )
            event.email_sent = True
            event.email_sent_at = datetime.utcnow()
            db.session.commit()
        except Exception as e:
            pass

    success_msg = f"'{title}' scheduled successfully on {start_dt.strftime('%d %b %Y')}!"
    if is_ajax:
        return jsonify({
            'success': True,
            'message': success_msg,
            'event_id': event.id,
            'google_calendar_url': generate_google_calendar_link(event)
        })
    
    flash(success_msg, 'success')
    return redirect(url_for('crm_calendar.view_calendar'))


@calendar_bp.route('/calendar/events/<int:event_id>/edit', methods=['POST'])
@crm_login_required
def edit_event(event_id):
    """Updates an existing calendar event or delivery deadline."""
    event = CRMCalendarEvent.query.get_or_404(event_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    data = request.get_json(silent=True) or request.form

    title = data.get('title', '').strip()
    if title:
        event.title = title

    event_type = data.get('event_type', '').strip()
    if event_type:
        event.event_type = event_type

    is_all_day = bool(data.get('is_all_day') in [True, '1', 'true', 'on', 'y', 'yes'])
    event.is_all_day = is_all_day

    event_date_str = (data.get('event_date') or data.get('start_date') or '').strip()
    start_time_str = data.get('start_time', '11:00').strip()
    duration_minutes = int(data.get('duration_minutes', 45) or 45)

    if event_date_str:
        try:
            if is_all_day:
                start_dt = datetime.strptime(event_date_str, "%Y-%m-%d")
                end_dt = start_dt.replace(hour=23, minute=59, second=59)
            else:
                dt_combined = f"{event_date_str} {start_time_str}"
                start_dt = datetime.strptime(dt_combined, "%Y-%m-%d %H:%M")
                end_dt = start_dt + timedelta(minutes=duration_minutes)

            event.start_time = start_dt
            event.end_time = end_dt
            event.duration_minutes = duration_minutes
        except Exception as e:
            return jsonify({'success': False, 'message': f'Invalid date format: {str(e)}'}), 400

    if 'location_type' in data:
        event.location_type = data.get('location_type', '').strip()
    if 'location_details' in data:
        event.location_details = data.get('location_details', '').strip()
    if 'meeting_notes' in data:
        event.meeting_notes = data.get('meeting_notes', '').strip()
    if 'assigned_to' in data:
        event.assigned_to = data.get('assigned_to', '').strip()
    if 'status' in data and data.get('status'):
        event.status = data.get('status').strip()
    if 'priority' in data and data.get('priority'):
        event.priority = data.get('priority').strip()

    event.updated_at = datetime.utcnow()
    db.session.commit()

    # Re-sync calendar if requested
    resend = data.get('resend_invites') in [True, '1', 'true', 'on']
    if resend and event.attendee_emails:
        try:
            store_url = current_app.config.get('STORE_BASE_URL', 'https://sweetscribbles.pikachooz.com')
            dispatch_calendar_invitations_and_sync(
                event=event,
                team_emails=event.attendee_email_list,
                store_base_url=store_url
            )
        except Exception:
            pass

    msg = f"'{event.title}' updated successfully."
    if is_ajax:
        return jsonify({'success': True, 'message': msg, 'event_id': event.id})
    flash(msg, 'success')
    return redirect(url_for('crm_calendar.view_calendar'))


@calendar_bp.route('/calendar/events/<int:event_id>/toggle-status', methods=['POST'])
@crm_login_required
def toggle_status(event_id):
    """Quick 1-click toggle to mark an event or delivery deadline as Completed."""
    event = CRMCalendarEvent.query.get_or_404(event_id)
    if event.status == 'completed':
        event.status = 'scheduled'
    else:
        event.status = 'completed'
    
    event.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'status': event.status,
        'message': f"Marked '{event.title}' as {event.status.title()}."
    })


@calendar_bp.route('/calendar/events/<int:event_id>/delete', methods=['POST'])
@crm_login_required
def delete_event(event_id):
    """Deletes a calendar event or delivery deadline."""
    event = CRMCalendarEvent.query.get_or_404(event_id)
    title = event.title
    db.session.delete(event)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': f"Event '{title}' deleted."
    })


@calendar_bp.route('/calendar/feed.ics')
def calendar_feed():
    """
    Live RFC 5545 iCalendar (WebCal) subscription feed.
    Can be subscribed to in macOS Apple Calendar or Google Calendar via URL.
    """
    # Return all active events (not cancelled)
    events = CRMCalendarEvent.query.filter(CRMCalendarEvent.status != 'cancelled').order_by(CRMCalendarEvent.start_time.asc()).all()
    feed_content = generate_live_webcal_feed(events)
    return Response(feed_content, mimetype='text/calendar', headers={
        'Content-Disposition': 'inline; filename="sweetscribbles_crm.ics"',
        'Cache-Control': 'no-cache, no-store, must-revalidate'
    })
