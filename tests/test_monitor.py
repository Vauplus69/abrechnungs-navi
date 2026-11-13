import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import monitor

class Monitoring(unittest.TestCase):
    def test_agent_and_notification_health_are_checked_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);now=1000000
            (root/'backup-last-success').write_text(str(now))
            (root/'cleanup-health.json').write_text(json.dumps({'last_attempt':now}))
            (root/'automation.json').write_text(json.dumps({'enabled':False,'invoice_dir':str(root)}))
            self.assertEqual(monitor.collect(root,root,True,now),[])
            (root/'automation.json').write_text(json.dumps({'enabled':True,'mail_enabled':True,'invoice_dir':str(root)}))
            self.assertEqual(monitor.collect(root,root,True,now),['agent_worker_stale','notification_worker_stale'])
            (root/'agent-worker-health.json').write_text(json.dumps({'last_success':now,'needs_review':0,'oldest_pending':None}))
            (root/'notification-worker-health.json').write_text(json.dumps({'last_success':now,'uncertain_deliveries':0,'oldest_pending_code':None}))
            self.assertEqual(monitor.collect(root,root,True,now),[])
            (root/'agent-worker-health.json').write_text(json.dumps({'last_success':now,'provider_deletion_review':1}))
            self.assertEqual(monitor.collect(root,root,True,now),['provider_deletion_pending'])
            (root/'agent-worker-health.json').write_text(json.dumps({'last_success':now,'provider_deletion_oldest':now-3601}))
            self.assertEqual(monitor.collect(root,root,True,now),['provider_deletion_pending'])
            (root/'agent-worker-health.json').write_text(json.dumps({'last_success':now}))
    def test_payment_monitoring_only_when_enabled_and_flags_stalled_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); now = 1000000
            (root/'backup-last-success').write_text(str(now))
            (root/'cleanup-health.json').write_text(json.dumps({'last_attempt':now}))
            cfg = {'enabled': False, 'invoice_dir': str(root)}
            (root/'payments.json').write_text(json.dumps(cfg))
            self.assertEqual(monitor.collect(root, root, True, now), [])
            cfg['enabled'] = True; (root/'payments.json').write_text(json.dumps(cfg))
            self.assertEqual(monitor.collect(root, root, True, now), ['payment_worker_stale'])
            (root/'payment-worker-health.json').write_text(json.dumps({'last_success':now,'needs_review':0,'oldest_pending':None}))
            self.assertEqual(monitor.collect(root, root, True, now), [])
            (root/'payment-worker-health.json').write_text(json.dumps({'last_success':now-601,'needs_review':1,'oldest_pending':now-601}))
            self.assertEqual(monitor.collect(root, root, True, now), ['payment_needs_review','payment_queue_stale','payment_worker_stale'])
    def test_failure_retry_dedup_and_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=root/'data';cfg=root/'cfg';data.mkdir();cfg.mkdir();now=1000000
            (cfg/'backup-last-success').write_text(str(now))
            (data/'cleanup-health.json').write_text(json.dumps({'last_attempt':now,'failed_deletions':1}))
            state=root/'state.json';failed=Mock(side_effect=OSError('synthetic'))
            with self.assertRaises(OSError):monitor.run(data,cfg,state,True,now,failed)
            self.assertFalse(state.exists())
            sender=Mock();self.assertTrue(monitor.run(data,cfg,state,True,now,sender)['notification_sent'])
            self.assertEqual(sender.call_args.args[0],['deletion_failed'])
            self.assertFalse(monitor.run(data,cfg,state,True,now+300,sender)['notification_sent']);self.assertEqual(sender.call_count,1)
            (data/'cleanup-health.json').write_text(json.dumps({'last_attempt':now+300,'failed_deletions':0}))
            self.assertEqual(monitor.run(data,cfg,state,True,now+300,sender)['issues'],[])
            (data/'cleanup-health.json').write_text(json.dumps({'last_attempt':now+301,'failed_deletions':1}))
            self.assertTrue(monitor.run(data,cfg,state,True,now+301,sender)['notification_sent'])
            self.assertEqual(sender.call_count,2)
    def test_stale_backup_and_cleanup_and_service(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(monitor.collect(root,root,False,1000000),['backup_stale','cleanup_stale','service_down'])
            (root/'backup-last-success').write_text('1000000');(root/'backup-last-failure').write_text('1000001')
            (root/'cleanup-health.json').write_text(json.dumps({'last_attempt':1000000,'cleanup_error':True}))
            self.assertEqual(monitor.collect(root,root,True,1000002),['backup_failed','cleanup_failed'])

class Availability(unittest.TestCase):
    def test_running_does_not_delay(self):
        probe=Mock(return_value=True); pause=Mock()
        self.assertTrue(monitor.application_active(probe,pause))
        self.assertEqual(probe.call_count,1);pause.assert_not_called()

    def test_short_backup_restart_does_not_alert(self):
        probe=Mock(side_effect=[False,True]);pause=Mock()
        self.assertTrue(monitor.application_active(probe,pause))
        pause.assert_called_once_with(3)
        self.assertEqual(probe.call_count,2)

    def test_persistent_outage_still_alerts(self):
        probe=Mock(return_value=False);pause=Mock()
        self.assertFalse(monitor.application_active(probe,pause))
        pause.assert_called_once_with(3)
        self.assertEqual(probe.call_count,2)
