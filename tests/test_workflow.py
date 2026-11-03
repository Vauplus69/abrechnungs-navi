import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import http.client
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import workflow
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,TextStringObject

def pdf(active=False):
    writer=PdfWriter();writer.add_blank_page(width=100,height=100)
    if active:
        writer.add_js('app.alert("test")')
    stream=io.BytesIO();writer.write(stream);return stream.getvalue()

class Files(unittest.TestCase):
    def test_pdf_and_disguised_file(self):
        workflow.allowed_file('beleg.pdf',pdf())
        with self.assertRaises(ValueError):workflow.allowed_file('beleg.pdf',b'<script>bad</script>')
        with self.assertRaises(ValueError):workflow.allowed_file('beleg.pdf',pdf(True))
    def test_image_content_and_extension(self):
        from PIL import Image
        stream=io.BytesIO();Image.new('RGB',(10,10)).save(stream,format='PNG')
        workflow.allowed_file('a.png',stream.getvalue())
        with self.assertRaises(ValueError):workflow.allowed_file('a.jpg',stream.getvalue())
    def test_password(self):
        hashed=workflow.password_hash('test-code')
        self.assertTrue(workflow.password_ok('test-code',hashed))
        self.assertFalse(workflow.password_ok('wrong',hashed))
    def test_totp_rfc_vector(self):
        secret=base64.b32encode(b'12345678901234567890').decode()
        self.assertEqual(workflow.totp(secret,59),'287082')

