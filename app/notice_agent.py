"""Production notification agent: fixed templates, durable outbox, no blind SMTP retry."""
from datetime import datetime
from email.message import EmailMessage
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from notification_templates import TEMPLATES,VERSION

MAILBOX = 'kontakt@abrechnungs-navi.de'
EVENTS = set(TEMPLATES)
ISSUES = {
    'advances': 'Die Vorauszahlungen konnten noch nicht eindeutig den Mietparteien und Zeiträumen zugeordnet werden. Bitte prüfen und ergänzen Sie die Angaben im Kundenbereich.',
    'master_data': 'Die Angaben zu Objekt, Abrechnungsjahr, Wohnungen, Flächen oder Vermieter konnten noch nicht vollständig zugeordnet werden. Bitte prüfen Sie die Unterlagen im Kundenbereich.',
    'scope': 'Objekt oder Abrechnungsjahr passen beim automatischen Abgleich noch nicht eindeutig zum Auftrag. Bitte prüfen Sie den Belegbestand im Kundenbereich.'}


def otp(secret, order, nonce):
    raw = hmac.new(secret, ('login:' + order + ':' + nonce).encode(), 'sha256').digest()
    return f'{int.from_bytes(raw[:8], "big") % 1000000:06d}'


class Notifications:
    def __init__(self, ledger):
        self.ledger = ledger
        with ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS notification_events('
                'id TEXT PRIMARY KEY,order_id TEXT NOT NULL,event TEXT NOT NULL,version TEXT NOT NULL,'
                'payload TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,'
                'template_version TEXT NOT NULL)')
            if 'template_version' not in {row['name'] for row in db.execute('PRAGMA table_info(notification_events)')}:
                db.execute("ALTER TABLE notification_events ADD COLUMN template_version TEXT NOT NULL DEFAULT 'legacy-review-required'")
            db.execute('CREATE TABLE IF NOT EXISTS notification_deliveries(event_id TEXT PRIMARY KEY,recipient TEXT NOT NULL,created REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS notification_receipts(id TEXT PRIMARY KEY,event_id TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL)')

    def enqueue(self, identity, event, version, payload=None, *, db=None):
        if event not in EVENTS or not re.fullmatch(r'AN-[a-f0-9]{32}', identity):
            raise ValueError('Ungültiger Benachrichtigungsanlass')
        key = hashlib.sha256(json.dumps([identity,event,str(version)]).encode()).hexdigest()
        def insert(connection):
            connection.execute('INSERT OR IGNORE INTO notification_events VALUES(?,?,?,?,?,?,?,?,?)',
                (key, identity, event, str(version), json.dumps(payload or {}), 'queued', time.time(), time.time(),VERSION))
        if db is not None:
            insert(db)
        else:
            with self.ledger.db() as connection:insert(connection)
        return key

    def render(self, record, context, secret):
        event=record['event'];payload=json.loads(record['payload'])
        if event not in TEMPLATES:raise ValueError('Unbekannte Mailvorlage')
        if record.get('template_version',VERSION)!=VERSION:raise ValueError('Mailvorlage muss erneut geprüft werden')
        template=TEMPLATES[event]
        recipient=MAILBOX if template['recipient']=='operator' else context['email']
        if not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+',recipient):raise ValueError('Ungültiger Empfänger')
        order=record['order_id']
        if not re.fullmatch(r'AN-[a-f0-9]{32}',order):raise ValueError('Ungültiger Auftragsbezug')
        if event=='access_code' and context.get('checkout_access') is True:
            nonce=payload.get('nonce','')
            if context.get('checkout_notification_verified') is not True or context.get('order_id')!=order or not re.fullmatch(r'[a-f0-9]{32}',nonce) or record['version']!='checkout:'+nonce:
                raise ValueError('Ungeprüfte Dokumentenanmeldung')
            text=template['text'].format_map({'access_code':otp(secret,order,nonce)})
            return dict(to=recipient,subject=template['subject'],text=text,event_id=record['id'],attachments=[],template_version=VERSION)
        checkout_fields={
            'order_confirmation':('order_date','service_description','total_price','contract_download_url','start_notice'),
            'invoice_available':('invoice_number','invoice_date','invoice_total','invoice_url'),
            'payment_action_required':('order_url',),
        }
        if event in checkout_fields:
            # Text creation only: the checkout integration must supply verified
            # persisted state. No customer/document payload may populate these.
            if context.get('checkout_notification_verified') is not True:
                raise ValueError('Bestellbenachrichtigung noch nicht angebunden und geprüft')
            if context.get('order_id')!=order:
                raise ValueError('Falsche Bestellzuordnung')
            if event=='order_confirmation' and not (context.get('order_accepted') is True and context.get('contract_download_ready') is True):
                raise ValueError('Bestellbestätigung noch nicht verfügbar')
            if event=='invoice_available' and not (context.get('invoice_issued') is True and context.get('invoice_download_ready') is True):
                raise ValueError('Festgeschriebene Rechnung noch nicht verfügbar')
            if event=='payment_action_required' and not (context.get('payment_state') in ('failed','canceled','expired') and context.get('payment_retry_allowed') is True):
                raise ValueError('Kein bestätigter fehlgeschlagener Zahlungsversuch')
            values={'order_id':order}
            for field in checkout_fields[event]:
                value=context.get(field)
                if not isinstance(value,str) or not value.strip() or len(value)>3000 or any(ord(c)<32 for c in value):
                    raise ValueError('Fehlender oder ungültiger Bestellplatzhalter')
                if field.endswith('_url'):
                    url=urlsplit(value)
                    if url.scheme!='https' or url.netloc!='abrechnungs-navi.de' or not url.path.startswith('/bestellen/') or url.fragment:
                        raise ValueError('Unzulässiger Bestelllink')
                values[field]=value
            return dict(to=recipient,subject=template['subject'],text=template['text'].format_map(values),
                        event_id=record['id'],attachments=[],template_version=VERSION)
        token=context['token']
        if not re.fullmatch(r'AN-[a-f0-9]{32}',order) or not re.fullmatch(r'[A-Za-z0-9_-]{32}',token):raise ValueError('Ungültiger Auftragsbezug')
        values=dict(portal_url='https://abrechnungs-navi.de/kunden/'+token,
                    operator_url='https://abrechnungs-navi.de/verwaltung/agenten/'+order,
                    order_id=order,version=record['version'],access_code='',issue_list='',deadline='')
        if event=='access_code':
            if not re.fullmatch(r'[a-f0-9]{32}',payload.get('nonce','')):raise ValueError('Ungültige Code-Anforderung')
            values['access_code']=otp(secret,order,payload['nonce'])
        elif event=='missing_inputs':
            codes=payload.get('codes',[])
            if not codes or any(code not in ISSUES for code in codes):raise ValueError('Ungeprüfte Rückfrage')
            values['issue_list']='\n'.join('- '+ISSUES[code] for code in sorted(set(codes)))
        elif event=='ready':
            values['deadline']=datetime.fromtimestamp(context['expires'],ZoneInfo('Europe/Berlin')).strftime('%d.%m.%Y um %H:%M Uhr')
        return dict(to=recipient,subject=template['subject'],text=template['text'].format_map(values),
                    event_id=record['id'],attachments=[],template_version=VERSION)

    def deliver_one(self, automation, sender):
        with self.ledger.db() as db:
            row = db.execute("SELECT * FROM notification_events WHERE state='queued' AND updated<=? ORDER BY updated LIMIT 1",(time.time(),)).fetchone()
        if row is None: return False
        if row['template_version']!=VERSION:
            with self.ledger.db() as db:
                db.execute("UPDATE notification_events SET state='template_review',updated=? WHERE id=? AND state='queued'",(time.time(),row['id']))
            return True
        disposition, context = automation.notice_context(dict(row))
        with self.ledger.db() as db:
            if disposition in ('defer','obsolete'):
                db.execute('UPDATE notification_events SET state=?,updated=? WHERE id=? AND state=?',
                    ('queued' if disposition=='defer' else 'obsolete',time.time()+60 if disposition=='defer' else time.time(),row['id'],'queued'))
                return True
            if db.execute("UPDATE notification_events SET state='reserved',updated=? WHERE id=? AND state='queued'",(time.time(),row['id'])).rowcount != 1:
                return True
        try:
            # Recheck the source version immediately before external delivery.
            disposition, context = automation.notice_context(dict(row))
            if disposition != 'send':
                with self.ledger.db() as db:
                    db.execute('UPDATE notification_events SET state=?,updated=? WHERE id=?',
                               ('queued' if disposition=='defer' else 'obsolete',time.time(),row['id']))
                return True
            key=automation.notification_secret(dict(row)) if callable(getattr(automation,'notification_secret',None)) else automation.secret()
            notice=self.render(dict(row),context,key)
            with self.ledger.db() as db:
                db.execute('INSERT OR IGNORE INTO notification_deliveries VALUES(?,?,?)',(row['id'],notice['to'],time.time()))
            sender(notice)
        except Exception:
            with self.ledger.db() as db:
                db.execute("UPDATE notification_events SET state='delivery_uncertain',updated=? WHERE id=?",(time.time(),row['id']))
            return True
        with self.ledger.db() as db:
            db.execute("UPDATE notification_events SET state='smtp_accepted',updated=? WHERE id=?",(time.time(),row['id']))
        return True


class SmtpSender:
    def __init__(self, password_path, credential_directory=None):
        self.password_path = Path(password_path); self.credential_directory=credential_directory
    def __call__(self, notice):
        from mollie_payments import protected_file
        password = protected_file(self.password_path,self.credential_directory).read_text().strip()
        if not password or notice.get('attachments') != []: raise ValueError('Versand nicht zulässig')
        msg=EmailMessage();msg['From']='Abrechnungs-Navi <'+MAILBOX+'>';msg['Reply-To']=MAILBOX
        msg['To']=notice['to'];msg['Subject']=notice['subject'];msg['Message-ID']='<'+notice['event_id']+'@abrechnungs-navi.de>'
        from invoicing import issuer
        sender=issuer(os.environ.get('AN_INVOICE_ISSUER_FILE','/etc/an-upload/invoice-issuer.json'))
        footer='\n'.join(sender[k] for k in ('name','address','city','email'))
        msg.set_content(notice['text']+'\n\n'+footer)
        with smtplib.SMTP('smtp.hostinger.com',587,timeout=25) as smtp:
            smtp.starttls(context=ssl.create_default_context());smtp.login(MAILBOX,password)
            if smtp.send_message(msg): raise RuntimeError('Empfänger nicht angenommen')
