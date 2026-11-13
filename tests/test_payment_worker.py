import contextlib
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import payment_worker
from mollie_payments import PROFILE


class WorkerTests(unittest.TestCase):
    def test_live_readonly_check_cannot_create_payment_or_open_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            config = Path(d) / 'config.json'
            config.write_text(json.dumps(dict(brand='abrechnungs-navi', profile_id=PROFILE,
                mode='live', enabled=False, live_release=False, key_path='SYNTHETIC-PATH', binding_path='SYNTHETIC-BINDING')))
            client = Mock()
            with patch('sys.argv', ['worker', '--check', '--config', str(config)]), \
                 patch.object(payment_worker, 'MolliePayments', return_value=client), \
                 patch.object(payment_worker.invoicing, 'Ledger', side_effect=AssertionError('No ledger access')), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                payment_worker.main()
            client.verify_profile.assert_called_once()
            client.create.assert_not_called()
            self.assertFalse(json.loads(output.getvalue())['payment_created'])

    def test_disabled_worker_does_not_load_credential(self):
        with tempfile.TemporaryDirectory() as d:
            config = Path(d) / 'config.json'
            config.write_text(json.dumps(dict(brand='abrechnungs-navi', profile_id=PROFILE,
                mode='live', enabled=False, live_release=False)))
            with patch('sys.argv', ['worker', '--config', str(config)]), \
                 patch.object(payment_worker, 'MolliePayments') as client, self.assertRaises(ValueError):
                payment_worker.main()
            client.assert_not_called()


if __name__ == '__main__': unittest.main()
