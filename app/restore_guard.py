"""Offline restore preparation. Never start workers from an old snapshot directly."""
import argparse
import json
from pathlib import Path
import sqlite3
import time


def fence(database):
    """Hold all external work: events after the snapshot may already have happened."""
    with sqlite3.connect(database) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Datenbank beschädigt')
        if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Datenbankbezüge beschädigt')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'notification_events' in tables:
            db.execute("UPDATE notification_events SET state='restore_review',updated=? WHERE state IN ('queued','reserved','smtp_accepted','delivery_uncertain','delivery_report_review')",(time.time(),))
        if 'payment_orders' in tables:
            if 'payment_events' in tables:
                db.execute("INSERT INTO payment_events(order_id,event,at) SELECT order_id,'restore_review',? FROM payment_orders",(time.time(),))
            db.execute("UPDATE payment_orders SET state='restore_review',requires_check=1,checked=NULL")
        if 'payment_jobs' in tables:
            db.execute("UPDATE payment_jobs SET state='restore_review',token=NULL,lease=NULL WHERE state IN ('queued','running')")
        if 'auto_jobs' in tables:
            db.execute("UPDATE auto_jobs SET state='restore_review',token=NULL,lease=NULL WHERE state NOT IN ('expired','superseded')")
        if 'auto_orders' in tables:
            db.execute("UPDATE auto_orders SET state='restore_review',released_version=NULL,last_code=NULL WHERE state!='expired'")
        if 'auto_sessions' in tables:db.execute('DELETE FROM auto_sessions')
        if 'auto_challenges' in tables:db.execute('DELETE FROM auto_challenges')
        if 'checkout_mail_sessions' in tables:db.execute('DELETE FROM checkout_mail_sessions')
        if 'checkout_mail_challenges' in tables:db.execute('DELETE FROM checkout_mail_challenges')
    return {'integrity':'ok','foreign_keys':'ok','external_work':'held','released_results':'held'}


def prepare(root):
    root=Path(root).resolve()
    if str(root) in ('/','/srv/an-upload'):raise ValueError('Nur getrennte Wiederherstellungsablage verwenden')
    db=root/'srv/an-upload/invoices/invoices.sqlite3'
    if not db.is_file() or db.is_symlink() or root not in db.resolve().parents:raise ValueError('Gesicherte Datenbank fehlt oder Pfad verlässt die Ablage')
    # Disable before inspecting mutable data. Leave live /etc completely untouched.
    for name in ('automation.json','payments.json','checkout.json'):
        path=root/'etc/an-upload'/name
        if root not in path.resolve().parents:raise ValueError('Konfiguration verlässt die Ablage')
        if path.exists():
            if path.is_symlink():raise ValueError('Konfiguration darf kein Link sein')
            cfg=json.loads(path.read_text());cfg['enabled']=False
            for key in ('mail_enabled','provider_cleanup_enabled','mail_receipts_enabled'):cfg[key]=False
            path.write_text(json.dumps(cfg,indent=2)+'\n');path.chmod(0o600)
    operator=root/'etc/an-upload/operator.json'
    if root not in operator.resolve().parents:raise ValueError('Konfiguration verlässt die Ablage')
    if operator.is_symlink():raise ValueError('Konfiguration darf kein Link sein')
    cfg=json.loads(operator.read_text()) if operator.exists() else {}
    cfg.update(provider_annex_complete=False,restore_tested_at=0,backup_tested_at=0)
    operator.parent.mkdir(parents=True,exist_ok=True)
    operator.write_text(json.dumps(cfg,indent=2)+'\n');operator.chmod(0o600)
    return fence(db)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('restored_root')
    print(json.dumps(prepare(parser.parse_args().restored_root)))
