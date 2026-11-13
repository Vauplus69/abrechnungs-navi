"""One bounded agent step. Real provider processing requires explicit operator evidence."""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--config',default='/etc/an-upload/automation.json')
    args=parser.parse_args();cfg=json.loads(Path(args.config).read_text())
    if cfg.get('brand')!='abrechnungs-navi' or cfg.get('region')!='eu1':raise ValueError('Marke oder Region falsch')
    if args.check:
        print(json.dumps({'configuration_checked':True,'automation_enabled':cfg.get('enabled') is True,
                          'provider_call_performed':False,'customer_result_released':False}));return
    if cfg.get('enabled') is not True:
        print(json.dumps({'state':'disabled'}));return
    os.environ['AN_AUTOMATION_CONFIG']=args.config
    import upload_app
    upload_app.install(upload_app)
    auto=upload_app.automation_service()
    auto.expire();auto.provision_due()
    def extractor(identity,config):
        from document_extraction import ExtractEU
        from document_dossier import SCHEMA
        credentials=os.environ.get('CREDENTIALS_DIRECTORY')
        key=Path(credentials)/'extend-key' if credentials else config['extend_key_path']
        return ExtractEU(key,config['provider_approval'],auto.root/identity[3:]/'provider',
                         SCHEMA,config['max_pages_total'],credential_directory=credentials)
    processed=auto.process_one(extractor)
    auto.queue_checked_provider_deletions()
    auto.expire()
    if cfg.get('provider_cleanup_enabled') is True:
        from provider_cleanup import ExtendDeletion,cleanup_one
        credentials=os.environ.get('CREDENTIALS_DIRECTORY')
        key=Path(credentials)/'extend-key' if credentials else cfg['extend_key_path']
        cleanup_one(auto.ledger,ExtendDeletion(key,cfg['provider_approval'],credentials))
    with auto.ledger.db() as db:
        review=db.execute("SELECT COUNT(*) FROM auto_orders WHERE state IN ('internal_review','waiting_policy','restore_review')").fetchone()[0]
        oldest=db.execute("SELECT MIN(due) FROM auto_jobs WHERE state IN ('queued','extracting','running') AND due<=?",(auto.now(),)).fetchone()[0]
        deletion_review=db.execute("SELECT COUNT(*) FROM auto_provider_deletions WHERE state IN ('retry','provider_lookup_required')").fetchone()[0]
        deletion_oldest=db.execute("SELECT MIN(created) FROM auto_provider_deletions WHERE state!='verified_absent'").fetchone()[0]
    target=auto.ledger.folder/'agent-worker-health.json';temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps({'last_success':time.time(),'needs_review':review,'oldest_pending':oldest,'provider_deletion_review':deletion_review,'provider_deletion_oldest':deletion_oldest}));temp.chmod(0o600);temp.replace(target)
    print(json.dumps({'step_processed':bool(processed),'customer_result_released':False}))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Agentenlauf angehalten: '+type(error).__name__,file=sys.stderr)
        raise SystemExit(1)
