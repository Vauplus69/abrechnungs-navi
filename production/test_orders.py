from pathlib import Path
import tempfile
import unittest
from orders import Orders
from payments import PaymentUncertain
from test_payments import order, payment


class FakeProvider:
    def __init__(self, uncertain=False):
        self.calls = 0
        self.uncertain = uncertain
        self.paid = False

    def create(self, value):
        self.calls += 1
        if self.uncertain:
            raise PaymentUncertain('synthetic timeout')
        return payment('open')

    def reconcile(self, payment_id, value):
        self.calls += 1
        return self.paid


class OrderTests(unittest.TestCase):
    def test_timeout_reservation_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'orders.sqlite'
            store = Orders(path); store.add(order())
            provider = FakeProvider(uncertain=True)
            with self.assertRaises(PaymentUncertain): store.create_payment(order()['id'], provider)
            restarted = Orders(path)
            with self.assertRaises(ValueError): restarted.create_payment(order()['id'], provider)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(restarted.get(order()['id'])['state'], 'payment_reserved')
            with self.assertRaises(ValueError): restarted.require_paid(order()['id'])

    def test_callback_uses_provider_and_refund_blocks_access(self):
        with tempfile.TemporaryDirectory() as d:
            store = Orders(Path(d) / 'orders.sqlite'); store.add(order())
            provider = FakeProvider()
            store.create_payment(order()['id'], provider)
            with self.assertRaises(ValueError): store.reconcile('tr_Unknown', provider)
            self.assertEqual(provider.calls, 1)
            self.assertFalse(store.reconcile(payment()['id'], provider))
            with self.assertRaises(ValueError): store.require_paid(order()['id'])
            provider.paid = True
            self.assertTrue(store.reconcile(payment()['id'], provider))
            store.require_paid(order()['id'])
            provider.paid = False
            self.assertFalse(store.reconcile(payment()['id'], provider))
            with self.assertRaises(ValueError): store.require_paid(order()['id'])

    def test_duplicate_order_cannot_replace_accepted_contract(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            store = Orders(Path(d) / 'orders.sqlite'); store.add(order())
            with self.assertRaises(sqlite3.IntegrityError): store.add({**order(), 'offer_sha256': 'e' * 64})
            import json
            self.assertEqual(json.loads(store.get(order()['id'])['payload'])['offer_sha256'], 'b' * 64)


if __name__ == '__main__': unittest.main()
