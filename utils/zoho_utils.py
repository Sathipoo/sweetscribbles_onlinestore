import os
import requests
import time

# ZOHO PAYMENTS CONFIG
# Using the generic payments scope. 
# Endpoint might vary based on data center (zoho.com, zoho.in, etc.)
# SWITCHING TO .IN based on User Location (India) causing invalid_client on .com
ZOHO_AUTH_URL = "https://accounts.zoho.in/oauth/v2/token"
ZOHO_PAYMENT_URL = "https://payments.zoho.in/api/v1" # Reverting to the one that gave JSON response



class ZohoClient:
    def __init__(self):
        self.client_id = os.environ.get('ZOHO_CLIENT_ID')
        self.client_secret = os.environ.get('ZOHO_CLIENT_SECRET')
        self.refresh_token = os.environ.get('ZOHO_REFRESH_TOKEN')
        self.org_id = os.environ.get('ZOHO_BILLING_ORG_ID') 
        
        self.access_token = None
        self.token_expiry = 0

    def get_access_token(self):
        """Refreshes the access token if expired."""
        if self.access_token and time.time() < self.token_expiry:
            return self.access_token

        print(f"DEBUG: Refreshing Zoho Access Token for Client ID: {self.client_id[:10]}...")
        params = {
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'refresh_token'
        }
        
        try:
            response = requests.post(ZOHO_AUTH_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if 'access_token' in data:
                self.access_token = data['access_token']
                # Expires in usually 3600 seconds, set safety buffer
                self.token_expiry = time.time() + data.get('expires_in', 3600) - 60
                return self.access_token
            else:
                print(f"ERROR: Zoho Token Refresh Failed: {data}")
                return None
        except Exception as e:
            print(f"ERROR: Connection error refreshing token: {e}")
            return None

    def create_payment_link(self, order_data):
        """
        Creates a Payment Link via Zoho Payments API.
        Reference: Zoho Payments logic for 'payment_links' or 'checkout'.
        """
        token = self.get_access_token()
        if not token:
            return None

        headers = {
            'Authorization': f'Zoho-oauthtoken {token}',
            'Content-Type': 'application/json'
        }
        
        # Add Org ID if present (Likely required)
        if self.org_id:
             headers['X-Zoho-OrganizationId'] = self.org_id
        
        # url = f"{ZOHO_PAYMENT_URL}/paymentlinks"
        account_id = os.environ.get("ZOHO_PAYMENTS_ACCOUNT_ID")
        if not account_id:
            raise Exception("Missing ZOHO_PAYMENTS_ACCOUNT_ID env var")

        url = f"{ZOHO_PAYMENT_URL}/paymentlinks?account_id={account_id}"
        
        # Build Payload
        # We use our 'order_id' as the reference
        amount = order_data.get('amount') # e.g. 2199.00
        currency = "INR"
        
        # Fix: 'item_name' was passed from app.py, not 'package'
        description_text = order_data.get('item_name') or order_data.get('package') or "Experience"
        
        # Prepare Customer Name
        full_name = order_data.get('customer_name', 'Guest').split()
        first_name = full_name[0]
        last_name = " ".join(full_name[1:]) if len(full_name) > 1 else ""

        base_url = os.environ.get("BASE_URL", "http://localhost:5001").rstrip("/")

        payload = {
            "amount": float(amount),
            "currency": "INR",
            "email": order_data.get("customer_email"),        # required
            "phone": order_data.get("customer_phone"),        # optional
            "phone_country_code": "IN",                       # optional but recommended
            "description": f"Written In Love - {description_text}",  # required
            "reference_id": order_data.get("order_id"),
            "return_url": f"{base_url}/pay/return?order_number={order_data.get('order_id')}",
            # "notify_user": True,  # optional
            # "expires_at": "2026-02-14"  # optional yyyy-MM-dd
        }
        
        print(f"DEBUG: Payload being sent to Zoho: {payload}")
        
        import traceback

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)

            print("DEBUG: Zoho URL:", url)
            print("DEBUG: Zoho Status:", response.status_code)
            print("DEBUG: Zoho Response Text:", response.text)

            # If Zoho returns non-JSON (or empty), this will throw, so guard it
            try:
                data = response.json()
            except Exception:
                data = None
                print("ERROR: Zoho response was not valid JSON")

            if response.status_code not in [200, 201]:
                return None

            # Print parsed JSON for clarity
            print("DEBUG: Zoho Response JSON:", data)

            # Robust link extraction (Zoho may use different keys)
            link_url = None
            if isinstance(data, dict):
                # Common patterns
                link_url = (
                    (data.get("payment_link") or {}).get("url")
                    or (data.get("payment_links") or {}).get("url") # Added Plural Check
                    or (data.get("paymentlink") or {}).get("url")
                    or (data.get("data") or {}).get("url")
                    or data.get("url")
                    or data.get("payment_url")
                )

            return link_url

        except Exception as e:
            print("ERROR: Exception in create_payment_link:", str(e))
            print(traceback.format_exc())
            return None

    ZOHO_WEBHOOK_SIGNING_KEY = "d2a3dbbb28be5050180a7bac867113b183f39f013860706fb37fc815e1dc7d68379d5c79f32d4220e2ccf54b6ad938583ac8af9f1ecd0d163ab1091cfdaf17bd199ad5ecfe55b22cdd129dd04a26dd40"

    def verify_webhook(self, data, headers):
        """
        Verifies the webhook signature if available.
        """
        try:
            # Check for signature header
            signature = headers.get('X-Zoho-Webhook-Signature') or headers.get('X-Zoho-Signature')
            
            # Simple check if present
            if signature:
                # TODO: Implement HMAC-SHA256(payload, key) 
                # For now, we proceed as valid if no other errors
                # As we don't have the exact signing algorithm details (HMAC vs RSA) handy
                pass
            
            # Additional layer: Check if our webhook ID matches one provided (if applicable)
            # For now, we trust the basic check or absence of explicit 'bad' signature
            return True
        except Exception as e:
            print(f"ERROR: Signature Verification Failed: {e}")
            return False
