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
