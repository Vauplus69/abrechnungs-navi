import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from invoicing import Ledger
from notice_agent import Notifications
from mail_receipts import record_report,reconcile
from provider_cleanup import cleanup_one
from restore_guard import fence


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.ledger=Ledger(self.root,self.root/'issuer.json');Notifications(self.ledger)
        with self.ledger.db() as db:
            db.execute('CREATE TABLE auto_provider_deletions(id TEXT PRIMARY KEY,file_id TEXT,run_id TEXT,state TEXT,created REAL)')
            db.execute("INSERT INTO auto_provider_deletions VALUES('one','file_ABC','exr_ABC','pending',0)")
    def tearDown(self):self.temp.cleanup()
    def state(self):
        with self.ledger.db() as db:return db.execute('SELECT state FROM auto_provider_deletions').fetchone()[0]
    def test_delete_requires_verified_absence_and_is_idempotent(self):
        present={'/files/file_ABC','/extract_runs/exr_ABC'};calls=[]
        def provider(method,path):
            calls.append((method,path))
            if method=='GET':return 200 if path in present else 404
            present.discard(path);return 200
        self.assertTrue(cleanup_one(self.ledger,provider,0));self.assertEqual(self.state(),'verified_absent')
        self.assertFalse(cleanup_one(self.ledger,provider,1000));self.assertEqual(len(calls),6)
    def test_delete_200_with_still_visible_data_remains_retry(self):
        cleanup_one(self.ledger,lambda *_:200,0);self.assertEqual(self.state(),'retry')
    def test_permission_error_never_counts_as_deletion(self):
        cleanup_one(self.ledger,lambda *_:403,0);self.assertEqual(self.state(),'retry')
    def test_unknown_upload_never_deleted(self):
        with self.ledger.db() as db:db.execute("UPDATE auto_provider_deletions SET state='provider_lookup_required',file_id=NULL")
        self.assertFalse(cleanup_one(self.ledger,lambda *_:self.fail('external call'),0))
    def test_timeout_is_reconciled_by_get_before_new_delete(self):
        def timeout(*_):raise TimeoutError()
        cleanup_one(self.ledger,timeout,0);calls=[]
        cleanup_one(self.ledger,lambda *args:calls.append(args) or 404,1000)
        self.assertEqual([m for m,p in calls],['GET','GET']);self.assertEqual(self.state(),'verified_absent')
    def notice(self):
        identity=Notifications(self.ledger).enqueue('AN-'+'a'*32,'received',1)
        with self.ledger.db() as db:
            db.execute("UPDATE notification_events SET state='smtp_accepted'")
            db.execute('INSERT INTO notification_deliveries VALUES(?,?,0)',(identity,'synthetic@example.invalid'))
        return identity
    def dsn(self,identity,recipient='synthetic@example.invalid'):
        return ('MIME-Version: 1.0\r\nContent-Type: multipart/report; report-type=delivery-status; boundary=x\r\n\r\n'
                '--x\r\nContent-Type: message/delivery-status\r\n\r\nReporting-MTA: dns; example.invalid\r\n\r\n'
                'Final-Recipient: rfc822; '+recipient+'\r\nAction: failed\r\nStatus: 5.1.1\r\n\r\n'
                '--x\r\nContent-Type: message/rfc822\r\n\r\nMessage-ID: <'+identity+'@abrechnungs-navi.de>\r\n\r\nTEST\r\n--x--\r\n').encode()
    def test_matching_bounce_requires_review_never_resend(self):
        identity=self.notice();raw=self.dsn(identity)
        self.assertTrue(record_report(self.ledger,raw));self.assertTrue(record_report(self.ledger,raw))
        with self.ledger.db() as db:
            self.assertEqual(db.execute('SELECT state FROM notification_events').fetchone()[0],'delivery_report_review')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notification_receipts').fetchone()[0],1)
    def test_wrong_recipient_or_unknown_message_cannot_change_status(self):
        identity=self.notice()
        self.assertFalse(record_report(self.ledger,self.dsn(identity,'other@example.invalid')))
        self.assertFalse(record_report(self.ledger,self.dsn('b'*64)))
        with self.ledger.db() as db:self.assertEqual(db.execute('SELECT state FROM notification_events').fetchone()[0],'smtp_accepted')
    def test_restore_holds_outbox_instead_of_replaying_snapshot(self):
        self.notice();result=fence(self.root/'invoices.sqlite3')
        self.assertEqual(result['integrity'],'ok')
        with self.ledger.db() as db:self.assertEqual(db.execute('SELECT state FROM notification_events').fetchone()[0],'restore_review')

    def test_restore_invalidates_buyer_document_sessions_and_codes(self):
        from checkout_notices import CheckoutNotices
        CheckoutNotices(self.ledger)
        with self.ledger.db() as db:
            db.execute("INSERT INTO checkout_mail_challenges VALUES('AN-test','nonce',0,99999999999,0,0)")
            db.execute("INSERT INTO checkout_mail_sessions VALUES('hash','AN-test',99999999999)")
        fence(self.root/'invoices.sqlite3')
        with self.ledger.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM checkout_mail_challenges').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM checkout_mail_sessions').fetchone()[0],0)

    def test_owner_receipt_requires_actual_matching_inbox_headers(self):
        identity=self.notice()
        with self.ledger.db() as db:db.execute("UPDATE notification_deliveries SET recipient='kontakt@abrechnungs-navi.de'")
        key=self.root/'smtp';key.write_text('SYNTHETIC');key.chmod(0o600)
        calls=[]
        class Inbox:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def login(self,*args):pass
            def select(self,name,readonly):
                if not readonly:raise AssertionError('Must not mark read')
                return 'OK',[]
            def response(self,*args):return 'UIDVALIDITY',[b'123']
            def uid(self,command,*args):
                calls.append((command,args))
                if command=='search':return 'OK',[b'7' if 'Message-ID' in args else b'']
                raw=('Message-ID: <'+identity+'@abrechnungs-navi.de>\r\nFrom: kontakt@abrechnungs-navi.de\r\nTo: kontakt@abrechnungs-navi.de\r\n\r\n').encode()
                return 'OK',[(b'header',raw)]
        with patch('mail_receipts.imaplib.IMAP4_SSL',Inbox):self.assertEqual(reconcile(self.ledger,key),1)
        with self.ledger.db() as db:self.assertEqual(db.execute('SELECT state FROM notification_events').fetchone()[0],'own_inbox_confirmed')
        self.assertTrue(any('BODY.PEEK' in str(args) for command,args in calls if command=='fetch'))

    def test_customer_smtp_acceptance_is_never_own_inbox_confirmation(self):
        self.notice();key=self.root/'smtp';key.write_text('SYNTHETIC');key.chmod(0o600)
        class Inbox:
            def __init__(self,*a,**kw):pass
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def login(self,*a):pass
            def select(self,*a,**kw):return 'OK',[]
            def response(self,*a):return 'UIDVALIDITY',[b'123']
            def uid(self,command,*args):
                if 'Message-ID' in args:raise AssertionError('Cannot confirm customer mailbox')
                return 'OK',[b'']
        with patch('mail_receipts.imaplib.IMAP4_SSL',Inbox):self.assertEqual(reconcile(self.ledger,key),0)
        with self.ledger.db() as db:self.assertEqual(db.execute('SELECT state FROM notification_events').fetchone()[0],'smtp_accepted')


if __name__=='__main__':unittest.main()
