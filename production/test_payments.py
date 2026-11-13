import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from payments import MolliePayments, PaymentUncertain, PROFILE, ORIGIN, price, validate_order, validate_payment


def order():
    return dict(id='AN-' + 'a' * 32, apartments=5, houses=2, total_cents=35500,
                contract_accepted=True, avv_accepted=True, consumer_information_delivered=True,
                offer_sha256='b' * 64, avv_sha256='c' * 64,
                consumer_information_sha256='d' * 64)


def payment(status='paid', mode='test'):
    return dict(id='tr_Example123', profileId=PROFILE, mode=mode, status=status,
                metadata={'brand': 'abrechnungs-navi', 'order_id': order()['id']},
                amount={'currency': 'EUR', 'value': '355.00'},
                _links={'checkout': {'href': 'https://www.mollie.com/checkout/example'}})


class Payments(unittest.TestCase):
    def test_group_readable_regular_files_cannot_impersonate_systemd_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); key=root/'mollie-key'; key.write_text('test_SYNTHETIC'); key.chmod(0o440)
            with self.assertRaises(ValueError): MolliePayments(key,'test')
            with self.assertRaises(ValueError): MolliePayments(key,'test',credential_directory=root)
            key.chmod(0o600)
            MolliePayments(key,'test')
    def test_isolated_api_test_cannot_remove_live_webhook(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); key = root / 'key'
            key.write_text('live_SYNTHETIC'); key.chmod(0o600)
            with self.assertRaises(ValueError):
                MolliePayments(key, 'live', True, test_without_webhook=True)
            calls = []
            def api(method, path, body=None, idem=None):
                calls.append(body)
                return {'id': PROFILE, 'website': ORIGIN} if path == '/profiles/me' else payment('open')
            key.write_text('test_SYNTHETIC')
            client = MolliePayments(key, 'test', transport=api, test_without_webhook=True)
            client.verify_profile(); client.create(order())
            self.assertNotIn('webhookUrl', calls[-1])
            self.assertTrue(calls[-1]['description'].startswith('TEST'))

    def test_old_payment_attempt_cannot_settle_new_attempt(self):
        p = payment(); p['metadata']['payment_attempt'] = 1
        with self.assertRaises(ValueError):
            validate_payment(p, {**order(), 'payment_id': p['id'], 'payment_attempt': 2}, 'test')

    def test_mode_bound_advanced_test_token_has_no_testmode_override(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); key=root/'key'; key.write_text('access_SYNTHETIC'); key.chmod(0o600)
            proof=root/'proof'; proof.write_text(json.dumps(dict(brand='abrechnungs-navi', profile_id=PROFILE,
                mode='test', permissions=['payments.read','payments.write']))); proof.chmod(0o600)
            calls=[]
            def api(method,path,body=None,idem=None):
                calls.append(body)
                return {'_embedded':{'payments':[]}} if method=='GET' else payment('open')
            client=MolliePayments(key,'test',transport=api,binding_path=proof)
            client.verify_profile(); client.create(order())
            self.assertEqual(calls[-1]['profileId'],PROFILE)
            self.assertNotIn('testmode',calls[-1])
    def test_scoped_live_token_requires_binding_and_completed_review(self):
        calls = []
        def api(method, path, body=None, idem=None):
            calls.append((method, path, body))
            if method == 'GET': return {'_embedded': {'payments': []}}
            return payment('open', 'live')
        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / 'key'; key.write_text('access_SYNTHETIC'); key.chmod(0o600)
            proof = Path(d) / 'binding'
            binding = dict(brand='abrechnungs-navi', profile_id=PROFILE, mode='live',
                           permissions=['payments.read', 'payments.write'])
            proof.write_text(json.dumps(binding)); proof.chmod(0o600)
            with self.assertRaises(ValueError): MolliePayments(key, 'live', True, api)
            c = MolliePayments(key, 'live', True, api, proof)
            with self.assertRaises(ValueError): c.verify_profile()
            self.assertEqual(calls, [])
            binding['website_review_complete'] = True
            proof.write_text(json.dumps(binding))
            c = MolliePayments(key, 'live', True, api, proof)
            c.verify_profile(); c.create(order())
            self.assertEqual(calls[-1][2]['profileId'], PROFILE)
            self.assertNotIn('testmode', calls[-1][2])
            binding['profile_id'] = 'other'
            proof.write_text(json.dumps(binding))
            with self.assertRaises(ValueError): MolliePayments(key, 'live', True, api, proof)

    def test_price_is_computed_and_tampering_rejected(self):
        self.assertEqual(price(5, 2), 35500)
        for changes in ({'total_cents': 1}, {'apartments': True}, {'houses': 6},
                        {'apartments': '5'}, {'apartments': 201}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_order({**order(), **changes})

    def test_contract_versions_and_consents_are_required(self):
        for field in ('contract_accepted', 'avv_accepted', 'consumer_information_delivered',
                      'offer_sha256', 'avv_sha256', 'consumer_information_sha256'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_order({**order(), field: False})

    def test_paid_only_from_matching_provider_object(self):
        o = {**order(), 'payment_id': 'tr_Example123'}
        self.assertTrue(validate_payment(payment(), o, 'test'))
        for status in ('open', 'pending', 'authorized', 'canceled', 'expired', 'failed'):
            self.assertFalse(validate_payment(payment(status), o, 'test'))

    def test_wrong_brand_id_mode_amount_and_profile_rejected(self):
        variants = [{'mode': 'live'}, {'id': 'tr_Other'}, {'profileId': 'other'},
                    {'metadata': {'brand': 'kostenfuxx', 'order_id': order()['id']}},
                    {'metadata': {'brand': 'abrechnungs-navi', 'order_id': 'AN-other'}},
                    {'amount': {'currency': 'USD', 'value': '355.00'}},
                    {'amount': {'currency': 'EUR', 'value': '3.55'}},
                    {'amount': {'currency': 'EUR', 'value': '355.000'}},
                    {'amount': {'currency': 'EUR', 'value': 'NaN'}}]
        for change in variants:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_payment({**payment(), **change}, {**order(), 'payment_id': 'tr_Example123'}, 'test')

    def test_refund_and_chargeback_stop_fulfilment(self):
        for field in ('amountRefunded', 'amountChargedBack'):
            p = {**payment(), field: {'currency': 'EUR', 'value': '0.01'}}
            self.assertFalse(validate_payment(p, {**order(), 'payment_id': p['id']}, 'test'))

    def client(self, root, transport, mode='test', release=False):
        key = root / ('key-' + mode)
        key.write_text(mode + '_SYNTHETICnotARealCredential123')
        key.chmod(0o600)
        return MolliePayments(key, mode, release, transport)

    def test_live_mode_requires_release_and_matching_key(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(ValueError): self.client(root, lambda *a: None, 'live')
            key = root / 'test'; key.write_text('test_SYNTHETIC'); key.chmod(0o600)
            with self.assertRaises(ValueError): MolliePayments(key, 'live', True)
            key.chmod(0o644)
            with self.assertRaises(ValueError): MolliePayments(key, 'test')
            link = root / 'link'; link.symlink_to(key)
            with self.assertRaises(ValueError): MolliePayments(link, 'test')

    def test_profile_checked_before_payment_and_idempotency_stable(self):
        calls = []
        def api(method, path, body=None, idem=None):
            calls.append((method, path, copy.deepcopy(body), idem))
            return {'id': PROFILE, 'website': ORIGIN} if path == '/profiles/me' else payment('open')
        with tempfile.TemporaryDirectory() as d:
            c = self.client(Path(d), api)
            with self.assertRaises(ValueError): c.create(order())
            c.verify_profile(); c.create(order()); c.create(order())
            self.assertEqual(calls[-1][-1], calls[-2][-1])
            self.assertNotIn('name', calls[-1][2]['metadata'])
            with self.assertRaises(ValueError): c.create({**order(), 'payment_id': 'tr_Example123'})

    def test_callback_retrieves_payment_instead_of_trusting_form(self):
        calls = []
        def api(method, path, *args):
            calls.append((method, path))
            return {'id': PROFILE, 'website': ORIGIN} if path == '/profiles/me' else payment()
        with tempfile.TemporaryDirectory() as d:
            c = self.client(Path(d), api); c.verify_profile()
            self.assertTrue(c.reconcile('tr_Example123', {**order(), 'payment_id': 'tr_Example123'}))
            self.assertEqual(calls[-1], ('GET', '/payments/tr_Example123'))
            before = len(calls)
            with self.assertRaises(ValueError): c.reconcile('tr_Other', {**order(), 'payment_id': 'tr_Example123'})
            self.assertEqual(len(calls), before)

    def test_external_checkout_and_unverified_live_profile_block(self):
        def api(method, path, *args):
            if path == '/profiles/me': return {'id': PROFILE, 'website': ORIGIN, 'status': 'unverified'}
            p = payment('open'); p['_links']['checkout']['href'] = 'https://mollie.com.evil.invalid/checkout'
            return p
        with tempfile.TemporaryDirectory() as d:
            c = self.client(Path(d), api); c.verify_profile()
            with self.assertRaises(PaymentUncertain): c.create(order())
            live = self.client(Path(d), api, 'live', True)
            with self.assertRaises(ValueError): live.verify_profile()


if __name__ == '__main__':
    unittest.main(verbosity=2)
