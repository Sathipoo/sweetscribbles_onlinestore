import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models.b2b import B2BClient, B2BOrder, B2BOrderItem, B2BProduct
from models.user import User

def test_admin_create_order_feature():
    print("=" * 70)
    print("RUNNING AUTOMATED TESTS FOR 'CREATE ORDER ON BEHALF OF CLIENT'")
    print("=" * 70)

    with app.app_context():
        # 1. Ensure admin user exists for test client session
        admin_user = User.query.filter_by(is_admin=True).first()
        if not admin_user:
            admin_user = User(name="Admin Tester", email="admin@sweetscribbles.com", is_admin=True)
            db.session.add(admin_user)
            db.session.commit()
            print("Created temporary admin user for test.")

        # 2. Ensure test client exists (e.g. Chandan Enterprises)
        chandan = B2BClient.query.filter_by(company_name="Chandan Enterprises").first()
        if not chandan:
            chandan = B2BClient(
                company_name="Chandan Enterprises",
                contact_name="Chandan Kumar",
                phone="+919888877777",
                email="chandan@chandanenterprises.in",
                shipping_address="HSR Layout, Bengaluru, Karnataka",
                gst_number="29ABCDE1234F1Z5"
            )
            db.session.add(chandan)
            db.session.commit()
            print("Created test client: Chandan Enterprises")
        else:
            print("Found existing test client: Chandan Enterprises (id:", chandan.id, ")")

        # 3. Ensure test client has a clean state or 0 orders for empty state test
        empty_client = B2BClient.query.filter_by(phone="+919111122222").first()
        if not empty_client:
            empty_client = B2BClient(
                company_name="Acme Zero Corp",
                contact_name="John Doe",
                phone="+919111122222",
                email="acme@zero.com"
            )
            db.session.add(empty_client)
            db.session.commit()
        # Clean orders for empty_client
        B2BOrder.query.filter_by(client_id=empty_client.id).delete()
        db.session.commit()

        client_c = app.test_client()
        with client_c.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        # -------------------------------------------------------------
        # TEST 1: Client Detail Page Rendering & Empty State CTA
        # -------------------------------------------------------------
        print("\n--- TEST 1: Client Detail Page Rendering & Modal Verification ---")
        resp = client_c.get(f'/admin/b2b/clients/{empty_client.id}')
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        html = resp.data.decode('utf-8')

        # Check top header button
        assert "+ Create Order / Quote for this Client" in html, "Top header button missing"
        # Check empty state CTA
        assert "+ Create First Order for Acme Zero Corp" in html, "Empty state CTA button missing"
        # Check Modal markup
        assert "id=\"createOrderForClientModal\"" in html, "Client Order Modal missing"
        assert "clientProductOptionSelect" in html, "Product option select missing"
        # Check Sixfold Drawer editions in modal
        assert "Curated Drawer Gift Set — Sixfold — Assorted Bliss Bites" in html, "Sixfold Assorted Bites missing"
        assert "Curated Drawer Gift Set — Sixfold — Just Nuts" in html, "Sixfold Just Nuts missing"
        # Check live calculation placeholders
        assert "clientLiveSubtotal" in html, "clientLiveSubtotal missing"
        assert "clientLiveTotal" in html, "clientLiveTotal missing"
        assert "clientLiveAdvAmount" in html, "clientLiveAdvAmount missing"
        print("✓ SUCCESS: Client detail view renders primary buttons, empty state CTA, and modal with all product editions!")

        # -------------------------------------------------------------
        # TEST 2: Create Order on Behalf of Existing Client
        # -------------------------------------------------------------
        print("\n--- TEST 2: Create Order on Behalf of Existing Client ---")
        sixfold = B2BProduct.query.get(12)
        assert sixfold is not None, "Product 12 (Sixfold Drawer) missing in DB"
        expected_rate = sixfold.price_assorted # 1699.0 for just nuts

        post_data = {
            'client_id': str(chandan.id),
            'product_option_key': '12__just_nuts',
            'box_count': '100',
            'quoted_price_per_box': str(expected_rate),
            'advance_percent': '40',
            'custom_occasion': 'Diwali Leadership Hampers',
            'stage': 'enquiry',
            'notes': 'Gold foil logo on box lid'
        }

        resp = client_c.post('/admin/b2b/orders/create', data=post_data, follow_redirects=False)
        assert resp.status_code == 302, f"Expected 302 redirect, got {resp.status_code}"
        redirect_url = resp.headers['Location']
        assert '/admin/b2b/orders/' in redirect_url, f"Unexpected redirect: {redirect_url}"
        order_id = int(redirect_url.rstrip('/').split('/')[-1])
        print(f"✓ Redirected to Quotation Builder for Order ID: {order_id}")

        # Verify Order in DB
        order = B2BOrder.query.get(order_id)
        assert order is not None, "Created order not found in DB"
        assert order.client_id == chandan.id, f"Expected client {chandan.id}, got {order.client_id}"
        assert order.box_count == 100, f"Expected 100 boxes, got {order.box_count}"
        assert "Just Nuts" in order.box_type, f"Expected Just Nuts in box_type, got {order.box_type}"
        assert order.advance_percent == 40.0, f"Expected 40% advance, got {order.advance_percent}"
        
        expected_subtotal = round(100 * expected_rate, 2)
        expected_total = round(expected_subtotal * 1.05, 2) # 5% GST
        expected_adv = round(expected_total * 0.40, 2)

        assert abs(order.subtotal_amount - expected_subtotal) < 0.01, f"Subtotal mismatch: {order.subtotal_amount} vs {expected_subtotal}"
        assert abs(order.total_amount - expected_total) < 0.01, f"Total mismatch: {order.total_amount} vs {expected_total}"
        assert abs(order.advance_amount_required - expected_adv) < 0.01, f"Advance mismatch: {order.advance_amount_required} vs {expected_adv}"

        # Verify line item creation
        assert len(order.items) == 1, f"Expected 1 line item, found {len(order.items)}"
        item = order.items[0]
        assert item.product_id == 12, f"Expected product_id 12, got {item.product_id}"
        assert item.quantity == 100, f"Expected quantity 100, got {item.quantity}"
        assert abs(item.unit_price - expected_rate) < 0.01, f"Unit price mismatch: {item.unit_price}"
        assert abs(item.total_price - expected_subtotal) < 0.01, f"Total price mismatch: {item.total_price}"

        # Verify audit log
        assert len(order.logs) >= 1, "Expected at least 1 order log entry"
        log = order.logs[0]
        assert "Order Initiated on Behalf of Client" in log.action_title, f"Unexpected log title: {log.action_title}"
        print(f"✓ SUCCESS: Order #{order.order_number} created with 5% GST (Subtotal: ₹{order.subtotal_amount:,.2f}, Total: ₹{order.total_amount:,.2f}, 40% Advance: ₹{order.advance_amount_required:,.2f}), line item, and audit log!")

        # -------------------------------------------------------------
        # TEST 3: Create Order with Inline New Client Onboarding
        # -------------------------------------------------------------
        print("\n--- TEST 3: Create Order with Inline Client Onboarding ---")
        inline_phone = "9845012345"
        inline_data = {
            'client_id': 'new',
            'new_company_name': 'Razorpay Software',
            'new_contact_name': 'Harshil Mathur',
            'new_phone': inline_phone,
            'new_email': 'harshil@razorpay.com',
            'new_gst_number': '29AADCR1234F1Z1',
            'new_industry': 'Fintech',
            'new_shipping_address': 'Koramangala, Bengaluru',
            'product_option_key': '1__premium', # Signature DIYA Box — Premium Edition
            'box_count': '250',
            'quoted_price_per_box': '345',
            'advance_percent': '50',
            'custom_occasion': 'Annual Founders Celebration',
            'stage': 'quotation_sent'
        }

        resp = client_c.post('/admin/b2b/orders/create', data=inline_data, follow_redirects=False)
        assert resp.status_code == 302, f"Expected 302 redirect, got {resp.status_code}"
        redirect_url = resp.headers['Location']
        new_order_id = int(redirect_url.rstrip('/').split('/')[-1])

        # Verify new client in DB
        new_client = B2BClient.query.filter_by(phone="+919845012345").first()
        assert new_client is not None, "New client was not created in DB"
        assert new_client.company_name == "Razorpay Software"
        assert new_client.gst_number == "29AADCR1234F1Z1"

        # Verify order in DB
        new_order = B2BOrder.query.get(new_order_id)
        assert new_order.client_id == new_client.id
        assert new_order.box_count == 250
        assert new_order.stage == 'quotation_sent'
        assert abs(new_order.subtotal_amount - (250 * 345.0)) < 0.01
        assert abs(new_order.total_amount - round(250 * 345.0 * 1.05, 2)) < 0.01
        assert len(new_order.items) == 1
        print(f"✓ SUCCESS: Inline client '{new_client.company_name}' onboarded and linked Order #{new_order.order_number} created!")

        # -------------------------------------------------------------
        # TEST 4: Orders Table & Dashboard Headers & Modals
        # -------------------------------------------------------------
        print("\n--- TEST 4: Orders Table & Dashboard Header Buttons & Modals ---")
        orders_resp = client_c.get('/admin/b2b/orders')
        assert orders_resp.status_code == 200
        orders_html = orders_resp.data.decode('utf-8')
        assert "+ Create Order on Behalf of Client" in orders_html, "Orders header button missing"
        assert "id=\"createOrderGeneralModal\"" in orders_html, "Orders general modal missing"
        assert "generalClientSelect" in orders_html, "General client select missing"
        print("✓ SUCCESS: Orders page contains header button and modal!")

        dash_resp = client_c.get('/admin/b2b/dashboard')
        assert dash_resp.status_code == 200
        dash_html = dash_resp.data.decode('utf-8')
        assert "+ Create Order" in dash_html, "Dashboard header button missing"
        assert "id=\"createOrderGeneralModal\"" in dash_html, "Dashboard general modal missing"
        print("✓ SUCCESS: Dashboard page contains '+ Create Order' button and modal!")

        clients_resp = client_c.get('/admin/b2b/clients')
        assert clients_resp.status_code == 200
        clients_html = clients_resp.data.decode('utf-8')
        assert "#createOrder" in clients_html, "Clients table quick order anchor missing"
        print("✓ SUCCESS: Clients directory table contains quick '+ Order' action links!")

        print("\n" + "=" * 70)
        print("ALL TESTS PASSED WITH 100% SUCCESS!")
        print("=" * 70)

if __name__ == '__main__':
    test_admin_create_order_feature()
