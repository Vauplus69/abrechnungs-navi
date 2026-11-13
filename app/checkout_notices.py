"""Persisted buyer notices and OTP-protected access to immutable invoice/contract bytes."""
from datetime import datetime
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import time
import zipfile
from zoneinfo import ZoneInfo

import invoicing
from notice_agent import Notifications, otp

CHECKOUT_EVENTS={'order_confirmation','invoice_available'}


class CheckoutNotices:
    def __init__(self,ledger):
        self.ledger=ledger;self.notices=Notifications(ledger)
        with ledger.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS checkout_mail_challenges(
                order_id TEXT PRIMARY KEY,nonce TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,
                failures INTEGER NOT NULL DEFAULT 0,used INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS checkout_mail_requests(order_id TEXT NOT NULL,created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS checkout_mail_sessions(
                id TEXT PRIMARY KEY,order_id TEXT NOT NULL,expires REAL NOT NULL);
            ''')

    def secret(self):
        path=self.ledger.folder/'checkout-notification.secret'
        if not path.exists():
            try:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as f:f.write(secrets.token_bytes(32))
            except FileExistsError:pass
        from mollie_payments import protected_file
        raw=protected_file(path).read_bytes()
        if len(raw)!=32:raise ValueError('Ungültiger Benachrichtigungsschlüssel')
        return raw

    def order(self,identity=None,offer_id=None):
        with self.ledger.db() as db:
            row=db.execute('SELECT a.payload AS acceptance,o.id,o.payload AS offer,o.sha256 FROM checkout_acceptances a '
                'JOIN checkout_offers o ON o.id=a.offer_id WHERE '+('a.order_id=?' if identity else 'o.id=?'),(identity or offer_id,)).fetchone()
            if row is None:raise ValueError('Bestellung nicht verfügbar')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='auto_orders'").fetchone():
                blocked=db.execute('SELECT withdrawn,expires,state FROM auto_orders WHERE order_id=?',
                    (json.loads(row['acceptance'])['id'],)).fetchone()
                if blocked and (blocked['withdrawn'] or blocked['expires']<=time.time() or blocked['state'] in ('closed','deletion_requested','local_deleted')):
                    raise ValueError('Bestellung gesperrt')
            docs=[dict(d) for d in db.execute('SELECT * FROM checkout_documents WHERE offer_id=?',(row['id'],))]
        accepted=json.loads(row['acceptance']);offer=json.loads(row['offer'])
        if hashlib.sha256(row['offer'].encode()).hexdigest()!=row['sha256'] or accepted['offer_sha256']!=row['sha256']:
            raise ValueError('Vertragsnachweis verändert')
        if accepted['id']!=offer['order']['reference'] or not re.fullmatch(r'AN-[a-f0-9]{32}',accepted['id']):raise ValueError('Falsche Bestellung')
        if accepted.get('offer_id')!=row['id'] or any(accepted.get(k)!=offer['order'][k] for k in ('apartments','houses','total_cents')):
            raise ValueError('Bestellung stimmt nicht mit Angebot überein')
        if not all(accepted.get(k) is True for k in ('contract_accepted','avv_accepted','consumer_information_delivered')):raise ValueError('Vertragsabschluss fehlt')
        if len(docs)!=3:raise ValueError('Vertragsunterlagen fehlen')
        for kind,field in [('avv','avv_sha256'),('terms','terms_sha256'),('consumer','consumer_information_sha256')]:
            d=next((d for d in docs if d['kind']==kind),None)
            if not d or hashlib.sha256(d['raw']).hexdigest()!=d['sha256'] or d['sha256']!=accepted[field] or d['sha256']!=offer['documents'][kind]['sha256']:
                raise ValueError('Vertragsunterlage verändert')
        return dict(accepted=accepted,offer=offer,offer_id=row['id'],docs=docs)

    def invoice(self,data):
        with self.ledger.db() as db:
            link=db.execute('SELECT invoice_id FROM checkout_invoice_links WHERE order_id=?',(data['accepted']['id'],)).fetchone()
            if not link or db.execute('SELECT 1 FROM invoices WHERE original_id=?',(link['invoice_id'],)).fetchone():raise ValueError('Rechnung nicht verfügbar')
        row=self.ledger.get(link['invoice_id']);payload=json.loads(row['payload'])
        if payload['order']!=data['offer']['order'] or payload['issuer']!=data['offer']['issuer']:raise ValueError('Rechnung falsch zugeordnet')
        return row,payload

    def packet(self,data):
        stream=io.BytesIO();a=data['accepted'];o=data['offer'];d=o['order']
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('Auftragsbestaetigung.json',json.dumps(a,ensure_ascii=False,indent=2))
            z.writestr('Angebot.json',json.dumps(o,ensure_ascii=False,indent=2))
            z.writestr('Auftragsbestaetigung.txt','\n'.join([
                'ABRECHNUNGS-NAVI – Auftragsbestätigung','Auftragsnummer: '+a['id'],
                'Rechnungsempfänger: '+d['customer'],'Anschrift: '+d['address']+', '+d['city'],
                'E-Mail: '+o['email'],'Objekt: '+o['property_address'],'Abrechnungsjahr: '+str(d['year']),
                'Wohnungen: '+str(d['apartments'])+'; Häuser: '+str(d['houses']),
                'Gesamtpreis einmalig: '+invoicing.money(d['total_cents']),invoicing.NOTICE,
                'Angenommen am: '+datetime.fromtimestamp(a['accepted_at'],ZoneInfo('Europe/Berlin')).isoformat(),
                'Voraussichtlicher Leistungsbeginn: '+d['service_date']+' (keine Terminzusage)',
                'Kein vorzeitiger Leistungsbeginn vereinbart. Kein Zahlungs- oder Leistungsnachweis.',
                'Die unveränderten Vertragsfassungen einschließlich AV-Vertrag und Widerrufsunterlagen liegen bei.',
                'Kontakt: kontakt@abrechnungs-navi.de']))
            for doc in data['docs']:
                z.writestr(doc['kind']+('.pdf' if doc['mime']=='application/pdf' else '.txt'),doc['raw'])
        return stream.getvalue()

    def notice_context(self,record):
        try:
            data=self.order(identity=record['order_id']);a=data['accepted'];o=data['offer'];payload=json.loads(record['payload'])
            if payload.get('offer_id')!=data['offer_id']:return 'obsolete',{}
            base='https://abrechnungs-navi.de/bestellen/'+data['offer_id']+'/dokumente/'
            context=dict(email=o['email'],order_id=a['id'],checkout_notification_verified=True)
            if record['event']=='access_code':
                with self.ledger.db() as db:c=db.execute('SELECT * FROM checkout_mail_challenges WHERE order_id=?',(a['id'],)).fetchone()
                if not c or c['used'] or c['failures']>=5 or c['expires']<=time.time() or c['nonce']!=payload.get('nonce') or record['version']!='checkout:'+c['nonce']:
                    return 'obsolete',{}
                return 'send',dict(context,checkout_access=True)
            if record['event']=='order_confirmation':
                if record['version']!=data['offer_id']:return 'obsolete',{}
                from automation_core import conservative_start
                start=conservative_start(a['accepted_at'],o['order']['service_date'])
                return 'send',dict(context,order_accepted=True,contract_download_ready=True,
                    order_date=datetime.fromtimestamp(a['accepted_at'],ZoneInfo('Europe/Berlin')).strftime('%d.%m.%Y'),
                    service_description=f"Nebenkostenabrechnung {o['order']['year']}: {o['order']['apartments']} Wohnung(en) in {o['order']['houses']} Haus/Häusern",
                    total_price=invoicing.money(o['order']['total_cents']),contract_download_url=base+'vertrag',
                    start_notice='Sie haben keinen vorzeitigen Beginn verlangt. Die Bearbeitung beginnt frühestens am '+datetime.fromtimestamp(start,ZoneInfo('Europe/Berlin')).strftime('%d.%m.%Y')+', nach Ablauf der maßgeblichen Widerrufsfrist und Erfüllung der weiteren vereinbarten Voraussetzungen.')
            if record['event']=='invoice_available':
                invoice,p=self.invoice(data)
                if record['version']!=str(invoice['id']):return 'obsolete',{}
                return 'send',dict(context,invoice_issued=True,invoice_download_ready=True,
                    invoice_number=invoice['number'],invoice_date=datetime.fromisoformat(p['issued']).strftime('%d.%m.%Y'),
                    invoice_total=invoicing.money(p['order']['total_cents']),invoice_url=base+'rechnung')
        except (ValueError,KeyError,TypeError,OSError):return 'obsolete',{}
        return 'obsolete',{}

    def request_code(self,offer_id):
        data=self.order(offer_id=offer_id);identity=data['accepted']['id'];now=time.time();self.secret()
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            last=db.execute('SELECT MAX(created),COUNT(*) FROM checkout_mail_requests WHERE order_id=? AND created>?',(identity,now-3600)).fetchone()
            if last[1]>=5 or last[0] and now-last[0]<60:return False
            nonce=secrets.token_hex(16)
            db.execute('INSERT OR REPLACE INTO checkout_mail_challenges VALUES(?,?,?,?,0,0)',(identity,nonce,now,now+600))
            db.execute('INSERT INTO checkout_mail_requests VALUES(?,?)',(identity,now))
            db.execute('DELETE FROM checkout_mail_requests WHERE created<?',(now-3600,))
            self.notices.enqueue(identity,'access_code','checkout:'+nonce,{'scope':'checkout','offer_id':offer_id,'nonce':nonce},db=db)
        return True

    def authenticate(self,offer_id,code):
        data=self.order(offer_id=offer_id);identity=data['accepted']['id'];now=time.time()
        token=secrets.token_urlsafe(32);valid=False
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            c=db.execute('SELECT * FROM checkout_mail_challenges WHERE order_id=?',(identity,)).fetchone()
            if c and not c['used'] and c['expires']>now and c['failures']<5:
                valid=isinstance(code,str) and re.fullmatch(r'\d{6}',code) and secrets.compare_digest(code,otp(self.secret(),identity,c['nonce']))
                if valid:
                    db.execute('UPDATE checkout_mail_challenges SET used=1 WHERE order_id=?',(identity,))
                    db.execute('DELETE FROM checkout_mail_sessions WHERE expires<=?',(now,))
                    db.execute('INSERT INTO checkout_mail_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),identity,now+1800))
                else:db.execute('UPDATE checkout_mail_challenges SET failures=failures+1 WHERE order_id=?',(identity,))
        if not valid:raise ValueError('Code ungültig oder abgelaufen')
        return token

    def authorize(self,offer_id,token):
        data=self.order(offer_id=offer_id)
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('Anmeldung erforderlich')
        with self.ledger.db() as db:
            s=db.execute('SELECT order_id,expires FROM checkout_mail_sessions WHERE id=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not s or s['order_id']!=data['accepted']['id'] or s['expires']<=time.time():raise ValueError('Anmeldung erforderlich')
        return data
