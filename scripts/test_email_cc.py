#!/usr/bin/env python3
"""
Test Suite: Verify automatic CC on all outbound emails
Validates:
1. send_b2b_email defaults to CC'ing Vishnu.govind@pikachooz.com
2. Email message headers (Cc: Vishnu.govind@pikachooz.com) and envelope recipients
3. All B2B email dispatchers include CC and record it in B2BCommunicationLog
4. send_email_otp in otp_utils also includes CC
"""

import os
import sys
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models.b2b import B2BClient, B2BOrder, B2BCommunicationLog
from utils.email_utils import (
    DEFAULT_CC_EMAIL,
    send_b2b_email,
    send_welcome_onboarding_email,
    send_quotation_email,
    send_advance_received_email,
    send_design_proof_email,
    send_production_eta_email,
    send_order_delivered_email
)
from utils.otp_utils import send_email_otp

def run_tests():
    print("=" * 70)
    print("RUNNING AUTOMATED TESTS FOR MANDATORY CC ON ALL OUTBOUND EMAILS")
    print("=" * 70)

    assert DEFAULT_CC_EMAIL == "Vishnu.govind@pikachooz.com", f"Expected DEFAULT_CC_EMAIL to be Vishnu.govind@pikachooz.com, got {DEFAULT_CC_EMAIL}"
    print(f"✓ Configured DEFAULT_CC_EMAIL: {DEFAULT_CC_EMAIL}")

    with app.app_context():
        # -------------------------------------------------------------
        # TEST 1: Unit Test send_b2b_email with Mocked SMTP
        # -------------------------------------------------------------
        print("\n--- TEST 1: send_b2b_email MIME Headers & Envelope Recipients ---")
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server

            success, msg = send_b2b_email(
                to_email="client@corporate.com",
                subject="Test Quotation",
                html_content="<p>Here is your quotation</p>"
            )

            assert success is True, f"send_b2b_email failed: {msg}"
            assert mock_server.sendmail.called, "server.sendmail was not called!"

            # Check args passed to sendmail(sender, recipients, msg_str)
            args, kwargs = mock_server.sendmail.call_args
            sender_arg, recipients_arg, raw_msg_arg = args[0], args[1], args[2]

            print(f"  SMTP Sender: {sender_arg}")
            print(f"  SMTP Envelope Recipients: {recipients_arg}")

            assert "client@corporate.com" in recipients_arg, "Primary recipient missing from envelope"
            assert "Vishnu.govind@pikachooz.com" in recipients_arg, "CC recipient Vishnu.govind@pikachooz.com missing from envelope!"

            # Verify 'Cc' header in raw MIME message
            assert "Cc: Vishnu.govind@pikachooz.com" in raw_msg_arg, "Cc header missing from MIME message!"
            assert "To: client@corporate.com" in raw_msg_arg, "To header missing from MIME message!"
            print("✓ SUCCESS: send_b2b_email correctly sets 'Cc: Vishnu.govind@pikachooz.com' header and delivers to both recipients!")

        # -------------------------------------------------------------
        # TEST 2: Custom CC Override or Exclusion
        # -------------------------------------------------------------
        print("\n--- TEST 2: Custom CC handling & Multiple CCs ---")
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server

            # Test multiple CCs
            success, msg = send_b2b_email(
                to_email="client@corporate.com",
                subject="Custom CC Test",
                html_content="<p>Test</p>",
                cc_email="Vishnu.govind@pikachooz.com, finance@pikachooz.com"
            )
            args, _ = mock_server.sendmail.call_args
            recipients = args[1]
            raw_msg = args[2]

            assert "Vishnu.govind@pikachooz.com" in recipients
            assert "finance@pikachooz.com" in recipients
            assert "finance@pikachooz.com" in raw_msg
            print("✓ SUCCESS: Multiple CC addresses supported and delivered!")

        # -------------------------------------------------------------
        # TEST 3: B2B Dispatchers (Welcome, Quotation, Advance, Design, Production, Delivered)
        # -------------------------------------------------------------
        print("\n--- TEST 3: All 6 B2B Dispatchers Logging with CC Tag ---")
        client = B2BClient.query.first()
        if not client:
            client = B2BClient(
                company_name="Test Corp",
                contact_name="Test Person",
                phone="+919000000001",
                email="test.client@example.com"
            )
            db.session.add(client)
            db.session.commit()

        order = B2BOrder.query.filter_by(client_id=client.id).first()
        if not order:
            order = B2BOrder(
                order_number="SSB2B-TESTCC",
                client_id=client.id,
                stage="enquiry",
                box_type="Signature Box",
                box_count=50,
                quoted_price_per_box=500.0,
                subtotal_amount=25000.0,
                total_amount=26250.0
            )
            db.session.add(order)
            db.session.commit()

        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server

            # 1. Welcome email
            w_succ, _ = send_welcome_onboarding_email(client, order)
            assert w_succ is True
            args, _ = mock_server.sendmail.call_args
            assert "Vishnu.govind@pikachooz.com" in args[1]

            # 2. Quotation email
            q_succ, _ = send_quotation_email(order, b"%PDF-1.4 test", "Quote.pdf")
            assert q_succ is True
            args, _ = mock_server.sendmail.call_args
            assert "Vishnu.govind@pikachooz.com" in args[1]

            # 3. Advance email
            adv_succ, _ = send_advance_received_email(order, 10000.0)
            assert adv_succ is True
            args, _ = mock_server.sendmail.call_args
            assert "Vishnu.govind@pikachooz.com" in args[1]

            # 4. Design proof email
            d_succ, _ = send_design_proof_email(order)
            assert d_succ is True
            args, _ = mock_server.sendmail.call_args
            assert "Vishnu.govind@pikachooz.com" in args[1]

            # 5. Production ETA email
            p_succ, _ = send_production_eta_email(order)
            assert p_succ is True
            args, _ = mock_server.sendmail.call_args
            assert "Vishnu.govind@pikachooz.com" in args[1]

            # 6. Delivered email
            del_succ, _ = send_order_delivered_email(order)
            assert del_succ is True
            args, _ = mock_server.sendmail.call_args
            assert "Vishnu.govind@pikachooz.com" in args[1]

            # Verify B2BCommunicationLog entries for this order contain CC tag
            recent_logs = B2BCommunicationLog.query.filter_by(order_id=order.id, channel='email').order_by(B2BCommunicationLog.id.desc()).limit(6).all()
            for l in recent_logs:
                print(f"  Log: [{l.event_type}] Preview: {l.message_preview}")
                assert "Vishnu.govind@pikachooz.com" in l.message_preview, f"CC missing from log preview: {l.message_preview}"

            print("✓ SUCCESS: All 6 dispatchers automatically CC Vishnu.govind@pikachooz.com and record it in communication logs!")

        # -------------------------------------------------------------
        # TEST 4: otp_utils send_email_otp CC Verification
        # -------------------------------------------------------------
        print("\n--- TEST 4: otp_utils send_email_otp with CC ---")
        with patch.dict(os.environ, {
            "MAIL_SERVER": "smtp.gmail.com",
            "MAIL_USERNAME": "test@pikachooz.com",
            "MAIL_PASSWORD": "secretpassword",
            "DEFAULT_CC_EMAIL": "Vishnu.govind@pikachooz.com"
        }):
            with patch("smtplib.SMTP") as mock_smtp_cls:
                mock_server = MagicMock()
                mock_smtp_cls.return_value = mock_server

                otp_succ = send_email_otp("customer@domain.com", "1234")
                assert otp_succ is True
                args, _ = mock_server.sendmail.call_args
                recipients = args[1]
                raw_msg = args[2]

                assert "customer@domain.com" in recipients
                assert "Vishnu.govind@pikachooz.com" in recipients
                assert "Cc: Vishnu.govind@pikachooz.com" in raw_msg
                print("✓ SUCCESS: send_email_otp also CC's Vishnu.govind@pikachooz.com!")

        print("\n" + "=" * 70)
        print("ALL TESTS PASSED WITH 100% SUCCESS! CC VERIFIED ON ALL EMAILS.")
        print("=" * 70)

if __name__ == "__main__":
    run_tests()
