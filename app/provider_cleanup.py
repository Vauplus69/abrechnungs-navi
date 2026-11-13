"""Bounded EU deletion of references retained by this application's own ledger.

200 DELETE is an acknowledgement; only subsequent GET 404 proves absence.
Unknown uploads remain operator work. No account-wide listing or deletion.
"""
import json
import re
import time
from urllib.request import Request, build_opener
from urllib.error import HTTPError

from document_extraction import NoRedirect
from mollie_payments import protected_file


class ExtendDeletion:
    def __init__(self, key_path, approval, credential_directory=None):
        if not isinstance(approval,dict) or approval.get('brand')!='abrechnungs-navi' or approval.get('region')!='eu1':
            raise ValueError('Eigene EU-Anbieterfreigabe erforderlich')
        if not all(approval.get(k) is True for k in ('contract_verified','subprocessors_verified','retention_verified','customer_avv_allows_extraction')):
            raise ValueError('Anbieterfreigabe fehlt')
        if not re.fullmatch(r'[a-f0-9]{64}',approval.get('provider_evidence_sha256','')):
            raise ValueError('Anbieternachweis fehlt')
        self.key=protected_file(key_path,credential_directory).read_text().strip()
        if not self.key or any(c in self.key for c in '\r\n'):raise ValueError('Ungültiger Schlüssel')

    def __call__(self, method, path):
        if method not in ('GET','DELETE') or not re.fullmatch(r'/(files/file_|extract_runs/exr_)[A-Za-z0-9]+',path):
            raise ValueError('Unzulässiger Löschaufruf')
        request=Request('https://api.eu1.extend.ai'+path,method=method,
                        headers={'Authorization':'Bearer '+self.key,'x-extend-api-version':'2026-02-09'})
        try:
            with build_opener(NoRedirect()).open(request,timeout=25) as response:
                # GET metadata may contain temporary download links: never persist it.
                return response.status
        except HTTPError as error:
            return error.code


def cleanup_one(ledger, transport, now=None):
    now=time.time() if now is None else now
    with ledger.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS provider_deletion_attempts(id TEXT PRIMARY KEY,due REAL NOT NULL,attempts INTEGER NOT NULL,verified REAL,last_error TEXT)')
        db.execute('BEGIN IMMEDIATE') if not db.in_transaction else None
        row=db.execute("SELECT d.* FROM auto_provider_deletions d LEFT JOIN provider_deletion_attempts a ON a.id=d.id WHERE d.state IN ('pending','retry','checking') AND COALESCE(a.due,0)<=? ORDER BY d.created LIMIT 1",(now,)).fetchone()
        if row is None:return False
        row=dict(row)
        # Lease before any external call; a crash resumes with GET, never assumes success.
        db.execute("INSERT INTO provider_deletion_attempts VALUES(?,?,1,NULL,NULL) ON CONFLICT(id) DO UPDATE SET due=excluded.due,attempts=attempts+1",(row['id'],now+300))
        db.execute("UPDATE auto_provider_deletions SET state='checking' WHERE id=?",(row['id'],))
    state='retry';error=None
    try:
        paths=[]
        if not re.fullmatch(r'file_[A-Za-z0-9]+',row['file_id'] or ''):raise ValueError('file_reference')
        if row['run_id']:
            if not re.fullmatch(r'exr_[A-Za-z0-9]+',row['run_id']):raise ValueError('run_reference')
            paths.append('/extract_runs/'+row['run_id'])
        paths.append('/files/'+row['file_id'])
        for path in paths:
            status=transport('GET',path)
            if status==404:continue
            if status!=200:raise ValueError('read_status_'+str(status))
            status=transport('DELETE',path)
            if status not in (200,404):raise ValueError('delete_status_'+str(status))
            if transport('GET',path)!=404:raise ValueError('absence_not_verified')
        state='verified_absent'
    except Exception as failure:
        # No provider content, credentials, or download URLs in durable errors.
        error=str(failure) if isinstance(failure,ValueError) and re.fullmatch(r'[a-z_0-9]+',str(failure)) else type(failure).__name__
    with ledger.db() as db:
        db.execute('UPDATE auto_provider_deletions SET state=? WHERE id=?',(state,row['id']))
        db.execute('UPDATE provider_deletion_attempts SET due=?,verified=?,last_error=? WHERE id=?',
                   (now+900,now if state=='verified_absent' else None,error,row['id']))
    return True
