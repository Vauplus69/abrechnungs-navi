import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from invoicing import Ledger
from notice_agent import Notifications,ISSUES,MAILBOX
from notification_templates import TEMPLATES,VERSION


def checkout_context():
    base='https://abrechnungs-navi.de/bestellen/'+'a'*40
    return dict(checkout_notification_verified=True,order_id='AN-'+'d'*32,
        order_accepted=True,contract_download_ready=True,invoice_issued=True,invoice_download_ready=True,
        payment_state='failed',payment_retry_allowed=True,order_date='13.11.2026',
        service_description='Nebenkostenabrechnung für zwei Wohnungen',total_price='148,00 EUR',
        contract_download_url=base+'/bestaetigung',start_notice='Beginn nach Ablauf der bestätigten Frist.',
        invoice_number='AN-2026-TEST',invoice_date='13.11.2026',invoice_total='148,00 EUR',
        invoice_url=base+'/rechnung',order_url=base+'/zahlung')


class Templates(unittest.TestCase):
    def test_all_templates_render_with_correct_recipient_without_attachments(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'test-ledger',Path(folder)/'unused.json')
            notices=Notifications(ledger)
            context=dict(email='synthetic@example.invalid',token='a'*32,expires=time.time()+86400)
            context.update(checkout_context())
            for event,template in TEMPLATES.items():
                payload={'nonce':'b'*32} if event=='access_code' else {'codes':['advances']} if event=='missing_inputs' else {}
                record=dict(id='c'*64,order_id='AN-'+'d'*32,event=event,version='1',payload=json.dumps(payload),template_version=VERSION)
                with self.subTest(event=event):
                    mail=notices.render(record,context,b'SYNTHETIC-SECRET-ONLY')
                    self.assertEqual(mail['to'],MAILBOX if template['recipient']=='operator' else context['email'])
                    self.assertEqual(mail['attachments'],[])
                    self.assertNotIn('{portal_url}',mail['text']);self.assertNotIn('{deadline}',mail['text'])
                    if event=='access_code':
                        self.assertNotIn('https://',mail['text']);self.assertRegex(mail['text'],r'\b\d{6}\b')
                    if template['recipient']=='operator':self.assertNotIn('/kunden/',mail['text'])

    def test_unreviewed_model_prose_cannot_become_customer_question(self):
        with tempfile.TemporaryDirectory() as folder:
            notices=Notifications(Ledger(Path(folder)/'ledger',Path(folder)/'unused'))
            record=dict(id='c'*64,order_id='AN-'+'d'*32,event='missing_inputs',version='1',payload=json.dumps({'codes':['UNTRUSTED_DOCUMENT_TEXT']}),template_version=VERSION)
            with self.assertRaises(ValueError):notices.render(record,dict(email='test@example.invalid',token='a'*32),b'test')

    def test_old_queue_is_not_silently_sent_with_new_template(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'ledger',Path(folder)/'unused')
            with ledger.db() as db:
                db.execute('CREATE TABLE notification_events(id TEXT PRIMARY KEY,order_id TEXT,event TEXT,version TEXT,payload TEXT,state TEXT,created REAL,updated REAL)')
                db.execute('INSERT INTO notification_events VALUES(?,?,?,?,?,?,?,?)',('c'*64,'AN-'+'d'*32,'received','1','{}','queued',0,0))
            notices=Notifications(ledger);context=Mock();sender=Mock()
            self.assertTrue(notices.deliver_one(context,sender))
            context.notice_context.assert_not_called();sender.assert_not_called()
            with ledger.db() as db:self.assertEqual(db.execute('SELECT state FROM notification_events').fetchone()[0],'template_review')


class CheckoutTemplateGuards(unittest.TestCase):
    def render(self,event,**updates):
        with tempfile.TemporaryDirectory() as folder:
            notice=Notifications(Ledger(Path(folder)/'ledger',Path(folder)/'unused'))
            context=dict(email='synthetic@example.invalid',**checkout_context());context.update(updates)
            record=dict(id='c'*64,order_id='AN-'+'d'*32,event=event,version='1',payload='{}',template_version=VERSION)
            return notice.render(record,context,b'SYNTHETIC-ONLY')

    def test_payment_notice_requires_terminal_status_and_retry_clearance(self):
        for state in ('open','pending','authorized','paid','uncertain','refunded','charged_back'):
            with self.subTest(state=state),self.assertRaises(ValueError):
                self.render('payment_action_required',payment_state=state)
        with self.assertRaises(ValueError):self.render('payment_action_required',payment_retry_allowed=False)

    def test_unwired_checkout_and_unissued_invoice_cannot_render(self):
        with self.assertRaises(ValueError):self.render('order_confirmation',checkout_notification_verified=False)
        with self.assertRaises(ValueError):self.render('order_confirmation',order_accepted=False)
        with self.assertRaises(ValueError):self.render('invoice_available',invoice_issued=False)
        with self.assertRaises(ValueError):self.render('invoice_available',invoice_download_ready=False)

    def test_foreign_links_missing_values_and_wrong_order_are_blocked(self):
        for url in ('https://evil.example/bestellen/a','https://abrechnungs-navi.de.evil.example/bestellen/a',
                    'http://abrechnungs-navi.de/bestellen/a','https://abrechnungs-navi.de/verwaltung/a'):
            with self.subTest(url=url),self.assertRaises(ValueError):self.render('invoice_available',invoice_url=url)
        with self.assertRaises(ValueError):self.render('invoice_available',invoice_number='')
        with self.assertRaises(ValueError):self.render('invoice_available',order_id='AN-'+'e'*32)

    def test_static_invoice_subject_and_no_unexpanded_placeholders(self):
        notice=self.render('invoice_available')
        self.assertEqual(notice['to'],'synthetic@example.invalid')
        self.assertNotIn('{invoice_',notice['text']);self.assertEqual(notice['attachments'],[])
        self.assertIn('keine weitere Zahlung',notice['text'])


if __name__=='__main__':unittest.main()
