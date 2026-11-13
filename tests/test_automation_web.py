import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import threading
import time
import unittest
import urllib.parse
from unittest.mock import patch

import test_automation as fixture
import automation_web
import workflow


class PortalHTTP(unittest.TestCase):
    def setUp(self):
        self.case=fixture.AutomationTests();self.case.setUp();self.auto=self.case.auto
        self.case.clock=self.case.portal['not_before']+1
        root=self.case.f.root
        (self.case.data/'kunden').mkdir()
        self.otp=root/'totp';self.otp.write_text('JBSWY3DPEHPK3PXP')
        backup=root/'backup';backup.write_text(str(time.time()))
        operator=root/'operator.json';operator.write_text(json.dumps(dict(provider_annex_complete=True,
            disk_encryption_verified=True,provider_mfa_verified=True,restore_tested_at=time.time(),backup_tested_at=time.time(),
            backup_location='SYNTHETIC TEST',backup_retention_days=30,avv_sha256=self.case.accepted['avv_sha256'])))
        payment_cfg=root/'payments.json'
        payment_cfg.write_text(json.dumps(dict(brand='abrechnungs-navi',profile_id='pfl_2fcc6rqot8',mode='test',enabled=True)))
        env=dict(AN_DATA_DIR=str(self.case.data),AN_INVOICE_DIR=str(root/'invoices'),AN_INVOICE_ISSUER_FILE=str(self.case.f.issuer),
            AN_OPERATOR_FILE=str(operator),AN_BACKUP_MARKER=str(backup),AN_TOTP_FILE=str(self.otp),AN_AUTOMATION_CONFIG=str(self.case.cfgpath),
            AN_CHECKOUT_CONFIG=str(self.case.f.cfg),AN_PAYMENT_CONFIG=str(payment_cfg),AN_TESTING='1')
        self.environment=patch.dict(os.environ,env);self.environment.start()
        self.factory=patch.object(automation_web,'Automation',return_value=self.auto);self.factory.start()
        source=Path(__file__).resolve().parents[1]/'app/upload_app.py'
        spec=importlib.util.spec_from_file_location('automation_test_http_app',source)
        self.app=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.app);self.app.install(self.app)
        self.server=self.app.ThreadingHTTPServer(('127.0.0.1',0),self.app.H)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='/kunden/'+self.case.token

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.factory.stop();self.environment.stop();self.case.tearDown()

    def request(self,method,path,values=None,cookie='',origin='https://abrechnungs-navi.de',raw=None):
        headers={'Origin':origin}
        if cookie:headers['Cookie']=cookie
        body=raw
        if values is not None:
            body=urllib.parse.urlencode(values);headers['Content-Type']='application/x-www-form-urlencoded'
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        conn.request(method,path,body,headers)
        response=conn.getresponse();data=response.read();head=dict(response.getheaders());status=response.status;conn.close()
        return status,head,data

    def test_payment_mail_landing_reveals_no_order_data_or_session(self):
        path='/bestellen/'+self.case.offer_id+'/zahlung-oeffnen'
        status,headers,body=self.request('GET',path)
        self.assertEqual(status,200)
        self.assertIn(('/bestellen/'+self.case.offer_id+'/zahlung').encode(),body)
        self.assertNotIn(self.case.identity.encode(),body)
        self.assertNotIn(b'synthetic@example.invalid',body)
        self.assertNotIn('Set-Cookie',headers)
        self.assertEqual(self.request('GET','/bestellen/'+self.case.offer_id+'/zahlung')[0],400)

    def customer(self):
        self.assertEqual(self.request('POST',self.base+'/code',{})[0],200)
        sent=[];self.case.drain(sent.append)
        code=re.search(r'\b\d{6}\b',next(m['text'] for m in sent if 'Zugangscode' in m['subject']))[0]
        status,headers,_=self.request('POST',self.base+'/anmelden',{'code':code})
        self.assertEqual(status,303);self.assertIn('HttpOnly',headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';')[0]

    def admin(self):
        status,headers,_=self.request('POST','/verwaltung/anmelden',{'otp':workflow.totp(self.otp.read_text())})
        self.assertEqual(status,303);return headers['Set-Cookie'].split(';')[0]

    def submit(self,customer):
        self.assertEqual(self.request('GET',self.base+'/vertrag',cookie=customer)[0],200)
        self.assertEqual(self.request('PUT',self.base+'/datei?name=Unterlagen.pdf',cookie=customer,raw=self.case.raw)[0],201)
        self.assertEqual(self.request('POST',self.base+'/einreichen',{'version':1},customer)[0],303)
        self.auto.process_one(self.case.extraction);self.auto.process_one(self.case.extraction)

    def test_end_to_end_authenticated_upload_agents_review_and_final_delivery(self):
        customer=self.customer();self.submit(customer)
        self.assertEqual(self.request('GET',self.base+'/ergebnis',cookie=customer)[0],409)
        self.assertEqual(self.request('GET','/verwaltung/agenten',cookie=customer)[0],401)
        admin=self.admin();operator='/verwaltung/agenten/'+self.case.identity
        status,_,body=self.request('GET',operator,cookie=admin)
        self.assertEqual(status,200);self.assertIn(b'Schlusspr',body)
        pdf=re.search(rb'/pdf/(abrechnung-\d{3}\.pdf)',body)[1].decode()
        self.assertEqual(self.request('GET',operator+'/pdf/'+pdf,cookie=customer)[0],401)
        status,_,reviewed=self.request('GET',operator+'/pdf/'+pdf,cookie=admin)
        self.assertEqual(status,200);self.assertTrue(reviewed.startswith(b'%PDF'))
        job=self.auto.current_job(self.case.identity)
        sha=hashlib.sha256((Path(job['bundle'])/'manifest.json').read_bytes()).hexdigest()
        values=dict(version=1,manifest_sha256=sha,original_visual_checked='yes',pdf_visual_checked='yes',allocation_checked='yes')
        self.assertEqual(self.request('POST',operator+'/freigeben',values,customer)[0],401)
        self.assertEqual(self.request('POST',operator+'/freigeben',{**values,'pdf_visual_checked':'no'},admin)[0],409)
        self.assertEqual(self.request('POST',operator+'/freigeben',values,admin)[0],303)
        status,_,result=self.request('GET',self.base+'/ergebnis',cookie=customer)
        self.assertEqual(status,200)
        import io,zipfile
        with zipfile.ZipFile(io.BytesIO(result)) as archive:self.assertEqual(archive.read(pdf),reviewed)
        sent=[];self.case.drain(sent.append)
        self.assertEqual(len([m for m in sent if m['subject']=='Ihre Nebenkostenabrechnung ist bereit']),1)

    def test_single_new_order_from_http_checkout_through_payment_to_released_pdf(self):
        """One new buyer journey, with only external transports simulated."""
        import checkout
        payment_cfg=self.case.f.root/'payments.json'
        payment_cfg.write_text(json.dumps(dict(brand='abrechnungs-navi',profile_id='pfl_2fcc6rqot8',mode='test',enabled=True)))
        with patch.dict(os.environ,AN_PAYMENT_CONFIG=str(payment_cfg)):
            status,headers,body=self.request('GET','/bestellen')
            self.assertEqual(status,200);cookie=headers['Set-Cookie'].split(';')[0]
            csrf=re.search(rb'name="csrf" value="([a-f0-9]+)"',body)[1].decode()
            status,headers,_=self.request('POST','/bestellen/angebot',{**self.case.f.values,'csrf':csrf},cookie)
            self.assertEqual(status,303);location=headers['Location']
            status,_,body=self.request('GET',location,cookie=cookie)
            self.assertEqual(status,200)
            sha=re.search(rb'name="offer_sha256" value="([a-f0-9]+)"',body)[1].decode()
            for kind in checkout.KINDS:self.assertEqual(self.request('GET',location+'/'+kind,cookie=cookie)[0],200)
            values=dict(csrf=csrf,offer_sha256=sha,contract='yes',avv='yes',consumer='yes')
            self.assertEqual(self.request('POST',location+'/annehmen',values,cookie)[0],303)
            # Buyer mails precede payment and do not depend on a paid portal.
            import io,zipfile
            with self.auto.ledger.db() as db:
                buyer=db.execute('SELECT order_id FROM checkout_acceptances WHERE offer_id=?',(location.rsplit('/',1)[-1],)).fetchone()[0]
            sent=[];self.case.drain(sent.append)
            buyer_mails=[m for m in sent if buyer in m['text']]
            self.assertTrue(any(m['subject']=='Ihre Bestellung bei Abrechnungs-Navi' for m in buyer_mails))
            invoice_mail=next(m for m in buyer_mails if m['subject']=='Ihre Rechnung von Abrechnungs-Navi')
            document_path=re.search(r'https://abrechnungs-navi.de(/bestellen/[a-f0-9]{40}/dokumente/rechnung)',invoice_mail['text'])[1]
            self.assertEqual(self.request('GET',document_path)[0],200)
            self.assertFalse(self.request('GET',document_path)[2].startswith(b'%PDF'))
            self.assertEqual(self.request('POST',document_path+'/code',{},origin='https://evil.invalid')[0],403)
            cfg=json.loads(self.case.cfgpath.read_text());cfg.update(mail_enabled=True,mail_provider_approved=True,mail_provider_evidence_sha256='d'*64)
            self.case.cfgpath.write_text(json.dumps(cfg))
            self.assertEqual(self.request('POST',document_path+'/code',{})[0],200)
            sent=[];self.case.drain(sent.append)
            code=re.search(r'\b\d{6}\b',next(m for m in sent if 'Zugangscode' in m['subject'])['text'])[0]
            status,headers,_=self.request('POST',document_path+'/anmelden',{'code':code})
            self.assertEqual(status,303);document_cookie=headers['Set-Cookie'].split(';')[0]
            self.assertIn('Secure',headers['Set-Cookie']);self.assertIn('HttpOnly',headers['Set-Cookie'])
            status,headers,pdf=self.request('GET',document_path,cookie=document_cookie)
            self.assertEqual(status,200);self.assertTrue(pdf.startswith(b'%PDF'))
            with self.auto.ledger.db() as db:invoice_id=db.execute('SELECT invoice_id FROM checkout_invoice_links WHERE order_id=?',(buyer,)).fetchone()[0]
            self.assertEqual(pdf,self.auto.ledger.get(invoice_id)['pdf'])
            packet=self.request('GET',document_path.rsplit('/',1)[0]+'/vertrag',cookie=document_cookie)
            self.assertEqual(packet[0],200)
            with zipfile.ZipFile(io.BytesIO(packet[2])) as archive:
                self.assertIn('consumer.txt',archive.namelist())
            self.assertEqual(self.request('POST',document_path+'/anmelden',{'code':code})[0],400)
            self.assertEqual(self.request('GET',location+'/zahlung',cookie=cookie)[0],200)
            self.assertTrue(self.case.payments.process_one(self.case.provider.client))
            identity=self.case.provider.payment['metadata']['order_id']
            self.assertNotEqual(identity,self.case.identity)
            with self.assertRaises(ValueError):self.auto.provision(identity)
            self.case.provider.payment['status']='paid'
            self.assertEqual(self.request('POST','/zahlung/webhook',{'id':self.case.provider.payment['id']},origin='')[0],200)
            self.assertTrue(self.case.payments.process_one(self.case.provider.client))
            self.assertEqual(self.case.payments.get(identity)['state'],'paid')
            self.case.identity=identity;self.case.portal=self.auto.provision(identity)
            self.case.token=self.case.portal['token'];self.base='/kunden/'+self.case.token
            self.case.clock=max(self.case.clock,self.case.portal['not_before']+1)
            # Continue the same order through OTP, real HTTP upload, agents,
            # operator MFA, checked PDF release and byte-identical download.
            self.test_end_to_end_authenticated_upload_agents_review_and_final_delivery()

    def test_portal_origin_session_and_source_ownership_boundaries(self):
        self.assertEqual(self.request('PUT',self.base+'/datei?name=a.pdf',raw=self.case.raw)[0],403)
        self.assertEqual(self.request('POST',self.base+'/code',{},origin='https://evil.invalid')[0],403)
        customer=self.customer()
        self.assertEqual(self.request('PUT',self.base+'/datei?name=a.pdf',cookie=customer,raw=self.case.raw,origin='https://evil.invalid')[0],403)
        self.assertEqual(self.request('PUT',self.base+'/datei?name=a.pdf',cookie=customer,raw=self.case.raw)[0],201)
        fid=self.auto.files(self.case.identity)[0]['id']
        self.assertEqual(self.request('GET',self.base+'/datei/'+fid,cookie=customer)[2],self.case.raw)
        unauth=self.request('GET',self.base+'/datei/'+fid)
        self.assertFalse(unauth[2].startswith(b'%PDF'))
        self.assertEqual(self.request('GET','/kunden/'+'x'*32+'/datei/'+fid,cookie=customer)[0],409)

    def test_head_does_not_confirm_contract_and_originals_remain_returnable_on_refund(self):
        customer=self.customer()
        self.assertEqual(self.request('HEAD',self.base+'/vertrag',cookie=customer)[0],200)
        self.assertIsNone(self.auto.get(self.case.identity)['confirmation_at'])
        self.assertEqual(self.request('PUT',self.base+'/datei?name=a.pdf',cookie=customer,raw=self.case.raw)[0],201)
        fid=self.auto.files(self.case.identity)[0]['id']
        self.case.payments.webhook(self.case.provider.payment['id'])
        self.assertEqual(self.request('GET',self.base+'/datei/'+fid,cookie=customer)[2],self.case.raw)
        self.assertEqual(self.request('GET',self.base+'/ergebnis',cookie=customer)[0],409)


if __name__=='__main__':unittest.main(verbosity=2)
