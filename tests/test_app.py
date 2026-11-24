import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
os.environ['SECRET_KEY'] = 'test-only-secret-key-01234567890123456789'
os.environ['DATABASE_URL'] = 'sqlite:///' + path
os.environ['COOKIE_SECURE'] = '0'
from app import app, db, User, Product, Order
from werkzeug.security import generate_password_hash


class AppTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        with app.app_context():
            db.drop_all(); db.create_all()
            db.session.add(User(username='admin', password_hash=generate_password_hash('supersecurepassword'), role='admin'))
            db.session.add(Product(name='Candle', price=100, stock=10))
            db.session.commit()

    def token(self):
        with self.client.session_transaction() as s:
            if '_csrf' not in s: s['_csrf'] = 'test-token'
        return 'test-token'

    def login(self):
        return self.client.post('/login', data={'_csrf': self.token(), 'username': 'admin', 'password': 'supersecurepassword'})

    def test_csrf_blocks_post(self):
        self.assertEqual(self.client.post('/login', data={'username': 'admin'}).status_code, 400)

    def test_full_manual_payment_flow(self):
        self.login()
        r = self.client.post('/create-order', data={'_csrf': self.token(), 'customer': 'Customer', 'product_id[]': '1', 'qty[]': '2', 'discount': '0', 'tax_rate': '0'})
        self.assertEqual(r.status_code, 302)
        with app.app_context():
            o = Order.query.first(); token = o.public_token; oid = o.id
        self.assertEqual(self.client.get('/pay/'+token).status_code, 200)
        self.client.post('/pay/'+token+'/report', data={'_csrf': self.token(), 'payment_ref': '123456789012'})
        with app.app_context(): self.assertEqual(db.session.get(Order, oid).status, 'PAYMENT_REPORTED')
        self.client.post('/orders/'+str(oid)+'/status', data={'_csrf': self.token(), 'action': 'confirm', 'verified': 'yes'})
        with app.app_context(): self.assertEqual(db.session.get(Order, oid).status, 'PAID')
        self.assertEqual(self.client.get('/invoice/'+token+'.pdf').status_code, 200)

    def test_unsigned_webhook_rejected(self):
        self.assertEqual(self.client.post('/webhooks/cashfree', json={'data': {}}).status_code, 401)


if __name__ == '__main__': unittest.main()
