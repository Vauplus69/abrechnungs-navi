import concurrent.futures
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from consent_tracking import Receipts

class ReceiptTests(unittest.TestCase):
    def test_consent_and_single_use(self):
        store=Receipts()
        self.assertEqual(store.issue('no'),{})
        self.assertEqual(store.issue(''),{})
        header=store.issue('yes')['Set-Cookie']
        self.assertIn('Secure; HttpOnly; SameSite=Strict',header)
        self.assertIn('Max-Age=120',header)
        identity=store.consume(header.split(';')[0])
        self.assertRegex(identity,'^[a-f0-9]{32}$')
        self.assertIsNone(store.consume(header.split(';')[0]))
        self.assertIsNone(store.consume('an_conversion=guess'))

    def test_expiry_and_concurrent_consumption(self):
        store=Receipts()
        with patch('consent_tracking.time.time',return_value=100):h=store.issue('yes')['Set-Cookie'].split(';')[0]
        with patch('consent_tracking.time.time',return_value=221):self.assertIsNone(store.consume(h))
        h=store.issue('yes')['Set-Cookie'].split(';')[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(store.consume,[h]*4))
        self.assertEqual(sum(x is not None for x in results),1)

    def test_http_only_real_saved_request_has_receipt(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'AN_DATA_DIR':tmp,'AN_TESTING':'1','AN_OPERATOR_FILE':tmp+'/no-release','AN_INVOICE_DIR':tmp+'/invoices'}):
            spec=importlib.util.spec_from_file_location('tracking_test_app',ROOT/'app/upload_app.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app);app.install(app)
            (Path(tmp)/'kunden').mkdir(exist_ok=True)
            # No SMTP, customer data or real customer request involved.
            app.mail_and_mark=lambda row:None
            server=app.ThreadingHTTPServer(('127.0.0.1',0),app.H);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(path,data=None,cookie='',origin='http://127.0.0.1'):
                c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                body=urllib.parse.urlencode(data or {});c.request('POST',path,body,{'Origin':origin,'Cookie':cookie,'Content-Type':'application/x-www-form-urlencoded'})
                r=c.getresponse();result=r.status,dict(r.getheaders()),r.read();c.close();return result
            values={'name':'SYNTHETIC ONLY','email':'synthetic@example.invalid','wohnungen':'1','jahr':'2025','ads_consent':'yes'}
            try:
                self.assertEqual(request('/tracking/receipt')[0],204)
                self.assertEqual(request('/tracking/receipt',origin='https://foreign.invalid')[0],403)
                for changes in [{'name':''},{'website':'spam'},{'ads_consent':'no'}]:
                    status,headers,_=request('/anfrage',dict(values,**changes));self.assertNotIn('Set-Cookie',headers)
                status,headers,_=request('/anfrage',values);self.assertEqual(status,303)
                cookie=headers['Set-Cookie'].split(';')[0]
                status,headers,body=request('/tracking/receipt',cookie=cookie);self.assertEqual(status,200)
                payload=json.loads(body);self.assertEqual(set(payload),{'transaction_id'});self.assertNotIn(b'SYNTHETIC',body)
                self.assertRegex(payload['transaction_id'],'^[a-f0-9]{32}$')
                self.assertIn('Max-Age=0',headers['Set-Cookie'])
                self.assertEqual(request('/tracking/receipt',cookie=cookie)[0],204)
                self.assertEqual(request('/tracking/receipt',cookie=cookie)[2],b'')
                self.assertEqual(len(app.load_anfragen()),2)
            finally:server.shutdown();server.server_close();thread.join()
