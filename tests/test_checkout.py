import concurrent.futures
from datetime import timedelta
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
import urllib.parse
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import checkout
import invoicing
from pypdf import PdfReader


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.issuer = self.root / 'issuer.json'
        self.issuer.write_text(json.dumps(dict(name='MUSTER – TESTAUSSTELLER', address='Testweg 1',
            city='12345 Teststadt', email='test@example.invalid', tax_mode='kleinunternehmer', tax_id='SYNTHETIC-ONLY')))
        self.cfg = self.root / 'checkout.json'
        self.docs = {}
        for kind in checkout.KINDS:
            path = self.root / (kind + '.txt')
            path.write_text('SYNTHETISCHE TESTUNTERLAGE – kein echter Vertrag: ' + kind)
            self.docs[kind] = dict(path=str(path), sha256=checkout.digest(path.read_bytes()), version='TEST-1', mime='text/plain; charset=utf-8')
        self.config = dict(brand='abrechnungs-navi', online_contract_approved=True, enabled=True, documents=self.docs)
        self.save_config()
        self.ledger = invoicing.Ledger(self.root / 'invoices', self.issuer)
        self.store = checkout.Checkout(self.ledger, self.cfg)
        self.session = 'a' * 43
        self.values = dict(customer='SYNTHETISCHER TESTKUNDE', address='Testweg 2', city='12345 Teststadt',
                           email='synthetic@example.invalid', property_address='MUSTEROBJEKT, Testweg 3',
                           country='DE', apartments='3', houses='1', year='2025',
                           service_date=(invoicing.today() + timedelta(days=30)).isoformat())

    def save_config(self): self.cfg.write_text(json.dumps(self.config))
    def tearDown(self): self.tmp.cleanup()
    def offer(self): return self.store.create_offer(self.values, self.session)

    def delivered(self, identity):
        for kind in checkout.KINDS: self.store.mark_delivered(identity, self.session, kind)

    def accept(self, identity, **overrides):
        row, _ = self.store.offer(identity, self.session)
        return self.store.accept(identity, self.session, row['sha256'], dict(contract=True, avv=True, consumer=True, **overrides))

    def test_price_and_invoice_derive_from_server_not_submitted_total(self):
        identity = self.store.create_offer({**self.values, 'total_cents': '1', 'apartments': '5', 'houses': '2'}, self.session)
        _, payload = self.store.offer(identity, self.session)
        self.assertEqual(payload['order']['total_cents'], 35500)
        self.assertEqual(self.ledger.listing(), [])
        self.delivered(identity); accepted = self.accept(identity)
        invoice = self.store.invoice(identity, self.session)
        body = '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(invoice['pdf'])).pages)
        self.assertIn('355,00', body)
        self.assertIn(accepted['id'], body)
        self.assertEqual(accepted['total_cents'], 35500)

    def test_contract_acceptance_requires_each_explicit_check_and_download(self):
        identity = self.offer(); row, _ = self.store.offer(identity, self.session)
        with self.assertRaisesRegex(ValueError, 'herunterladen'): self.accept(identity)
        self.delivered(identity)
        for missing in ('contract', 'avv', 'consumer'):
            checks = dict(contract=True, avv=True, consumer=True); checks[missing] = False
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                self.store.accept(identity, self.session, row['sha256'], checks)
        with self.assertRaises(ValueError): self.accept(identity, early_start=True)
        self.assertEqual(self.ledger.listing(), [])

    def test_version_change_blocks_acceptance_but_keeps_original_snapshot(self):
        identity = self.offer(); self.delivered(identity)
        old = self.store.document(identity, self.session, 'avv')['raw']
        path = Path(self.docs['avv']['path']); path.write_text('TEST VERSION 2')
        self.docs['avv']['sha256'] = checkout.digest(path.read_bytes()); self.docs['avv']['version'] = 'TEST-2'
        self.save_config()
        with self.assertRaisesRegex(ValueError, 'aktualisiert'): self.accept(identity)
        self.assertEqual(self.store.document(identity, self.session, 'avv')['raw'], old)

    def test_wrong_session_offer_hash_and_expired_offer_rejected(self):
        identity = self.offer(); self.delivered(identity)
        with self.assertRaises(ValueError): self.store.offer(identity, 'b' * 43)
        with self.assertRaises(ValueError): self.store.accept(identity, self.session, '0' * 64, dict(contract=True, avv=True, consumer=True))
        with patch.object(checkout.time, 'time', return_value=10**12):
            with self.assertRaisesRegex(ValueError, 'abgelaufen'): self.accept(identity)

    def test_no_invoice_before_acceptance_and_same_invoice_after_restart(self):
        identity = self.offer()
        with self.assertRaises(ValueError): self.store.invoice(identity, self.session)
        self.delivered(identity); first = self.accept(identity)
        invoice = self.store.invoice(identity, self.session)
        restarted = checkout.Checkout(invoicing.Ledger(self.root / 'invoices', self.issuer), self.cfg)
        self.assertEqual(restarted.invoice(identity, self.session)['id'], invoice['id'])
        self.assertEqual(self.accept(identity), first)
        self.assertEqual(len(self.ledger.listing()), 1)

    def test_crash_between_invoice_and_link_does_not_allocate_another_number(self):
        identity = self.offer(); self.delivered(identity); self.accept(identity)
        _, payload = self.store.offer(identity, self.session)
        invoice_id = self.ledger._write({'order': payload['order'], 'issuer': payload['issuer']}, draft_id=identity)
        self.assertEqual(self.store.invoice(identity, self.session)['id'], invoice_id)
        self.assertEqual(len(self.ledger.listing()), 1)

    def test_parallel_clicks_create_one_acceptance_and_one_invoice(self):
        identity = self.offer(); self.delivered(identity)
        def submit(_):
            accepted = self.accept(identity)
            return accepted['id'], self.store.invoice(identity, self.session)['id']
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(8)))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len(self.ledger.listing()), 1)

    def test_packet_contains_exact_accepted_documents_and_invoice(self):
        identity = self.offer(); self.delivered(identity); accepted = self.accept(identity)
        with zipfile.ZipFile(io.BytesIO(self.store.packet(identity, self.session))) as packet:
            self.assertIn('Auftragsbestaetigung.txt', packet.namelist())
            for kind in checkout.KINDS:
                self.assertEqual(packet.read(kind + '.txt'), Path(self.docs[kind]['path']).read_bytes())
            self.assertIn(accepted['id'], packet.read('Auftragsbestaetigung.txt').decode())
            self.assertEqual(packet.read('Vorausrechnung.pdf'), self.store.invoice(identity, self.session)['pdf'])

    def test_invalid_input_and_missing_issuer_identifier_stop_before_offer(self):
        for change in ({'apartments': '0'}, {'houses': '4'}, {'email': 'bad'}, {'country': 'US'},
                       {'service_date': invoicing.today().isoformat()}, {'customer': 'A\nB'}, {'year': '9999'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.store.create_offer({**self.values, **change}, self.session)
        company = json.loads(self.issuer.read_text()); company['tax_id'] = ''; self.issuer.write_text(json.dumps(company))
        with self.assertRaisesRegex(ValueError, '250'):
            self.store.create_offer({**self.values, 'apartments': '6'}, self.session)

    def test_unapproved_documents_fail_closed_and_accepted_records_are_immutable(self):
        self.config['online_contract_approved'] = False; self.save_config()
        with self.assertRaises(ValueError): self.offer()
        self.config['online_contract_approved'] = True; self.save_config()
        identity = self.offer(); self.delivered(identity); self.accept(identity)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.db() as db: db.execute('DELETE FROM checkout_acceptances WHERE offer_id=?', (identity,))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.ledger.db() as db: db.execute('UPDATE checkout_offers SET sha256=? WHERE id=?', ('0' * 64, identity))

    def test_http_form_to_packet_and_security_boundaries(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Base(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self): return self.send(404, 'not found')
            def do_POST(self): return self.send(404, 'not found')
            def send(self, status, body, ctype='text/html; charset=utf-8', extra=None):
                raw = body.encode() if isinstance(body, str) else body
                self.send_response(status); self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(raw))); self.send_header('Cache-Control', 'no-store')
                for k, v in (extra or {}).items(): self.send_header(k, v)
                self.end_headers()
                if self.command != 'HEAD': self.wfile.write(raw)
        app = types.SimpleNamespace(H=Base, DATA_DIR=str(self.root / 'data'), readiness=lambda: [],
                                    page=lambda title, body: '<!doctype html><html lang="de"><title>' + title + '</title>' + body + '</html>')
        env = dict(AN_CHECKOUT_CONFIG=str(self.cfg), AN_INVOICE_DIR=str(self.root / 'invoices'), AN_INVOICE_ISSUER_FILE=str(self.issuer))
        with patch.dict(os.environ, env):
            checkout.install(app)
            server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            def request(method, path, values=None, cookie='', origin='https://abrechnungs-navi.de'):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                data = urllib.parse.urlencode(values) if values is not None else None
                connection.request(method, path, data, {'Cookie': cookie, 'Origin': origin, 'Content-Type': 'application/x-www-form-urlencoded'})
                response = connection.getresponse(); raw = response.read(); headers = dict(response.getheaders()); status = response.status; connection.close()
                return status, headers, raw
            try:
                status, headers, body = request('GET', '/bestellen')
                self.assertEqual(status, 200)
                self.assertIn('HttpOnly', headers['Set-Cookie']); self.assertIn('Secure', headers['Set-Cookie'])
                cookie = headers['Set-Cookie'].split(';')[0]
                csrf = re.search(rb'name="csrf" value="([a-f0-9]+)"', body)[1].decode()
                values = {**self.values, 'csrf': csrf}
                self.assertEqual(request('POST', '/bestellen/angebot', values, cookie, origin='https://evil.invalid')[0], 403)
                self.assertEqual(request('POST', '/bestellen/angebot', {**values, 'csrf': 'wrong'}, cookie)[0], 403)
                status, headers, _ = request('POST', '/bestellen/angebot', values, cookie)
                self.assertEqual(status, 303); location = headers['Location']
                self.assertEqual(request('GET', location)[0], 400)
                status, _, body = request('GET', location, cookie=cookie)
                self.assertEqual(status, 200)
                self.assertIn(b'Zahlungspflichtig bestellen', body)
                offer_sha = re.search(rb'name="offer_sha256" value="([a-f0-9]+)"', body)[1].decode()
                accept = dict(csrf=csrf, offer_sha256=offer_sha, contract='yes', avv='yes', consumer='yes')
                self.assertEqual(request('POST', location + '/annehmen', accept, cookie)[0], 400)
                for kind in checkout.KINDS:
                    self.assertEqual(request('HEAD', location + '/' + kind, cookie=cookie)[0], 200)
                self.assertEqual(request('POST', location + '/annehmen', accept, cookie)[0], 400)
                for kind in checkout.KINDS:
                    self.assertEqual(request('GET', location + '/' + kind, cookie=cookie)[0], 200)
                for _ in range(2): self.assertEqual(request('POST', location + '/annehmen', accept, cookie)[0], 303)
                self.assertEqual(len(self.ledger.listing()), 1)
                status, _, raw = request('GET', location + '/paket', cookie=cookie)
                self.assertEqual(status, 200)
                with zipfile.ZipFile(io.BytesIO(raw)) as packet: self.assertIn('Vorausrechnung.pdf', packet.namelist())
                self.config['enabled'] = False; self.save_config()
                self.assertEqual(request('GET', '/bestellen')[0], 503)
                self.assertEqual(request('GET', location + '/paket', cookie=cookie)[0], 200)
            finally:
                server.shutdown(); server.server_close(); worker.join()


if __name__ == '__main__': unittest.main(verbosity=2)
