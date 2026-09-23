import os
import uuid
import urllib.parse
from datetime import datetime, timedelta
from utils.email_utils import send_b2b_email, _render_luxury_email_layout

# Default core team auto-sync recipients
DEFAULT_TEAM_AUTO_SYNC = [
    "vishnu.govind@pikachooz.com",
    "sathishkumar.dm@pikachooz.com",
    "pooja.sathish@pikachooz.com"
]


def format_utc_timestamp(dt, all_day=False):
    """Formats a datetime to RFC 5545 timestamp."""
    if not dt:
        dt = datetime.utcnow()
    if all_day:
        return dt.strftime("%Y%m%d")
    return dt.strftime("%Y%m%dT%H%M%SZ")


def escape_ics_text(text):
    """Escapes characters according to RFC 5545 specs."""
    if not text:
        return ""
    text = str(text)
    text = text.replace('\\', '\\\\')
    text = text.replace(';', '\\;')
    text = text.replace(',', '\\,')
    text = text.replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\n')
    return text


def generate_ics_calendar(event, attendees=None, method='REQUEST'):
    """
    Generates standard RFC 5545 iCalendar (.ics) content for an event.
    When delivered to Gmail/Google Calendar with method=REQUEST, Google Calendar
    automatically creates the event and displays interactive RSVP options.
    """
    now_utc = format_utc_timestamp(datetime.utcnow())
    uid = event.ics_uid or f"ss_event_{uuid.uuid4().hex[:16]}@sweetscribbles.com"

    summary = escape_ics_text(event.title)
    description = escape_ics_text(event.meeting_notes or f"Sweet Scribbles B2B Event - {event.event_type_display}")
    location = escape_ics_text(event.location_details or event.location_type or "Online / Sweet Scribbles Studio")
    
    organizer_name = escape_ics_text(event.organizer_name or "Sweet Scribbles Corporate")
    organizer_email = event.organizer_email or "pooja.sathish@pikachooz.com"

    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//Sweet Scribbles//B2B CRM Calendar//EN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now_utc}",
    ]

    if event.is_all_day:
        dt_start = format_utc_timestamp(event.start_time, all_day=True)
        # End date in all-day events is exclusive in iCal
        end_date = event.end_time + timedelta(days=1) if event.end_time else event.start_time + timedelta(days=1)
        dt_end = format_utc_timestamp(end_date, all_day=True)
        lines.append(f"DTSTART;VALUE=DATE:{dt_start}")
        lines.append(f"DTEND;VALUE=DATE:{dt_end}")
    else:
        dt_start = format_utc_timestamp(event.start_time)
        dt_end = format_utc_timestamp(event.end_time or (event.start_time + timedelta(minutes=event.duration_minutes or 45)))
        lines.append(f"DTSTART:{dt_start}")
        lines.append(f"DTEND:{dt_end}")

    lines.append(f"SUMMARY:{summary}")
    lines.append(f"DESCRIPTION:{description}")
    lines.append(f"LOCATION:{location}")
    lines.append(f"ORGANIZER;CN=\"{organizer_name}\":mailto:{organizer_email}")

    # Attendees
    all_attendees = set()
    if attendees:
        for a in attendees:
            if a and a.strip():
                all_attendees.add(a.strip())
    if event.attendee_emails:
        for a in event.attendee_emails.split(','):
            if a and a.strip():
                all_attendees.add(a.strip())

    for att in sorted(all_attendees):
        clean_att = escape_ics_text(att)
        lines.append(f"ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE;CN=\"{clean_att}\":mailto:{clean_att}")

    lines.append("STATUS:CONFIRMED")
    lines.append("SEQUENCE:0")
    lines.append("TRANSP:OPAQUE")

    # Alarm 15 minutes before
    lines.extend([
        "BEGIN:VALARM",
        "TRIGGER:-PT15M",
        "ACTION:DISPLAY",
        f"DESCRIPTION:Reminder: {summary}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR"
    ])

    return "\r\n".join(lines) + "\r\n"


def generate_google_calendar_link(event):
    """
    Generates a direct 1-click web URL to create the event in Google Calendar:
    https://calendar.google.com/calendar/render?action=TEMPLATE&...
    """
    base_url = "https://calendar.google.com/calendar/render"

    if event.is_all_day:
        start_str = event.start_time.strftime("%Y%m%d")
        end_date = event.end_time + timedelta(days=1) if event.end_time else event.start_time + timedelta(days=1)
        end_str = end_date.strftime("%Y%m%d")
        dates_param = f"{start_str}/{end_str}"
    else:
        start_str = format_utc_timestamp(event.start_time)
        end_dt = event.end_time or (event.start_time + timedelta(minutes=event.duration_minutes or 45))
        end_str = format_utc_timestamp(end_dt)
        dates_param = f"{start_str}/{end_str}"

    details = event.meeting_notes or f"Sweet Scribbles B2B Event - {event.event_type_display}"
    if event.lead:
        details += f"\n\nCompany: {event.lead.company_name}\nPrimary POC: {event.lead.contact_name} ({event.lead.phone or ''})"

    params = {
        "action": "TEMPLATE",
        "text": event.title or "Sweet Scribbles Meeting",
        "dates": dates_param,
        "details": details,
        "location": event.location_details or event.location_type or "Sweet Scribbles Studio"
    }

    if event.attendee_emails:
        params["add"] = event.attendee_emails

    return f"{base_url}?{urllib.parse.urlencode(params)}"


