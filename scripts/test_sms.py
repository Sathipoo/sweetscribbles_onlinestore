#!/usr/bin/env python3
"""
Sweet Scribbles — Live MSG91 SMS Testing & Diagnostic Suite
Usage:
    ./venv/bin/python scripts/test_sms.py <10-digit-mobile-number> [template_type]

Template Types (Optional, default is login_otp):
    login_otp        - Sweet Scribbles Login OTP
    enquiry_otp      - B2B Enquiry Verification OTP
    b2b_confirmed    - B2B Order Confirmed (Advance Paid)
    b2b_design_ready - B2B Design Proof Ready for Review
    b2b_production   - B2B Production Starting (Count & ETA Locked)
    b2b_delivered    - B2B Delivery Completed
    order_dispatched - Retail Order Dispatched
    order_delivered  - Retail Order Delivered
    order_cancelled  - Retail Order Cancelled
    refund_processed - Retail Refund Processed
"""
import sys
import os
import requests
from dotenv import load_dotenv

# Load environment
load_dotenv()

TEMPLATES = {
    'login_otp': {
        'name': 'Sweet Scribbles Login OTP',
        'template_id': os.environ.get('MSG91_FLOW_ID_LOGIN_OTP', '6a968b032ea5913edc096f32'),
        'dlt_id': '1777178764089646500',
        'variables': {'OTP': '8391'}
    },
    'enquiry_otp': {
        'name': 'B2B Enquiry Verification OTP',
        'template_id': os.environ.get('MSG91_FLOW_ID_B2B_ENQUIRY_OTP', '6a968a0b9573e5b9ed0a3322'),
        'dlt_id': '1777178814958474414',
        'variables': {'OTP': '5124'}
    },
    'b2b_confirmed': {
        'name': 'B2B Order Confirmed (Advance Paid)',
        'template_id': os.environ.get('MSG91_FLOW_B2B_CONFIRMED', '6a968a2eec51de1c5a0dfba2'),
        'dlt_id': '1777178814972248686',
        'variables': {
            'order_id': 'SSB2B-1042',
            'tracking_url': 'https://sweetscribbles.com/b2b/portal'
        }
    },
    'b2b_design_ready': {
        'name': 'B2B Design Proof Ready for Approval',
        'template_id': os.environ.get('MSG91_FLOW_B2B_DESIGN_READY', '6a968a53d4862bc0bc06a222'),
        'dlt_id': '1777178814994298667',
        'variables': {
            'order_id': 'SSB2B-1042',
            'approval_url': 'https://sweetscribbles.com/b2b/portal'
        }
    },
    'b2b_production': {
        'name': 'B2B Details Locked & Production Beginning',
        'template_id': os.environ.get('MSG91_FLOW_B2B_PRODUCTION', '6a968a804987363ec200b4f3'),
        'dlt_id': '1777178815013976698',
        'variables': {
            'box_count': '150',
            'eta_date': '25 Oct 2026',
            'order_url': 'https://sweetscribbles.com/b2b/portal'
        }
    },
    'b2b_delivered': {
        'name': 'B2B Delivery Completed',
        'template_id': os.environ.get('MSG91_FLOW_B2B_DELIVERED', '6a968a9ada33fde5c70da2d3'),
        'dlt_id': '1777178815025246994',
        'variables': {
            'order_id': 'SSB2B-1042',
            'order_url': 'https://sweetscribbles.com/b2b/portal'
        }
    },
    'order_received': {
        'name': 'Retail Order Received & Confirmed',
        'template_id': os.environ.get('MSG91_FLOW_ORDER_RECEIVED', '6a96fb22885c2799d8068ad2'),
        'dlt_id': '1777178827434243630',
        'variables': {
            'order_id': 'SS-8419',
            'total_amount': '599'
        }
    },
    'order_dispatched': {
        'name': 'Retail Order Dispatched',
        'template_id': os.environ.get('MSG91_FLOW_ORDER_DISPATCHED', '6a968958b79b19fb7e05dc52'),
        'dlt_id': '1777178764868868260',
        'variables': {
            'order_id': 'SS-8419',
            'courier_name': 'Bluedart Express',
            'tracking_number': 'BLU1098234'
        }
    },
    'order_delivered': {
        'name': 'Retail Order Delivered',
        'template_id': os.environ.get('MSG91_FLOW_ORDER_DELIVERED', '6a96899c705d42bcc806ec93'),
        'dlt_id': '1777178764879957542',
        'variables': {
            'order_id': 'SS-8419'
        }
    },
    'order_cancelled': {
        'name': 'Retail Order Cancelled',
        'template_id': os.environ.get('MSG91_FLOW_ORDER_CANCELLED', '6a9689cf1b7f8acb820a1ca2'),
        'dlt_id': '1777178764884908554',
        'variables': {
            'order_id': 'SS-8419'
        }
    },
    'refund_processed': {
        'name': 'Retail Refund Processed',
        'template_id': os.environ.get('MSG91_FLOW_REFUND_PROCESSED', '6a9689e8839a6c860c02bc63'),
        'dlt_id': '1777178764892921906',
        'variables': {
            'amount': '1250',
            'order_id': 'SS-8419'
        }
    }
}

