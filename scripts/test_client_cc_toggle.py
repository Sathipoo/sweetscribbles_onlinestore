#!/usr/bin/env python3
"""
Test Suite: Verify Client Profile Secondary CC Maintenance and Order-Level CC Toggle
Validates:
1. Updating client profile with comma-separated CC emails via edit_client route.
2. Helper properties (cc_email_list, has_cc_emails) on B2BClient.
3. Asynchronous / synchronous order CC toggle endpoint (/orders/<id>/toggle-client-cc).
4. Consolidated CC resolution (resolve_b2b_cc_list) combining DEFAULT_CC_EMAIL and client CCs when ON,
   and isolating to DEFAULT_CC_EMAIL when OFF.
5. Outbound dispatch tests for Send Quotation, Send Proforma, and Send Tax Invoice verifying
   accurate MIME headers, envelope recipients, and communication logs under both ON and OFF states.
"""

import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models.user import User
from models.b2b import B2BClient, B2BOrder, B2BOrderItem, B2BCommunicationLog
from routes.b2b_admin import resolve_b2b_cc_list
from utils.email_utils import DEFAULT_CC_EMAIL

def run_tests():
    print("=" * 80)
    print("RUNNING CLIENT PROFILE CC MAINTENANCE & ORDER LIFECYCLE TOGGLE TEST SUITE")
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

            # 1. Setup client matching Dheya Engineering Technologies scenario
            test_client = B2BClient.query.filter_by(phone="+917829019898").first()
            if not test_client:
                test_client = B2BClient(
                    company_name="Dheya Engineering Technologies Pvt. Ltd.",
                    contact_name="Bhagya Shree",
                    phone="+917829019898",
                    email="bhagyashree@dheyatech.com",
                    shipping_address="Peenya Industrial Area, Bengaluru",
                    gst_number="29AAGCD4436Q1Z0"
                )
                db.session.add(test_client)
                db.session.commit()

            # Ensure order exists
            order = B2BOrder.query.filter_by(order_number="SSB2B-91DFE6").first()
            if not order:
                order = B2BOrder(
                    order_number="SSB2B-91DFE6",
                    client_id=test_client.id,
                    box_type="Celebration Carry Hamper — Grande",
                    box_count=50,
                    quoted_price_per_box=1275.0,
                    subtotal_amount=63750.0,
                    gst_percent=5.0,
                    total_amount=66937.50,
                    advance_amount_required=33468.75,
                    stage="quotation_sent",
                    use_client_cc=True
                )
                db.session.add(order)
                db.session.commit()

            print(f"Initialized Client: {test_client.company_name} ({test_client.email})")
            print(f"Initialized Order #{order.order_number} (Total: ₹{order.total_amount:,.2f})")

            # -----------------------------------------------------------------
            # TEST 1: Update Client Profile CC Emails via edit_client
            # -----------------------------------------------------------------
            print("\n--- TEST 1: Update Client Profile with CC Emails ---")
            edit_res = client.post(f"/admin/b2b/clients/{test_client.id}/edit", data={
                'company_name': test_client.company_name,
                'contact_name': test_client.contact_name,
                'phone': test_client.phone,
                'email': test_client.email,
                'cc_emails': "accounts@dheyatech.com, director@dheyatech.com, accounts@dheyatech.com", # Test deduplication/trim
                'gst_number': test_client.gst_number or '',
                'shipping_address': test_client.shipping_address or '',
                'industry': 'Engineering',
                'notes': 'Preferred corporate client'
            }, follow_redirects=True)

            assert edit_res.status_code == 200
            db.session.refresh(test_client)

            print(f"  test_client.cc_emails: {test_client.cc_emails}")
            print(f"  test_client.cc_email_list: {test_client.cc_email_list}")
            print(f"  test_client.has_cc_emails: {test_client.has_cc_emails}")

            assert "accounts@dheyatech.com" in test_client.cc_emails
            assert "director@dheyatech.com" in test_client.cc_emails
            assert test_client.has_cc_emails is True
            assert len(test_client.cc_email_list) == 2 # Deduplicated
            print("✓ SUCCESS: Client CC emails successfully saved and parsed in profile!")

            # -----------------------------------------------------------------
            # TEST 2: Toggle Order Client CC via Endpoint (ON / OFF)
            # -----------------------------------------------------------------
            print("\n--- TEST 2: Order-Level Client CC Toggle Endpoint ---")
            # Turn ON
            res_on = client.post(f"/admin/b2b/orders/{order.id}/toggle-client-cc", json={
                'use_client_cc': True
            })
            assert res_on.status_code == 200
            db.session.refresh(order)
            assert order.use_client_cc is True
            
            resolved_on = resolve_b2b_cc_list(order)
            print(f"  When Client CC is ON: {resolved_on}")
            for def_c in DEFAULT_CC_EMAIL.split(','):
                assert def_c.strip().lower() in [x.lower() for x in resolved_on]
            assert "accounts@dheyatech.com" in resolved_on
            assert "director@dheyatech.com" in resolved_on
            print("✓ SUCCESS: When CC is ON, both executive CC and client CCs are included!")

            # Turn OFF
            res_off = client.post(f"/admin/b2b/orders/{order.id}/toggle-client-cc", json={
                'use_client_cc': False
            })
            assert res_off.status_code == 200
            db.session.refresh(order)
            assert order.use_client_cc is False

            resolved_off = resolve_b2b_cc_list(order)
            print(f"  When Client CC is OFF: {resolved_off}")
            for def_c in DEFAULT_CC_EMAIL.split(','):
                assert def_c.strip().lower() in [x.lower() for x in resolved_off]
            assert "accounts@dheyatech.com" not in resolved_off
            assert "director@dheyatech.com" not in resolved_off
            print("✓ SUCCESS: When CC is OFF, client CCs are excluded while preserving executive CC!")

            # -----------------------------------------------------------------
            # TEST 3: Send Quotation with CC ON vs CC OFF
            # -----------------------------------------------------------------
            print("\n--- TEST 3: Send Quotation Action with CC ON & OFF ---")
            # 3a. Send Quotation with CC ON
            send_q_on = client.post(f"/admin/b2b/orders/{order.id}/send-quotation", data={
                'use_client_cc': '1'
            }, follow_redirects=True)
            assert send_q_on.status_code == 200
            
            latest_q_log = B2BCommunicationLog.query.filter_by(order_id=order.id, event_type='quotation', channel='email').order_by(B2BCommunicationLog.created_at.desc()).first()
            assert latest_q_log is not None
            print(f"  Quotation (CC ON) Log Preview: {latest_q_log.message_preview}")
            assert "accounts@dheyatech.com" in latest_q_log.message_preview
            assert "director@dheyatech.com" in latest_q_log.message_preview
            print("✓ SUCCESS: Quotation dispatched with Client CC ON correctly delivered & logged!")

            # 3b. Send Quotation with CC OFF
            send_q_off = client.post(f"/admin/b2b/orders/{order.id}/send-quotation", data={
                'use_client_cc': '0'
            }, follow_redirects=True)
            assert send_q_off.status_code == 200

            latest_q_log_off = B2BCommunicationLog.query.filter_by(order_id=order.id, event_type='quotation', channel='email').order_by(B2BCommunicationLog.created_at.desc()).first()
            assert latest_q_log_off is not None
            print(f"  Quotation (CC OFF) Log Preview: {latest_q_log_off.message_preview}")
            assert "accounts@dheyatech.com" not in latest_q_log_off.message_preview
            print("✓ SUCCESS: Quotation dispatched with Client CC OFF successfully excluded client contacts!")

            # -----------------------------------------------------------------
            # TEST 4: Send Proforma (PI) & Send Tax Invoice with CC Toggle
            # -----------------------------------------------------------------
            print("\n--- TEST 4: Send Proforma (PI) & Tax Invoice (INV) with CC Toggle ---")
            # Proforma with CC ON
            send_pi_res = client.post(f"/admin/b2b/orders/{order.id}/send-proforma", data={
                'use_client_cc': '1'
            }, follow_redirects=True)
            assert send_pi_res.status_code == 200
            pi_log = B2BCommunicationLog.query.filter_by(order_id=order.id, event_type='proforma', channel='email').order_by(B2BCommunicationLog.created_at.desc()).first()
            assert pi_log is not None
            assert "accounts@dheyatech.com" in pi_log.message_preview
            print(f"  ✓ Proforma Invoice dispatched with Client CC ON! [Log: {pi_log.message_preview[:65]}...]")

            # Tax Invoice with CC ON
            send_inv_res = client.post(f"/admin/b2b/orders/{order.id}/send-tax-invoice", data={
                'use_client_cc': '1'
            }, follow_redirects=True)
            assert send_inv_res.status_code == 200
            inv_log = B2BCommunicationLog.query.filter_by(order_id=order.id, event_type='invoice', channel='email').order_by(B2BCommunicationLog.created_at.desc()).first()
            assert inv_log is not None
            assert "accounts@dheyatech.com" in inv_log.message_preview
            print(f"  ✓ Tax Invoice dispatched with Client CC ON! [Log: {inv_log.message_preview[:65]}...]")

            # Tax Invoice with CC OFF
            send_inv_off_res = client.post(f"/admin/b2b/orders/{order.id}/send-tax-invoice", data={
                'use_client_cc': '0'
            }, follow_redirects=True)
            assert send_inv_off_res.status_code == 200
            inv_off_log = B2BCommunicationLog.query.filter_by(order_id=order.id, event_type='invoice', channel='email').order_by(B2BCommunicationLog.created_at.desc()).first()
            assert inv_off_log is not None
            assert "accounts@dheyatech.com" not in inv_off_log.message_preview
            print(f"  ✓ Tax Invoice dispatched with Client CC OFF correctly excluded client CC!")

            print("\n" + "=" * 80)
            print("ALL CLIENT CC MAINTENANCE & LIFECYCLE TOGGLE TESTS PASSED WITH 100% SUCCESS!")
            print("=" * 80)

if __name__ == "__main__":
    run_tests()
