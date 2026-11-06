import concurrent.futures
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from unittest.mock import patch
from datetime import timedelta

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import invoicing as inv
import workflow
from pypdf import PdfReader


class Invoices(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.cfg=self.root/'issuer.json'
        self.company={'name':'MUSTER – kein echter Rechnungsaussteller','address':'Testweg 1','city':'12345 Musterstadt','email':'test@example.invalid','tax_mode':'kleinunternehmer','tax_id':''}
        self.cfg.write_text(json.dumps(self.company))
        self.store=inv.Ledger(self.root/'invoices',self.cfg)
        self.values={'customer':'MUSTERKUNDE','address':'Musterweg 1','city':'12345 Musterstadt','country':'DE','reference':'TEST-ONLY-001','apartments':'3','houses':'1','year':'2025','service_date':inv.today().isoformat(),'kind':'service'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_draft_and_pdf_do_not_allocate_number(self):
        key=self.store.make_draft(self.values)
        self.assertEqual(self.store.listing(),[])
        data=self.store.draft(key)
        self.assertEqual(data['order']['total_cents'],20700)
        raw=inv.render_pdf(data,True)
        body=''.join(p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages)
        self.assertIn('ENTWURF',body)
        self.assertIn('207,00',body)
        self.assertNotIn('19 %',body)
        self.assertEqual(self.store.listing(),[])

    def test_issue_persist_idempotent_and_immutable(self):
        key=self.store.make_draft(self.values)
        identity=self.store.issue(key)
        self.assertEqual(self.store.issue(key),identity)
        row=self.store.get(identity)
        self.assertRegex(row['number'],r'^AN-\d{4}-000001$')
        data=json.loads(row['payload'])
        self.assertEqual(data['order']['total_cents'],20700)
        self.assertEqual(hashlib.sha256(row['pdf']).hexdigest(),row['sha256'])
        self.assertEqual(inv.Ledger(self.root/'invoices',self.cfg).get(identity)['pdf'],row['pdf'])
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.db() as c:c.execute('UPDATE invoices SET number=? WHERE id=?',('changed',identity))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.db() as c:c.execute('DELETE FROM invoices WHERE id=?',(identity,))

    def test_missing_tax_identifier_over_250_blocks_without_number(self):
        key=self.store.make_draft(dict(self.values,apartments='4'))
        with self.assertRaisesRegex(ValueError,'250'):
            self.store.issue(key)
        self.assertEqual(self.store.listing(),[])

    def test_configuration_change_requires_new_draft(self):
        key=self.store.make_draft(self.values)
        self.cfg.write_text(json.dumps(dict(self.company,tax_id='SYNTHETIC-TEST-ONLY')))
        with self.assertRaisesRegex(ValueError,'geändert'):
            self.store.issue(key)
        key=self.store.make_draft(dict(self.values,apartments='4'))
        row=self.store.get(self.store.issue(key))
        self.assertEqual(json.loads(row['payload'])['order']['total_cents'],26600)

    def test_cancellation_is_separate_negative_invoice(self):
        identity=self.store.issue(self.store.make_draft(self.values))
        original=self.store.get(identity)['pdf']
        cancellation=self.store.cancel(identity,'MUSTER – vollständige Stornierung')
        self.assertEqual(self.store.cancel(identity,'Erneuter Klick'),cancellation)
        self.assertNotEqual(cancellation,identity)
        row=self.store.get(cancellation)
        self.assertTrue(json.loads(row['payload'])['cancellation_of'])
        body=''.join(p.extract_text() for p in PdfReader(io.BytesIO(row['pdf'])).pages)
        self.assertIn('Stornorechnung',body)
        self.assertIn('-207,00',body)
        self.assertEqual(self.store.get(identity)['pdf'],original)
        with self.assertRaises(ValueError):self.store.cancel(cancellation,'Nochmals')

    def test_invalid_data_and_tampered_price(self):
        for changes in [{'country':'AT'},{'country':''},{'apartments':'0'},{'houses':'4'},{'customer':''},{'service_date':'bad'},{'kind':'unknown'},{'customer':'Bad\nHeader'},{'apartments':'1e2'},{'service_date':(inv.today()+timedelta(days=1)).isoformat()}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.store.make_draft(dict(self.values,**changes))
        key=self.store.make_draft(dict(self.values,total_cents=1))
        self.assertEqual(self.store.draft(key)['order']['total_cents'],20700)

    def test_concurrent_numbers_and_double_click(self):
        keys=[self.store.make_draft(self.values) for _ in range(4)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            ids=list(pool.map(self.store.issue,keys))
        self.assertEqual(len(set(ids)),4)
        self.assertEqual(len({self.store.get(i)['number'] for i in ids}),4)
        key=self.store.make_draft(self.values)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            duplicate=list(pool.map(self.store.issue,[key]*3))
        self.assertEqual(len(set(duplicate)),1)

    def test_http_auth_origin_preview_issue_download_and_storno(self):
        data=self.root/'data';data.mkdir();(data/'kunden').mkdir()
        otp=self.root/'otp';otp.write_text('JBSWY3DPEHPK3PXP')
        env={'AN_DATA_DIR':str(data),'AN_TESTING':'1','AN_TOTP_FILE':str(otp),'AN_OPERATOR_FILE':str(self.root/'not-a-release.json'),'AN_BACKUP_MARKER':str(self.root/'not-a-backup'),'AN_INVOICE_DIR':str(self.root/'http-invoices'),'AN_INVOICE_ISSUER_FILE':str(self.cfg)}
        with patch.dict(os.environ,env):
            spec=importlib.util.spec_from_file_location('tested_invoice_app',ROOT/'app/upload_app.py')
            app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app);app.install(app)
            server=app.ThreadingHTTPServer(('127.0.0.1',0),app.H)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def req(method,path,body=None,cookie='',origin='http://127.0.0.1'):
                headers={'Origin':origin}
                if cookie:headers['Cookie']=cookie
                if isinstance(body,dict):body=urllib.parse.urlencode(body);headers['Content-Type']='application/x-www-form-urlencoded'
                c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10);c.request(method,path,body,headers)
                r=c.getresponse();result=r.status,dict(r.getheaders()),r.read();c.close();return result
            try:
                self.assertEqual(req('GET',inv.BASE)[0],401)
                self.assertEqual(req('POST',inv.BASE+'/entwurf',self.values)[0],401)
                status,headers,_=req('POST','/verwaltung/anmelden',{'otp':workflow.totp(otp.read_text())})
                self.assertEqual(status,303);cookie=headers['Set-Cookie'].split(';')[0]
                self.assertEqual(req('GET',inv.BASE,cookie=cookie)[0],200)
                self.assertEqual(req('POST',inv.BASE+'/entwurf',self.values,cookie,'https://foreign.invalid')[0],403)
                status,h,_=req('POST',inv.BASE+'/entwurf',self.values,cookie)
                self.assertEqual(status,303);draft=h['Location'];key=draft.rsplit('/',1)[-1]
                self.assertEqual(req('GET',draft,cookie=cookie)[0],200)
                self.assertEqual(req('GET',draft+'/pdf',cookie=cookie)[0],200)
                self.assertEqual(req('POST',inv.BASE+'/ausstellen',{'draft':key},cookie)[0],400)
                status,h,_=req('POST',inv.BASE+'/ausstellen',{'draft':key,'confirm':'yes'},cookie)
                self.assertEqual(status,303);invoice=h['Location']
                pdf=req('GET',invoice+'/pdf',cookie=cookie)
                self.assertEqual(pdf[0],200);self.assertEqual(pdf[1]['Content-Type'],'application/pdf')
                self.assertEqual(req('GET',invoice+'/pdf')[0],401)
                self.assertEqual(req('POST',inv.BASE+'/ausstellen',{'draft':key,'confirm':'yes'},cookie)[1]['Location'],invoice)
                status,h,_=req('POST',inv.BASE+'/storno',{'id':invoice.rsplit('/',1)[-1],'reason':'MUSTER','confirm':'yes'},cookie)
                self.assertEqual(status,303)
                cancelled=req('GET',h['Location']+'/pdf',cookie=cookie)
                self.assertEqual(cancelled[0],200)
                cancellation_text=''.join(page.extract_text() for page in PdfReader(io.BytesIO(cancelled[2])).pages)
                self.assertIn('Stornorechnung',cancellation_text)
                self.assertIn('-207,00',cancellation_text)
                self.assertEqual(list((data/'kunden').iterdir()),[])
            finally:
                server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
