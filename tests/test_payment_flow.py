import concurrent.futures
import copy
import http.client
import json
import os
import re
import threading
import types
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import test_checkout as fixture
import checkout
from mollie_payments import MolliePayments, PROFILE, ORIGIN, PaymentUncertain
from payment_flow import PaymentFlow, settings


class Provider:
    """Actual adapter with a synthetic transport, never a network client."""
    def __init__(self, root):
        key = root / 'synthetic-key'; key.write_text('test_SYNTHETICnotReal'); key.chmod(0o600)
        self.calls = []; self.payment = None; self.records = {}; self.fail_post = False; self.fail_get = False
        self.client = MolliePayments(key, 'test', transport=self.transport)

    def transport(self, method, path, body=None, idem=None):
        self.calls.append((method, path, copy.deepcopy(body), idem))
        if path == '/profiles/me': return {'id': PROFILE, 'website': ORIGIN}
        if method == 'POST':
            if self.fail_post: raise PaymentUncertain('SYNTHETIC timeout')
            number = 122 + sum(c[0] == 'POST' for c in self.calls)
            self.payment = dict(id='tr_Synthetic' + str(number), mode='test', profileId=PROFILE,
                status='open', amount=copy.deepcopy(body['amount']), metadata=copy.deepcopy(body['metadata']),
                _links={'checkout': {'href': 'https://www.mollie.com/checkout/SYNTHETIC'}})
            self.records[self.payment['id']] = self.payment
        elif self.fail_get: raise PaymentUncertain('SYNTHETIC GET timeout')
        elif path.rsplit('/', 1)[-1] != self.payment['id']:
            return copy.deepcopy(self.records[path.rsplit('/', 1)[-1]])
        return copy.deepcopy(self.payment)


class PaymentFlowTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.CheckoutTests(); self.f.setUp()
        self.identity = self.f.offer(); self.f.delivered(self.identity)
        self.accepted = self.f.accept(self.identity)
        self.f.store.invoice(self.identity, self.f.session)
        self.flow = PaymentFlow(self.f.ledger)
        self.provider = Provider(self.f.root)

    def tearDown(self): self.f.tearDown()
    def request(self): return self.flow.request(self.accepted['id'], 'test')
    def process(self): return self.flow.process_one(self.provider.client)
    def paid(self):
        self.request(); self.process()
        self.provider.payment['status'] = 'paid'; self.process()

    def test_paid_only_after_independent_get_not_create_or_return(self):
        self.request()
        self.process()
        with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])
        self.provider.payment['status'] = 'paid'
        self.process()
        row = self.flow.require_paid(self.accepted['id'])
        self.assertEqual(row['state'], 'paid')
        self.assertEqual(self.provider.calls[-1][:2], ('GET', '/payments/tr_Synthetic123'))
        self.assertNotIn('customer', self.provider.calls[1][2]['metadata'])
        self.assertIn(self.identity, self.provider.calls[1][2]['redirectUrl'])

    def test_parallel_requests_and_duplicate_webhooks_create_one_payment(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.request(), range(8)))
        self.process()
        for _ in range(12): self.flow.webhook('tr_Synthetic123')
        self.provider.payment['status'] = 'paid'
        self.process()
        self.assertFalse(self.process())
        self.assertEqual(sum(c[0] == 'POST' for c in self.provider.calls), 1)
        self.flow.require_paid(self.accepted['id'])

    def test_uncertain_create_survives_restart_without_second_post(self):
        self.request(); self.provider.fail_post = True; self.process()
        self.assertEqual(self.flow.get(self.accepted['id'])['state'], 'uncertain')
        restarted = PaymentFlow(self.f.ledger); restarted.request(self.accepted['id'], 'test')
        self.assertFalse(restarted.process_one(self.provider.client))
        self.assertEqual(sum(c[0] == 'POST' for c in self.provider.calls), 1)
        with self.assertRaises(ValueError): restarted.require_paid(self.accepted['id'])

    def test_recovery_verifies_existing_payment_without_second_creation(self):
        self.request(); self.process()
        with self.f.ledger.db() as db:
            db.execute("UPDATE payment_orders SET state='uncertain',payment_id=NULL,checkout=NULL")
            db.execute("UPDATE payment_jobs SET state='done'")
        self.flow.request_recovery(self.accepted['id'], 'tr_Synthetic123')
        self.process()
        with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])
        self.provider.payment['status'] = 'paid'; self.process()
        self.flow.require_paid(self.accepted['id'])
        self.assertEqual(sum(c[0] == 'POST' for c in self.provider.calls), 1)
        self.assertTrue(self.flow.get(self.accepted['id'])['checkout'].startswith('https://www.mollie.com/'))

    def test_recovery_cannot_bind_another_orders_payment(self):
        self.request(); self.process()
        with self.f.ledger.db() as db:
            db.execute("UPDATE payment_orders SET state='uncertain',payment_id=NULL")
            db.execute("UPDATE payment_jobs SET state='done'")
        self.provider.payment['metadata']['order_id'] = 'AN-' + 'f' * 32
        self.flow.request_recovery(self.accepted['id'], 'tr_Synthetic123'); self.process()
        self.assertIsNone(self.flow.get(self.accepted['id'])['payment_id'])
        with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])

    def test_crashed_reserved_job_is_reclaimed_but_post_not_repeated(self):
        self.request(); job = self.flow.claim()
        with self.f.ledger.db() as db:
            db.execute("UPDATE payment_orders SET state='reserved'")
            db.execute('UPDATE payment_jobs SET lease=? WHERE id=?', (0, job['id']))
        self.process()
        self.assertEqual(self.flow.get(self.accepted['id'])['state'], 'uncertain')
        self.assertEqual(sum(c[0] == 'POST' for c in self.provider.calls), 0)

    def test_unknown_ids_do_not_trigger_provider_requests(self):
        self.assertFalse(self.flow.webhook('tr_Unknown123'))
        with self.assertRaises(ValueError): self.flow.webhook('../other')
        self.assertFalse(self.process()); self.assertEqual(self.provider.calls, [])

    def test_refund_or_chargeback_revokes_clearance_before_worker_checks(self):
        for field in ('amountRefunded', 'amountChargedBack'):
            with self.subTest(field=field):
                if not self.provider.payment: self.paid()
                self.provider.payment[field] = {'currency': 'EUR', 'value': '0.01'}
                self.flow.webhook('tr_Synthetic123')
                with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])
                self.process()
                self.assertEqual(self.flow.get(self.accepted['id'])['state'], 'held')
                with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])
                self.provider.payment.pop(field)

    def test_amount_profile_brand_currency_and_mode_mismatch_block(self):
        self.request(); self.process()
        original = copy.deepcopy(self.provider.payment)
        for changes in ({'amount': {'currency': 'EUR', 'value': '0.01'}}, {'profileId': 'pfl_OTHER'},
                        {'mode': 'live'}, {'metadata': {'brand': 'kostenfuxx', 'order_id': self.accepted['id']}},
                        {'amount': {'currency': 'USD', 'value': '207.00'}}):
            with self.subTest(changes=changes):
                self.provider.payment = {**original, 'status': 'paid', **changes}
                self.flow.webhook('tr_Synthetic123'); self.process()
                self.assertEqual(self.flow.get(self.accepted['id'])['state'], 'blocked')
                with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])

    def test_authorization_pending_failed_and_expired_never_release(self):
        self.request(); self.process()
        for state in ('authorized', 'pending', 'failed', 'expired', 'canceled'):
            self.provider.payment['status'] = state
            self.flow.webhook('tr_Synthetic123'); self.process()
            with self.subTest(state=state), self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])

    def test_canceled_invoice_blocks_even_previously_paid_order(self):
        self.paid()
        invoice = self.f.store.invoice(self.identity, self.f.session)
        self.f.ledger.cancel(invoice['id'], 'SYNTHETISCHE STORNIERUNG')
        with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])
        self.flow.webhook('tr_Synthetic123'); self.process()
        self.assertEqual(self.flow.get(self.accepted['id'])['state'], 'blocked')

    def test_stale_status_and_get_failure_fail_closed_then_retry_get_only(self):
        self.paid()
        with self.f.ledger.db() as db: db.execute('UPDATE payment_orders SET checked=0')
        with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])
        self.provider.fail_get = True; self.process()
        with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])
        self.provider.fail_get = False
        with self.f.ledger.db() as db: db.execute("UPDATE payment_jobs SET due=0 WHERE state='queued'")
        self.process(); self.flow.require_paid(self.accepted['id'])
        self.assertEqual(sum(c[0] == 'POST' for c in self.provider.calls), 1)

    def test_changed_order_mode_and_unaccepted_order_are_rejected(self):
        self.request()
        with self.assertRaises(ValueError): self.flow.request(self.accepted['id'], 'live')
        other = self.f.offer()
        _, offer = self.f.store.offer(other, self.f.session)
        with self.assertRaises(ValueError): self.flow.request(offer['order']['reference'], 'test')

    def test_retry_only_after_verified_terminal_status_with_new_idempotency(self):
        self.request(); self.process()
        with self.assertRaises(ValueError): self.flow.retry(self.accepted['id'], 'test')
        self.provider.payment['status'] = 'canceled'; self.process()
        self.flow.retry(self.accepted['id'], 'test')
        with self.assertRaises(ValueError): self.flow.retry(self.accepted['id'], 'test')
        self.process()
        posts = [c for c in self.provider.calls if c[0] == 'POST']
        self.assertEqual(len(posts), 2)
        self.assertNotEqual(posts[0][3], posts[1][3])
        self.assertEqual(posts[1][2]['metadata']['payment_attempt'], 2)
        self.provider.payment['status'] = 'paid'; self.process()
        self.flow.require_paid(self.accepted['id'])
        self.flow.webhook('tr_Synthetic123'); self.process(); self.process()
        self.flow.require_paid(self.accepted['id'])
        self.assertEqual(len([c for c in self.provider.calls if c[0] == 'POST']), 2)

    def test_unexpected_prior_payment_blocks_current_paid_attempt(self):
        self.request(); self.process()
        self.provider.payment['status'] = 'expired'; self.process()
        self.flow.retry(self.accepted['id'], 'test'); self.process()
        self.provider.payment['status'] = 'paid'; self.process()
        self.provider.records['tr_Synthetic123']['status'] = 'paid'
        self.flow.webhook('tr_Synthetic123'); self.process()
        with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])
        self.flow.webhook('tr_Synthetic124'); self.process()
        with self.assertRaises(ValueError): self.flow.require_paid(self.accepted['id'])

    def test_http_order_payment_webhook_return_and_customer_isolation(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Base(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self): self.send(404, 'Not found')
            def do_POST(self): self.send(404, 'Not found')
            def send(self, status, body, ctype='text/html; charset=utf-8', extra=None):
                raw = body.encode() if isinstance(body, str) else body
                self.send_response(status); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(raw)))
                for k, v in (extra or {}).items(): self.send_header(k, v)
                self.end_headers()
                if self.command != 'HEAD': self.wfile.write(raw)
        payment_cfg = self.f.root / 'payments.json'
        payment_cfg.write_text(json.dumps(dict(brand='abrechnungs-navi', profile_id=PROFILE, mode='test', enabled=True)))
        env = dict(AN_CHECKOUT_CONFIG=str(self.f.cfg), AN_PAYMENT_CONFIG=str(payment_cfg),
            AN_INVOICE_DIR=str(self.f.root / 'invoices'), AN_INVOICE_ISSUER_FILE=str(self.f.issuer))
        app = types.SimpleNamespace(H=Base, DATA_DIR=str(self.f.root / 'data'), readiness=lambda: [],
                                    page=lambda title, body: '<title>' + title + '</title>' + body)
        with patch.dict(os.environ, env):
            checkout.install(app)
            server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            def request(method, path, data=None, cookie='', origin=ORIGIN):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                conn.request(method, path, urllib.parse.urlencode(data) if data is not None else None,
                             {'Cookie': cookie, 'Origin': origin, 'Content-Type': 'application/x-www-form-urlencoded'})
                response = conn.getresponse(); result = response.read(); headers = dict(response.getheaders()); status = response.status; conn.close()
                return status, headers, result
            try:
                _, headers, body = request('GET', '/bestellen')
                cookie = headers['Set-Cookie'].split(';')[0]
                csrf = re.search(rb'name="csrf" value="([a-f0-9]+)"', body)[1].decode()
                _, headers, _ = request('POST', '/bestellen/angebot', {**self.f.values, 'csrf': csrf}, cookie)
                location = headers['Location']
                _, _, body = request('GET', location, cookie=cookie)
                offer_sha = re.search(rb'name="offer_sha256" value="([a-f0-9]+)"', body)[1].decode()
                for kind in checkout.KINDS: request('GET', location + '/' + kind, cookie=cookie)
                accepted_fields = dict(csrf=csrf, offer_sha256=offer_sha, contract='yes', avv='yes', consumer='yes')
                self.assertEqual(request('POST', location + '/annehmen', accepted_fields, cookie)[0], 303)
                self.assertEqual(request('GET', location + '/zahlung')[0], 400)
                self.assertEqual(request('GET', location + '/zahlung', cookie=cookie)[0], 200)
                self.process()
                order_id = self.provider.payment['metadata']['order_id']
                self.assertFalse(app.payment_clearance({'payment_order_id': order_id}))
                self.assertEqual(request('POST', '/zahlung/webhook', {'id': 'tr_Synthetic123', 'status': 'paid'}, origin='')[0], 400)
                self.assertEqual(request('POST', '/zahlung/webhook', {'id': 'tr_Unknown123'}, origin='')[0], 200)
                self.provider.payment['status'] = 'paid'
                self.assertEqual(request('POST', '/zahlung/webhook', {'id': 'tr_Synthetic123'}, origin='')[0], 200)
                self.assertFalse(app.payment_clearance({'payment_order_id': order_id}))
                self.process()
                self.assertTrue(app.payment_clearance({'payment_order_id': order_id}))
                self.assertTrue(app.payment_clearance({}))
                self.assertIn(b'unabh', request('GET', location + '/zahlung', cookie=cookie)[2])
                self.assertEqual(request('GET', '/zahlung/rueckkehr?auftrag=' + location.rsplit('/',1)[-1])[0], 200)
                self.assertEqual(request('POST', location + '/annehmen', accepted_fields, cookie)[0], 303)
                self.assertEqual(sum(c[0] == 'POST' for c in self.provider.calls), 1)
            finally:
                server.shutdown(); server.server_close(); worker.join()


if __name__ == '__main__': unittest.main(verbosity=2)
