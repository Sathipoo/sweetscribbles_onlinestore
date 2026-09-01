import os
import random
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

def normalize_phone(phone):
    """Normalize phone number to standard format with leading +91 for 10-digit Indian numbers."""
    if not phone:
        return ""
    digits = "".join(c for c in phone if c.isdigit())
    # 10-digit Indian number
    if len(digits) == 10:
        return f"+91{digits}"
    # 12-digit Indian number starting with 91
    elif len(digits) == 12 and digits.startswith('91'):
        return f"+{digits}"
    # 11-digit number starting with 0
    elif len(digits) == 11 and digits.startswith('0'):
        return f"+91{digits[1:]}"
    elif digits:
        return f"+{digits}"
    return ""

def format_phone_for_msg91(phone):
    """Format phone number for MSG91 API without leading + (e.g. 91XXXXXXXXXX)."""
    if not phone:
        return ""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"91{digits}"
    elif len(digits) == 11 and digits.startswith('0'):
        return f"91{digits[1:]}"
    return digits

def generate_otp(length=4):
    """Generate a numeric OTP (default 4-digit)."""
    return "".join(random.choices("0123456789", k=length))

def send_msg91_otp(phone, otp, flow_id=None):
    """
    Sends an OTP via MSG91 Flow API (https://api.msg91.com/api/v5/flow/)
    using the approved DLT template.
    """
    auth_key = os.environ.get('MSG91_AUTH_KEY') or os.environ.get('msg91_authkey')
    sender_id = os.environ.get('MSG91_SENDER_ID', 'PIKCHZ')
    target_template_id = flow_id or os.environ.get('MSG91_FLOW_ID_LOGIN_OTP', '6a968b032ea5913edc096f32')
    
    formatted_phone = format_phone_for_msg91(phone)


    if auth_key and target_template_id and formatted_phone:
        try:
            url = "https://api.msg91.com/api/v5/flow/"
            headers = {
                "authkey": auth_key.strip(),
                "content-type": "application/json",
                "accept": "application/json"
            }
            payload = {
                "template_id": target_template_id.strip(),
                "flow_id": target_template_id.strip(),
                "sender": sender_id.strip(),
                "recipients": [
                    {
                        "mobiles": formatted_phone,
                        "OTP": str(otp),
                        "otp": str(otp)
                    }
                ]
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            res_data = {}
            try:
                res_data = response.json()
            except Exception:
                res_data = {"text": response.text}
                
            print(f"[MSG91 OTP Flow] Status: {response.status_code} | Phone: {formatted_phone} | Template: {target_template_id} | Response: {res_data}")
            
            if response.status_code in (200, 201, 202) and res_data.get('type') != 'error':
                return True
            else:
                print(f"[MSG91 OTP Flow ERROR] Failed response: {res_data}")
        except Exception as e:
            print(f"[MSG91 OTP Flow EXCEPTION] {e}")

    # Mock / Sandbox Mode for local dev or when keys/templates are pending
    print("\n" + "="*50)
    print(f"[SMS OTP DEV MOCK / LOG]")
    print(f"Phone: {phone} (Formatted for MSG91: {formatted_phone})")
    print(f"Template/Flow ID: {target_template_id}")
    print(f"OTP: {otp}")
    print("="*50 + "\n")
    return False



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

            This code is valid for 10 minutes. If you did not request this code, please ignore this email.

            Sweet Scribbles Team - A Pikachooz Product
            """
            msg.attach(MIMEText(body, 'plain'))

            server = smtplib.SMTP(mail_server, port, timeout=10)
            server.starttls()
            server.login(mail_username, mail_password)
            server.send_message(msg)
            server.quit()
            print(f"[OTP] Successfully sent real SMTP email to {email}")
            return True
        except Exception as e:
            print(f"[OTP ERROR] Failed to send SMTP email to {email}: {e}")
            
    # Mock / Sandbox Mode
    print("\n" + "="*50)
    print(f"[EMAIL OTP DEV MOCK]")
    print(f"To: {email}")
    print(f"OTP: {otp}")
    print("="*50 + "\n")
    return False

def send_b2b_sms(phone, flow_key, variables_dict):
    """
    Generic dispatcher for B2B DLT flow messages via MSG91.
    flow_key corresponds to env var or fallback flow_id.
    """
    auth_key = os.environ.get('MSG91_AUTH_KEY') or os.environ.get('msg91_authkey')
    sender_id = os.environ.get('MSG91_SENDER_ID', 'PIKCHZ')
    target_template_id = os.environ.get(flow_key)
    
    formatted_phone = format_phone_for_msg91(phone)

    if auth_key and target_template_id and formatted_phone:
        try:
            url = "https://api.msg91.com/api/v5/flow/"
            headers = {
                "authkey": auth_key.strip(),
                "content-type": "application/json",
                "accept": "application/json"
            }
            recipient = {"mobiles": formatted_phone}
            recipient.update(variables_dict)
            
            payload = {
                "template_id": target_template_id.strip(),
                "flow_id": target_template_id.strip(),
                "sender": sender_id.strip(),
                "recipients": [recipient]
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            res_data = {}
            try:
                res_data = response.json()
            except Exception:
                res_data = {"text": response.text}
                
            print(f"[MSG91 B2B SMS] Flow: {flow_key} | Status: {response.status_code} | Payload: {payload} | Response: {res_data}")
            if response.status_code in (200, 201, 202) and res_data.get('type') != 'error':
                return True
            else:
                print(f"[MSG91 B2B SMS ERROR] Failed: {res_data}")
        except Exception as e:
            print(f"[MSG91 B2B SMS EXCEPTION] Error calling MSG91 Flow API: {e}")

    # Dev/Mock fallback
    print("\n" + "="*50)
    print(f"[B2B SMS DEV MOCK / LOG]")
    print(f"To: {phone} (Formatted: {formatted_phone})")
    print(f"Flow Key: {flow_key} (ID: {target_template_id})")
    print(f"Variables: {variables_dict}")
    print("="*50 + "\n")
    return False

def send_b2b_enquiry_otp(phone, otp):
    """Sends B2B enquiry mobile verification OTP (DLT Template ID 1777178814958474414)."""
    flow_id = os.environ.get('MSG91_FLOW_ID_B2B_ENQUIRY_OTP', '6a968a0b9573e5b9ed0a3322')
    return send_msg91_otp(phone, otp, flow_id=flow_id)

def send_retail_sms(phone, flow_key, variables_dict):
    """
    Generic dispatcher for Retail DLT SMS notifications via MSG91.
    """
    return send_b2b_sms(phone, flow_key, variables_dict)

def send_order_dispatched_sms(phone, order_id, courier_name, tracking_number):
    """Sends retail order dispatched SMS (DLT Template ID 1777178764868868260)."""
    return send_retail_sms(phone, 'MSG91_FLOW_ORDER_DISPATCHED', {
        'order_id': str(order_id),
        'courier_name': str(courier_name),
        'tracking_number': str(tracking_number)
    })

def send_order_delivered_sms(phone, order_id):
    """Sends retail order delivered SMS (DLT Template ID 1777178764879957542)."""
    return send_retail_sms(phone, 'MSG91_FLOW_ORDER_DELIVERED', {
        'order_id': str(order_id)
    })

def send_order_cancelled_sms(phone, order_id):
    """Sends retail order cancellation SMS (DLT Template ID 1777178764884908554)."""
    return send_retail_sms(phone, 'MSG91_FLOW_ORDER_CANCELLED', {
        'order_id': str(order_id)
    })

def send_refund_processed_sms(phone, amount, order_id):
    """Sends refund processed SMS (DLT Template ID 1777178764892921906)."""
    return send_retail_sms(phone, 'MSG91_FLOW_REFUND_PROCESSED', {
        'amount': str(amount),
        'order_id': str(order_id)
    })


