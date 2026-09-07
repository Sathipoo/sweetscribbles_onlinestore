import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from extensions import db
from models.b2b import B2BClient, B2BOrder, B2BProduct

app = create_app()

def test_hampers_page():
    print("Testing /b2b/hampers page...")
    client = app.test_client()

    # 1. Test /b2b/hampers
    res = client.get('/b2b/hampers')
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    html = res.get_data(as_text=True)

    required_keywords = [
        "Celebration Hampers",
        "Celebration Carry Hamper — Petite",
        "Celebration Carry Hamper — Grande",
        "Grand Celebration Magnetic Hamper",
        "Curated Drawer Gift Set — Sixfold",
        "Premium Three-Jar Gift Set",
        "Hex Trio Chocolate Gift Set",
        "Items Available for Hamper Curation",
        "Sweet Box",
        "Namkeen Box",
        "Choco Box",
        "Scented Candles",
        "Essential Oils",
        "Interactive Hamper Calculator",
        "Vishnu Govind",
        "enquiryModal"
    ]

    for kw in required_keywords:
        assert kw in html, f"Missing required keyword in /b2b/hampers: {kw}"
    print("  ✓ /b2b/hampers loaded with all required content, sections, and modal!")

    # 2. Test B2B index link
    res_idx = client.get('/b2b/')
    assert res_idx.status_code == 200
    idx_html = res_idx.get_data(as_text=True)
    assert "/b2b/hampers" in idx_html, "B2B index missing link to /b2b/hampers"
    print("  ✓ B2B index has link to /b2b/hampers!")

    # 3. Test Customer Home / Navbar link
    res_home = client.get('/')
    assert res_home.status_code == 200
    home_html = res_home.get_data(as_text=True)
    assert "/b2b/hampers" in home_html, "Customer base navbar missing link to /b2b/hampers"
    print("  ✓ Customer navbar has link to /b2b/hampers!")

    # 4. Test PDF brochure availability
    pdf_path = os.path.join(app.root_path, 'static/uploads/Sweet_Scribbles_Celebration_Hampers_Catalogue.pdf')
    assert os.path.exists(pdf_path), f"Catalogue PDF not found at {pdf_path}"
    print(f"  ✓ PDF catalogue exists and is {os.path.getsize(pdf_path)} bytes!")

    # 5. Test Enquiry Submission for a Hamper with OTP
    otp_res = client.post('/b2b/send-enquiry-otp', json={'phone': '9876543210'})
    assert otp_res.status_code == 200, f"Failed to send OTP: {otp_res.get_data(as_text=True)}"
    otp_data = otp_res.get_json()
    assert otp_data.get('success') is True
    dev_otp = otp_data.get('dev_otp')

    # If dev_otp is None (e.g. non-debug), extract from session
    if not dev_otp:
        with client.session_transaction() as sess:
            dev_otp = sess['b2b_enquiry_otp']['otp']

    enquiry_payload = {
        'company_name': 'Hampers Festive Corp',
        'contact_name': 'Rohan Mehta',
        'email': 'rohan@festivecorp.com',
        'phone': '9876543210',
        'box_type': 'Celebration Carry Hamper — Grande',
        'box_count': 100,
        'custom_occasion': 'Diwali Corporate Gifting',
        'custom_message': 'Need custom logo foiling and gift cards.',
        'otp': dev_otp
    }

    res_sub = client.post('/b2b/submit-enquiry', json=enquiry_payload)
    assert res_sub.status_code == 200, f"Expected 200, got {res_sub.status_code}: {res_sub.get_data(as_text=True)}"
    data = res_sub.get_json()
    assert data.get('success') is True, f"Enquiry submission unsuccessful: {data}"

    with app.app_context():
        order = B2BOrder.query.filter_by(box_type='Celebration Carry Hamper — Grande').first()
        assert order is not None, "Order for Celebration Carry Hamper — Grande not found in DB!"
        assert order.box_count == 100
        print(f"  ✓ Successfully verified B2BOrder creation: {order.order_number} for {order.box_count} hampers in stage {order.stage}!")

    print("\nALL HAMPERS & GIFT SETS TESTS PASSED PERFECTLY!")

if __name__ == '__main__':
    test_hampers_page()
