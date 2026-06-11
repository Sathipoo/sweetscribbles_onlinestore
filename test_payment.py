import unittest
from unittest.mock import patch
from app import create_app
from extensions import db
from models.product import Product
from models.order import Order, OrderItem
from models.coupon import Coupon
import uuid

class TestZohoPayments(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        # Start database nested transaction
        db.session.begin_nested()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        self.app_context.pop()

    @patch('routes.customer.ZohoClient')
    def test_checkout_discount_applied_to_payment_link(self, mock_zoho_class):
        # Create a mock ZohoClient instance
        mock_zoho = mock_zoho_class.return_value
        mock_zoho.create_payment_link.return_value = ("https://payments.zoho.in/mock-link", "PL_MOCK_123")

        # Set up a test product
        prod = Product(
            name="Discountable Bite",
            sku=f"TEST-DISC-{uuid.uuid4().hex[:6]}",
            category="bites",
            sale_price=200.0,
            available_qty=10
        )
        db.session.add(prod)
        db.session.flush()

        # Add a test coupon for 10% off
        coupon_code = f"TEST10-{uuid.uuid4().hex[:6]}"
        coupon = Coupon(code=coupon_code, discount_type="percent", discount_value=10.0, is_active=True)
        db.session.add(coupon)
        db.session.commit()

        # Setup cart and apply coupon in session
        with self.client.session_transaction() as sess:
            sess['cart'] = [{
                'product_id': prod.id,
                'quantity': 2,
                'custom_message': '',
                'custom_logo_url': None
            }]
            sess['coupon_code'] = coupon_code

        # Submit checkout
        response = self.client.post('/checkout', data={
            'customer_name': 'Test User',
            'customer_email': 'test@user.com',
            'customer_phone': '9999999999',
            'shipping_address': '123 Sweet Lane'
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "https://payments.zoho.in/mock-link")

        # Verify that ZohoClient was called with the correct DISCOUNTED amount (2 * 200 - 10% = 360)
        mock_zoho.create_payment_link.assert_called_once()
        called_args = mock_zoho.create_payment_link.call_args[0][0]
        self.assertEqual(called_args['amount'], 360.0)

    @patch('routes.customer.ZohoClient')
    def test_pay_return_verifies_zoho_status(self, mock_zoho_class):
        mock_zoho = mock_zoho_class.return_value
        # Mock payment status to be 'paid'
        mock_zoho.check_payment_link_status.return_value = 'paid'

        # Create pending order
        order = Order(
            order_number=f"SS-RETURN-{uuid.uuid4().hex[:6]}",
            total_amount=100.0,
            status="Pending",
            zoho_payment_link_id="PL_VERIFY_123"
        )
        db.session.add(order)
        db.session.commit()

        # Visit return URL (should verify and mark Paid)
        response = self.client.get(f'/pay/return?order_number={order.order_number}')
        self.assertEqual(response.status_code, 200)

        db.session.refresh(order)
        self.assertEqual(order.status, 'Paid')
        mock_zoho.check_payment_link_status.assert_called_once_with("PL_VERIFY_123")

    @patch('routes.customer.ZohoClient')
    def test_pay_return_does_not_approve_if_zoho_unpaid(self, mock_zoho_class):
        mock_zoho = mock_zoho_class.return_value
        # Mock payment status to be 'generated' (not paid yet)
        mock_zoho.check_payment_link_status.return_value = 'generated'

        order = Order(
            order_number=f"SS-RETURN-{uuid.uuid4().hex[:6]}",
            total_amount=100.0,
            status="Pending",
            zoho_payment_link_id="PL_UNPAID_123"
        )
        db.session.add(order)
        db.session.commit()

        # Visit return URL (should check Zoho, but keep Pending)
        response = self.client.get(f'/pay/return?order_number={order.order_number}')
        self.assertEqual(response.status_code, 200)

        db.session.refresh(order)
        self.assertEqual(order.status, 'Pending') # Still Pending!

    def test_pay_webhook_updates_status(self):
        order = Order(
            order_number=f"SS-WEBHOOK-{uuid.uuid4().hex[:6]}",
            total_amount=50.0,
            status="Pending"
        )
        db.session.add(order)
        db.session.commit()

        # Send mock Zoho webhook payload
        payload = {
            "event_type": "payment_link.paid",
            "event_object": {
                "payment_link": {
                    "reference_id": order.order_number
                }
            }
        }

        response = self.client.post('/pay/webhook', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Success", response.data)

        db.session.refresh(order)
        self.assertEqual(order.status, 'Paid')
        self.assertEqual(order.payment_status, 'Paid')

    def test_restore_cart_rebuilds_session_cart(self):
        prod = Product(
            name="Restorable Product",
            sku=f"TEST-RESTORE-{uuid.uuid4().hex[:6]}",
            category="bites",
            sale_price=150.0,
            available_qty=10
        )
        db.session.add(prod)
        db.session.flush()

        order = Order(
            order_number=f"SS-RESTORE-{uuid.uuid4().hex[:6]}",
            total_amount=150.0,
            status="Pending"
        )
        db.session.add(order)
        db.session.flush()

        order_item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            quantity=2,
            price_at_purchase=150.0,
            custom_message="Gift wrap"
        )
        db.session.add(order_item)
        db.session.commit()

        # Visit the restore cart endpoint
        response = self.client.get(f'/cart/restore/{order.order_number}')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/cart', response.location)

        # Verify cart was rebuilt in session
        with self.client.session_transaction() as sess:
            self.assertEqual(len(sess['cart']), 1)
            self.assertEqual(sess['cart'][0]['product_id'], prod.id)
            self.assertEqual(sess['cart'][0]['quantity'], 2)
            self.assertEqual(sess['cart'][0]['custom_message'], "Gift wrap")

    def test_pay_webhook_unrecognized_order_returns_200(self):
        # Send mock Zoho webhook payload for an order that doesn't exist
        payload = {
            "event_type": "payment_link.paid",
            "event_object": {
                "payment_link": {
                    "reference_id": "SS-NONEXISTENT-ORDER"
                }
            }
        }

        response = self.client.post('/pay/webhook', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Order Not Found in Storefront", response.data)

    @patch('routes.customer.ZohoClient')
    def test_order_status_api_checks_status(self, mock_zoho_class):
        mock_zoho = mock_zoho_class.return_value
        mock_zoho.check_payment_link_status.return_value = 'paid'

        order = Order(
            order_number=f"SS-API-{uuid.uuid4().hex[:6]}",
            total_amount=120.0,
            status="Pending",
            zoho_payment_link_id="PL_API_123"
        )
        db.session.add(order)
        db.session.commit()

        # Query status API
        response = self.client.get(f'/api/order/status/{order.order_number}')
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(data['status'], 'Paid')
        self.assertEqual(data['payment_status'], 'Paid')

        db.session.refresh(order)
        self.assertEqual(order.status, 'Paid')

    @patch('routes.customer.ZohoClient')
    def test_pay_return_verifies_zoho_succeeded_status(self, mock_zoho_class):
        mock_zoho = mock_zoho_class.return_value
        # Mock payment status to be 'succeeded' (case-insensitive check covers this)
        mock_zoho.check_payment_link_status.return_value = 'SUCCEEDED'

        # Create pending order
        order = Order(
            order_number=f"SS-RETURN-{uuid.uuid4().hex[:6]}",
            total_amount=100.0,
            status="Pending",
            zoho_payment_link_id="PL_VERIFY_SUCCEEDED"
        )
        db.session.add(order)
        db.session.commit()

        # Visit return URL (should verify and mark Paid)
        response = self.client.get(f'/pay/return?order_number={order.order_number}')
        self.assertEqual(response.status_code, 200)

        db.session.refresh(order)
        self.assertEqual(order.status, 'Paid')
        mock_zoho.check_payment_link_status.assert_called_once_with("PL_VERIFY_SUCCEEDED")

    @patch('routes.customer.ZohoClient')
    def test_order_status_api_checks_succeeded_status(self, mock_zoho_class):
        mock_zoho = mock_zoho_class.return_value
        # Mock payment status to be 'succeeded'
        mock_zoho.check_payment_link_status.return_value = 'succeeded'

        order = Order(
            order_number=f"SS-API-{uuid.uuid4().hex[:6]}",
            total_amount=120.0,
            status="Pending",
            zoho_payment_link_id="PL_API_SUCCEEDED"
        )
        db.session.add(order)
        db.session.commit()

        # Query status API
        response = self.client.get(f'/api/order/status/{order.order_number}')
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(data['status'], 'Paid')
        self.assertEqual(data['payment_status'], 'Paid')

        db.session.refresh(order)
        self.assertEqual(order.status, 'Paid')

if __name__ == '__main__':
    unittest.main()