class EndToEnd(unittest.TestCase):
    def test_gates_upload_publish_download_and_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';(data/'kunden').mkdir(parents=True)
            cfg=root/'operator.json';otp=root/'otp';backup=root/'backup'
            otp.write_text('JBSWY3DPEHPK3PXP');backup.write_text(str(time.time()))
            config={'provider_annex_complete':True,'disk_encryption_verified':True,
                    'provider_mfa_verified':True,'restore_tested_at':time.time(),
                    'backup_tested_at':time.time(),'backup_location':'TEST EXTERN',
                    'backup_retention_days':30,'avv_sha256':'TEST-ONLY'}
            cfg.write_text(json.dumps(config))
            env={'AN_DATA_DIR':str(data),'AN_OPERATOR_FILE':str(cfg),'AN_TOTP_FILE':str(otp),
                 'AN_BACKUP_MARKER':str(backup),'AN_TESTING':'1'}
            with patch.dict(os.environ,env):
                spec=importlib.util.spec_from_file_location('tested_upload',ROOT/'app/upload_app.py')
                app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
                app.send_withdrawal_confirmation=lambda row:True
                workflow.install(app)
                server=app.ThreadingHTTPServer(('127.0.0.1',0),app.H)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                admin_cookie='';client_cookie=''
                def request(method,path,body=None,cookie='',origin=True):
                    conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                    headers={}
                    if origin:headers['Origin']='http://127.0.0.1'
                    if cookie:headers['Cookie']=cookie
                    if isinstance(body,dict):body=urllib.parse.urlencode(body);headers['Content-Type']='application/x-www-form-urlencoded'
                    conn.request(method,path,body=body,headers=headers)
                    response=conn.getresponse();result=response.read();h=dict(response.getheaders());status=response.status;conn.close()
                    return status,h,result
                try:
                    self.assertEqual(request('GET','/verwaltung')[0],401)
                    status,headers,_=request('POST','/verwaltung/anmelden',{'otp':workflow.totp(otp.read_text())})
                    self.assertEqual(status,303);admin_cookie=headers['Set-Cookie'].split(';')[0]
                    self.assertEqual(request('GET','/verwaltung',cookie=admin_cookie)[0],200)
                    values={'name':'TEST SYNTHETIC','order':'TEST-001','contract_at':time.time()-15*86400,
                            'avv':'yes','paid':'yes','evidence':'TEST LOCAL ONLY'}
                    self.assertEqual(request('POST','/verwaltung/neu',{**values,'avv':'no'},admin_cookie)[0],400)
                    self.assertEqual(request('POST','/verwaltung/neu',{**values,'contract_at':time.time()},admin_cookie)[0],409)
                    cfg.unlink()
                    self.assertEqual(request('POST','/verwaltung/neu',values,admin_cookie)[0],503)
                    cfg.write_text(json.dumps(config))
                    status,_,body=request('POST','/verwaltung/neu',values,admin_cookie)
                    self.assertEqual(status,200)
                    import re
                    code=re.search(rb'uebermitteln\): ([A-Za-z0-9_-]+)',body).group(1).decode()
                    token=next(iter(app.load()))
                    self.assertEqual(request('PUT',f'/hochladen/api/{token}?name=beleg.pdf',pdf())[0],403)
                    status,headers,_=request('POST',f'/hochladen/{token}/anmelden',{'code':code})
                    self.assertEqual(status,303);client_cookie=headers['Set-Cookie'].split(';')[0]
                    self.assertEqual(request('PUT',f'/hochladen/api/{token}?name=beleg.pdf',pdf(),client_cookie,False)[0],403)
                    self.assertEqual(request('PUT',f'/hochladen/api/{token}?name=beleg.pdf',pdf(True),client_cookie)[0],400)
                    self.assertEqual(request('PUT',f'/hochladen/api/{token}?name=beleg.pdf',pdf(),client_cookie)[0],201)
                    self.assertEqual(request('PUT',f'/verwaltung/ergebnis/{token}',pdf(),admin_cookie)[0],201)
                    self.assertEqual(request('GET',f'/hochladen/{token}/datei/ergebnis.pdf',cookie=client_cookie)[0],404)
                    self.assertEqual(request('POST','/verwaltung/fertig',{'token':token},admin_cookie)[0],400)
                    self.assertEqual(request('POST','/verwaltung/fertig',{'token':token,'reviewed':'yes','notice':'yes'},admin_cookie)[0],200)
                    deadline=app.load()[token]['delete_at']
                    self.assertEqual(request('POST','/verwaltung/fertig',{'token':token,'reviewed':'yes','notice':'yes'},admin_cookie)[0],409)
                    self.assertEqual(app.load()[token]['delete_at'],deadline)
                    self.assertEqual(request('GET',f'/hochladen/{token}/datei/ergebnis.pdf',cookie=client_cookie)[0],200)
                    self.assertEqual(request('GET',f'/hochladen/{token}/datei/beleg.pdf',cookie=client_cookie)[0],200)
                    self.assertEqual(request('PUT',f'/hochladen/api/{token}?name=weiter.pdf',pdf(),client_cookie)[0],403)
                    self.assertEqual(request('POST','/verwaltung/offen',{'token':token},admin_cookie)[0],400)
                    self.assertEqual(request('PUT',f'/verwaltung/ergebnis/{token}',pdf(),admin_cookie)[0],201)
                    self.assertEqual(request('GET',f'/hochladen/{token}/datei/ergebnis-entwurf.pdf',cookie=client_cookie)[0],404)
                    self.assertEqual(request('POST','/verwaltung/fertig',{'token':token,'reviewed':'yes','notice':'yes'},admin_cookie)[0],200)
                    self.assertEqual(app.load()[token]['delete_at'],deadline)
                    # Fristablauf: keine Verlaengerung, Download gesperrt, Dateien wirklich entfernt.
                    db=app.load();db[token]['delete_at']=time.time()-1;app.save(db)
                    self.assertEqual(request('GET',f'/hochladen/{token}/datei/beleg.pdf',cookie=client_cookie)[0],404)
                    app.cleanup();self.assertFalse(Path(app.customer_dir(token)).exists());self.assertNotIn(token,app.load())
                    log=(data/'audit.jsonl').read_text()
                    self.assertNotIn(token,log);self.assertNotIn('TEST SYNTHETIC',log)
                    # Widerruf in zwei Schritten; kein echter Mailversand.
                    w={'name':'TEST','email':'test@example.invalid','vertrag':'TEST-001'}
                    self.assertIn(b'Widerruf bestaetigen',request('POST','/widerruf/pruefen',w)[2])
                    self.assertEqual(request('POST','/widerruf',{**w,'confirm':'yes'})[0],200)
                    self.assertTrue(json.loads((data/'widerrufe.json').read_text())[0]['mail'])
                    # Alter Bestand behaelt alte Frist; keine stille Migration.
                    app.save({'A'*32:{'name':'LEGACY','created':time.time(),'expires':time.time(),'done':time.time()}})
                    self.assertGreater(app.delete_at(app.load()['A'*32]),time.time()+180*86400)
                finally:
                    server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
