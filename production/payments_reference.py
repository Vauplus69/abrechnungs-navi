"""Mollie test-only adapter: callbacks retrieve authoritative state, never trust POST paid=true."""
import json,re,hashlib
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*a,**kw):return None
class MollieTest:
 def __init__(self,key_path,webhook_url=None):
  p=Path(key_path)
  if p.stat().st_mode & 0o077:raise ValueError('Mollie-Testschlüssel muss 0600 sein')
  self.key=p.read_text().strip();self.webhook_url=webhook_url
  if webhook_url and not webhook_url.startswith('https://abrechnungs-navi.de/'):raise ValueError('Nur eigene AN-Webhook-Adresse erlaubt')
  if not self.key.startswith('test_') or not re.fullmatch(r'test_[A-Za-z0-9]+',self.key):raise ValueError('Nur Mollie-Testschlüssel erlaubt')
 def request(self,method,path,body=None,idempotency=None):
  if not (re.fullmatch(r'/payments(?:/tr_[A-Za-z0-9]+)?',path) or method=='GET' and path=='/profiles/me'):raise ValueError('Ungültiger Zahlungs-API-Pfad')
  headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'}
  if idempotency:headers['Idempotency-Key']=idempotency
  req=Request('https://api.mollie.com/v2'+path,data=json.dumps(body).encode() if body else None,headers=headers,method=method)
  try:
   with build_opener(NoRedirect()).open(req,timeout=25) as r:
    raw=r.read(1000001)
    if len(raw)>1000000:raise ValueError('Antwortlimit')
    return json.loads(raw)
  except Exception:raise RuntimeError('Mollie-Anfrage fehlgeschlagen; Status vor Wiederholung prüfen') from None
 def verify_profile(self):
  p=self.request('GET','/profiles/me')
  if p.get('id')!='pfl_2fcc6rqot8' or p.get('website','').rstrip('/')!='https://abrechnungs-navi.de':raise ValueError('Falsches Mollie-Profil')
  return p['id']
 def create(self,order,base):
  body={'amount':{'currency':'EUR','value':f'{order["total_cents"]/100:.2f}'},'description':'TEST Abrechnungs-Navi '+order['id'],'metadata':{'order_id':order['id'],'brand':'abrechnungs-navi'},'redirectUrl':base+'/payment/'+order['token'],'locale':'de_DE'}
  if self.webhook_url:body['webhookUrl']=self.webhook_url
  return self.request('POST','/payments',body,hashlib.sha256(('AN-TEST-'+order['id']).encode()).hexdigest())
 def retrieve(self,payment_id):return self.request('GET','/payments/'+payment_id)

def verified_payment(payment,order):
 if payment.get('profileId')!='pfl_2fcc6rqot8':raise ValueError('Falsches Mollie-Profil')
 if payment.get('mode')!='test' or payment.get('id')!=order['payment_id']:raise ValueError('Falscher Zahlungsmodus oder falsche Zahlungs-ID')
 if payment.get('metadata',{}).get('order_id')!=order['id'] or payment.get('metadata',{}).get('brand')!='abrechnungs-navi':raise ValueError('Zahlung gehört nicht zu diesem Auftrag')
 amount=payment.get('amount',{})
 if amount.get('currency')!='EUR' or amount.get('value')!=f'{order["total_cents"]/100:.2f}':raise ValueError('Zahlbetrag stimmt nicht')
 return payment.get('status')=='paid'
