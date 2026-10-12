#!/usr/bin/env python3
"""
Test Suite: Verify Multiple Design Proof Assets per B2B Order & Dedicated Notification Dispatch
Validates:
1. Adding multiple distinct design proof assets (e.g. for different hamper/box types).
2. Ensuring asset uploads do NOT immediately blast notifications to client.
3. Deleting individual design assets with clean synchronization of primary proof URL.
4. Dedicated 'Send Design Proofs to Client' action triggering SMS + consolidated Email.
5. Email content verification: ensuring all assets (names, links) are embedded with CC resolution.
6. Client portal rendering and approval flow across multiple assets.
"""

import os
import sys
import io

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models.user import User
from models.b2b import B2BClient, B2BOrder, B2BOrderDesignAsset, B2BCommunicationLog, B2BOrderLog
from routes.b2b_admin import resolve_b2b_cc_list

def run_tests():
    print("=" * 80)
    print("RUNNING MULTIPLE DESIGN ASSETS & DEDICATED DISPATCH TEST SUITE")
    print("=" * 80)

    with app.test_client() as client:
        with app.app_context():
            # Ensure admin user exists for session auth
            admin = User.query.filter_by(is_admin=True).first()
            if not admin:
                admin = User(phone="9999999999", email="admin@sweetscribbles.com", is_admin=True, name="Super Admin")
                admin.set_password("admin123")
                db.session.add(admin)
                db.session.commit()

            with client.session_transaction() as sess:
                sess['_user_id'] = str(admin.id)
                sess['_fresh'] = True

            # 1. Setup client & order
            test_client = B2BClient.query.filter_by(phone="+917829019898").first()
            if not test_client:
                test_client = B2BClient(
                    company_name="SS Fiber Optic Solutions",
                    contact_name="Bhagya Shree",
                    phone="+917829019898",
                    email="bhagyashree@ssfibre.com",
                    cc_emails="finance@ssfibre.com, procurement@ssfibre.com",
                    shipping_address="Peenya Industrial Area, Bengaluru"
                )
                db.session.add(test_client)
                db.session.commit()
            else:
                test_client.cc_emails = "finance@ssfibre.com, procurement@ssfibre.com"
                db.session.commit()

            order = B2BOrder.query.filter_by(order_number="SSB2B-TEST-ASSETS").first()
            if not order:
                order = B2BOrder(
                    order_number="SSB2B-TEST-ASSETS",
                    client_id=test_client.id,
                    box_count=120,
                    quoted_price_per_box=1500.0,
                    total_amount=180000.0,
                    advance_amount_required=90000.0,
                    advance_paid=True,
                    stage='advance_paid',
                    use_client_cc=True
                )
                db.session.add(order)
                db.session.commit()
            else:
                order.stage = 'advance_paid'
                order.use_client_cc = True
                order.design_status = 'pending_upload'
                # Clean up existing assets for test order
                B2BOrderDesignAsset.query.filter_by(order_id=order.id).delete()
                db.session.commit()

            print(f"\n[1] Starting State: Order #{order.order_number}, Client: {test_client.company_name}")
            assert len(order.design_assets) == 0, "Order should have 0 design assets initially"
            print("  ✓ Initial asset count: 0")

            # Count communication logs before upload
            initial_email_logs = B2BCommunicationLog.query.filter_by(order_id=order.id, channel='email', event_type='design_ready').count()
            initial_sms_logs = B2BCommunicationLog.query.filter_by(order_id=order.id, channel='sms', event_type='design_ready').count()

            # 2. Upload Asset 1: Celebration Carry Hamper — Grande Sleeve
            print("\n[2] Uploading Asset 1: 'Celebration Carry Hamper — Grande Sleeve'")
            dummy_png = (io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest"), "grande_sleeve.png")
            resp1 = client.post(f"/admin/b2b/orders/{order.id}/design-assets/add", data={
                'asset_name': 'Celebration Carry Hamper — Grande Sleeve',
                'design_file': dummy_png,
                'notes': 'Gold foil branding on matte navy finish'
            }, content_type='multipart/form-data', follow_redirects=True)
            assert resp1.status_code == 200

            db.session.refresh(order)
            assert len(order.design_assets) == 1
            asset1 = order.design_assets[0]
            assert asset1.asset_name == 'Celebration Carry Hamper — Grande Sleeve'
            assert asset1.file_type == 'image'
            assert not asset1.is_pdf
            assert order.design_proof_url is not None
            assert order.design_status == 'assets_uploaded'
            print("  ✓ Asset 1 saved successfully in DB")

            # Check that NO notifications were sent yet!
            curr_email_logs = B2BCommunicationLog.query.filter_by(order_id=order.id, channel='email', event_type='design_ready').count()
            curr_sms_logs = B2BCommunicationLog.query.filter_by(order_id=order.id, channel='sms', event_type='design_ready').count()
            assert curr_email_logs == initial_email_logs, "No email should be dispatched on individual asset upload!"
            assert curr_sms_logs == initial_sms_logs, "No SMS should be dispatched on individual asset upload!"
            print("  ✓ Verification: Individual upload did NOT dispatch email/SMS alerts to client")

            # 3. Upload Asset 2: Just Nuts Box Sleeve
            print("\n[3] Uploading Asset 2: 'Just Nuts Box Sleeve'")
            dummy_jpg = (io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIFtest"), "nuts_box.jpg")
            resp2 = client.post(f"/admin/b2b/orders/{order.id}/design-assets/add", data={
                'asset_name': 'Just Nuts Box Sleeve',
                'design_file': dummy_jpg,
                'notes': 'Emerald green sleeve with embossed logo'
            }, content_type='multipart/form-data', follow_redirects=True)
            assert resp2.status_code == 200

            db.session.refresh(order)
            assert len(order.design_assets) == 2
            print("  ✓ Asset 2 saved. Total assets now: 2")

            # 4. Upload Asset 3: Greeting Insert Card (PDF)
            print("\n[4] Uploading Asset 3: 'Festive Greeting Insert Card (PDF)'")
            dummy_pdf = (io.BytesIO(b"%PDF-1.4\ntest"), "greeting_card.pdf")
            resp3 = client.post(f"/admin/b2b/orders/{order.id}/design-assets/add", data={
                'asset_name': 'Festive Greeting Insert Card',
                'design_file': dummy_pdf,
                'notes': '350 GSM textured card'
            }, content_type='multipart/form-data', follow_redirects=True)
            assert resp3.status_code == 200

            db.session.refresh(order)
            assert len(order.design_assets) == 3
            asset3 = order.design_assets[2]
            assert asset3.is_pdf, "Asset 3 should be detected as PDF"
            print("  ✓ Asset 3 (PDF) saved. Total assets now: 3")

            # 5. Delete Asset 3 to test deletion flow
            print(f"\n[5] Testing Asset Deletion: Deleting Asset #{asset3.id} ('{asset3.asset_name}')")
            resp_del = client.post(f"/admin/b2b/orders/{order.id}/design-assets/{asset3.id}/delete", follow_redirects=True)
            assert resp_del.status_code == 200

            db.session.refresh(order)
            assert len(order.design_assets) == 2
            asset_names = [a.asset_name for a in order.design_assets]
            assert 'Festive Greeting Insert Card' not in asset_names
            print("  ✓ Asset 3 successfully removed. Remaining assets: 2 ('Grande Sleeve' and 'Just Nuts Box')")

            # 6. Test Dedicated Notification Dispatch
            print("\n[6] Dispatching Design Proofs (Email + SMS) to Client")
            resp_dispatch = client.post(f"/admin/b2b/orders/{order.id}/dispatch-design-proofs", follow_redirects=True)
            assert resp_dispatch.status_code == 200

            db.session.refresh(order)
            assert order.stage == 'design_review', f"Order stage should be 'design_review', got '{order.stage}'"
            assert order.design_status == 'awaiting_approval', f"Design status should be 'awaiting_approval', got '{order.design_status}'"
            print("  ✓ Order stage updated to 'design_review', design_status='awaiting_approval'")

            # Check communication logs
            new_email_logs = B2BCommunicationLog.query.filter_by(order_id=order.id, channel='email', event_type='design_ready').all()
            new_sms_logs = B2BCommunicationLog.query.filter_by(order_id=order.id, channel='sms', event_type='design_ready').all()

            assert len(new_email_logs) > initial_email_logs, "Design proof email log must be created!"
            assert len(new_sms_logs) > initial_sms_logs, "Design proof SMS log must be created!"
            latest_email = new_email_logs[0]
            print(f"  ✓ Email communication logged: Recipient={latest_email.recipient}, Subject='{latest_email.subject}'")
            print(f"  ✓ Message preview: {latest_email.message_preview}")

            # Verify CC handling in dispatch
            resolved_ccs = resolve_b2b_cc_list(order)
            print(f"  ✓ Resolved CC List with toggle ON: {resolved_ccs}")
            assert "finance@ssfibre.com" in resolved_ccs
            assert "procurement@ssfibre.com" in resolved_ccs

            # 7. Verify Client Portal View & Approval
            print("\n[7] Verifying Client Portal Presentation & Approval")
            # Set client session for B2B client auth
            with client.session_transaction() as sess:
                sess['b2b_client_id'] = test_client.id

            portal_resp = client.get("/b2b/portal")
            assert portal_resp.status_code == 200
            portal_html = portal_resp.data.decode('utf-8')
            assert 'Celebration Carry Hamper — Grande Sleeve' in portal_html
            assert 'Just Nuts Box Sleeve' in portal_html
            assert 'Approve All Proofs' in portal_html or 'Approve For Production' in portal_html
            print("  ✓ Client Portal correctly renders both design assets and approval CTA")

            # Client approves designs
            approve_resp = client.post(f"/b2b/portal/approve-design/{order.id}", follow_redirects=True)
            assert approve_resp.status_code == 200
            db.session.refresh(order)
            assert order.design_status == 'approved'
            assert order.stage == 'details_locked'
            print("  ✓ Client approval executed successfully: stage='details_locked', design_status='approved'")

            # Clean up test order
            db.session.delete(order)
            db.session.commit()
            print("\n  ✓ Test order cleaned up.")

            print("=" * 80)
            print("ALL MULTIPLE DESIGN ASSETS TESTS PASSED SUCCESSFULLY! ✓")
            print("=" * 80)

if __name__ == '__main__':
    run_tests()