def dispatch_calendar_invitations_and_sync(event, team_emails=None, client_emails=None, store_base_url="https://sweetscribbles.pikachooz.com"):
    """
    Sends meeting/deadline confirmations & invitations with attached .ics calendar requests.
    - Sends to executive team (vishnu.govind@pikachooz.com, sathishkumar.dm@pikachooz.com) for auto Google Calendar addition.
    - Sends to client attendees if provided.
    Returns (success_count, total_count, errors)
    """
    # Consolidate team emails
    team_list = list(team_emails) if team_emails else list(DEFAULT_TEAM_AUTO_SYNC)
    if event.organizer_email and event.organizer_email not in team_list:
        team_list.append(event.organizer_email)

    client_list = list(client_emails) if client_emails else []
    all_recipients = list(set([e.strip() for e in (team_list + client_list) if e and e.strip()]))

    ics_content = generate_ics_calendar(event, attendees=all_recipients, method='REQUEST')
    ics_attachment = ("invite.ics", ics_content.encode('utf-8'), "text/calendar; charset=UTF-8; method=REQUEST")

    gcal_link = generate_google_calendar_link(event)
    date_formatted = event.start_time.strftime("%A, %d %B %Y")
    time_formatted = "All Day" if event.is_all_day else f"{event.start_time.strftime('%I:%M %p')} - {(event.end_time or event.start_time + timedelta(minutes=event.duration_minutes)).strftime('%I:%M %p')} (IST)"

    success_count = 0
    errors = []

    # 1. Team Notification (vishnu.govind@pikachooz.com & sathishkumar.dm@pikachooz.com)
    team_subject = f"📅 Confirmed: {event.title} on {date_formatted} [{time_formatted}]"
    lead_info_html = ""
    if event.lead:
        lead_dossier_url = f"{store_base_url}/crm/leads/{event.lead.id}"
        lead_info_html = f"""
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin: 16px 0;">
            <p style="margin: 0 0 6px 0; font-size: 14px; color: #1e293b;"><strong>🏢 Client / Lead:</strong> {event.lead.company_name}</p>
            <p style="margin: 0 0 6px 0; font-size: 13px; color: #475569;"><strong>👤 Primary POC:</strong> {event.lead.contact_name} ({event.lead.designation or 'POC'})</p>
            <p style="margin: 0 0 6px 0; font-size: 13px; color: #475569;"><strong>📞 Phone:</strong> {event.lead.phone or 'N/A'} | <strong>✉️ Email:</strong> {event.lead.email or 'N/A'}</p>
            <p style="margin: 0; font-size: 13px;"><a href="{lead_dossier_url}" style="color: #b45309; font-weight: 600; text-decoration: underline;">Open Lead Dossier in CRM &rarr;</a></p>
        </div>
        """

    team_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; line-height: 1.6;">
        <h3 style="color: #0f172a; margin-top: 0; font-size: 18px;">Calendar Event Added to Sweet Scribbles</h3>
        <p style="font-size: 14px; color: #475569;">A new calendar milestone has been scheduled and linked to your calendar:</p>
        
        <div style="background: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 16px; margin: 14px 0; border-radius: 4px;">
            <p style="margin: 0 0 6px 0; font-size: 16px; font-weight: bold; color: #92400e;">{event.title}</p>
            <p style="margin: 0 0 4px 0; font-size: 13px; color: #78350f;"><strong>Category:</strong> {event.event_type_display} &bull; <strong>Status:</strong> {event.status.title()}</p>
            <p style="margin: 0 0 4px 0; font-size: 13px; color: #78350f;"><strong>Date:</strong> {date_formatted}</p>
            <p style="margin: 0; font-size: 13px; color: #78350f;"><strong>Time:</strong> {time_formatted}</p>
        </div>

        {lead_info_html}

        <div style="background: #f1f5f9; border-radius: 6px; padding: 12px; font-size: 13px; color: #334155; margin-bottom: 18px;">
            <strong>📍 Location / Mode:</strong> {event.location_details or event.location_type or 'Online / Sweet Scribbles Studio'}<br>
            <strong>👥 Participants / Attendees:</strong> {event.attendee_emails or 'Internal Team'}<br>
            {f'<strong>📝 Notes / Agenda:</strong><br><span style="white-space: pre-line;">{event.meeting_notes}</span>' if event.meeting_notes else ''}
        </div>

        <p style="font-size: 12px; color: #64748b; margin-top: 20px;">
            * The attached calendar invite (.ics) has been recognized by Google Calendar. You can also click below to open directly in Google Calendar:
        </p>
    </div>
    """

    team_html = _render_luxury_email_layout(
        title=f"Calendar Event: {event.title}",
        preheader=f"{event.event_type_display} scheduled for {date_formatted}",
        body_html=team_body,
        cta_text="📅 Open in Google Calendar",
        cta_url=gcal_link
    )

    # Dispatch to team
    for team_email in team_list:
        ok, msg = send_b2b_email(
            to_email=team_email,
            subject=team_subject,
            html_content=team_html,
            attachments=[ics_attachment],
            cc_email=None
        )
        if ok:
            success_count += 1
        else:
            errors.append(f"{team_email}: {msg}")

    # 2. Client Invitation (if client attendees exist)
    if client_list:
        client_subject = f"Invitation: {event.title} with Sweet Scribbles"
        client_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; line-height: 1.6;">
            <p style="font-size: 15px;">Dear Partner,</p>
            <p style="font-size: 14px; color: #334155;">
                We are pleased to confirm our scheduled corporate session with Sweet Scribbles. We look forward to curating and presenting our exclusive handcrafted gifting collections for your organization.
            </p>

            <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 18px; margin: 18px 0;">
                <h4 style="margin: 0 0 10px 0; color: #92400e; font-size: 16px;">{event.title}</h4>
                <p style="margin: 0 0 6px 0; font-size: 14px; color: #451a03;"><strong>📅 Date:</strong> {date_formatted}</p>
                <p style="margin: 0 0 6px 0; font-size: 14px; color: #451a03;"><strong>⏰ Time:</strong> {time_formatted}</p>
                <p style="margin: 0 0 6px 0; font-size: 14px; color: #451a03;"><strong>📍 Meeting Link / Location:</strong> {event.location_details or 'Google Meet (Link in calendar invitation)'}</p>
                {f'<p style="margin: 8px 0 0 0; font-size: 13px; color: #78350f;"><strong>Agenda:</strong><br>{event.meeting_notes}</p>' if event.meeting_notes else ''}
            </div>

            <p style="font-size: 13px; color: #475569;">
                Please find the attached calendar invitation (.ics) to seamlessly add this session to your calendar. You may also click the button below to add it directly to your Google Calendar.
            </p>

            <div style="margin-top: 25px; padding-top: 15px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b;">
                <strong>Sweet Scribbles Corporate Gifting</strong><br>
                Bangalore, India &bull; <a href="{store_base_url}/b2b" style="color: #b45309;">Explore Catalog</a>
            </div>
        </div>
        """

        client_html = _render_luxury_email_layout(
            title=event.title,
            preheader=f"Sweet Scribbles Meeting on {date_formatted}",
            body_html=client_body,
            cta_text="Add to Google Calendar",
            cta_url=gcal_link
        )

        for client_email in client_list:
            ok, msg = send_b2b_email(
                to_email=client_email,
                subject=client_subject,
                html_content=client_html,
                attachments=[ics_attachment],
                cc_email="pooja.sathish@pikachooz.com"
            )
            if ok:
                success_count += 1
            else:
                errors.append(f"{client_email}: {msg}")

    return success_count, len(all_recipients), errors


