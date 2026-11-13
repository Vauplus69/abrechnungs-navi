"""Buyer confirmation, immutable invoice delivery and separate document OTP."""
import io
import json
from pathlib import Path
import re
import time
import unittest
import zipfile
from unittest.mock import patch

import test_checkout as fixture
from automation_core import Automation
from notice_agent import otp


class BuyerNotices(unittest.TestCase):
    def setUp(self):
        self.f=fixture.CheckoutTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.offer=self.f.offer();self.f.delivered(self.offer);self.accepted=self.f.accept(self.offer)
        self.identity=self.accepted['id'];self.buyer=self.f.store.customer_notices
        cfg=self.f.root/'automation.json'
        cfg.write_text(json.dumps(dict(brand='abrechnungs-navi',region='eu1',enabled=True,
            **{k:self.accepted[k] for k in ('avv_sha256','terms_sha256','consumer_information_sha256')})))
        self.auto=Automation(self.f.ledger,self.f.root/'data',cfg,Path(__file__).resolve().parents[1]/'abrechnung/rechner.py',operator_ready=lambda:True)

    def records(self,event=None):
        with self.f.ledger.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM notification_events'+(' WHERE event=?' if event else ''),(event,) if event else ())]

    def drain(self):
        sent=[]
        for _ in range(10):
            if not self.auto.notices.deliver_one(self.auto,sent.append):break
        return sent

    def test_acceptance_queues_once_without_payment_or_portal(self):
        self.f.accept(self.offer)
        self.assertEqual(len(self.records('order_confirmation')),1)
        sent=self.drain();self.assertEqual(len(sent),1)
        self.assertIn('/dokumente/vertrag',sent[0]['text'])
        self.assertIn('noch keinen Zahlungseingang',sent[0]['text'])
        self.assertEqual(sent[0]['to'],'synthetic@example.invalid')
        self.assertNotIn('MUSTEROBJEKT',sent[0]['text'])
        self.assertEqual(self.drain(),[])

    def test_issued_invoice_is_bound_once_and_delivered_unchanged(self):
        invoice=self.f.store.invoice(self.offer,self.f.session)
        second=self.f.store.invoice(self.offer,self.f.session)
        self.assertEqual(invoice['id'],second['id'])
        records=self.records('invoice_available');self.assertEqual(len(records),1)
        disposition,ctx=self.auto.notice_context(records[0]);self.assertEqual(disposition,'send')
        self.assertEqual(ctx['invoice_number'],invoice['number'])
        self.assertIn('/dokumente/rechnung',ctx['invoice_url'])
        self.buyer.request_code(self.offer)
        with self.f.ledger.db() as db:c=db.execute('SELECT * FROM checkout_mail_challenges').fetchone()
        token=self.buyer.authenticate(self.offer,otp(self.buyer.secret(),self.identity,c['nonce']))
        data=self.buyer.authorize(self.offer,token)
        actual,_=self.buyer.invoice(data);self.assertEqual(actual['pdf'],invoice['pdf'])
        with zipfile.ZipFile(io.BytesIO(self.buyer.packet(data))) as z:
            self.assertIn('Auftragsbestaetigung.txt',z.namelist())
            for kind in ('terms','avv','consumer'):
                self.assertEqual(z.read(kind+'.txt'),self.f.docs[kind]['path'] and Path(self.f.docs[kind]['path']).read_bytes())

    def test_new_browser_requires_separate_one_use_code_and_limits_requests(self):
        with self.assertRaises(ValueError):self.buyer.authorize(self.offer,'')
        self.assertTrue(self.buyer.request_code(self.offer));self.assertFalse(self.buyer.request_code(self.offer))
        notice=self.records('access_code')[0]
        disposition,ctx=self.auto.notice_context(notice);self.assertEqual(disposition,'send')
        mail=self.auto.notices.render(notice,ctx,self.auto.notification_secret(notice))
        self.assertNotIn('https://',mail['text'])
        code=re.search(r'\b\d{6}\b',mail['text'])[0]
        token=self.buyer.authenticate(self.offer,code)
        with self.assertRaises(ValueError):self.buyer.authenticate(self.offer,code)
        self.assertEqual(self.auto.notice_context(notice)[0],'obsolete')
        self.assertEqual(self.buyer.authorize(self.offer,token)['accepted']['id'],self.identity)
        with self.f.ledger.db() as db:
            self.assertNotIn(token,db.execute('SELECT id FROM checkout_mail_sessions').fetchone()[0])
            db.execute('UPDATE checkout_mail_sessions SET expires=0')
        with self.assertRaises(ValueError):self.buyer.authorize(self.offer,token)

    def test_wrong_codes_lock_and_new_challenge_invalidates_old_code(self):
        self.buyer.request_code(self.offer)
        with self.f.ledger.db() as db:c=db.execute('SELECT * FROM checkout_mail_challenges').fetchone()
        good=otp(self.buyer.secret(),self.identity,c['nonce']);wrong='000000' if good!='000000' else '111111'
        for _ in range(5):
            with self.assertRaises(ValueError):self.buyer.authenticate(self.offer,wrong)
        with self.assertRaises(ValueError):self.buyer.authenticate(self.offer,good)
        with patch('checkout_notices.time.time',return_value=time.time()+61):self.assertTrue(self.buyer.request_code(self.offer))
        self.assertEqual(self.auto.notice_context(self.records('access_code')[0])[0],'obsolete')

    def test_code_cannot_access_other_order_or_canceled_invoice(self):
        invoice=self.f.store.invoice(self.offer,self.f.session)
        self.buyer.request_code(self.offer)
        with self.f.ledger.db() as db:c=db.execute('SELECT * FROM checkout_mail_challenges').fetchone()
        token=self.buyer.authenticate(self.offer,otp(self.buyer.secret(),self.identity,c['nonce']))
        other=self.f.offer();self.f.delivered(other);self.f.accept(other)
        with self.assertRaises(ValueError):self.buyer.authorize(other,token)
        self.f.ledger.cancel(invoice['id'],'SYNTHETIC TEST')
        self.assertEqual(self.auto.notice_context(self.records('invoice_available')[0])[0],'obsolete')
        with self.assertRaises(ValueError):self.buyer.invoice(self.buyer.authorize(self.offer,token))

    def test_order_and_notification_commit_atomically(self):
        other=self.f.offer();self.f.delivered(other)
        with patch.object(self.buyer.notices,'enqueue',side_effect=RuntimeError('SYNTHETIC failure')):
            with self.assertRaises(RuntimeError):self.f.accept(other)
        with self.f.ledger.db() as db:self.assertIsNone(db.execute('SELECT 1 FROM checkout_acceptances WHERE offer_id=?',(other,)).fetchone())

    def test_existing_orders_are_not_emailed_on_module_initialization(self):
        self.drain()
        from checkout_notices import CheckoutNotices
        CheckoutNotices(self.f.ledger)
        self.assertEqual(self.drain(),[])

    def test_restore_preserves_exact_invoice_and_holds_delivery_and_logins(self):
        import sqlite3
        from invoicing import Ledger
        from checkout_notices import CheckoutNotices
        from restore_guard import fence
        original=self.f.store.invoice(self.offer,self.f.session)
        self.buyer.request_code(self.offer)
        with self.f.ledger.db() as db:c=db.execute('SELECT * FROM checkout_mail_challenges').fetchone()
        token=self.buyer.authenticate(self.offer,otp(self.buyer.secret(),self.identity,c['nonce']))
        folder=self.f.root/'restored';folder.mkdir()
        target=folder/'invoices.sqlite3'
        with self.f.ledger.db() as source,sqlite3.connect(target) as dest:source.backup(dest)
        fence(target)
        ledger=Ledger(folder,self.f.issuer);restored=CheckoutNotices(ledger)
        self.assertEqual(ledger.get(original['id'])['pdf'],original['pdf'])
        with self.assertRaises(ValueError):restored.authorize(self.offer,token)
        with ledger.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM checkout_mail_challenges').fetchone()[0],0)
            self.assertTrue(all(r[0]=='restore_review' for r in db.execute('SELECT state FROM notification_events')))


if __name__=='__main__':unittest.main()