def send_test(target_phone, template_key='login_otp'):
    auth_key = os.environ.get('MSG91_AUTH_KEY') or os.environ.get('msg91_authkey')
    sender_id = os.environ.get('MSG91_SENDER_ID', 'PIKCHZ')

    if template_key not in TEMPLATES:
        print(f"Unknown template '{template_key}'. Choose from: {list(TEMPLATES.keys())}")
        return

    tpl = TEMPLATES[template_key]
    template_id = tpl['template_id']

    digits = "".join(c for c in target_phone if c.isdigit())
    if len(digits) == 10:
        formatted_phone = f"91{digits}"
    elif len(digits) == 12 and digits.startswith('91'):
        formatted_phone = digits
    else:
        formatted_phone = digits

    print("=" * 68)
    print("        SWEET SCRIBBLES — LIVE MSG91 DLT SMS DISPATCH        ")
    print("=" * 68)
    print(f"• Sender ID / PE    : {sender_id} (PIKACHOOZ / 1701178685802195041)")
    print(f"• Template Name     : {tpl['name']}")
    print(f"• DLT Template ID   : {tpl['dlt_id']}")
    print(f"• MSG91 Template ID : {template_id}")
    print(f"• Recipient Mobile  : +{formatted_phone}")
    print(f"• Variables         : {tpl['variables']}")
    print("-" * 68)

    url = "https://api.msg91.com/api/v5/flow/"
    headers = {
        "authkey": auth_key.strip(),
        "content-type": "application/json",
        "accept": "application/json"
    }

    recipient = {"mobiles": formatted_phone}
    recipient.update(tpl['variables'])

    payload = {
        "template_id": template_id.strip(),
        "flow_id": template_id.strip(),
        "sender": sender_id.strip(),
        "short_url": "0",
        "recipients": [recipient]
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=12)
        print(f"HTTP Status: {res.status_code}")
        try:
            data = res.json()
            print(f"MSG91 Response: {data}")
            if res.status_code in (200, 201, 202) and data.get('type') == 'success':
                print("\n" + "=" * 68)
                print(f"✅ SUCCESS! SMS successfully delivered to telecom queue.")
                print(f"   Message Request ID: {data.get('message')}")
                print(f"   The SMS should ring on +{formatted_phone} in a few seconds.")
                print("=" * 68 + "\n")
            else:
                print(f"\n❌ MSG91 Error: {data}")
        except Exception:
            print(f"Raw Response: {res.text}")
    except Exception as e:
        print(f"\n❌ Connection Error: {e}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: ./venv/bin/python scripts/test_sms.py <10-digit-mobile> [template_type]")
        print("Available template types: " + ", ".join(TEMPLATES.keys()))
        sys.exit(1)
        
    phone = sys.argv[1]
    key = sys.argv[2] if len(sys.argv) > 2 else 'login_otp'
    send_test(phone, key)
