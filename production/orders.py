"""Durable payment coordinator; a timeout never creates a second payment.

HTTP callers must authenticate order ownership before using this service.
No webhook body can mark an order paid: Mollie's retrieved object decides.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from payments import validate_order


class Orders:
    def __init__(self, database):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS orders '
                       '(id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL, '
                       'payment_id TEXT UNIQUE, checkout TEXT, updated REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events '
                       '(id INTEGER PRIMARY KEY, order_id TEXT NOT NULL, event TEXT NOT NULL, at REAL NOT NULL)')
        self.database.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=FULL')
        return db

    def add(self, order):
        validate_order(order)
        if order.get('payment_id'):
            raise ValueError('Neuer Auftrag darf keine Zahlung enthalten')
        payload = json.dumps(order, sort_keys=True, ensure_ascii=False)
        with closing(self.connect()) as db, db:
            db.execute('INSERT INTO orders VALUES (?, ?, ?, NULL, NULL, ?)',
                       (order['id'], payload, 'contracted', time.time()))

    def get(self, order_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if row is None:
            raise ValueError('Auftrag nicht gefunden')
        return dict(row)

    def create_payment(self, order_id, provider):
        # Persist the reservation before any network request. Concurrent callers
        # and process restarts cannot silently issue another payment request.
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            if row is None or row['state'] != 'contracted':
                raise ValueError('Zahlung bereits reserviert oder Auftrag nicht zahlbar')
            db.execute('UPDATE orders SET state=?, updated=? WHERE id=?',
                       ('payment_reserved', time.time(), order_id))
            db.execute('INSERT INTO events(order_id,event,at) VALUES (?,?,?)',
                       (order_id, 'payment_reserved', time.time()))
            order = json.loads(row['payload'])
        try:
            payment = provider.create(order)
        except Exception:
            # Includes interrupted/uncertain provider responses; retain the
            # reservation. Recovery requires a matched provider payment ID.
            raise
        with closing(self.connect()) as db, db:
            db.execute('UPDATE orders SET state=?,payment_id=?,checkout=?,updated=? '
                       'WHERE id=? AND state=?',
                       ('payment_open', payment['id'], payment['_links']['checkout']['href'],
                        time.time(), order_id, 'payment_reserved'))
        return self.get(order_id)

    def reconcile(self, payment_id, provider):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM orders WHERE payment_id=?', (payment_id,)).fetchone()
        if row is None:
            raise ValueError('Zahlung nicht zugeordnet')
        order = {**json.loads(row['payload']), 'payment_id': payment_id}
        paid = provider.reconcile(payment_id, order)
        # Rechecking a previously paid order catches refunds and chargebacks;
        # downloadable artifacts must check this state on every retrieval.
        state = 'paid' if paid else 'payment_unsettled'
        with closing(self.connect()) as db, db:
            db.execute('UPDATE orders SET state=?,updated=? WHERE id=?',
                       (state, time.time(), row['id']))
            db.execute('INSERT INTO events(order_id,event,at) VALUES (?,?,?)',
                       (row['id'], state, time.time()))
        return paid

    def require_paid(self, order_id):
        if self.get(order_id)['state'] != 'paid':
            raise ValueError('Zahlung nicht bestätigt')
