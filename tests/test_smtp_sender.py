import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from notice_agent import SmtpSender

class SenderFooter(unittest.TestCase):
    def test_protected_issuer_footer_without_tax_number(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);password=root/'password';password.write_text('synthetic-password');password.chmod(0o600)
            cfg=root/'issuer.json';cfg.write_text(json.dumps(dict(name='Synthetic Seller',address='Testweg 1',city='12345 Teststadt',email='seller@example.invalid',tax_mode='kleinunternehmer',tax_id='PRIVATE-TAX-ID')))
            notice=dict(to='buyer@example.invalid',subject='Test',event_id='a'*64,text='Code: 123456',attachments=[])
            with patch.dict('os.environ',{'AN_INVOICE_ISSUER_FILE':str(cfg)}),patch('notice_agent.smtplib.SMTP') as smtp:
                smtp.return_value.__enter__.return_value.send_message.return_value={}
                SmtpSender(password)(notice)
                message=smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
                self.assertIn('Synthetic Seller\nTestweg 1\n12345 Teststadt',message.get_content())
                self.assertNotIn('PRIVATE-TAX-ID',message.get_content())

    def test_missing_sender_configuration_blocks_sending(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);password=root/'password';password.write_text('synthetic-password');password.chmod(0o600)
            with patch.dict('os.environ',{'AN_INVOICE_ISSUER_FILE':str(root/'missing')}),patch('notice_agent.smtplib.SMTP') as smtp:
                with self.assertRaises(ValueError):SmtpSender(password)(dict(to='buyer@example.invalid',subject='Test',event_id='b'*64,text='Test',attachments=[]))
                smtp.assert_not_called()