def generate_live_webcal_feed(events):
    """
    Generates a full multi-event RFC 5545 iCalendar feed string.
    Suitable for live subscription in macOS Apple Calendar or Google Calendar via URL.
    """
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//Sweet Scribbles//B2B CRM Live Calendar Feed//EN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Sweet Scribbles CRM & Fulfillment",
        "X-WR-CALDESC:Corporate Client Meetings, Order Delivery Deadlines, and Office Milestones",
        "X-WR-TIMEZONE:Asia/Kolkata",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H"
    ]

    now_utc = format_utc_timestamp(datetime.utcnow())

    for event in events:
        uid = event.ics_uid or f"ss_event_{event.id}_{uuid.uuid4().hex[:8]}@sweetscribbles.com"
        summary = escape_ics_text(event.title)
        notes = event.meeting_notes or ""
        if event.lead:
            notes += f" [Client: {event.lead.company_name}]"
        description = escape_ics_text(notes)
        location = escape_ics_text(event.location_details or event.location_type or "")

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_utc}",
        ])

        if event.is_all_day:
            dt_start = format_utc_timestamp(event.start_time, all_day=True)
            end_date = event.end_time + timedelta(days=1) if event.end_time else event.start_time + timedelta(days=1)
            dt_end = format_utc_timestamp(end_date, all_day=True)
            lines.append(f"DTSTART;VALUE=DATE:{dt_start}")
            lines.append(f"DTEND;VALUE=DATE:{dt_end}")
        else:
            lines.append(f"DTSTART:{format_utc_timestamp(event.start_time)}")
            lines.append(f"DTEND:{format_utc_timestamp(event.end_time or (event.start_time + timedelta(minutes=event.duration_minutes or 45)))}")

        lines.extend([
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
            f"LOCATION:{location}",
            f"STATUS:{'CONFIRMED' if event.status != 'cancelled' else 'CANCELLED'}",
            "END:VEVENT"
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
