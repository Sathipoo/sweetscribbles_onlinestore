import unittest
from app import create_app
from extensions import db
from models.product import Product
from models.order import Order, OrderItem
from flask import session
import uuid

class TestStockManagement(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        # Start database nested transaction so we can rollback
        db.session.begin_nested()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()
        self.app_context.pop()

    def test_stock_policies_applied_only_to_bites_and_choco(self):
        # Create a test bites product with 5 stock
        bites_product = Product(
            name="Test Bites",
            sku=f"TEST-BB-01-{uuid.uuid4().hex[:6]}",
            category="bites",
            sale_price=100.0,
            available_qty=5,
            low_stock_threshold=2
        )
        db.session.add(bites_product)
        db.session.commit()

        # Add more than available stock to cart (should fail/redirect with flash warning)
        with self.client.session_transaction() as sess:
            sess['cart'] = []
            
        # Post to product detail
        response = self.client.post(f'/product/{bites_product.id}', data={'quantity': 10})
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'/product/{bites_product.id}', response.location)

        # Add valid quantity (should succeed)
        response = self.client.post(f'/product/{bites_product.id}', data={'quantity': 3})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/cart', response.location)
        
        # Verify cart content
        with self.client.session_transaction() as sess:
            self.assertEqual(len(sess['cart']), 1)
            self.assertEqual(sess['cart'][0]['product_id'], bites_product.id)
            self.assertEqual(sess['cart'][0]['quantity'], 3)

    def test_custom_gifting_exempt_from_stock_policies(self):
        # Create a gifting product with 0 stock
        gift_product = Product(
            name="Test Gift Box",
            sku=f"TEST-GB-01-{uuid.uuid4().hex[:6]}",
            category="gifting",
            sale_price=1000.0,
            available_qty=0
        )
        db.session.add(gift_product)
        db.session.commit()

        # Adding 10 items to cart should succeed even though available_qty is 0
        response = self.client.post(f'/product/{gift_product.id}', data={'quantity': 10})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/cart', response.location)

    def test_stock_deduction_on_payment_success(self):
        # Create a bites product with 10 stock
        prod = Product(
            name="Stock Bites",
            sku=f"TEST-BB-02-{uuid.uuid4().hex[:6]}",
            category="bites",
            sale_price=50.0,
            available_qty=10
        )
        db.session.add(prod)
        db.session.flush()

        # Create a pending order
        order_num = f"TESTORDER-{uuid.uuid4().hex[:6]}"
        order = Order(
            order_number=order_num,
            total_amount=150.0,
            customer_name="Test Customer",
            customer_email="test@test.com",
            status="Pending"
        )
        db.session.add(order)
        db.session.flush()

        order_item = OrderItem(
            order_id=order.id,
            product_id=prod.id,
            quantity=3,
            price_at_purchase=50.0
        )
        db.session.add(order_item)
        db.session.commit()

        # Perform payment simulation success which triggers deduction
        response = self.client.post(f'/pay/simulate/{order.order_number}', data={'action': 'success'})
        self.assertEqual(response.status_code, 302)

        # Reload product and order
        db.session.refresh(prod)
        db.session.refresh(order)

        # Available qty should be 10 - 3 = 7
        self.assertEqual(prod.available_qty, 7)
        self.assertTrue(order.is_stock_deducted)
        self.assertEqual(order.status, 'Paid')

        # Run payment simulation success again, available qty should STILL be 7 (no double-deductions)
        response = self.client.post(f'/pay/simulate/{order.order_number}', data={'action': 'success'})
        db.session.refresh(prod)
        self.assertEqual(prod.available_qty, 7)

    def test_deactivated_product_inaccessible_and_hidden(self):
        # Create a deactivated product
        deactivated_prod = Product(
            name="Ghost Bite",
            sku=f"TEST-GHOST-{uuid.uuid4().hex[:6]}",
            category="bites",
            sale_price=100.0,
            available_qty=10,
            is_active=False
        )
        db.session.add(deactivated_prod)
        db.session.commit()

        # 1. Product detail page should return 404
        response = self.client.get(f'/product/{deactivated_prod.id}')
        self.assertEqual(response.status_code, 404)

        # 2. Should not appear in home page lists
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Ghost Bite", response.data)

        # 3. Should not appear in collections dynamic loops
        response = self.client.get('/collections')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Ghost Bite", response.data)

if __name__ == '__main__':
    unittest.main()
