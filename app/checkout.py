"""Versioned online offers, explicit acceptance and idempotent invoice linkage.

Lives in the existing invoice database; never sends mail or creates payments.
Document bytes and accepted terms remain immutable, including after deployment.
"""
from datetime import date, timedelta
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import sqlite3
import time
import zipfile
import urllib.parse
from pathlib import Path

import invoicing

KINDS = ('terms', 'avv', 'consumer')
LABELS = {'terms': 'Leistungsbedingungen', 'avv': 'AV-Vertrag einschließlich Anlagen',
          'consumer': 'Verbraucherinformationen, Widerrufsbelehrung und Musterformular'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class Checkout:
    def __init__(self, ledger, config_path):
        self.ledger = ledger
        self.config_path = Path(config_path)
        with ledger.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS checkout_offers(
                id TEXT PRIMARY KEY, session_hash TEXT NOT NULL, created REAL NOT NULL,
                expires REAL NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS checkout_documents(
                offer_id TEXT NOT NULL REFERENCES checkout_offers(id), kind TEXT NOT NULL,
                mime TEXT NOT NULL, version TEXT NOT NULL, sha256 TEXT NOT NULL, raw BLOB NOT NULL,
                PRIMARY KEY(offer_id,kind));
              CREATE TABLE IF NOT EXISTS checkout_receipts(
                offer_id TEXT NOT NULL, kind TEXT NOT NULL, sha256 TEXT NOT NULL, at REAL NOT NULL,
                PRIMARY KEY(offer_id,kind));
              CREATE TABLE IF NOT EXISTS checkout_acceptances(
                offer_id TEXT PRIMARY KEY REFERENCES checkout_offers(id), order_id TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL, created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS checkout_invoice_links(
                order_id TEXT PRIMARY KEY, invoice_id INTEGER UNIQUE NOT NULL REFERENCES invoices(id));
            ''')
            for table in ('checkout_offers', 'checkout_documents', 'checkout_acceptances', 'checkout_invoice_links'):
                for action in ('UPDATE', 'DELETE'):
                    db.execute(f'CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action.lower()} '
                               f'BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,\'Checkout record is immutable\'); END')
        from checkout_notices import CheckoutNotices
        self.customer_notices=CheckoutNotices(ledger)

    def configuration(self):
        cfg = json.loads(self.config_path.read_text())
        if cfg.get('brand') != 'abrechnungs-navi' or cfg.get('online_contract_approved') is not True:
            raise ValueError('Online-Vertragsfassung noch nicht freigegeben')
        return cfg

    def documents(self):
        cfg = self.configuration()
        result = {}
        for kind in KINDS:
            entry = cfg.get('documents', {}).get(kind, {})
            path = Path(entry.get('path', ''))
            if path.is_symlink() or not path.is_file():
                raise ValueError('Vertragsunterlage fehlt: ' + kind)
            raw = path.read_bytes()
            if not raw or len(raw) > 5_000_000 or digest(raw) != entry.get('sha256'):
                raise ValueError('Vertragsfassung verändert: ' + kind)
            version = invoicing.text(entry.get('version', ''), 80)
            mime = entry.get('mime')
            if mime not in ('application/pdf', 'text/plain; charset=utf-8'):
                raise ValueError('Vertragsunterlagen müssen PDF oder Text sein')
            result[kind] = dict(raw=raw, sha256=digest(raw), version=version, mime=mime)
        return result

    def create_offer(self, values, session):
        if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', session):
            raise ValueError('Sitzung fehlt')
        docs = self.documents()
        identity = secrets.token_hex(20)
        # The accounting validator is the authoritative price calculation.
        values = dict(values, reference='AN-' + secrets.token_hex(16), kind='advance')
        data = invoicing.order(values)
        if date.fromisoformat(data['service_date']) < invoicing.today() + timedelta(days=15):
            raise ValueError('Voraussichtlichen Leistungsbeginn mindestens 15 Kalendertage später wählen')
        email = invoicing.text(values.get('email', ''), 254)
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email):
            raise ValueError('Gültige E-Mail-Adresse erforderlich')
        property_address = invoicing.text(values.get('property_address', ''), 250)
        company = invoicing.issuer(self.ledger.config_path)
        if data['total_cents'] > 25000 and not company['tax_id']:
            raise ValueError('Ausstellerkennung für Rechnungen über 250 € fehlt')
        payload = {'order': data, 'issuer': company, 'email': email,
                   'property_address': property_address,
                   'documents': {k: {a: d[a] for a in ('sha256', 'version', 'mime')} for k, d in docs.items()},
                   'price_version': data['price_version'], 'early_start_requested': False}
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        now = time.time()
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM checkout_offers WHERE session_hash=? AND created>?',
                          (digest(session.encode()), now - 3600)).fetchone()[0] >= 5:
                raise ValueError('Bitte später erneut versuchen; maximal fünf Angebote pro Stunde')
            db.execute('INSERT INTO checkout_offers VALUES(?,?,?,?,?,?)',
                       (identity, digest(session.encode()), now, now + 86400, serialized, digest(serialized.encode())))
            for kind, doc in docs.items():
                db.execute('INSERT INTO checkout_documents VALUES(?,?,?,?,?,?)',
                           (identity, kind, doc['mime'], doc['version'], doc['sha256'], doc['raw']))
        return identity

    def offer(self, identity, session, *, unexpired=False):
        if not re.fullmatch(r'[a-f0-9]{40}', identity):
            raise ValueError('Angebot nicht gefunden')
        with self.ledger.db() as db:
            row = db.execute('SELECT * FROM checkout_offers WHERE id=?', (identity,)).fetchone()
        if row is None or not secrets.compare_digest(row['session_hash'], digest(session.encode())):
            raise ValueError('Angebot nicht gefunden')
        if digest(row['payload'].encode()) != row['sha256']:
            raise ValueError('Angebotsintegrität verletzt')
        if unexpired and row['expires'] <= time.time():
            raise ValueError('Angebot abgelaufen; bitte neu erstellen')
        return dict(row), json.loads(row['payload'])

    def document(self, identity, session, kind):
        self.offer(identity, session)
        with self.ledger.db() as db:
            row = db.execute('SELECT * FROM checkout_documents WHERE offer_id=? AND kind=?', (identity, kind)).fetchone()
        if row is None or digest(row['raw']) != row['sha256']:
            raise ValueError('Vertragsunterlage nicht verfügbar')
        return row

    def mark_delivered(self, identity, session, kind):
        doc = self.document(identity, session, kind)
        with self.ledger.db() as db:
            db.execute('INSERT OR IGNORE INTO checkout_receipts VALUES(?,?,?,?)',
                       (identity, kind, doc['sha256'], time.time()))

    def accept(self, identity, session, submitted_sha, checks):
        row, payload = self.offer(identity, session)
        if not secrets.compare_digest(row['sha256'], submitted_sha):
            raise ValueError('Angebotsfassung stimmt nicht überein')
        for field in ('contract', 'avv', 'consumer'):
            if checks.get(field) is not True:
                raise ValueError('Ausdrückliche Zustimmung fehlt: ' + field)
        if checks.get('early_start'):
            raise ValueError('Vorzeitiger Leistungsbeginn wird hier nicht vereinbart')
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload FROM checkout_acceptances WHERE offer_id=?', (identity,)).fetchone()
            if existing:
                return json.loads(existing['payload'])
            if row['expires'] <= time.time():
                raise ValueError('Angebot abgelaufen')
            current = self.documents()
            if any(current[k]['sha256'] != payload['documents'][k]['sha256'] for k in KINDS):
                raise ValueError('Vertragsunterlagen aktualisiert; neues Angebot erforderlich')
            if invoicing.issuer(self.ledger.config_path) != payload['issuer']:
                raise ValueError('Aussteller geändert; neues Angebot erforderlich')
            receipts = {r['kind']: r['sha256'] for r in db.execute(
                'SELECT kind,sha256 FROM checkout_receipts WHERE offer_id=?', (identity,))}
            if any(receipts.get(k) != payload['documents'][k]['sha256'] for k in KINDS):
                raise ValueError('Bitte zuerst alle Vertragsunterlagen herunterladen')
            acceptance = dict(id=payload['order']['reference'], apartments=payload['order']['apartments'],
                              houses=payload['order']['houses'], total_cents=payload['order']['total_cents'],
                              offer_sha256=row['sha256'], avv_sha256=payload['documents']['avv']['sha256'],
                              consumer_information_sha256=payload['documents']['consumer']['sha256'],
                              terms_sha256=payload['documents']['terms']['sha256'],
                              contract_accepted=True, avv_accepted=True, consumer_information_delivered=True,
                              accepted_at=time.time(), acceptance_method='online-explicit-checkboxes-v1',
                              early_start_requested=False, state='contracted', offer_id=identity)
            db.execute('INSERT INTO checkout_acceptances VALUES(?,?,?,?)',
                       (identity, acceptance['id'], json.dumps(acceptance, sort_keys=True), time.time()))
            self.customer_notices.notices.enqueue(acceptance['id'],'order_confirmation',identity,{'offer_id':identity},db=db)
        return acceptance

    def invoice(self, identity, session):
        _, payload = self.offer(identity, session)
        with self.ledger.db() as db:
            accepted = db.execute('SELECT order_id FROM checkout_acceptances WHERE offer_id=?', (identity,)).fetchone()
        if accepted is None:
            raise ValueError('Angebot noch nicht beauftragt')
        # Stable draft key makes this safe after a crash between invoice write
        # and link insertion. A duplicate click cannot allocate another number.
        invoice_id = self.ledger._write({'order': payload['order'], 'issuer': payload['issuer']}, draft_id=identity)
        with self.ledger.db() as db:
            inserted=db.execute('INSERT OR IGNORE INTO checkout_invoice_links VALUES(?,?)', (accepted['order_id'], invoice_id)).rowcount
            if inserted:self.customer_notices.notices.enqueue(accepted['order_id'],'invoice_available',str(invoice_id),{'offer_id':identity},db=db)
        return self.ledger.get(invoice_id)

    def packet(self, identity, session):
        row, payload = self.offer(identity, session)
        with self.ledger.db() as db:
            accepted = db.execute('SELECT payload FROM checkout_acceptances WHERE offer_id=?', (identity,)).fetchone()
        if accepted is None:
            raise ValueError('Auftrag noch nicht bestätigt')
        result = io.BytesIO()
        with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('Angebot.json', json.dumps(payload, ensure_ascii=False, indent=2))
            archive.writestr('Auftragsbestaetigung.json', accepted['payload'])
            confirmation = json.loads(accepted['payload'])
            data = payload['order']
            archive.writestr('Auftragsbestaetigung.txt', '\n'.join((
                'ABRECHNUNGS-NAVI – Auftragsbestätigung',
                'Auftragsnummer: ' + confirmation['id'],
                'Rechnungsempfänger: ' + data['customer'],
                'Anschrift: ' + data['address'] + ', ' + data['city'],
                'E-Mail: ' + payload['email'],
                'Objekt(e): ' + payload['property_address'],
                'Abrechnungsjahr: ' + str(data['year']),
                'Wohnungen: ' + str(data['apartments']) + '; Häuser: ' + str(data['houses']),
                'Gesamtpreis einmalig: ' + invoicing.money(data['total_cents']),
                invoicing.NOTICE,
                'Angenommen am: ' + invoicing.datetime.fromtimestamp(confirmation['accepted_at'], invoicing.ZONE).isoformat(),
                'Voraussichtlicher Leistungsbeginn: ' + data['service_date'] + ' (keine Terminzusage)',
                'Kein vorzeitiger Leistungsbeginn vereinbart. Diese Bestätigung ist kein Zahlungs- oder Leistungsnachweis.',
                'Die Vertragsfassungen einschließlich AV-Vertrag und Widerrufsunterlagen liegen unverändert bei.',
                'Kontakt: kontakt@abrechnungs-navi.de', '')))
            for kind in KINDS:
                doc = self.document(identity, session, kind)
                archive.writestr(kind + ('.pdf' if doc['mime'] == 'application/pdf' else '.txt'), doc['raw'])
            invoice = self.invoice(identity, session)
            archive.writestr('Vorausrechnung.pdf', invoice['pdf'])
        return result.getvalue()


def install(app):
    """Attach to the existing authenticated application; public launch stays gated."""
    old = app.H
    config_path = os.environ.get('AN_CHECKOUT_CONFIG', '/etc/an-upload/checkout.json')
    from payment_flow import PaymentFlow, settings as payment_settings
    payment_path = os.environ.get('AN_PAYMENT_CONFIG', '/etc/an-upload/payments.json')

    def payment_flow():
        ledger = invoicing.ledger(app)
        Checkout(ledger, config_path)
        return PaymentFlow(ledger)

    def payment_clearance(customer):
        identity = customer.get('payment_order_id')
        if not identity: return True  # Existing individually released orders retain their workflow.
        try:
            cfg = payment_settings(payment_path)
            row = payment_flow().require_paid(identity)
            return row['mode'] == cfg['mode']
        except (ValueError, OSError, KeyError, sqlite3.Error): return False
    app.payment_clearance = payment_clearance
    if hasattr(app, 'admin_page'):
        previous_admin = app.admin_page
        def admin_page(*args, **kwargs):
            return previous_admin(*args, **kwargs).replace('<h1>Auftragsfreigaben</h1>',
                '<h1>Auftragsfreigaben</h1><p><a href="/verwaltung/bestellungen">Onlinebestellungen und Vertragsnachweise</a></p>')
        app.admin_page = admin_page

    def service(accepting=False):
        store = Checkout(invoicing.ledger(app), config_path)
        if accepting:
            cfg = store.configuration()
            if cfg.get('enabled') is not True or app.readiness():
                raise ValueError('Die Onlinebestellung ist noch nicht freigeschaltet')
        return store

    def secret(store):
        path = store.ledger.folder / 'checkout-session.secret'
        if not path.exists():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(secrets.token_bytes(32)); stream.flush(); os.fsync(stream.fileno())
            except FileExistsError:
                pass
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('Sitzungsschlüssel nicht geschützt')
        raw = path.read_bytes()
        if len(raw) != 32:
            raise ValueError('Sitzungsschlüssel ungültig')
        return raw

    def csrf(session, key):
        return hmac.new(key, ('csrf:' + session).encode(), 'sha256').hexdigest()

    def field(label, name, kind='text', value='', extra=''):
        return f'<label>{html.escape(label)}<input name="{name}" type="{kind}" value="{html.escape(str(value), quote=True)}" required {extra}></label>'

    def screen(title, body):
        return app.page(title, '<style>.checkout{max-width:760px;margin:auto}.checkout label{display:block;margin:18px 0}.checkout input:not([type=checkbox]){display:block;width:100%;padding:12px;font:inherit;border:1px solid #8c9caa;border-radius:8px;box-sizing:border-box}.checkout input[type=checkbox]{width:20px;height:20px;vertical-align:middle;margin-right:8px}.checkout button{padding:14px 22px;font:inherit}.checkout .total{font-size:28px;font-weight:700}.checkout dt{font-weight:700;margin-top:12px}.checkout dd{margin:4px 0}.checkout a{text-decoration:underline}</style><main class="checkout"><p><a href="/">Abrechnungs-Navi</a></p>' + body + '</main>')

    class Handler(old):
        def checkout_session(self, store, create=False):
            from http.cookies import SimpleCookie, CookieError
            cookie = SimpleCookie()
            try: cookie.load(self.headers.get('Cookie', ''))
            except CookieError: pass
            value = cookie['an_checkout'].value if 'an_checkout' in cookie else ''
            key = secret(store)
            parts = value.split('.')
            if len(parts) == 3 and re.fullmatch(r'[A-Za-z0-9_-]{43}', parts[0]) and parts[1].isdigit():
                signed = '.'.join(parts[:2])
                expected = hmac.new(key, signed.encode(), 'sha256').hexdigest()
                if secrets.compare_digest(parts[2], expected) and 0 <= time.time() - int(parts[1]) <= 172800:
                    return parts[0], key, {}
            if not create:
                raise ValueError('Sitzung abgelaufen; bitte Bestellung erneut öffnen')
            session = secrets.token_urlsafe(32)
            signed = session + '.' + str(int(time.time()))
            value = signed + '.' + hmac.new(key, signed.encode(), 'sha256').hexdigest()
            return session, key, {'Set-Cookie': 'an_checkout=' + value + '; Path=/bestellen; Max-Age=172800; HttpOnly; Secure; SameSite=Strict'}

        def checkout_send(self, code, body, mime='text/html; charset=utf-8', headers=None):
            return self.send(code, body, mime, {'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
                                              'Referrer-Policy': 'no-referrer', 'Cache-Control':'no-store', **(headers or {})})

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path
            documents=re.fullmatch(r'/bestellen/([a-f0-9]{40})/dokumente/(vertrag|rechnung)',path)
            if documents:
                identity,kind=documents.groups()
                try:
                    store=service()
                    from http.cookies import SimpleCookie
                    cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
                    token=cookies['an_checkout_documents'].value if 'an_checkout_documents' in cookies else ''
                    try:data=store.customer_notices.authorize(identity,token)
                    except ValueError:
                        return self.checkout_send(200,screen('Dokumente geschützt öffnen',
                            '<h1>Ihre Vertragsunterlagen und Rechnung</h1><p>Fordern Sie einen einmaligen Code an. Er wird an die bei der Bestellung hinterlegte E-Mail-Adresse gesendet und gilt zehn Minuten.</p>'
                            f'<form method="post" action="{path}/code"><button>Zugangscode anfordern</button></form>'
                            f'<form method="post" action="{path}/anmelden"><label>Zugangscode<input name="code" inputmode="numeric" pattern="[0-9]{{6}}" required autocomplete="one-time-code"></label><button>Dokument öffnen</button></form>'
                            '<p>Bitte senden Sie keine Mieterbelege per E-Mail.</p>'))
                    if kind=='rechnung':
                        invoice,_=store.customer_notices.invoice(data)
                        return self.checkout_send(200,invoice['pdf'],'application/pdf',{'Content-Disposition':'attachment; filename="Abrechnungs-Navi-Rechnung.pdf"'})
                    return self.checkout_send(200,store.customer_notices.packet(data),'application/zip',{'Content-Disposition':'attachment; filename="Abrechnungs-Navi-Vertragsunterlagen.zip"'})
                except (ValueError,OSError,KeyError):return self.checkout_send(404,screen('Dokument nicht verfügbar','<h1>Dokument nicht verfügbar</h1><p>Bitte antworten Sie auf unsere Bestell-E-Mail. Es wurde kein neuer Auftrag und keine neue Zahlung angelegt.</p>'))
            payment_notice=re.fullmatch(r'/bestellen/([a-f0-9]{40})/zahlung-oeffnen',path)
            if payment_notice:
                # Generic same-site navigation restores a valid Strict cookie
                # after an email click. This route reveals no order details.
                target='/bestellen/'+payment_notice[1]+'/zahlung'
                return self.checkout_send(200,screen('Zahlungsstatus öffnen',
                    '<h1>Zahlungsstatus sicher öffnen</h1><p>Verwenden Sie den Browser, in dem Sie bestellt haben.</p>'
                    '<p><a class="btn" href="'+target+'">Geschützten Zahlungsstatus öffnen</a></p>'
                    '<p>Falls Ihre Sitzung abgelaufen ist oder Sie einen anderen Browser verwenden, antworten Sie auf unsere E-Mail. Bitte bestellen oder bezahlen Sie nicht erneut, solange der Vorgang unklar ist.</p>'))
            if path == '/zahlung/rueckkehr':
                # A cross-site redirect does not carry the Strict checkout
                # cookie. An explicit same-site click restores its normal use.
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                identity = query.get('auftrag', [''])[0]
                target = '/bestellen/' + identity + '/zahlung' if re.fullmatch(r'[a-f0-9]{40}', identity) else '/bestellen'
                return self.checkout_send(200, screen('Zahlungsstatus prüfen', '<h1>Zurück von Mollie</h1><p>Die Rückkehr allein bestätigt noch keinen Zahlungseingang.</p><p><a href="' + target + '">Zahlungsstatus sicher prüfen</a></p>'))
            if path == '/verwaltung/bestellungen':
                if not self.admin_auth(): return
                store = Checkout(invoicing.ledger(app), config_path)
                with store.ledger.db() as db:
                    rows = db.execute('SELECT a.payload AS acceptance,o.payload AS offer,l.invoice_id '
                        'FROM checkout_acceptances a JOIN checkout_offers o ON o.id=a.offer_id '
                        'LEFT JOIN checkout_invoice_links l ON l.order_id=a.order_id ORDER BY a.created DESC LIMIT 200').fetchall()
                content = '<p><a href="/verwaltung">Zur Verwaltung</a></p><h1>Onlinebestellungen</h1><p>Vertragsabschluss und Rechnung sind keine Zahlungs- oder Bearbeitungsfreigabe.</p>'
                for row in rows:
                    accepted = json.loads(row['acceptance']); offer = json.loads(row['offer'])
                    content += '<section><h2>' + html.escape(accepted['id']) + '</h2><p>' + html.escape(offer['order']['customer']) + ' · ' + invoicing.money(accepted['total_cents']) + '</p>'
                    if row['invoice_id']:
                        content += f'<p><a href="{invoicing.BASE}/{row["invoice_id"]}">Festgeschriebene Vorausrechnung öffnen</a></p>'
                    else: content += '<p>Rechnungsverknüpfung noch ausstehend; vorhandene Auftragsbestätigung prüfen.</p>'
                    payment = payment_flow().get(accepted['id'])
                    if payment:
                        content += '<p>Zahlungsstatus: ' + html.escape(payment['state']) + ' · Modus: ' + html.escape(payment['mode']) + '</p>'
                        if payment['state'] in ('uncertain','reserved','blocked') and not payment['payment_id']:
                            content += '<form method="post" action="/verwaltung/zahlungen/abgleichen"><input type="hidden" name="order_id" value="' + html.escape(accepted['id'], quote=True) + '"><label>Zahlungs-ID aus dem Mollie-Konto<input name="payment_id" required pattern="tr_[A-Za-z0-9]+"></label><label><input type="checkbox" name="confirm" value="yes" required> Nur vorhandene Zahlung unabhängig abgleichen; keine neue Zahlung anlegen.</label><button>Vorhandene Zahlung prüfen lassen</button></form>'
                    content += '<details><summary>Vertragsnachweise anzeigen</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(json.dumps(accepted, ensure_ascii=False, indent=2)) + '</pre></details></section>'
                if not rows: content += '<p>Noch keine Onlinebestellungen vorhanden.</p>'
                return self.checkout_send(200, screen('Onlinebestellungen', content))
            if path != '/bestellen' and not path.startswith('/bestellen/'):
                return super().do_GET()
            try:
                store = service(accepting=path == '/bestellen')
            except (OSError, ValueError, KeyError):
                return self.checkout_send(503, screen('Bestellung noch nicht verfügbar', '<h1>Onlinebestellung noch nicht verfügbar</h1><p>Bitte noch keine Bestellung oder Unterlagen senden.</p>'))
            try:
                session, key, headers = self.checkout_session(store, create=path == '/bestellen')
                if path == '/bestellen':
                    fields = field('Name / Rechnungsempfänger', 'customer', extra='maxlength="150" autocomplete="name"')
                    fields += field('Straße und Hausnummer', 'address', extra='maxlength="180" autocomplete="street-address"')
                    fields += field('Postleitzahl und Ort', 'city', extra='maxlength="150"')
                    fields += field('E-Mail-Adresse', 'email', 'email', extra='maxlength="254" autocomplete="email"')
                    fields += field('Adresse des abzurechnenden Objekts / der Objekte', 'property_address', extra='maxlength="250"')
                    fields += field('Wohnungen insgesamt', 'apartments', 'number', 1, 'min="1" max="200"')
                    fields += field('Häuser insgesamt', 'houses', 'number', 1, 'min="1" max="200"')
                    fields += field('Abrechnungsjahr', 'year', 'number', invoicing.today().year - 1, f'min="2000" max="{invoicing.today().year}"')
                    earliest = (invoicing.today() + timedelta(days=15)).isoformat()
                    fields += field('Voraussichtlicher Leistungsbeginn', 'service_date', 'date', earliest, f'min="{earliest}"')
                    fields += '<input type="hidden" name="country" value="DE">'
                    fields += f'<input type="hidden" name="csrf" value="{csrf(session, key)}">'
                    return self.checkout_send(200, screen('Angebot erstellen', '<h1>Ihr Angebot zur Nebenkostenabrechnung</h1><p>89 € für die erste Wohnung je Haus, 59 € für jede weitere Wohnung im selben Haus. Einmalig, kein Abo. Keine gesonderte Umsatzsteuer.</p><p>Rechnungsanschrift in Deutschland. Bitte keine Mieterdaten oder Belege eingeben. Der Leistungsbeginn wird erst nach Zahlung, vollständigen Unterlagen und zulässigem Beginn bestätigt; der Wunschtermin ist keine Terminzusage.</p><form method="post" action="/bestellen/angebot">' + fields + '<button>Angebot unverbindlich prüfen</button></form>'), headers=headers)
                match = re.fullmatch(r'/bestellen/([a-f0-9]{40})(?:/(terms|avv|consumer|paket|rechnung|bestaetigung|zahlung))?', path)
                if not match:
                    return self.checkout_send(404, 'Nicht gefunden', 'text/plain; charset=utf-8')
                identity, action = match.groups()
                row, payload = store.offer(identity, session)
                if action == 'zahlung':
                    # No payment ID or status can be supplied by this browser.
                    invoice = store.invoice(identity, session)
                    flow = payment_flow(); order_id = payload['order']['reference']
                    payment = flow.get(order_id)
                    if payment:
                        flow.request_check(order_id)
                    state = payment['state'] if payment else 'not_requested'
                    messages = {'not_requested': 'Der Zahlungsbetrieb ist noch nicht freigeschaltet.',
                        'requested': 'Ihr Zahlungslink wird vorbereitet. Bitte aktualisieren Sie diese Seite in wenigen Sekunden.',
                        'reserved': 'Ihr Zahlungslink wird vorbereitet. Bitte warten Sie; legen Sie keinen zweiten Auftrag an.',
                        'open': 'Die Zahlung ist noch offen.', 'pending': 'Mollie verarbeitet Ihre Zahlung noch.',
                        'authorized': 'Die Zahlung ist autorisiert, aber noch nicht eingegangen.',
                        'paid': 'Ihr Zahlungseingang ist unabhängig bestätigt.',
                        'held': 'Eine Erstattung oder Rückbuchung liegt vor. Die Bearbeitung ist gesperrt.',
                        'uncertain': 'Der Zahlungsstatus ist noch unklar. Es wird keine zweite Zahlung angelegt.',
                        'blocked': 'Die Zahlung muss geprüft werden. Die Bearbeitung bleibt gesperrt.',
                        'failed': 'Die Zahlung ist fehlgeschlagen. Bitte kontaktieren Sie uns.',
                        'expired': 'Die Zahlung ist abgelaufen. Bitte kontaktieren Sie uns.',
                        'canceled': 'Die Zahlung wurde abgebrochen. Bitte kontaktieren Sie uns.'}
                    if payment and payment['requires_check']:
                        message = 'Der aktuelle Zahlungsstatus wird bei Mollie geprüft. Die Bearbeitung bleibt bis zur Bestätigung gesperrt.'
                    else: message = messages.get(state, 'Der Zahlungsstatus wird geprüft.')
                    if state == 'paid':
                        try: flow.require_paid(order_id)
                        except ValueError: message = 'Der aktuelle Zahlungseingang wird erneut geprüft. Die Bearbeitung bleibt bis dahin gesperrt.'
                    content = '<h1>Ihre Zahlung</h1><p>Auftrag ' + html.escape(order_id) + '</p><p>' + html.escape(message) + '</p>'
                    if payment and payment['checkout'] and state in ('open', 'pending', 'authorized'):
                        content += '<p><a class="btn" rel="noreferrer" href="' + html.escape(payment['checkout'], quote=True) + '">Zur sicheren Zahlung bei Mollie</a></p>'
                    if payment and state in ('failed', 'expired', 'canceled') and not payment['requires_check']:
                        content += f'<form method="post" action="/bestellen/{identity}/zahlung/wiederholen"><input type="hidden" name="csrf" value="{csrf(session, key)}"><button>Neuen Zahlungsversuch starten</button></form>'
                    content += f'<p><a href="/bestellen/{identity}/zahlung">Zahlungsstatus aktualisieren</a></p><p>Nach bestätigter Zahlung gelten weiterhin die Voraussetzungen zum Leistungsbeginn und die abschließende persönliche Prüfung Ihrer Abrechnung.</p>'
                    if state=='paid' and not payment['requires_check']:
                        content+=f'<p><a class="btn" href="/bestellen/{identity}/unterlagen">Geschützten Kundenbereich öffnen</a></p>'
                    refresh = {'Refresh': f'5; url=/bestellen/{identity}/zahlung'} if payment and state in ('requested','reserved') and time.time()-payment['updated'] < 120 else {}
                    return self.checkout_send(200, screen('Ihre Zahlung', content), headers=refresh)
                if action in KINDS:
                    doc = store.document(identity, session, action)
                    suffix = '.pdf' if doc['mime'] == 'application/pdf' else '.txt'
                    result = self.checkout_send(200, doc['raw'], doc['mime'], {'Content-Disposition': 'attachment; filename="' + action + suffix + '"'})
                    if self.command != 'HEAD': store.mark_delivered(identity, session, action)
                    return result
                if action == 'paket':
                    return self.checkout_send(200, store.packet(identity, session), 'application/zip', {'Content-Disposition': 'attachment; filename="Abrechnungs-Navi-Vertragsunterlagen.zip"'})
                if action in ('rechnung', 'bestaetigung'):
                    invoice = store.invoice(identity, session)
                    if action == 'rechnung':
                        return self.checkout_send(200, invoice['pdf'], 'application/pdf', {'Content-Disposition': 'attachment; filename="Vorausrechnung.pdf"'})
                    return self.checkout_send(200, screen('Auftrag bestätigt', '<h1>Ihr Auftrag ist gespeichert</h1><p>Auftragsnummer: ' + html.escape(payload['order']['reference']) + '</p><p><a href="/bestellen/' + identity + '/zahlung">Zahlung und Zahlungsstatus öffnen</a></p><p>Die Bearbeitung startet erst nach bestätigter Zahlung und zulässigem Leistungsbeginn.</p><p><a href="/bestellen/' + identity + '/paket">Vertragsunterlagen, Auftragsbestätigung und Vorausrechnung herunterladen</a></p><p>Bitte speichern Sie dieses Paket. Ein automatischer E-Mail-Versand erfolgt hier noch nicht.</p>'))
                data = payload['order']
                summary = '<dl>' + ''.join('<dt>' + label + '</dt><dd>' + html.escape(str(value)) + '</dd>' for label, value in (
                    ('Rechnungsempfänger', data['customer']), ('Anschrift', data['address'] + ', ' + data['city']),
                    ('E-Mail', payload['email']), ('Objekt', payload['property_address']), ('Abrechnungsjahr', data['year']),
                    ('Wohnungen / Häuser', f'{data["apartments"]} / {data["houses"]}'), ('Voraussichtlicher Leistungsbeginn', data['service_date']))) + '</dl>'
                summary += '<p class="total">Gesamtpreis: ' + invoicing.money(data['total_cents']) + '</p><p>' + html.escape(invoicing.NOTICE) + '</p>'
                links = '<ul>' + ''.join(f'<li><a href="/bestellen/{identity}/{kind}">{LABELS[kind]} herunterladen</a> – Fassung {html.escape(payload["documents"][kind]["version"])}</li>' for kind in KINDS) + '</ul>'
                checks = ''.join(f'<label><input type="checkbox" name="{name}" value="yes" required>{label}</label>' for name, label in (
                    ('contract', 'Ich beauftrage die oben beschriebene Leistung zum angezeigten Gesamtpreis und akzeptiere die Leistungsbedingungen.'),
                    ('avv', 'Ich schließe den vollständigen AV-Vertrag einschließlich Anlagen für diesen Auftrag.'),
                    ('consumer', 'Ich habe die Verbraucherinformationen, Widerrufsbelehrung und das Musterformular heruntergeladen.')))
                hidden = f'<input type="hidden" name="csrf" value="{csrf(session, key)}"><input type="hidden" name="offer_sha256" value="{row["sha256"]}">'
                return self.checkout_send(200, screen('Angebot prüfen', '<h1>Angebot prüfen und beauftragen</h1>' + summary + '<p>Das Angebot gilt 24 Stunden. Änderungen sind vor der Bestellung über ein neues Angebot möglich.</p><p><a href="/bestellen">Angaben korrigieren / neues Angebot</a></p>' + links + '<p>Bitte alle drei Unterlagen herunterladen. Es wird kein vorzeitiger Leistungsbeginn vereinbart. Der Auftrag enthält keine Rechts- oder Steuerberatung.</p><form method="post" action="/bestellen/' + identity + '/annehmen">' + hidden + checks + '<button>Zahlungspflichtig bestellen</button></form>'))
            except (ValueError, OSError, KeyError):
                return self.checkout_send(400, screen('Bestellung prüfen', '<h1>Bestellung nicht verfügbar</h1><p>Bitte prüfen Sie die Sitzung und Ihre Eingaben oder erstellen Sie ein neues Angebot.</p><p><a href="/bestellen">Neu beginnen</a></p>'))

        do_HEAD = do_GET

        def do_POST(self):
            path = urllib.parse.urlsplit(self.path).path
            documents=re.fullmatch(r'/bestellen/([a-f0-9]{40})/dokumente/(vertrag|rechnung)/(code|anmelden)',path)
            if documents:
                identity,kind,action=documents.groups();target='/bestellen/'+identity+'/dokumente/'+kind
                if self.headers.get('Origin')!='https://abrechnungs-navi.de':return self.checkout_send(403,'Ungültiger Ursprung','text/plain; charset=utf-8')
                try:
                    if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/x-www-form-urlencoded':raise ValueError('Ungültige Formulardaten')
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<=length<=1024:raise ValueError('Ungültige Formulardaten')
                    values=urllib.parse.parse_qs(self.rfile.read(length).decode(),max_num_fields=5)
                    store=service()
                    if action=='code':
                        cfg=json.loads(Path(os.environ.get('AN_AUTOMATION_CONFIG','/etc/an-upload/automation.json')).read_text())
                        if app.readiness() or cfg.get('brand')!='abrechnungs-navi' or cfg.get('region')!='eu1' or cfg.get('enabled') is not True or cfg.get('mail_enabled') is not True or cfg.get('mail_provider_approved') is not True or not re.fullmatch(r'[a-f0-9]{64}',cfg.get('mail_provider_evidence_sha256','')):
                            return self.checkout_send(503,screen('Versand noch nicht freigeschaltet','<h1>Versand noch nicht freigeschaltet</h1><p>Bitte kontaktieren Sie uns über kontakt@abrechnungs-navi.de.</p>'))
                        try:store.customer_notices.request_code(identity)
                        except ValueError:pass
                        return self.checkout_send(200,screen('Zugangscode angefordert','<h1>Zugangscode angefordert</h1><p>Wenn ein passender Auftrag vorliegt und die Anforderungsgrenze nicht erreicht ist, wird der Code an die hinterlegte Adresse gesendet.</p><p><a href="'+target+'">Code eingeben</a></p>'))
                    token=store.customer_notices.authenticate(identity,values.get('code',[''])[0])
                    return self.checkout_send(303,'',headers={'Location':target,'Set-Cookie':'an_checkout_documents='+token+'; Path=/bestellen/'+identity+'/dokumente; Max-Age=1800; HttpOnly; Secure; SameSite=Strict'})
                except (ValueError,OSError,KeyError,UnicodeError):return self.checkout_send(400,screen('Anmeldung nicht abgeschlossen','<h1>Anmeldung nicht abgeschlossen</h1><p>Bitte prüfen Sie den Code oder fordern Sie einen neuen an.</p><p><a href="'+target+'">Zur Anmeldung</a></p>'))
            if path == '/verwaltung/zahlungen/abgleichen':
                if not self.admin_auth(): return
                if self.headers.get('Origin') != 'https://abrechnungs-navi.de':
                    return self.checkout_send(403, 'Ungültiger Ursprung', 'text/plain; charset=utf-8')
                try:
                    if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/x-www-form-urlencoded': raise ValueError('Formulardaten erforderlich')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 1000: raise ValueError('Ungültige Größe')
                    values = urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8'), max_num_fields=3)
                    if set(values) != {'order_id','payment_id','confirm'} or any(len(v) != 1 for v in values.values()): raise ValueError('Ungültige Felder')
                    if values['confirm'][0] != 'yes': raise ValueError('Bestätigung fehlt')
                    payment_flow().request_recovery(values['order_id'][0], values['payment_id'][0])
                    return self.checkout_send(303, '', headers={'Location': '/verwaltung/bestellungen'})
                except (ValueError, KeyError, OSError):
                    return self.checkout_send(400, 'Abgleich nicht möglich; Angaben und Auftragsstatus prüfen', 'text/plain; charset=utf-8')
            if path == '/zahlung/webhook':
                # Mollie sends an object ID, never an authoritative paid flag.
                # Persist work before acknowledging; unavailable storage yields
                # a retryable failure instead of losing the notification.
                try: payment_settings(payment_path)
                except (OSError, ValueError, KeyError):
                    return self.checkout_send(503, 'Zahlungsbetrieb noch nicht freigeschaltet', 'text/plain; charset=utf-8')
                try:
                    if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/x-www-form-urlencoded':
                        raise ValueError('Formulardaten erforderlich')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 512: raise ValueError('Ungültige Größe')
                    values = urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8'), max_num_fields=4)
                    if set(values) != {'id'} or len(values['id']) != 1: raise ValueError('Nur Zahlungskennung zulässig')
                    payment_flow().webhook(values['id'][0])
                    return self.checkout_send(200, 'OK', 'text/plain; charset=utf-8')
                except ValueError:
                    return self.checkout_send(400, 'Ungültige Rückmeldung', 'text/plain; charset=utf-8')
                except (OSError, sqlite3.Error):
                    return self.checkout_send(503, 'Prüfung derzeit nicht verfügbar', 'text/plain; charset=utf-8')
            if not path.startswith('/bestellen/'):
                return super().do_POST()
            try:
                store = service(accepting=True)
            except (OSError, ValueError, KeyError):
                return self.checkout_send(503, 'Onlinebestellung noch nicht freigeschaltet', 'text/plain; charset=utf-8')
            try:
                if self.headers.get('Origin') != 'https://abrechnungs-navi.de':
                    return self.checkout_send(403, 'Ungültiger Ursprung', 'text/plain; charset=utf-8')
                if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/x-www-form-urlencoded':
                    raise ValueError('Formulardaten erforderlich')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 20000: raise ValueError('Anfrage zu groß')
                values = urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8'), keep_blank_values=True, max_num_fields=32)
                if any(len(v) != 1 for v in values.values()): raise ValueError('Doppelte Formularfelder')
                values = {k: v[0] for k, v in values.items()}
                session, key, _ = self.checkout_session(store)
                if not secrets.compare_digest(values.get('csrf', ''), csrf(session, key)):
                    return self.checkout_send(403, 'Sitzungsnachweis fehlt', 'text/plain; charset=utf-8')
                if path == '/bestellen/angebot':
                    identity = store.create_offer(values, session)
                    return self.checkout_send(303, '', headers={'Location': '/bestellen/' + identity})
                retry = re.fullmatch(r'/bestellen/([a-f0-9]{40})/zahlung/wiederholen', path)
                if retry:
                    _, payload = store.offer(retry[1], session)
                    cfg = payment_settings(payment_path)
                    payment_flow().retry(payload['order']['reference'], cfg['mode'])
                    return self.checkout_send(303, '', headers={'Location': '/bestellen/' + retry[1] + '/zahlung'})
                match = re.fullmatch(r'/bestellen/([a-f0-9]{40})/annehmen', path)
                if match:
                    accepted = store.accept(match[1], session, values.get('offer_sha256', ''),
                                 {k: values.get(k) == 'yes' for k in ('contract', 'avv', 'consumer', 'early_start')})
                    store.invoice(match[1], session)
                    try: cfg = payment_settings(payment_path)
                    except (ValueError, OSError): cfg = None
                    if cfg: payment_flow().request(accepted['id'], cfg['mode'])
                    return self.checkout_send(303, '', headers={'Location': '/bestellen/' + match[1] + '/bestaetigung'})
                return self.checkout_send(404, 'Nicht gefunden', 'text/plain; charset=utf-8')
            except (ValueError, OSError, KeyError) as exc:
                return self.checkout_send(400, screen('Eingaben prüfen', '<h1>Bitte Eingaben prüfen</h1><p>' + html.escape(str(exc)) + '</p><p><a href="/bestellen">Neues Angebot erstellen</a></p>'))
    app.H = Handler
