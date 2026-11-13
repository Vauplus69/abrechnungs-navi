import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import agent_worker
import notification_worker


class WorkerGuards(unittest.TestCase):
    def config(self,folder,**fields):
        path=Path(folder)/'automation.json'
        path.write_text(json.dumps(dict(brand='abrechnungs-navi',region='eu1',enabled=False,mail_enabled=False,**fields)))
        return path

    def test_agent_check_is_readonly_even_without_provider_credential(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=self.config(folder)
            with patch('sys.argv',['worker','--check','--config',str(cfg)]),contextlib.redirect_stdout(io.StringIO()) as out:
                agent_worker.main()
            self.assertFalse(json.loads(out.getvalue())['provider_call_performed'])

    def test_disabled_agent_does_not_load_customer_application(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=self.config(folder)
            with patch('sys.argv',['worker','--config',str(cfg)]),contextlib.redirect_stdout(io.StringIO()) as out:
                agent_worker.main()
            self.assertEqual(json.loads(out.getvalue())['state'],'disabled')

    def test_notice_check_cannot_send_mail(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=self.config(folder)
            with patch('sys.argv',['worker','--check','--config',str(cfg)]),patch('notice_agent.SmtpSender') as smtp,contextlib.redirect_stdout(io.StringIO()) as out:
                notification_worker.main()
            smtp.assert_not_called();self.assertFalse(json.loads(out.getvalue())['mail_sent'])

    def test_notification_provider_approval_cannot_be_assumed(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/'automation.json'
            cfg.write_text(json.dumps(dict(brand='abrechnungs-navi',region='eu1',enabled=True,mail_enabled=True,mail_provider_approved=False)))
            with patch('sys.argv',['worker','--config',str(cfg)]),patch('notice_agent.SmtpSender') as smtp,contextlib.redirect_stdout(io.StringIO()) as out:
                notification_worker.main()
            smtp.assert_not_called();self.assertFalse(json.loads(out.getvalue())['mail_sent'])


if __name__=='__main__':unittest.main()
