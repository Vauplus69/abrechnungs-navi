"""Durable payment jobs in the existing invoice ledger. Web handlers hold no API key."""
import json
import re
import secrets
import time
from pathlib import Path

from mollie_payments import PROFILE, PaymentUncertain, validate_order, validate_payment, checkout_url


def settings(path, *, enabled=True):
    value = json.loads(Path(path).read_text())
    if value.get('brand') != 'abrechnungs-navi' or value.get('profile_id') != PROFILE or value.get('mode') not in ('test', 'live'):
        raise ValueError('Ungültige Zahlungskonfiguration')
    if enabled and (value.get('enabled') is not True or value['mode'] == 'live' and value.get('live_release') is not True):
        raise ValueError('Zahlungsbetrieb noch nicht aktiviert')
    return value


class PaymentFlow:
    def __init__(self, ledger):
        self.ledger = ledger
        with ledger.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS payment_orders(
                order_id TEXT PRIMARY KEY REFERENCES checkout_acceptances(order_id),
                mode TEXT NOT NULL, state TEXT NOT NULL, payment_id TEXT UNIQUE, checkout TEXT,
                checked REAL, requires_check INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 1, prior_paid INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS payment_previous(
                payment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, attempt INTEGER NOT NULL, state TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS payment_jobs(
                id INTEGER PRIMARY KEY, order_id TEXT NOT NULL REFERENCES payment_orders(order_id),
                action TEXT NOT NULL, state TEXT NOT NULL, token TEXT, lease REAL,
                due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT);
              CREATE UNIQUE INDEX IF NOT EXISTS queued_payment_job ON payment_jobs(order_id,action) WHERE state='queued';
              CREATE TABLE IF NOT EXISTS payment_events(
                id INTEGER PRIMARY KEY, order_id TEXT NOT NULL, event TEXT NOT NULL, at REAL NOT NULL);
            ''')
            columns = {r['name'] for r in db.execute('PRAGMA table_info(payment_orders)')}
            for column in ('attempt', 'prior_paid'):
                if column not in columns:
                    db.execute(f'ALTER TABLE payment_orders ADD COLUMN {column} INTEGER NOT NULL DEFAULT {1 if column == "attempt" else 0}')
        from notice_agent import Notifications
        self.notices=Notifications(ledger)

    @staticmethod
    def event(db, identity, event):
        db.execute('INSERT INTO payment_events(order_id,event,at) VALUES(?,?,?)', (identity, event, time.time()))

    def accepted(self, identity):
        with self.ledger.db() as db:
            row = db.execute('SELECT a.payload AS acceptance,o.payload AS offer,o.sha256,l.invoice_id '
                'FROM checkout_acceptances a JOIN checkout_offers o ON o.id=a.offer_id '
                'LEFT JOIN checkout_invoice_links l ON l.order_id=a.order_id WHERE a.order_id=?', (identity,)).fetchone()
            if row is None or row['invoice_id'] is None:
                raise ValueError('Bestätigter Auftrag und Vorausrechnung fehlen')
            if db.execute('SELECT 1 FROM invoices WHERE original_id=?', (row['invoice_id'],)).fetchone():
                raise ValueError('Vorausrechnung storniert')
        import hashlib
        accepted = json.loads(row['acceptance']); offer = json.loads(row['offer'])
        if hashlib.sha256(row['offer'].encode()).hexdigest() != row['sha256'] or accepted.get('offer_sha256') != row['sha256']:
            raise ValueError('Vertragsnachweis verändert')
        validate_order(accepted)
        for field in ('apartments', 'houses', 'total_cents'):
            if accepted[field] != offer['order'][field]: raise ValueError('Angebot stimmt nicht mit Auftrag überein')
        for field, kind in (('avv_sha256', 'avv'), ('consumer_information_sha256', 'consumer'), ('terms_sha256', 'terms')):
            if accepted.get(field) != offer['documents'][kind]['sha256']: raise ValueError('Vertragsfassung stimmt nicht überein')
        invoice = json.loads(self.ledger.get(row['invoice_id'])['payload'])
        if invoice['order'] != offer['order'] or invoice['issuer'] != offer['issuer']:
            raise ValueError('Vorausrechnung stimmt nicht mit Angebot überein')
        return accepted

    def get(self, identity):
        with self.ledger.db() as db:
            row = db.execute('SELECT * FROM payment_orders WHERE order_id=?', (identity,)).fetchone()
        return dict(row) if row else None

    def problem_notice_context(self, record):
        """Recheck one verified failed attempt immediately before notification."""
        identity=record['order_id']
        try:
            accepted=self.accepted(identity)
            row=self.get(identity)
            payload=json.loads(record['payload'])
        except (ValueError,KeyError,TypeError):return 'obsolete',{}
        if not row or row['state'] not in ('failed','canceled','expired') or row['prior_paid'] or row['attempt']>=20:
            return 'obsolete',{}
        if str(row['attempt'])!=record['version'] or payload.get('payment_id')!=row['payment_id'] or payload.get('mode')!=row['mode']:
            return 'obsolete',{}
        with self.ledger.db() as db:
            # Previous-attempt callbacks may still reveal a successful payment.
            if db.execute("SELECT 1 FROM payment_jobs WHERE order_id=? AND state IN ('queued','running') AND action LIKE 'prior:%'",(identity,)).fetchone():
                return 'defer',{}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='auto_orders'").fetchone():
                portal=db.execute('SELECT withdrawn,expires,state FROM auto_orders WHERE order_id=?',(identity,)).fetchone()
                if portal and (portal['withdrawn'] or portal['expires']<=time.time() or portal['state'] in ('closed','deletion_requested','local_deleted')):
                    return 'obsolete',{}
            offer_row=db.execute('SELECT id,payload FROM checkout_offers WHERE id=?',(accepted['offer_id'],)).fetchone()
        if row['requires_check'] or not row['checked'] or not 0<=time.time()-row['checked']<=300:
            self.request_check(identity)
            return 'defer',{}
        if not offer_row or not re.fullmatch(r'[a-f0-9]{40}',offer_row['id']):return 'obsolete',{}
        offer=json.loads(offer_row['payload'])
        return 'send',dict(email=offer['email'],order_id=identity,checkout_notification_verified=True,
            payment_state=row['state'],payment_retry_allowed=True,
            order_url='https://abrechnungs-navi.de/bestellen/'+offer_row['id']+'/zahlung-oeffnen')

    @staticmethod
    def queue(db, identity, action):
        db.execute('INSERT OR IGNORE INTO payment_jobs(order_id,action,state,due) VALUES(?,?,?,?)',
                   (identity, action, 'queued', time.time()))

    def request(self, identity, mode):
        self.accepted(identity)
        if mode not in ('test', 'live'): raise ValueError('Zahlungsmodus fehlt')
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM payment_orders WHERE order_id=?', (identity,)).fetchone()
            if row and row['mode'] != mode: raise ValueError('Auftragsmodus darf nicht geändert werden')
            if row is None:
                db.execute('INSERT INTO payment_orders(order_id,mode,state,updated) VALUES(?,?,?,?)',
                           (identity, mode, 'requested', time.time()))
                self.queue(db, identity, 'create'); self.event(db, identity, 'requested')
        return self.get(identity)

    def webhook(self, payment_id):
        if not isinstance(payment_id, str) or not re.fullmatch(r'tr_[A-Za-z0-9]{1,100}', payment_id):
            raise ValueError('Ungültige Zahlungskennung')
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT order_id FROM payment_orders WHERE payment_id=?', (payment_id,)).fetchone()
            if row is None:
                previous = db.execute('SELECT order_id FROM payment_previous WHERE payment_id=?', (payment_id,)).fetchone()
                if previous is None: return False  # No requests for arbitrary external IDs.
                db.execute('UPDATE payment_orders SET requires_check=1 WHERE order_id=?', (previous['order_id'],))
                self.queue(db, previous['order_id'], 'prior:' + payment_id)
                return True
            db.execute('UPDATE payment_orders SET requires_check=1 WHERE order_id=?', (row['order_id'],))
            self.queue(db, row['order_id'], 'check')
        return True

    def retry(self, identity, mode):
        self.accepted(identity)
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM payment_orders WHERE order_id=?', (identity,)).fetchone()
            if row is None or row['mode'] != mode or row['state'] not in ('failed', 'canceled', 'expired') or row['requires_check'] or row['prior_paid']:
                raise ValueError('Ein weiterer Zahlungsversuch ist derzeit nicht zulässig')
            if not row['checked'] or time.time() - row['checked'] > 300:
                raise ValueError('Zahlungsstatus zuerst aktualisieren')
            if row['attempt'] >= 20:
                raise ValueError('Bitte kontaktieren Sie uns vor weiteren Zahlungsversuchen')
            db.execute('INSERT INTO payment_previous VALUES(?,?,?,?)', (row['payment_id'], identity, row['attempt'], row['state']))
            db.execute("UPDATE payment_orders SET state='requested',payment_id=NULL,checkout=NULL,checked=NULL,requires_check=1,attempt=attempt+1,updated=? WHERE order_id=?", (time.time(), identity))
            self.queue(db, identity, 'create'); self.event(db, identity, 'retry_requested')
        return self.get(identity)

    def request_recovery(self, identity, payment_id):
        """Operator supplies a hint; only a verified provider GET may bind it."""
        self.accepted(identity)
        if not isinstance(payment_id, str) or not re.fullmatch(r'tr_[A-Za-z0-9]{1,100}', payment_id):
            raise ValueError('Ungültige Zahlungskennung')
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM payment_orders WHERE order_id=?', (identity,)).fetchone()
            if row is None or row['payment_id'] or row['state'] not in ('reserved','uncertain','blocked'):
                raise ValueError('Kein unklarer Zahlungsversuch zum Abgleichen vorhanden')
            self.queue(db, identity, 'recover:' + payment_id)
            self.event(db, identity, 'recovery_requested')

    def request_check(self, identity):
        row = self.get(identity)
        if row is None or not row['payment_id']: return
        if row['requires_check'] or not row['checked'] or time.time() - row['checked'] > 30:
            with self.ledger.db() as db: self.queue(db, identity, 'check')

    def require_paid(self, identity):
        self.accepted(identity)
        row = self.get(identity)
        if row is None or row['state'] != 'paid' or row['requires_check'] or row['prior_paid'] or not row['checked'] or not 0 <= time.time() - row['checked'] <= 300:
            self.request_check(identity)
            raise ValueError('Zahlung noch nicht unabhängig bestätigt oder erneute Prüfung erforderlich')
        return row

    def queue_due(self):
        with self.ledger.db() as db:
            rows = db.execute("SELECT order_id FROM payment_orders WHERE payment_id IS NOT NULL AND "
                "state NOT IN ('canceled','expired','failed','blocked','restore_review') AND (checked IS NULL OR checked < ?) "
                'ORDER BY COALESCE(checked,0) LIMIT 20', (time.time() - 240,)).fetchall()
            for row in rows: self.queue(db, row['order_id'], 'check')

    def claim(self):
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # GET jobs can be retried; CREATE jobs still meet the persistent
            # reservation and therefore never blindly repeat an uncertain POST.
            db.execute("UPDATE payment_jobs SET state='queued', token=NULL WHERE state='running' AND lease<? "
                       "AND NOT EXISTS(SELECT 1 FROM payment_jobs q WHERE q.order_id=payment_jobs.order_id AND q.action=payment_jobs.action AND q.state='queued')", (time.time(),))
            db.execute("UPDATE payment_jobs SET state='superseded' WHERE state='running' AND lease<?", (time.time(),))
            job = db.execute("SELECT * FROM payment_jobs j WHERE state='queued' AND due<=? AND NOT EXISTS "
                "(SELECT 1 FROM payment_jobs r WHERE r.order_id=j.order_id AND r.state='running') ORDER BY id LIMIT 1", (time.time(),)).fetchone()
            if job is None: return None
            token = secrets.token_hex(16)
            db.execute("UPDATE payment_jobs SET state='running',token=?,lease=?,attempts=attempts+1 WHERE id=?", (token, time.time()+300, job['id']))
        return {**dict(job), 'token': token, 'attempts': job['attempts'] + 1}

    def process_one(self, provider):
        job = self.claim()
        if job is None: return False
        identity = job['order_id']; error = None; reserved = False
        try:
            row = self.get(identity); accepted = {**self.accepted(identity), 'payment_attempt': row['attempt']}
            if row['mode'] != provider.mode: raise ValueError('Falscher Worker-Zahlungsmodus')
            if job['action'] == 'create':
                if not provider.profile_verified: provider.verify_profile()
                with self.ledger.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    changed = db.execute("UPDATE payment_orders SET state='reserved',updated=? WHERE order_id=? AND state='requested' AND payment_id IS NULL", (time.time(), identity)).rowcount
                    if changed != 1:
                        if row['payment_id']: return self.finish(job)
                        raise PaymentUncertain('Bereits reservierte Zahlung zuerst abgleichen')
                    self.event(db, identity, 'reserved')
                reserved = True
                payment = provider.create(accepted)
                validate_payment(payment, {**accepted, 'payment_id': payment['id']}, row['mode'])
                with self.ledger.db() as db:
                    db.execute("UPDATE payment_orders SET payment_id=?,checkout=?,state='open',requires_check=1,updated=? WHERE order_id=?",
                               (payment['id'], payment['_links']['checkout']['href'], time.time(), identity))
                    self.queue(db, identity, 'check'); self.event(db, identity, 'payment_created')
            elif job['action'] == 'check':
                if not provider.profile_verified: provider.verify_profile()
                payment = provider.retrieve(row['payment_id'], {**accepted, 'payment_id': row['payment_id']})
                paid = validate_payment(payment, {**accepted, 'payment_id': row['payment_id']}, row['mode'])
                status = payment.get('status')
                if status not in ('open', 'pending', 'authorized', 'paid', 'failed', 'canceled', 'expired'):
                    raise ValueError('Unbekannter Zahlungsstatus')
                state = 'blocked' if row['prior_paid'] else ('paid' if paid else ('held' if status == 'paid' else status))
                # Recheck cancellation immediately before a clearance commit.
                self.accepted(identity)
                with self.ledger.db() as db:
                    changed=db.execute('UPDATE payment_orders SET state=?,checked=?,requires_check=0,updated=? WHERE order_id=? AND attempt=? AND payment_id=?',
                               (state, time.time(), time.time(), identity,row['attempt'],row['payment_id'])).rowcount
                    if changed and row['state'] != state:self.event(db, identity, state)
                    if changed and state in ('failed','canceled','expired') and not row['prior_paid'] and row['attempt']<20:
                        self.notices.enqueue(identity,'payment_action_required',str(row['attempt']),
                            {'payment_id':row['payment_id'],'mode':row['mode']},db=db)
            elif job['action'].startswith('prior:'):
                pid = job['action'][6:]
                with self.ledger.db() as db:
                    previous = db.execute('SELECT * FROM payment_previous WHERE payment_id=? AND order_id=?', (pid, identity)).fetchone()
                if previous is None: raise ValueError('Unbekannter früherer Zahlungsversuch')
                if not provider.profile_verified: provider.verify_profile()
                old_order = {**accepted, 'payment_id': pid, 'payment_attempt': previous['attempt']}
                payment = provider.retrieve(pid, old_order)
                paid = validate_payment(payment, old_order, row['mode'])
                with self.ledger.db() as db:
                    if paid:
                        db.execute("UPDATE payment_orders SET state='blocked',prior_paid=1,requires_check=1 WHERE order_id=?", (identity,))
                        self.event(db, identity, 'unexpected_prior_payment')
                    elif row['payment_id']: self.queue(db, identity, 'check')
            elif job['action'].startswith('recover:'):
                if row['payment_id']: return self.finish(job)
                pid = job['action'][8:]
                with self.ledger.db() as db:
                    if db.execute('SELECT 1 FROM payment_orders WHERE payment_id=?', (pid,)).fetchone() or db.execute('SELECT 1 FROM payment_previous WHERE payment_id=?', (pid,)).fetchone():
                        raise ValueError('Zahlung bereits zugeordnet')
                if not provider.profile_verified: provider.verify_profile()
                recovered_order = {**accepted, 'payment_id': pid}
                payment = provider.retrieve(pid, recovered_order)
                validate_payment(payment, recovered_order, row['mode'])
                link = checkout_url(payment, required=payment.get('status') == 'open')
                # Recovery binds the ID, never treats the operator's hint as
                # paid and never issues a new provider payment.
                with self.ledger.db() as db:
                    db.execute("UPDATE payment_orders SET payment_id=?,checkout=?,state='open',requires_check=1,updated=? WHERE order_id=? AND payment_id IS NULL", (pid, link, time.time(), identity))
                    self.queue(db, identity, 'check'); self.event(db, identity, 'payment_recovered')
            else: raise ValueError('Unbekannte Zahlungsaktion')
        except PaymentUncertain:
            error = 'provider_uncertain'
            with self.ledger.db() as db:
                retry_creation = job['action'] == 'create' and not reserved and row['state'] == 'requested'
                db.execute("UPDATE payment_orders SET state=?,requires_check=1,updated=? WHERE order_id=?",
                           ('requested' if retry_creation else 'uncertain', time.time(), identity))
                if job['action'] == 'check': self.queue(db, identity, 'check')
                if job['action'].startswith('prior:'): self.queue(db, identity, job['action'])
                if job['action'].startswith('recover:'): self.queue(db, identity, job['action'])
                if retry_creation: self.queue(db, identity, 'create')
                self.event(db, identity, 'provider_uncertain')
        except (ValueError, KeyError, TypeError):
            error = 'validation_blocked'
            with self.ledger.db() as db:
                db.execute("UPDATE payment_orders SET state='blocked',requires_check=1,updated=? WHERE order_id=?", (time.time(), identity))
                self.event(db, identity, 'validation_blocked')
        self.finish(job, error)
        return True

    def finish(self, job, error=None):
        with self.ledger.db() as db:
            db.execute('UPDATE payment_jobs SET state=?,error=? WHERE id=? AND token=?',
                       ('failed' if error else 'done', error, job['id'], job['token']))
            if error == 'provider_uncertain':
                db.execute("UPDATE payment_jobs SET due=? WHERE order_id=? AND state='queued'", (time.time()+60, job['order_id']))
        return True
