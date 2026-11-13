"""Deliver only current, approved transactional notices; no documents or payment credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--config',default='/etc/an-upload/automation.json')
    args=parser.parse_args();cfg=json.loads(Path(args.config).read_text())
    if cfg.get('brand')!='abrechnungs-navi' or cfg.get('region')!='eu1':raise ValueError('Marke oder Region falsch')
    allowed=cfg.get('enabled') is True and cfg.get('mail_enabled') is True and cfg.get('mail_provider_approved') is True
    if args.check:
        print(json.dumps({'configuration_checked':True,'mail_enabled':allowed,'mail_sent':False}));return
    if not allowed:print(json.dumps({'state':'disabled','mail_sent':False}));return
    if not re.fullmatch(r'[a-f0-9]{64}',cfg.get('mail_provider_evidence_sha256','')):raise ValueError('Mail-Anbieternachweis fehlt')
    os.environ['AN_AUTOMATION_CONFIG']=args.config
    import upload_app
    upload_app.install(upload_app);auto=upload_app.automation_service()
    from notice_agent import SmtpSender
    credentials=os.environ.get('CREDENTIALS_DIRECTORY')
    key=Path(credentials)/'smtp-password' if credentials else Path(cfg['smtp_password_path'])
    sender=SmtpSender(key,credentials)
    from mollie_payments import protected_file
    protected_file(key,credentials)
    with auto.ledger.db() as db:
        db.execute("UPDATE notification_events SET state='delivery_uncertain' WHERE state='reserved' AND updated<?",(time.time()-300,))
    count=0
    for _ in range(10):
        if not auto.notices.deliver_one(auto,sender):break
        count+=1
    if cfg.get('mail_receipts_enabled') is True:
        from mail_receipts import reconcile
        reconcile(auto.ledger,key,credentials)
    with auto.ledger.db() as db:
        uncertain=db.execute("SELECT COUNT(*) FROM notification_events WHERE state IN ('delivery_uncertain','template_review','delivery_report_review','restore_review')").fetchone()[0]
        oldest=db.execute("SELECT MIN(created) FROM notification_events WHERE state='queued' AND event='access_code'").fetchone()[0]
    target=auto.ledger.folder/'notification-worker-health.json';temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps({'last_success':time.time(),'uncertain_deliveries':uncertain,'oldest_pending_code':oldest}));temp.chmod(0o600);temp.replace(target)
    print(json.dumps({'events_processed':count,'delivery_uncertain':uncertain}))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Benachrichtigungsagent angehalten: '+type(error).__name__,file=sys.stderr)
        raise SystemExit(1)
