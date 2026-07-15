import os
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def normalize_phone(phone):
    """Normalize phone number to digits and leading +."""
    if not phone:
        return ""
    cleaned = "".join(c for c in phone if c.isdigit() or c == '+')
    # Default to +91 prefix if it's a 10 digit number
    if len(cleaned) == 10 and not cleaned.startswith('+'):
        cleaned = f"+91{cleaned}"
    elif len(cleaned) == 12 and cleaned.startswith('91') and not cleaned.startswith('+'):
        cleaned = f"+{cleaned}"
    return cleaned

def generate_otp():
    """Generate a 6-digit numeric OTP."""
    return "".join(random.choices("0123456789", k=6))

def send_email_otp(email, otp):
    """
    Sends an OTP to the user's email.
    If SMTP credentials are not configured in the environment,
    falls back to printing the OTP to the console.
    """
    mail_server = os.environ.get('MAIL_SERVER')
    mail_port = os.environ.get('MAIL_PORT', 587)
    mail_username = os.environ.get('MAIL_USERNAME')
    mail_password = os.environ.get('MAIL_PASSWORD')
    sender_email = os.environ.get('MAIL_DEFAULT_SENDER', mail_username)

    if mail_server and mail_username and mail_password:
        try:
            # Parse port
            try:
                port = int(mail_port)
            except ValueError:
                port = 587
                
            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = email
            msg['Subject'] = f"{otp} is your Sweet Scribbles Verification Code"

            body = f"""
            Hello,

            Your verification OTP is: {otp}

            This code is valid for 5 minutes. If you did not request this code, please ignore this email.

            Sweet Scribbles Team
            """
            msg.attach(MIMEText(body, 'plain'))

            # Standard SMTP send with STARTTLS
            server = smtplib.SMTP(mail_server, port, timeout=10)
            server.starttls()
            server.login(mail_username, mail_password)
            server.send_message(msg)
            server.quit()
            print(f"[OTP] Successfully sent real SMTP email to {email}")
            return True
        except Exception as e:
            print(f"[OTP ERROR] Failed to send SMTP email to {email}: {e}")
            # Fall back to logging in console
            
    # Mock / Sandbox Mode
    print("\n" + "="*50)
    print(f"[EMAIL OTP DEV MOCK]")
    print(f"To: {email}")
    print(f"OTP: {otp}")
    print("="*50 + "\n")
    return False

def send_sms_otp(phone, otp):
    """
    Sends an OTP to the user's phone via Twilio (if credentials exist),
    otherwise falls back to logging the OTP to the console.
    """
    twilio_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    twilio_token = os.environ.get('TWILIO_AUTH_TOKEN')
    twilio_number = os.environ.get('TWILIO_PHONE_NUMBER')

    if twilio_sid and twilio_token and twilio_number:
        try:
            import requests
            # Clean/format phone number
            clean_phone = phone.strip()
            if not clean_phone.startswith('+') and len(clean_phone) == 10:
                clean_phone = f"+91{clean_phone}" # Default to Indian country code if 10 digits
                
            url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json"
            data = {
                "To": clean_phone,
                "From": twilio_number,
                "Body": f"Your Sweet Scribbles verification OTP is {otp}. Valid for 5 minutes."
            }
            response = requests.post(url, data=data, auth=(twilio_sid, twilio_token), timeout=10)
            if response.status_code in (200, 201):
                print(f"[OTP] Successfully sent Twilio SMS to {clean_phone}")
                return True
            else:
                print(f"[OTP ERROR] Twilio SMS API responded with status {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[OTP ERROR] Twilio SMS client exception: {e}")

    # Mock / Sandbox Mode
    print("\n" + "="*50)
    print(f"[SMS OTP DEV MOCK]")
    print(f"Phone: {phone}")
    print(f"OTP: {otp}")
    print("="*50 + "\n")
    return False
