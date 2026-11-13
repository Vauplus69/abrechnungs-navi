"""Synthetic payment-to-outbox tests; transports never contact Mollie or SMTP."""
import json
from pathlib import Path
import time
import unittest
import test_payment_flow as fixture
from automation_core import Automation


class PaymentNotifications(unittest.TestCase):
    def setUp(self):
        self.case=fixture.PaymentFlowTests();self.case.setUp();self.addCleanup(self.case.tearDown)
        self.flow=self.case.flow;self.provider=self.case.provider
        self.identity=self.case.accepted['id'];self.ledger=self.case.f.ledger
        cfg=self.case.f.root/'automation.json'
        cfg.write_text(json.dumps(dict(brand='abrechnungs-navi',region='eu1',enabled=True,
            **{k:self.case.accepted[k] for k in ('avv_sha256','terms_sha256','consumer_information_sha256')})))
        self.auto=Automation(self.ledger,self.case.f.root/'data',cfg,
            Path(__file__).resolve().parents[1]/'abrechnung/rechner.py',operator_ready=lambda:True)

    def create(self):
        self.case.request();self.case.process()

    def terminal(self,state='failed'):
        self.create();self.provider.payment['status']=state;self.case.process()

    def records(self):
        with self.ledger.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM notification_events WHERE event='payment_action_required' ORDER BY version")]

    def sent(self):
        result=[]
        for _ in range(10):
            if not self.auto.notices.deliver_one(self.auto,result.append):break
        keys={r['id'] for r in self.records()}
        return [m for m in result if m['event_id'] in keys]

    def check_terminal(self,state):
        self.terminal(state)
        record=self.records()[0]
        self.assertEqual(self.auto.notice_context(record)[0],'send')
        with self.ledger.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM auto_orders').fetchone()[0],0)
        result=self.sent();self.assertEqual(len(result),1)
        self.assertEqual(result[0]['to'],'synthetic@example.invalid')
        self.assertIn('/zahlung-oeffnen',result[0]['text'])
        self.assertNotIn(self.provider.payment['id'],result[0]['text'])
        self.assertEqual(result[0]['attachments'],[])

    def test_failed_notifies_without_paid_portal(self):self.check_terminal('failed')
    def test_canceled_notifies_without_paid_portal(self):self.check_terminal('canceled')
    def test_expired_notifies_without_paid_portal(self):self.check_terminal('expired')

    def test_webhook_alone_never_enqueues_notice(self):
        self.create();self.provider.payment['status']='failed'
        self.flow.webhook(self.provider.payment['id'])
        self.assertEqual(self.records(),[])

    def test_pending_and_authorized_are_not_payment_failures(self):
        self.create()
        for state in ('open','pending','authorized','paid'):
            self.provider.payment['status']=state
            self.flow.webhook(self.provider.payment['id']);self.case.process()
            self.assertEqual(self.records(),[])

    def test_uncertain_retrieval_and_wrong_amount_never_notify(self):
        self.create();self.provider.fail_get=True;self.case.process()
        self.assertEqual(self.records(),[])
        self.provider.fail_get=False;self.provider.payment['status']='failed'
        self.provider.payment['amount']['value']='0.01'
        with self.ledger.db() as db:db.execute("UPDATE payment_jobs SET due=0 WHERE state='queued'")
        self.case.process();self.assertEqual(self.records(),[])

    def test_duplicate_checks_and_restart_send_once(self):
        self.terminal();self.assertEqual(len(self.sent()),1)
        for _ in range(3):
            self.flow.webhook(self.provider.payment['id']);self.case.process()
        self.assertEqual(len(self.records()),1);self.assertEqual(self.sent(),[])
        from payment_flow import PaymentFlow
        restarted=PaymentFlow(self.ledger)
        self.assertEqual(restarted.problem_notice_context(self.records()[0])[0],'send')
        self.assertEqual(self.sent(),[])

    def test_retry_invalidates_old_notice_and_versions_new_attempt(self):
        self.terminal();self.flow.retry(self.identity,'test');self.case.process()
        self.assertEqual(self.auto.notice_context(self.records()[0])[0],'obsolete')
        self.provider.payment['status']='expired';self.case.process()
        self.assertEqual([r['version'] for r in self.records()],['1','2'])
        self.assertEqual(len(self.sent()),1)

    def test_later_paid_or_blocked_status_suppresses_queued_notice(self):
        self.terminal();record=self.records()[0]
        self.provider.payment['status']='paid';self.flow.webhook(self.provider.payment['id']);self.case.process()
        self.assertEqual(self.auto.notice_context(record)[0],'obsolete');self.assertEqual(self.sent(),[])

    def test_stale_or_new_webhook_defers_until_independent_recheck(self):
        self.terminal();record=self.records()[0]
        with self.ledger.db() as db:db.execute('UPDATE payment_orders SET checked=?',(time.time()-301,))
        self.assertEqual(self.auto.notice_context(record)[0],'defer')
        self.case.process();self.assertEqual(self.auto.notice_context(record)[0],'send')
        self.flow.webhook(self.provider.payment['id'])
        self.assertEqual(self.auto.notice_context(record)[0],'defer')

    def test_operator_gate_prior_callbacks_and_withdrawal_prevent_delivery(self):
        self.terminal();record=self.records()[0]
        self.auto.operator_ready=lambda:False
        self.assertEqual(self.auto.notice_context(record)[0],'defer')
        self.auto.operator_ready=lambda:True
        with self.ledger.db() as db:
            self.flow.queue(db,self.identity,'prior:tr_SyntheticOld')
        self.assertEqual(self.auto.notice_context(record)[0],'defer')
        with self.ledger.db() as db:
            db.execute("UPDATE payment_jobs SET state='done'")
            db.execute('INSERT INTO auto_orders(order_id,token,state,created,expires,not_before,withdrawn) VALUES(?,?,?,?,?,?,?)',
                (self.identity,'a'*32,'awaiting_upload',time.time(),time.time()+1000,0,1))
        self.assertEqual(self.auto.notice_context(record)[0],'obsolete')

    def test_canceled_invoice_and_attempt_limit_suppress_notice(self):
        self.terminal();record=self.records()[0]
        with self.ledger.db() as db:db.execute('UPDATE payment_orders SET attempt=20')
        self.assertEqual(self.auto.notice_context(record)[0],'obsolete')
        with self.ledger.db() as db:
            db.execute('UPDATE payment_orders SET attempt=1')
            invoice=db.execute('SELECT invoice_id FROM checkout_invoice_links WHERE order_id=?',(self.identity,)).fetchone()[0]
        self.ledger.cancel(invoice,'SYNTHETIC TEST')
        self.assertEqual(self.auto.notice_context(record)[0],'obsolete')


if __name__=='__main__':unittest.main()
