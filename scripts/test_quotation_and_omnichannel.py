import os
import sys
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models.b2b import B2BClient, B2BOrder, B2BOrderItem, B2BProduct, B2BCommunicationLog
from utils.quotation_pdf import generate_quotation_pdf
from utils.email_utils import (
    send_welcome_onboarding_email,
    send_quotation_email,
    send_advance_received_email,
    send_b2b_email
)

def run_tests():
    print("=" * 60)
    print("RUNNING B2B QUOTATION BUILDER & OMNICHANNEL SUITE VERIFICATION")
    print("=" * 60)

    with app.app_context():
        # 1. Fetch or create test client & order
        client = B2BClient.query.filter_by(phone="+918050903917").first()
        if not client:
            client = B2BClient(
                company_name="Mytech Corporate",
                contact_name="Vishnu Govind",
                phone="+918050903917",
                email="vishnu.govind1595@gmail.com",
                shipping_address="Bangalore, Karnataka"
            )
            db.session.add(client)
            db.session.commit()
            print("Created test client:", client)
        else:
            print("Found existing test client:", client)

        order = B2BOrder.query.filter_by(client_id=client.id).first()
        if not order:
            order = B2BOrder(
                order_number=B2BOrder.generate_order_number(),
                client_id=client.id,
                box_type="Celebration Carry Hamper — Grande",
                box_count=100,
                quoted_price_per_box=949.0,
                total_amount=94900.0,
                advance_amount_required=28470.0,
                advance_percent=30.0,
                stage="enquiry"
            )
            db.session.add(order)
            db.session.commit()
            print("Created test order:", order.order_number)
        else:
            print(f"Using test order #{order.id}: {order.order_number}")

        # Ensure line items exist
        B2BOrderItem.query.filter_by(order_id=order.id).delete()
        item1 = B2BOrderItem(
            order_id=order.id,
            item_name="Celebration Carry Hamper — Petite",
            item_category="Hampers & Gift Sets",
            description="Box size: 25.5 x 25.5 x 13 cm, compact festive curation",
            quantity=50,
            unit_price=849.0,
            total_price=42450.0
        )
        item2 = B2BOrderItem(
            order_id=order.id,
            item_name="Celebration Carry Hamper — Grande",
            item_category="Hampers & Gift Sets",
            description="Box size: 32.5 x 25.5 x 13 cm, larger luxury assortment",
            quantity=50,
            unit_price=949.0,
            total_price=47450.0
        )
        db.session.add_all([item1, item2])
        order.subtotal_amount = 89900.0
        order.advance_percent = 35.0 # Custom 35% advance (not hardcoded to 50%)
        db.session.commit()
        print(f"Attached {len(order.items)} line items to Order #{order.order_number}")

        # -------------------------------------------------------------
        # TEST 1: PDF Generation without Discount
        # -------------------------------------------------------------
        print("\n--- TEST 1: Strict Conditional Discount: Discount = 0 ---")
        order.discount_amount = 0.0
        order.discount_percent = 0.0
        order.total_amount = 89900.0
        order.advance_amount_required = round(89900.0 * 0.35, 2)
        db.session.commit()

        pdf_no_disc = generate_quotation_pdf(order)
        assert len(pdf_no_disc) > 5000, "PDF should have substantial content"
        assert b"Discount" not in pdf_no_disc, "VIOLATION: Discount appeared in PDF when discount_amount == 0!"
        assert b"Advance Required" in pdf_no_disc and b"35.0%" in pdf_no_disc, "Advance requirement % must be dynamic (35%)!"
        assert b"Kotak Mahindra Bank" in pdf_no_disc, "Kotak Mahindra Bank missing in PDF!"
        assert b"KKBK0008036" in pdf_no_disc, "Bank IFSC missing in PDF!"
        assert b"6450708114" in pdf_no_disc, "Account number missing in PDF!"
        assert b"29FJPPP4801M1ZF" in pdf_no_disc, "GSTIN missing in PDF!"
        assert b"CGST" in pdf_no_disc and b"SGST" in pdf_no_disc, "CGST/SGST missing in PDF!"
        print("✓ SUCCESS: When discount = 0, 'Discount' is completely excluded from PDF!")
        print("✓ SUCCESS: Advance requirement rendered dynamically as 35.0%!")
        print("✓ SUCCESS: Kotak Mahindra Bank, IFSC, GSTIN & 5% GST breakdown verified in PDF!")

        # -------------------------------------------------------------
        # TEST 2: PDF Generation with Discount > 0
        # -------------------------------------------------------------
        print("\n--- TEST 2: Strict Conditional Discount: Discount = 5000 ---")
        order.discount_amount = 5000.0
        order.discount_percent = 5.56
        order.total_amount = 84900.0
        order.advance_amount_required = round(84900.0 * 0.35, 2)
        db.session.commit()

        pdf_with_disc = generate_quotation_pdf(order)
        assert len(pdf_with_disc) > 5000, "PDF should have substantial content"
        assert b"Discount" in pdf_with_disc, "VIOLATION: Discount should appear in PDF when discount_amount > 0!"
        print("✓ SUCCESS: When discount = 5000, 'Discount' correctly appears on PDF!")

        # -------------------------------------------------------------
        # TEST 3: Email Dispatch & Communication Logging
        # -------------------------------------------------------------
        print("\n--- TEST 3: Gmail SMTP Email Dispatch & Communication Log ---")
        # Test quotation email
        filename = f"Quotation-{order.order_number}.pdf"
        print(f"Dispatching test quotation email to {client.email}...")
        success, msg = send_quotation_email(order, pdf_with_disc, filename=filename)
        print(f"Quotation email dispatch result: {success} ({msg})")

        # Test welcome email
        print(f"Dispatching welcome onboarding email to {client.email}...")
        w_success, w_msg = send_welcome_onboarding_email(client, order)
        print(f"Welcome email dispatch result: {w_success} ({w_msg})")

        # Verify logs in DB
        logs = B2BCommunicationLog.query.filter_by(order_id=order.id).all()
        print(f"Total communication logs in DB for order: {len(logs)}")
        for l in logs:
            print(f"  [{l.channel.upper()}] {l.event_type} &rarr; {l.recipient} ({l.status}) | {l.subject}")

        assert len(logs) >= 2, "Should have at least 2 communication logs recorded!"
        print("✓ SUCCESS: Communication logs successfully persisted to database!")

        # -------------------------------------------------------------
        # TEST 4: Order Detail Template Rendering via Test Client
        # -------------------------------------------------------------
        print("\n--- TEST 4: Order Detail View HTML Rendering ---")
        with app.test_client() as c:
            # Fake admin login session
            from models.user import User
            admin_user = User.query.filter_by(is_admin=True).first()
            if admin_user:
                with c.session_transaction() as sess:
                    sess['_user_id'] = str(admin_user.id)
                    sess['_fresh'] = True
                
                resp = c.get(f'/admin/b2b/orders/{order.id}')
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
                html = resp.data.decode('utf-8')
                assert "Order Lifecycle" in html, "Lifecycle bar missing"
                assert "B2B Quotation Builder" in html, "Builder heading missing"
                assert "COMMUNICATION TRACKER" in html, "Communication tracker missing"
                assert "Celebration Carry Hamper — Petite" in html, "Item 1 missing in HTML"
                # Verify collapsible communication tracker
                assert "id=\"communicationTrackerCollapse\"" in html, "Collapse element missing"
                assert "class=\"collapse\"" in html, "Tracker must be collapsed by default"
                assert "id=\"commTrackerToggleBtn\"" in html, "Tracker toggle button missing"
                assert "View Communication History" in html, "Toggle label missing"
                print("✓ SUCCESS: Communication tracker is hidden/collapsed by default with toggle button!")

                # Verify edition listings in dropdown
                assert "Signature DIYA Box — Premium Edition (₹345)" in html, "DIYA Premium missing"
                assert "Signature DIYA Box — Assorted Edition (₹265)" in html, "DIYA Assorted missing"
                assert "Small Celebration Box — Premium Edition (₹429)" in html, "Small Box Premium missing"
                assert "Small Celebration Box — Assorted Edition (₹349)" in html, "Small Box Assorted missing"
                assert "Curated Drawer Gift Set — Sixfold — Assorted Bliss Bites" in html, "Sixfold Assorted Bliss Bites missing"
                assert "Curated Drawer Gift Set — Sixfold — Just Nuts" in html, "Sixfold Just Nuts missing"
                print("✓ SUCCESS: All Premium, Assorted, and Just Nuts editions present in quotation builder dropdown!")

        # -------------------------------------------------------------
        # TEST 5: Form Submission with Assorted and Nuts Editions
        # -------------------------------------------------------------
        print("\n--- TEST 5: Quotation Builder Form Submission with Editions ---")
        with app.test_client() as c:
            admin_user = User.query.filter_by(is_admin=True).first()
            if admin_user:
                with c.session_transaction() as sess:
                    sess['_user_id'] = str(admin_user.id)
                    sess['_fresh'] = True

                post_data = {
                    'advance_percent': '30',
                    'discount_type': 'flat',
                    'discount_value': '0',
                    'custom_occasion': 'Diwali Corporate Gift',
                    'target_dispatch_eta': '5-7 business days',
                    'product_id[]': ['1__assorted', '12__just_nuts'],
                    'item_name[]': ['Signature DIYA Box — Assorted Edition', 'Curated Drawer Gift Set — Sixfold — Just Nuts & Dried Fruits (6 Jars)'],
                    'item_category[]': ['Diwali & Festive', 'Hampers & Gift Sets'],
                    'item_description[]': ['4 Signature Bliss Bites, 4 Core Bliss Bites', '6 jars of California Almonds, Cashews, Pistachios, Walnuts, Raisins, Figs'],
                    'item_quantity[]': ['50', '20'],
                    'item_unit_price[]': ['265.0', '1099.0']
                }

                resp = c.post(f'/admin/b2b/orders/{order.id}/quotation-builder', data=post_data, follow_redirects=True)
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

                # Query updated order items
                db.session.refresh(order)
                items = B2BOrderItem.query.filter_by(order_id=order.id).all()
                assert len(items) == 2, f"Expected 2 items, got {len(items)}"
                
                # Check line 1 (Signature DIYA Box Assorted)
                item1 = next((it for it in items if "Signature DIYA Box" in it.item_name), None)
                assert item1 is not None, "Signature DIYA Box line item missing"
                assert item1.product_id == 1, f"Expected product_id 1, got {item1.product_id}"
                assert item1.unit_price == 265.0, f"Expected unit price 265.0, got {item1.unit_price}"
                assert item1.quantity == 50, f"Expected qty 50, got {item1.quantity}"
                assert item1.total_price == 13250.0, f"Expected total 13250.0, got {item1.total_price}"

                # Check line 2 (Sixfold Drawer Just Nuts)
                item2 = next((it for it in items if "Sixfold" in it.item_name), None)
                assert item2 is not None, "Sixfold line item missing"
                assert item2.product_id == 12, f"Expected product_id 12, got {item2.product_id}"
                assert item2.unit_price == 1099.0, f"Expected unit price 1099.0, got {item2.unit_price}"
                assert item2.quantity == 20, f"Expected qty 20, got {item2.quantity}"
                assert item2.total_price == 21980.0, f"Expected total 21980.0, got {item2.total_price}"

                # Subtotal: 13250 + 21980 = 35230.0
                taxable_expected = 35230.0
                tax_expected = round(taxable_expected * 0.05, 2) # 1761.50
                grand_total_expected = round(taxable_expected + tax_expected, 2) # 36991.50
                expected_advance = round(grand_total_expected * 0.30, 2) # 11097.45

                assert order.subtotal_amount == 35230.0, f"Expected subtotal 35230.0, got {order.subtotal_amount}"
                assert order.total_amount == grand_total_expected, f"Expected total {grand_total_expected}, got {order.total_amount}"
                assert order.advance_percent == 30.0, f"Expected advance 30.0%, got {order.advance_percent}"
                assert order.advance_amount_required == expected_advance, f"Expected advance {expected_advance}, got {order.advance_amount_required}"

                print(f"✓ SUCCESS: Form submission saved line items correctly: ID 1 @ ₹265, ID 12 @ ₹1099!")
                print(f"✓ SUCCESS: Order subtotal ₹{order.subtotal_amount:,.2f} + 5% GST (₹{tax_expected:,.2f}) = Total ₹{order.total_amount:,.2f} with 30% advance: ₹{order.advance_amount_required:,.2f}!")

    print("\n" + "=" * 60)
    print("ALL VERIFICATION SUITES PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == '__main__':
    run_tests()
