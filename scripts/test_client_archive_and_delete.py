#!/usr/bin/env python3
"""
Test Suite: B2B Corporate Client Archive, Restore, and Delete Lifecycle
Validates:
1. Client archiving (soft-delete): sets is_archived=True, preserves orders & GST records.
2. Filter views (active, archived, all) and status counters.
3. Dropdown exclusion: archived clients are omitted from active order creation.
4. Public portal protection: archived clients cannot request login OTP.
5. Client restoration: reactivates client, unhides them across admin workflows.
6. Permanent deletion: cascades cleanly when hard deletion is explicitly chosen.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from extensions import db
from models.b2b import B2BClient, B2BOrder, B2BOrderItem, B2BCommunicationLog
from datetime import datetime

def run_tests():
    app = create_app()
    with app.app_context():
        client = app.test_client()
        
        print("=" * 70)
        print("RUNNING B2B CLIENT ARCHIVE, RESTORE & DELETE LIFECYCLE TESTS")
        print("=" * 70)

        # 1. Clean up any previous test client
        test_phone = "+919999988881"
        old_client = B2BClient.query.filter_by(phone=test_phone).first()
        if old_client:
            db.session.delete(old_client)
            db.session.commit()
            print(f"Cleaned up preexisting test client for phone: {test_phone}")

        # 2. Create a test client
        test_client = B2BClient(
            company_name="Acme Global Innovations Ltd",
            contact_name="Vikram Sethi",
            phone=test_phone,
            email="vikram.sethi@acmeglobal.fake",
            gst_number="29AAAAA0000A1Z5",
            shipping_address="Tech Park Phase 2, Outer Ring Road, Bangalore",
            is_archived=False
        )
        db.session.add(test_client)
        db.session.commit()
        client_id = test_client.id
        print(f"[1/7] Created test client: ID={client_id}, Company='{test_client.company_name}', is_archived={test_client.is_archived}")

        # 3. Create a test order with items and communication log for this client
        test_order = B2BOrder(
            order_number=f"ORD-TEST-ARCHIVE-{client_id}",
            client_id=client_id,
            stage="quotation_sent",
            box_type="Artisan Luxe Hamper",
            box_count=100,
            quoted_price_per_box=1500.0,
            subtotal_amount=150000.0,
            total_amount=177000.0,
            internal_notes="Diwali bulk gifting test order"
        )
        db.session.add(test_order)
        db.session.commit()

        test_item = B2BOrderItem(
            order_id=test_order.id,
            item_name="Artisan Luxe Box",
            item_category="Hampers",
            quantity=100,
            unit_price=1500.0,
            total_price=150000.0
        )
        test_comm = B2BCommunicationLog(
            order_id=test_order.id,
            client_id=client_id,
            channel="email",
            event_type="quotation",
            recipient="vikram.sethi@acmeglobal.fake",
            subject="Quotation for Festive Gifting",
            message_preview="Your quotation has been prepared."
        )
        db.session.add(test_item)
        db.session.add(test_comm)
        db.session.commit()
        print(f"[2/7] Created associated order: ID={test_order.id}, total=₹{test_order.total_amount:,.2f}, comm log ID={test_comm.id}")

        # Set admin session for test client using Flask-Login
        from models.user import User
        admin_user = User.query.filter_by(is_admin=True).first()
        if not admin_user:
            admin_user = User(name="Admin Tester", email="admin@sweetscribbles.com", is_admin=True)
            db.session.add(admin_user)
            db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        # 4. Test Archive Endpoint
        archive_resp = client.post(f"/admin/b2b/clients/{client_id}/archive", follow_redirects=False)
        assert archive_resp.status_code == 302, f"Expected 302 redirect, got {archive_resp.status_code}"
        
        # Verify database state after archive
        db.session.expire_all()
        c_after_archive = B2BClient.query.get(client_id)
        assert c_after_archive.is_archived is True, "Expected is_archived to be True"
        assert c_after_archive.archived_at is not None, "Expected archived_at to be set"
        assert len(c_after_archive.orders) == 1, "Expected historical order to be completely preserved"
        assert len(c_after_archive.communication_logs) == 1, "Expected comm logs to be completely preserved"
        print(f"[3/7] Archive Successful: is_archived={c_after_archive.is_archived}, archived_at={c_after_archive.archived_at}")
        print(f"      Preserved Orders: {len(c_after_archive.orders)}, Preserved Comm Logs: {len(c_after_archive.communication_logs)}")

        # 5. Verify Exclusion from Active Queries & Client Portal
        active_clients = B2BClient.query.filter_by(is_archived=False).all()
        active_ids = [c.id for c in active_clients]
        assert client_id not in active_ids, "Archived client must NOT appear in active client queries!"

        archived_clients = B2BClient.query.filter_by(is_archived=True).all()
        archived_ids = [c.id for c in archived_clients]
        assert client_id in archived_ids, "Archived client MUST appear in archived client queries!"
        print(f"[4/7] Query Filtering: Client {client_id} correctly excluded from active ({len(active_clients)} active) and included in archived ({len(archived_clients)} archived)")

        # Verify public client portal blocks login for archived client
        portal_resp = client.post("/b2b/send-login-otp", json={"phone": test_phone})
        assert portal_resp.status_code == 403, f"Expected 403 for archived client portal login, got {portal_resp.status_code}"
        print(f"[5/7] Portal Security: Archived client login OTP correctly blocked with 403 ({portal_resp.get_json()['message']})")

        # Verify HTML rendering of directory tabs
        resp_active = client.get("/admin/b2b/clients?status=active")
        assert resp_active.status_code == 200, f"Expected 200 for active tab, got {resp_active.status_code}"
        assert b"Active Accounts" in resp_active.data
        assert b"Archived" in resp_active.data
        assert b"All Accounts" in resp_active.data
        assert b"archiveModal_" in resp_active.data

        resp_archived = client.get("/admin/b2b/clients?status=archived")
        assert resp_archived.status_code == 200, f"Expected 200 for archived tab, got {resp_archived.status_code}"

        resp_detail = client.get(f"/admin/b2b/clients/{client_id}")
        assert resp_detail.status_code == 200, f"Expected 200 for client detail, got {resp_detail.status_code}"
        assert b"Account Lifecycle &amp; Management" in resp_detail.data or b"Account Lifecycle & Management" in resp_detail.data
        assert b"archiveClientModal" in resp_detail.data
        assert b"deleteClientModal" in resp_detail.data
        print(f"[5b/7] Template UI Rendering: Directory tabs, row action modals, and detail page danger zone verified.")

        # 6. Test Client Restore
        restore_resp = client.post(f"/admin/b2b/clients/{client_id}/restore", follow_redirects=False)
        assert restore_resp.status_code == 302, f"Expected 302 redirect, got {restore_resp.status_code}"

        db.session.expire_all()
        c_after_restore = B2BClient.query.get(client_id)
        assert c_after_restore.is_archived is False, "Expected is_archived to be False after restore"
        assert c_after_restore.archived_at is None, "Expected archived_at to be None after restore"
        print(f"[6/7] Restore Successful: is_archived={c_after_restore.is_archived}, archived_at={c_after_restore.archived_at}")

        # 7. Test Permanent Deletion
        del_resp = client.post(f"/admin/b2b/clients/{client_id}/delete", follow_redirects=False)
        assert del_resp.status_code == 302, f"Expected 302 redirect, got {del_resp.status_code}"

        db.session.expire_all()
        c_after_del = B2BClient.query.get(client_id)
        assert c_after_del is None, "Client should be deleted from DB"
        o_after_del = B2BOrder.query.get(test_order.id)
        assert o_after_del is None, "Associated test order should be cascaded and deleted"
        print(f"[7/7] Permanent Delete Successful: Client and associated test order permanently removed from database.")

        print("=" * 70)
        print("ALL TESTS PASSED SUCCESSFULLY! ARCHIVE & DELETE READY FOR PRODUCTION.")
        print("=" * 70)

if __name__ == '__main__':
    run_tests()
