"""Per-order closure and erasure; no provider calls and no legal-retention guesses.

Never equate a pseudonymous display or local purge with completed global erasure.
Callers must hold the portal lock and persist the blocked state before any purge.
"""
import copy
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import time

STATES = {'closed', 'deletion_requested', 'local_deleted'}
CHECKS = ('identity_scope', 'extend', 'chatwoot', 'email', 'automation',
          'backups', 'retention')


def blocked(row):
    return bool(row.get('lifecycle'))


def request(row, action, now=None):
    if action not in ('close', 'request_deletion'):
        raise ValueError('Unbekannte Aktion')
    out = copy.deepcopy(row)
    previous = out.get('lifecycle', {})
    if previous.get('state') == 'local_deleted':
        return out
    state = 'deletion_requested' if action == 'request_deletion' else 'closed'
    if previous.get('state') == 'deletion_requested':
        state = 'deletion_requested'
    out['lifecycle'] = {
        'reference': previous.get('reference') or 'AN-' + secrets.token_hex(8).upper(),
        'state': state,
        'requested_at': previous.get('requested_at', time.time() if now is None else now),
    }
    # Never restore a retired code. Existing sessions are also rejected by blocked().
    out.pop('access_hash', None)
    return out


def summary(row):
    life = row['lifecycle']
    return {key: life[key] for key in ('reference', 'state', 'requested_at')}


def hidden_identities(db):
    names, emails = set(), set()
    for row in db.values():
        if not blocked(row):
            continue
        if row.get('name'):
            names.add(row['name'].strip().casefold())
        for field in ('email', 'agentic_email', 'privacy_email'):
            if row.get(field):
                emails.add(row[field].strip().casefold())
    return names, emails


def hide_auxiliary(row, db):
    names, emails = hidden_identities(db)
    return (row.get('name', '').strip().casefold() in names or
            row.get('email', '').strip().casefold() in emails)


def purge_local(app, token, checks, evidence, now=None):
    """Remove this order only, after external review. Not a global erasure receipt.

    evidence is an opaque reference to the operator's review, never free text.
    Backups must have expired/been erased before the operator may attest that check. The marker below is an audit
    aid, not an implemented backup restore filter.
    """
    if set(checks) != set(CHECKS) or any(checks[k] is not True for k in CHECKS):
        raise ValueError('Pruefung aller Systeme und Aufbewahrung fehlt')
    if not re.fullmatch(r'PR-[A-Z0-9-]{8,64}', evidence):
        raise ValueError('Neutrale Pruefreferenz PR-… erforderlich')
    db = app.load()
    row = db.get(token)
    if not row or row.get('lifecycle', {}).get('state') != 'deletion_requested':
        raise ValueError('Kein bestaetigter Loeschauftrag')
    # Do not erase shared contact data across an unreviewed second order.
    email = (row.get('privacy_email') or row.get('email') or row.get('agentic_email') or '').strip().casefold()
    if not email:
        raise ValueError('Kontaktzuordnung fehlt; systemuebergreifende Pruefung erforderlich')
    for other_token, other in db.items():
        other_email = (other.get('privacy_email') or other.get('email') or other.get('agentic_email') or '').strip().casefold()
        if other_token != token and other_email == email and other.get('lifecycle', {}).get('state') != 'local_deleted':
            raise ValueError('Weitere Auftraege derselben Adresse zuerst gemeinsam pruefen')
    root = Path(app.DATA_DIR) / 'kunden'
    folder = Path(app.customer_dir(token))
    if folder.parent.resolve() != root.resolve() or folder.name != token or folder.is_symlink():
        raise ValueError('Ungueltiges Kundenverzeichnis')
    # Keep only a minimal neutral record; raw copies in provider systems are not
    # inferred from this result. Retained invoices live in the separate ledger.
    stamp = time.time() if now is None else now
    life = summary(row)
    life.update(state='local_deleted', local_deleted_at=stamp, review=evidence)
    tombstone = {'lifecycle': life, 'expires': stamp, 'delete_at': stamp + 183 * 86400}
    if folder.exists():
        shutil.rmtree(folder)  # Errors leave the blocked source row for retry.
    inquiries = app.load_anfragen()
    app.save_anfragen([r for r in inquiries if r.get('email', '').strip().casefold() != email])
    withdrawals = Path(app.DATA_DIR) / 'widerrufe.json'
    if withdrawals.exists():
        import json
        rows = json.loads(withdrawals.read_text())
        tmp = withdrawals.with_suffix('.tmp')
        tmp.write_text(json.dumps([r for r in rows if r.get('email', '').strip().casefold() != email]))
        os.chmod(tmp, 0o600)
        os.replace(tmp, withdrawals)
    # A fingerprint supports restore suppression without keeping the access URL.
    marker = Path(app.DATA_DIR) / 'privacy-restore-blocks.jsonl'
    import json
    fd = os.open(marker, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'a') as stream:
        stream.write(json.dumps({'token_sha256': hashlib.sha256(token.encode()).hexdigest(),
                                 'reference': life['reference'], 'at': stamp}) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    db[token] = tombstone
    app.save(db)
    return life
