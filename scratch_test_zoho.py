import os
from dotenv import load_dotenv
load_dotenv()

# Override BASE_URL to simulate production domain
os.environ['BASE_URL'] = 'https://sweetscribbles.pikachooz.com'

from utils.zoho_utils import ZohoClient

client = ZohoClient()
print("--- Creating Mock Payment Link with Public Domain ---")
link, link_id = client.create_payment_link({
    'order_id': 'TEST-ORDER-12345',
    'amount': 100.0,
    'customer_email': 'test@gmail.com',
    'customer_phone': '9876543210',
    'customer_name': 'Test Sathish',
    'package': 'Test Package'
})

print("Result Link:", link)
print("Result Link ID:", link_id)
