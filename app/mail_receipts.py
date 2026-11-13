"""Read-only inbox evidence. Delivery reports are reports, not proof of reading.

No automatic resend, no arbitrary links, no attachments retained from incoming mail.
"""
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import hashlib
import imaplib
import re
import ssl
import time

from notice_agent import MAILBOX
from mollie_payments import protected_file


def record_report(ledger, raw):
    if len(raw)>65536:return False
    message=BytesParser(policy=policy.default).parsebytes(raw)
    if message.get_content_type()!='multipart/report' or message.get_param('report-type')!='delivery-status':return False
    message_id=message.get('Original-Envelope-Id','')
    for part in message.walk():
        if part.get_content_type()=='message/rfc822':
            for original in part.get_payload() or []:
                message_id=original.get('Message-ID','')
        if part.get_content_type()=='text/rfc822-headers':
            original=BytesParser(policy=policy.default).parsebytes(part.get_payload(decode=True) or b'')
            message_id=original.get('Message-ID','')
    match=re.fullmatch(r'<([a-f0-9]{64})@abrechnungs-navi\.de>',str(message_id).strip())
    if not match:return False
    event_id=match[1];reports=[]
    for part in message.walk():
        if part.get_content_type()!='message/delivery-status':continue
        for block in part.get_payload() or []:
            recipient=str(block.get('Final-Recipient','')).split(';')[-1].strip().lower()
            action=str(block.get('Action','')).strip().lower()
            status=str(block.get('Status','')).strip()
            if (action,status[:1]) in (('failed','5'),('delayed','4'),('delivered','2')):
                reports.append((recipient,action,status))
    with ledger.db() as db:
        row=db.execute('SELECT recipient FROM notification_deliveries WHERE event_id=?',(event_id,)).fetchone()
        if row is None:return False
        matched=[x for x in reports if x[0]==row['recipient'].lower()]
        if len(matched)!=1:return False
        recipient,action,status=matched[0]
        if not re.fullmatch(r'[245]\.[0-9]{1,3}\.[0-9]{1,3}',status):return False
        evidence=hashlib.sha256(raw).hexdigest()
        db.execute('INSERT OR IGNORE INTO notification_receipts VALUES(?,?,?,?,?)',
                   (evidence,event_id,action+'_reported',status,time.time()))
        # Reports can be spoofed: operator review is required; never trigger retry.
        if action in ('failed','delayed'):
            db.execute("UPDATE notification_events SET state='delivery_report_review',updated=? WHERE id=? AND state IN ('smtp_accepted','delivery_uncertain','delivery_report_review')",(time.time(),event_id))
    return True


def reconcile(ledger,password_path,credential_directory=None):
    password=protected_file(password_path,credential_directory).read_text().strip()
    checked=0
    with imaplib.IMAP4_SSL('imap.hostinger.com',993,ssl_context=ssl.create_default_context(),timeout=10) as inbox:
        inbox.login(MAILBOX,password)
        if inbox.select('INBOX',readonly=True)[0]!='OK':raise ValueError('Posteingang nicht lesbar')
        # Only own-address receipts can be confirmed by this mailbox.
        with ledger.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS mail_inbox_checks(event_id TEXT PRIMARY KEY,checked REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS mail_receipt_cursor(validity TEXT PRIMARY KEY,last_uid INTEGER NOT NULL)')
            rows=db.execute("SELECT d.event_id FROM notification_deliveries d JOIN notification_events e ON e.id=d.event_id LEFT JOIN mail_inbox_checks c ON c.event_id=d.event_id WHERE d.recipient=? AND e.state IN ('smtp_accepted','delivery_uncertain') ORDER BY COALESCE(c.checked,0),e.updated LIMIT 2",(MAILBOX,)).fetchall()
        for row in rows:
            identity=row['event_id'];mid='<'+identity+'@abrechnungs-navi.de>'
            kind,data=inbox.uid('search',None,'HEADER','Message-ID','"'+mid+'"')
            if kind!='OK':raise ValueError('Posteingangsabgleich fehlgeschlagen')
            for uid in (data[0] or b'').split()[-2:]:
                kind,data=inbox.uid('fetch',uid,'(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM TO)])')
                if kind!='OK':continue
                raw=next((item[1] for item in data if isinstance(item,tuple)),b'')
                msg=BytesParser(policy=policy.default).parsebytes(raw)
                if str(msg.get('Message-ID','')).strip()!=mid or parseaddr(msg.get('From',''))[1]!=MAILBOX or parseaddr(msg.get('To',''))[1]!=MAILBOX:continue
                with ledger.db() as db:
                    db.execute('INSERT OR IGNORE INTO notification_receipts VALUES(?,?,?,?,?)',(hashlib.sha256(raw).hexdigest(),identity,'own_inbox_confirmed','',time.time()))
                    db.execute("UPDATE notification_events SET state='own_inbox_confirmed',updated=? WHERE id=? AND state IN ('smtp_accepted','delivery_uncertain')",(time.time(),identity))
                checked+=1
            with ledger.db() as db:
                db.execute('INSERT INTO mail_inbox_checks VALUES(?,?) ON CONFLICT(event_id) DO UPDATE SET checked=excluded.checked',(identity,time.time()))
        validity_data=inbox.response('UIDVALIDITY')[1]
        validity=(validity_data[0] or b'').decode('ascii')
        if not re.fullmatch(r'[0-9]+',validity):raise ValueError('Postfachkennung fehlt')
        with ledger.db() as db:
            prior=db.execute('SELECT last_uid FROM mail_receipt_cursor WHERE validity=?',(validity,)).fetchone()
            last=prior['last_uid'] if prior else 0
        kind,data=inbox.uid('search',None,'UID',str(last+1)+':*','HEADER','Content-Type','"multipart/report"')
        if kind!='OK':raise ValueError('Rückläuferabgleich fehlgeschlagen')
        for uid in [u for u in (data[0] or b'').split() if int(u)>last][:3]:
            kind,data=inbox.uid('fetch',uid,'(BODY.PEEK[]<0.65537>)')
            if kind!='OK':continue
            raw=next((item[1] for item in data if isinstance(item,tuple)),b'')
            if record_report(ledger,raw):checked+=1
            with ledger.db() as db:
                db.execute('INSERT INTO mail_receipt_cursor VALUES(?,?) ON CONFLICT(validity) DO UPDATE SET last_uid=excluded.last_uid',(validity,int(uid)))
    return checked
