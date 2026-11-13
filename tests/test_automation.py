import copy
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import unittest
import zipfile
from zoneinfo import ZoneInfo

import test_checkout as checkout_fixture
import test_payment_flow as payment_fixture
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'production'))
import test_dossier_review as dossier_fixture
from automation_core import Automation, conservative_start
from document_extraction import ExtractEU, leaves


def document(value):
    from reportlab.pdfgen.canvas import Canvas
    stream=io.BytesIO();canvas=Canvas(stream)
    y=810
    for field,item in leaves(value):
        canvas.drawString(30,y,field+': '+item);y-=15
        if y<40:canvas.showPage();y=810
    canvas.save();return stream.getvalue()


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.f=checkout_fixture.CheckoutTests();self.f.setUp()
        self.f.values.update(apartments='2',property_address='TEST Haus 1')
        self.offer_id=self.f.offer();self.f.delivered(self.offer_id)
        self.accepted=self.f.accept(self.offer_id);self.identity=self.accepted['id']
        self.f.store.invoice(self.offer_id,self.f.session)
        from payment_flow import PaymentFlow
        self.payments=PaymentFlow(self.f.ledger);self.provider=payment_fixture.Provider(self.f.root)
        self.payments.request(self.identity,'test');self.payments.process_one(self.provider.client)
        self.provider.payment['status']='paid';self.payments.process_one(self.provider.client)
        self.values=dossier_fixture.facts();self.raw=document(self.values)
        self.key=self.f.root/'extend-key';self.key.write_text('SYNTHETIC-ONLY');self.key.chmod(0o600)
        self.cfgpath=self.f.root/'automation.json'
        self.cfg=dict(brand='abrechnungs-navi',region='eu1',enabled=True,avv_sha256=self.accepted['avv_sha256'],
            terms_sha256=self.accepted['terms_sha256'],consumer_information_sha256=self.accepted['consumer_information_sha256'],
            automatic_start_policy_approved=True,reviewer_name='SYNTHETISCHER TESTPRÜFER',max_pages_total=100,budget_id='a'*64,
            provider_approval=dict(brand='abrechnungs-navi',region='eu1',contract_verified=True,subprocessors_verified=True,
                retention_verified=True,customer_avv_allows_extraction=True,provider_evidence_sha256='b'*64))
        self.cfgpath.write_text(json.dumps(self.cfg));self.data=self.f.root/'data';self.data.mkdir()
        import time
        self.clock=time.time()
        self.auto=Automation(self.f.ledger,self.data,self.cfgpath,Path(__file__).resolve().parents[1]/'abrechnung/rechner.py',
            operator_ready=lambda:True,clock=lambda:self.clock)
        self.portal=self.auto.provision(self.identity);self.token=self.portal['token']
        self.calls=[]

    def tearDown(self):self.f.tearDown()

    def extraction(self,identity,cfg):
        from document_dossier import SCHEMA
        expected=copy.deepcopy(self.values)
        def api(method,path,body=None,content_type=None):
            self.calls.append((method,path))
            if path=='/files/upload':return {'id':'file_Synthetic'}
            return {'id':'exr_Synthetic','status':'PROCESSED','file':{'id':'file_Synthetic'},
                'output':{'value':expected,'metadata':{field:{'ocrConfidence':0.99,'citations':[{'fileId':'file_Synthetic','page':{'number':1},'referenceText':item}]}
                    for field,item in leaves(expected)}}}
        return ExtractEU(self.key,cfg['provider_approval'],self.auto.root/identity[3:]/'provider',SCHEMA,cfg['max_pages_total'],api)

    def submit(self):
        self.auto.upload(self.token,'SYNTHETISCHE Unterlagen.pdf',self.raw)
        self.auto.confirm_delivery(self.token)
        self.auto.submit(self.token)
        self.clock=max(self.clock,self.portal['not_before']+1)

    def draft(self):
        self.submit()
        self.auto.process_one(self.extraction);self.auto.process_one(self.extraction)
        self.assertEqual(self.auto.get(self.identity)['state'],'needs_final_review')
        return self.auto.current_job(self.identity)

    def approve(self):
        job=self.auto.current_job(self.identity)
        sha=hashlib.sha256((Path(job['bundle'])/'manifest.json').read_bytes()).hexdigest()
        self.auto.approve(self.identity,job['version'],sha,dict(original_visual_checked=True,pdf_visual_checked=True,allocation_checked=True))

    def drain(self,sender):
        for _ in range(20):
            if not self.auto.notices.deliver_one(self.auto,sender):break

    def test_paid_upload_extract_original_checks_and_private_draft(self):
        job=self.draft()
        self.assertEqual(self.calls,[('POST','/files/upload'),('POST','/extract_runs')])
        self.assertTrue(Path(job['bundle']).is_dir())
        with self.assertRaises(ValueError):self.auto.result(self.token)
        sent=[];self.drain(sent.append)
        self.assertTrue(any('Schlussprüfung' in m['subject'] for m in sent))
        self.assertFalse(any(m['subject']=='Ihre Nebenkostenabrechnung ist bereit' for m in sent))
        self.assertTrue(all(m['attachments']==[] for m in sent))

    def test_human_approval_releases_exact_pdf_bytes_and_only_then_notifies_customer(self):
        job=self.draft();folder=Path(job['bundle'])
        expected={p.name:p.read_bytes() for p in folder.glob('abrechnung-*.pdf')}
        self.approve()
        with zipfile.ZipFile(io.BytesIO(self.auto.result(self.token))) as archive:
            self.assertEqual({name:archive.read(name) for name in archive.namelist()},expected)
        sent=[];self.drain(sent.append)
        ready=[m for m in sent if m['subject']=='Ihre Nebenkostenabrechnung ist bereit']
        self.assertEqual(len(ready),1);self.assertEqual(ready[0]['to'],self.f.values['email'])
        self.assertNotIn('TEST A',ready[0]['text'])
        self.assertNotIn('Grundsteuer',ready[0]['text'])

    def test_new_source_version_supersedes_old_draft_and_suppresses_stale_notices(self):
        old=self.draft();oldsha=hashlib.sha256((Path(old['bundle'])/'manifest.json').read_bytes()).hexdigest()
        self.auto.upload(self.token,'Neue Unterlage.pdf',document({'note':'NEUE SYNTHETISCHE ANGABE'}))
        with self.assertRaises(ValueError):self.auto.approve(self.identity,old['version'],oldsha,dict(original_visual_checked=True,pdf_visual_checked=True,allocation_checked=True))
        sent=[];self.drain(sent.append)
        self.assertFalse(any('Schlussprüfung' in m['subject'] for m in sent))

    def test_missing_advances_trigger_controlled_customer_question_no_free_model_text(self):
        self.values['advances'].pop();self.raw=document(self.values)
        self.submit();self.auto.process_one(self.extraction);self.auto.process_one(self.extraction)
        self.assertEqual(self.auto.get(self.identity)['state'],'needs_customer_input')
        sent=[];self.drain(sent.append)
        questions=[m for m in sent if 'Bitte prüfen' in m['subject']]
        self.assertEqual(len(questions),1)
        self.assertIn('Vorauszahlungen',questions[0]['text'])
        self.assertNotIn('TEST B',questions[0]['text'])
        self.assertEqual(self.auto.get(self.identity)['released_version'],None)

    def test_confirmed_payment_does_not_bypass_confirmation_deadline_or_provider_approval(self):
        self.auto.upload(self.token,'Quelle.pdf',self.raw);self.auto.submit(self.token)
        self.auto.process_one(self.extraction)
        self.assertEqual(self.auto.get(self.identity)['state'],'waiting_confirmation');self.assertEqual(self.calls,[])
        self.auto.confirm_delivery(self.token);self.clock+=61;self.auto.process_one(self.extraction)
        self.assertEqual(self.auto.get(self.identity)['state'],'waiting_start');self.assertEqual(self.calls,[])
        self.clock=self.portal['not_before']+1
        self.cfg['provider_approval']['contract_verified']=False;self.cfgpath.write_text(json.dumps(self.cfg))
        self.auto.process_one(self.extraction)
        self.assertEqual(self.auto.get(self.identity)['state'],'waiting_policy');self.assertEqual(self.calls,[])

    def test_payment_reversal_blocks_processing_and_result_download(self):
        self.draft();self.approve()
        self.provider.payment['amountRefunded']={'currency':'EUR','value':'0.01'}
        self.payments.webhook(self.provider.payment['id'])
        with self.assertRaises(ValueError):self.auto.result(self.token)
        sent=[];self.drain(sent.append)
        self.assertFalse(any(m['subject']=='Ihre Nebenkostenabrechnung ist bereit' for m in sent))

    def test_changed_original_or_pdf_cannot_be_approved(self):
        job=self.draft();source=self.auto.files(self.identity)[0]
        Path(source['path']).write_bytes(b'CHANGED SYNTHETIC SOURCE')
        with self.assertRaises(ValueError):self.approve()
        self.assertIsNone(self.auto.get(self.identity)['released_version'])

    def test_exhausted_budget_stops_before_provider_upload(self):
        self.cfg['max_pages_total']=0;self.cfgpath.write_text(json.dumps(self.cfg))
        self.submit();self.auto.process_one(self.extraction)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.auto.get(self.identity)['state'],'internal_review')

    def test_otp_is_single_use_rate_limited_and_not_stored_in_outbox(self):
        self.auto.request_code(self.token);self.auto.request_code(self.token)
        sent=[];self.drain(sent.append)
        codes=[m for m in sent if 'Zugangscode' in m['subject']]
        self.assertEqual(len(codes),1)
        code=re.search(r'\b\d{6}\b',codes[0]['text'])[0]
        self.assertNotIn('/kunden/',codes[0]['text'])
        with self.f.ledger.db() as db:
            stored=db.execute("SELECT payload FROM notification_events WHERE event='access_code'").fetchone()[0]
        self.assertNotIn(code,stored)
        session=self.auto.login(self.token,code)
        self.assertTrue(self.auto.authenticated(self.token,session))
        with self.assertRaises(ValueError):self.auto.login(self.token,code)
        self.assertFalse(self.auto.authenticated(self.token,'x'*43))

    def test_ambiguous_delivery_is_not_blindly_repeated(self):
        calls=[]
        def sender(notice):
            calls.append(notice['event_id'])
            raise OSError('SYNTHETIC SMTP timeout')
        self.drain(sender)
        self.assertFalse(self.auto.notices.deliver_one(self.auto,sender))
        self.assertTrue(calls)
        self.assertEqual(len(calls),len(set(calls)))
        with self.f.ledger.db() as db:
            self.assertTrue(all(r[0]=='delivery_uncertain' for r in db.execute('SELECT state FROM notification_events')))

    def test_expiry_removes_active_personal_files_cache_and_sessions(self):
        self.draft();self.auto.request_code(self.token)
        self.clock=self.auto.get(self.identity)['expires']+1
        self.auto.expire()
        self.assertFalse((self.auto.root/self.identity[3:]).exists())
        job=self.auto.current_job(self.identity)
        self.assertEqual(job['checked'],'[]');self.assertIsNone(job['candidate'])
        self.assertEqual(self.auto.files(self.identity),[])
        with self.f.ledger.db() as db:
            reference=db.execute('SELECT file_id,run_id,state FROM auto_provider_deletions').fetchone()
        self.assertEqual(tuple(reference),('file_Synthetic','exr_Synthetic','pending'))

    def test_unknown_scope_and_heating_stay_internal(self):
        self.values['costs'][0]['name']='Heizkosten';self.values['allocations'][0]['cost_name']='Heizkosten'
        self.raw=document(self.values);self.submit();self.auto.process_one(self.extraction);self.auto.process_one(self.extraction)
        self.assertEqual(self.auto.get(self.identity)['state'],'internal_review')
        sent=[];self.drain(sent.append)
        self.assertTrue(any(m['to']=='kontakt@abrechnungs-navi.de' for m in sent))
        self.assertFalse(any('Bitte prüfen' in m['subject'] for m in sent))

    def test_withdrawal_notice_blocks_processing_even_after_payment(self):
        (self.data/'widerrufe.json').write_text(json.dumps([{'vertrag':self.identity}]))
        with self.assertRaises(ValueError):self.auto.upload(self.token,'Quelle.pdf',self.raw)
        self.assertEqual(self.calls,[])

    def test_duplicate_upload_and_submission_do_not_duplicate_jobs_or_pages(self):
        first=self.auto.upload(self.token,'Quelle.pdf',self.raw)
        self.assertEqual(self.auto.upload(self.token,'Doppel.pdf',self.raw),first)
        self.auto.confirm_delivery(self.token);self.auto.submit(self.token);self.auto.submit(self.token)
        self.clock=self.portal['not_before']+1;self.auto.process_one(self.extraction);self.auto.process_one(self.extraction)
        with self.f.ledger.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM auto_jobs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM auto_page_budget').fetchone()[0],1)

    def test_shared_page_budget_is_not_reset_for_another_order(self):
        self.cfg['max_pages_total']=1;self.cfgpath.write_text(json.dumps(self.cfg))
        self.draft()
        second=self.f.offer();self.f.delivered(second);accepted=self.f.accept(second);self.f.store.invoice(second,self.f.session)
        self.payments.request(accepted['id'],'test');self.payments.process_one(self.provider.client)
        self.provider.payment['status']='paid';self.payments.process_one(self.provider.client)
        portal=self.auto.provision(accepted['id'])
        self.auto.upload(portal['token'],'SYNTHETIC.pdf',self.raw);self.auto.confirm_delivery(portal['token']);self.auto.submit(portal['token'])
        self.auto.process_one(self.extraction)
        self.assertEqual(self.auto.get(accepted['id'])['state'],'internal_review')
        self.assertEqual(len(self.calls),2)

    def test_final_approval_is_idempotent_and_does_not_extend_retention(self):
        job=self.draft();sha=hashlib.sha256((Path(job['bundle'])/'manifest.json').read_bytes()).hexdigest()
        self.approve();expires=self.auto.get(self.identity)['expires'];self.clock+=100
        self.auto.approve(self.identity,job['version'],sha,dict(original_visual_checked=True,pdf_visual_checked=True,allocation_checked=True))
        self.assertEqual(self.auto.get(self.identity)['expires'],expires)
        with self.f.ledger.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notification_events WHERE event='ready'").fetchone()[0],1)

    def test_initial_manual_phase_cannot_be_bypassed_by_auto_configuration(self):
        self.draft()
        self.cfg['release_mode']='automatic';self.cfgpath.write_text(json.dumps(self.cfg))
        with self.assertRaises(ValueError):self.approve()
        with self.assertRaises(ValueError):self.auto.result(self.token)
        self.assertIsNone(self.auto.get(self.identity)['released_version'])

    def test_checked_provider_results_are_queued_once_and_remain_usable_without_provider(self):
        self.draft();self.auto.queue_checked_provider_deletions();self.auto.queue_checked_provider_deletions()
        with self.f.ledger.db() as db:
            rows=db.execute('SELECT * FROM auto_provider_deletions').fetchall()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['state'],'pending')
        before=list(self.calls)
        result=self.extraction(self.identity,self.cfg).extract(self.raw)
        self.assertEqual(result['provider_file_id'],'file_Synthetic');self.assertEqual(self.calls,before)

    def test_restored_paid_and_released_order_cannot_resume_or_resend(self):
        from restore_guard import fence
        self.draft();self.approve()
        fence(self.f.ledger.folder/'invoices.sqlite3')
        self.payments.queue_due()
        with self.f.ledger.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM payment_jobs WHERE state='queued'").fetchone()[0],0)
            self.assertEqual(db.execute('SELECT state FROM payment_orders').fetchone()[0],'restore_review')
        with self.assertRaises(ValueError):self.auto.result(self.token)
        self.assertFalse(self.auto.notices.deliver_one(self.auto,lambda *_:self.fail('mail must remain held')))

    def test_wrong_codes_expiry_and_wrong_avv_fail_closed(self):
        self.auto.request_code(self.token)
        with self.f.ledger.db() as db:nonce=db.execute('SELECT nonce FROM auto_challenges').fetchone()[0]
        from notice_agent import otp
        good=otp(self.auto.secret(),self.identity,nonce);bad='000000' if good!='000000' else '111111'
        for _ in range(5):
            with self.assertRaises(ValueError):self.auto.login(self.token,bad)
        with self.assertRaises(ValueError):self.auto.login(self.token,good)
        self.cfg['avv_sha256']='f'*64;self.cfgpath.write_text(json.dumps(self.cfg))
        with self.assertRaises(ValueError):self.auto.upload(self.token,'x.pdf',self.raw)
        self.assertEqual(self.calls,[])


class Calendar(unittest.TestCase):
    def test_weekends_holidays_and_requested_date_are_conservative(self):
        zone=ZoneInfo('Europe/Berlin')
        for start,expected in (('2026-12-11','2026-12-29'),('2026-10-19','2026-11-03'),('2026-03-20','2026-04-08')):
            stamp=datetime.fromisoformat(start).replace(tzinfo=zone).timestamp()
            actual=datetime.fromtimestamp(conservative_start(stamp,start),zone).date().isoformat()
            self.assertEqual(actual,expected)


if __name__=='__main__':unittest.main(verbosity=2)
