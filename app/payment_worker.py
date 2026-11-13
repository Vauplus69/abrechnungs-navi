"""Credential-isolated oneshot worker. --check performs GET only, never a payment POST."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

import invoicing
from mollie_payments import MolliePayments, PaymentUncertain
from payment_flow import PaymentFlow, settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--config', default='/etc/an-upload/payments.json')
    args = parser.parse_args()
    cfg = settings(args.config, enabled=not args.check)
    credentials = os.environ.get('CREDENTIALS_DIRECTORY')
    if credentials:
        key = str(Path(credentials) / 'mollie-key')
        binding = str(Path(credentials) / 'mollie-binding')
    else:
        key = cfg['key_path']; binding = cfg.get('binding_path')
    # A read-only configuration check may inspect an existing live credential
    # before the worker is enabled. It cannot enter the creation branch below.
    provider = MolliePayments(key, cfg['mode'], live_release=args.check or cfg.get('live_release') is True,
                              binding_path=binding, credential_directory=credentials)
    provider.verify_profile()
    if args.check:
        print(json.dumps({'configuration_checked': True, 'mode': cfg['mode'],
                          'profile_id': cfg['profile_id'], 'payment_created': False}))
        return
    ledger = invoicing.Ledger(cfg['invoice_dir'], cfg['issuer_path'])
    flow = PaymentFlow(ledger)
    flow.queue_due()
    count = 0
    for _ in range(10):
        if not flow.process_one(provider): break
        count += 1
    with ledger.db() as db:
        needs_review = db.execute("SELECT COUNT(*) FROM payment_orders WHERE state IN ('blocked','held','restore_review') OR prior_paid=1 "
            "OR (state='uncertain' AND (payment_id IS NULL OR checked IS NULL OR checked<?))", (time.time()-600,)).fetchone()[0]
        oldest = db.execute("SELECT MIN(due) FROM payment_jobs WHERE state IN ('queued','running')").fetchone()[0]
    health = {'last_success': time.time(), 'needs_review': needs_review,
              'oldest_pending': oldest, 'jobs_processed': count}
    target = ledger.folder / 'payment-worker-health.json'
    temp = target.with_suffix('.tmp'); temp.write_text(json.dumps(health)); temp.chmod(0o600); temp.replace(target)
    print(json.dumps({'jobs_processed': count, 'mode': cfg['mode']}))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, PaymentUncertain):
        # Neither upstream response bodies nor paths to credentials in logs.
        print('Zahlungsworker: Konfiguration oder Anbieterprüfung nicht erfolgreich', file=sys.stderr)
        sys.exit(1)
