import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.parse
from unittest.mock import patch

import sys
APP_ROOT = Path(__file__).resolve().parents[1] / 'app'
if not APP_ROOT.exists():
    APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))
import customer_lifecycle as life


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.saved_env = dict(os.environ)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ['AN_DATA_DIR'] = str(self.root)
        os.environ['AN_OPERATOR_FILE'] = str(self.root / 'operator.json')
        os.environ['AN_TOTP_FILE'] = str(self.root / 'otp')
        (self.root / 'otp').write_text('TEST')
        spec = importlib.util.spec_from_file_location('portal_test', APP_ROOT / 'upload_app.py')
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)
        self.app.install(self.app)
        self.token = 'A' * 32
        self.original = {'workflow': self.app.VERSION, 'name': 'SYNTHETIC NAME',
                         'email': 'synthetic@example.invalid', 'order': 'SYNTHETIC-ORDER',
                         'expires': 4000000000, 'access_hash': 'old-code', 'created': 1}
        self.app.save({self.token: copy.deepcopy(self.original)})
        self.app.save_anfragen([{'name': self.original['name'], 'email': self.original['email'],
                                'nachricht': 'PRIVATE TEXT', 'zeit': 4000000000}])

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.clear()
        os.environ.update(self.saved_env)

    def request(self, action='request_deletion'):
        db = self.app.load()
        db[self.token] = life.request(db[self.token], action, now=100)
        self.app.save(db)
        return db[self.token]

    def handler(self, path, fields=None, auth=True, origin='https://abrechnungs-navi.de'):
        h = object.__new__(self.app.H)
        body = urllib.parse.urlencode(fields or {}).encode()
        h.path = path
        h.headers = {'Origin': origin, 'Content-Length': str(len(body))}
        h.rfile = io.BytesIO(body)
        h.admin_auth = lambda: auth
        h.send = lambda code, body, *args, **kw: (code, body)
        return h

    def test_reference_is_random_stable_and_no_access_code(self):
        row = self.request('close')
        self.assertRegex(row['lifecycle']['reference'], r'^AN-[A-F0-9]{16}$')
        upgraded = life.request(row, 'request_deletion')
        self.assertEqual(row['lifecycle']['reference'], upgraded['lifecycle']['reference'])
        self.assertNotIn('access_hash', upgraded)
        self.assertEqual(life.request(upgraded, 'close')['lifecycle']['state'], 'deletion_requested')

    def test_hidden_admin_and_auxiliary_identity(self):
        self.request()
        page = self.app.admin_page(self.app.load())
        for value in ('SYNTHETIC NAME', 'synthetic@example.invalid', 'PRIVATE TEXT', 'SYNTHETIC-ORDER'):
            self.assertNotIn(value, page)
        self.assertIn('Loeschwunsch in Pruefung', page)

    def test_closed_customer_cannot_authenticate_download_or_upload(self):
        self.request('close')
        h = self.handler('/hochladen/' + self.token)
        self.assertIsNone(h.customer(self.token))
        self.assertEqual(h.do_GET()[0], 404)
        h.path = '/verwaltung/datei/' + self.token + '/private.pdf'
        self.assertEqual(h.do_GET()[0], 404)
        h.path = '/verwaltung/ergebnis/' + self.token
        self.assertEqual(h.do_PUT()[0], 403)

    def test_customer_download_rechecks_closure_after_session_check(self):
        h = self.handler('/hochladen/' + self.token + '/datei/private.pdf')
        def close_during_session_check(*args):
            self.request('close')
            return {'role': 'customer'}
        h.session = close_during_session_check
        self.assertEqual(h.do_GET()[0], 404)

    def test_closed_cannot_be_reopened_by_rotating_code(self):
        self.request('close')
        h = self.handler('/verwaltung/code', {'token': self.token})
        self.assertEqual(h.do_POST()[0], 409)

    def test_post_requires_origin_and_admin(self):
        h = self.handler('/verwaltung/datenschutz/schliessen', {'token': self.token, 'confirm': 'yes'}, origin='https://evil.invalid')
        self.assertEqual(h.do_POST()[0], 403)
        h = self.handler('/verwaltung/datenschutz/schliessen', {'token': self.token, 'confirm': 'yes'}, auth=False)
        self.assertIsNone(h.do_POST())
        self.assertNotIn('lifecycle', self.app.load()[self.token])

    def test_post_closure_and_erasure_upgrade(self):
        for endpoint in ('schliessen', 'anfordern'):
            h = self.handler('/verwaltung/datenschutz/' + endpoint, {'token': self.token, 'confirm': 'yes'})
            self.assertEqual(h.do_POST()[0], 200)
        self.assertEqual(self.app.load()[self.token]['lifecycle']['state'], 'deletion_requested')

    def test_cleanup_keeps_pending_provider_references(self):
        self.original['expires'] = 1
        self.app.save({self.token: self.original})
        self.request()
        self.app.cleanup()
        self.assertIn(self.token, self.app.load())

    def test_no_purge_without_all_reviews(self):
        self.request()
        with self.assertRaises(ValueError):
            life.purge_local(self.app, self.token, {}, 'PR-SYNTHETIC-123')
        self.assertIn('name', self.app.load()[self.token])

    def test_wrong_confirmation_never_deletes(self):
        self.request()
        h = self.handler('/verwaltung/datenschutz/loeschen', {'token': self.token, 'confirm': 'wrong'})
        self.assertEqual(h.do_POST()[0], 400)
        self.assertIn('name', self.app.load()[self.token])

    def test_local_purge_removes_files_and_matching_contact_rows(self):
        self.request()
        folder = Path(self.app.customer_dir(self.token))
        folder.mkdir(parents=True)
        (folder / 'private.pdf').write_text('SYNTHETIC')
        withdrawals = self.root / 'widerrufe.json'
        withdrawals.write_text(json.dumps([{'email': self.original['email'], 'name': self.original['name']}]))
        out = life.purge_local(self.app, self.token, dict.fromkeys(life.CHECKS, True), 'PR-SYNTHETIC-123', now=200)
        self.assertEqual(out['state'], 'local_deleted')
        self.assertFalse(folder.exists())
        self.assertEqual(self.app.load_anfragen(), [])
        self.assertEqual(json.loads(withdrawals.read_text()), [])
        self.assertNotIn('name', self.app.load()[self.token])
        self.assertNotIn('synthetic@example.invalid', (self.root / 'kunden.json').read_text())
        self.assertNotIn(self.token, (self.root / 'privacy-restore-blocks.jsonl').read_text())
        self.app.admin_page(self.app.load())

    def test_purge_file_failure_keeps_blocked_metadata(self):
        self.request()
        Path(self.app.customer_dir(self.token)).mkdir(parents=True)
        with patch('customer_lifecycle.shutil.rmtree', side_effect=OSError('test')):
            with self.assertRaises(OSError):
                life.purge_local(self.app, self.token, dict.fromkeys(life.CHECKS, True), 'PR-SYNTHETIC-123')
        self.assertEqual(self.app.load()[self.token]['lifecycle']['state'], 'deletion_requested')

    def test_shared_email_blocks_unreviewed_cross_order_erasure(self):
        self.request()
        db = self.app.load()
        db['B' * 32] = self.original
        self.app.save(db)
        with self.assertRaises(ValueError):
            life.purge_local(self.app, self.token, dict.fromkeys(life.CHECKS, True), 'PR-SYNTHETIC-123')

    def test_symlink_cannot_erase_another_directory(self):
        self.request()
        folder = Path(self.app.customer_dir(self.token))
        folder.parent.mkdir(parents=True)
        target = self.root / 'unrelated'
        target.mkdir()
        folder.symlink_to(target)
        with self.assertRaises(ValueError):
            life.purge_local(self.app, self.token, dict.fromkeys(life.CHECKS, True), 'PR-SYNTHETIC-123')
        self.assertTrue(target.exists())


if __name__ == '__main__':
    unittest.main()
