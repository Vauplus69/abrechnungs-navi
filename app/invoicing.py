"""Internal PDF invoices. Separate ledger, explicit issue, immutable documents; no mail/payment API."""
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

BASE = '/verwaltung/rechnungen'
NOTICE = 'Steuerbefreiung für Kleinunternehmer gemäß § 19 UStG. Es wird keine Umsatzsteuer ausgewiesen.'
ZONE = ZoneInfo('Europe/Berlin')


def today():
    return datetime.now(ZONE).date()


def money(cents):
    return f'{cents / 100:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.') + ' €'


def text(value, limit=180, required=True):
    value = str(value).strip()
    if (required and not value) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('Bitte vollständige, gültige Angaben ohne Zeilenumbrüche eingeben.')
    return value


def integer(value, low, high):
    if not re.fullmatch(r'\d{1,4}', str(value)) or not low <= int(value) <= high:
        raise ValueError('Wohnungen, Häuser oder Abrechnungsjahr sind ungültig.')
    return int(value)


def issuer(config_path):
    try:
        cfg = json.loads(Path(config_path).read_text())
    except (OSError, ValueError):
        raise ValueError('Aussteller-Konfiguration fehlt. Bitte zuerst geschützte Rechnungsdaten hinterlegen.')
    if cfg.get('tax_mode') != 'kleinunternehmer':
        raise ValueError('Dieses Rechnungsmodul ist derzeit ausschließlich für § 19 UStG eingerichtet.')
    result = {k: text(cfg.get(k, ''), 180) for k in ('name', 'address', 'city', 'email')}
    result['tax_id'] = text(cfg.get('tax_id', ''), 80, False)
    result['tax_mode'] = cfg['tax_mode']
    return result


def order(values):
    data = {k: text(values.get(k, ''), n) for k, n in
            [('customer', 150), ('address', 180), ('city', 150), ('reference', 100)]}
    if values.get('country') != 'DE':
        raise ValueError('Das Rechnungsmodul ist derzeit für Rechnungsanschriften in Deutschland eingerichtet.')
    data['country'] = 'DE'
    data['apartments'] = integer(values.get('apartments', ''), 1, 200)
    data['houses'] = integer(values.get('houses', ''), 1, data['apartments'])
    data['year'] = integer(values.get('year', ''), 2000, today().year)
    data['kind'] = values.get('kind', '')
    if data['kind'] not in ('service', 'advance'):
        raise ValueError('Bitte Rechnung für erbrachte Leistung oder Vorausrechnung wählen.')
    try:
        service = date.fromisoformat(values.get('service_date', ''))
    except (ValueError, TypeError):
        raise ValueError('Leistungsdatum oder voraussichtliches Leistungsdatum fehlt.')
    if data['kind'] == 'service' and service > today():
        raise ValueError('Eine bereits erbrachte Leistung darf kein zukünftiges Leistungsdatum haben.')
    if data['kind'] == 'advance' and service < today():
        raise ValueError('Bei einer Vorausrechnung bitte das erwartete Leistungsdatum prüfen.')
    data['service_date'] = service.isoformat()
    data['total_cents'] = data['houses'] * 8900 + (data['apartments'] - data['houses']) * 5900
    data['price_version'] = '89-59-KU-2026-11'
    return data


class Ledger:
    def __init__(self, folder, config_path):
        self.folder = Path(folder)
        self.config_path = Path(config_path)

    def connect(self):
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        db_path = self.folder / 'invoices.sqlite3'
        conn = sqlite3.connect(db_path, timeout=20)
        os.chmod(db_path, 0o600)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA synchronous=FULL')
        conn.executescript('''
          CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS invoices(
            id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE, year INTEGER NOT NULL, serial INTEGER NOT NULL,
            draft_id TEXT UNIQUE, original_id INTEGER UNIQUE REFERENCES invoices(id),
            payload TEXT NOT NULL, pdf BLOB NOT NULL, sha256 TEXT NOT NULL, created REAL NOT NULL,
            UNIQUE(year,serial));
          CREATE TRIGGER IF NOT EXISTS immutable_invoice_update BEFORE UPDATE ON invoices
            BEGIN SELECT RAISE(ABORT,'Issued invoices cannot be overwritten'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_invoice_delete BEFORE DELETE ON invoices
            BEGIN SELECT RAISE(ABORT,'Issued invoices cannot be deleted'); END;
        ''')
        return conn

    @contextmanager
    def db(self):
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def make_draft(self, values):
        data = order(values)
        company = issuer(self.config_path)
        key = secrets.token_hex(20)
        payload = {'order': data, 'issuer': company}
        with self.db() as conn:
            conn.execute('DELETE FROM drafts WHERE created < ? AND id NOT IN (SELECT draft_id FROM invoices WHERE draft_id IS NOT NULL)', (time.time() - 86400,))
            conn.execute('INSERT INTO drafts VALUES(?,?,?)', (key, time.time(), json.dumps(payload, ensure_ascii=False)))
        return key

    def draft(self, key):
        if not re.fullmatch('[a-f0-9]{40}', key):
            raise ValueError('Entwurf nicht gefunden.')
        with self.db() as conn:
            row = conn.execute('SELECT * FROM drafts WHERE id=?', (key,)).fetchone()
        if not row or row['created'] < time.time() - 86400:
            raise ValueError('Entwurf abgelaufen. Bitte neu erstellen.')
        return json.loads(row['payload'])

    def issue(self, key):
        # Snapshot rechecked against current root-owned configuration before issuing.
        payload = self.draft(key)
        company = issuer(self.config_path)
        if company != payload['issuer']:
            raise ValueError('Ausstellerdaten geändert. Bitte neuen Entwurf prüfen.')
        if payload['order']['total_cents'] > 25000 and not company['tax_id']:
            raise ValueError('Über 250 € muss zuerst die Steuernummer, USt-IdNr. oder Kleinunternehmer-ID geschützt hinterlegt werden.')
        return self._write(payload, key)

    def _write(self, payload, draft_id=None, original_id=None):
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT id FROM invoices WHERE draft_id=? OR original_id=?', (draft_id, original_id)).fetchone()
            if existing:
                conn.rollback()
                return existing['id']
            year = today().year
            serial = conn.execute('SELECT COALESCE(MAX(serial),0)+1 FROM invoices WHERE year=?', (year,)).fetchone()[0]
            number = f'AN-{year}-{serial:06d}'
            payload = dict(payload, number=number, issued=today().isoformat(), due=(today()+timedelta(days=14)).isoformat())
            raw = render_pdf(payload)
            record = conn.execute('INSERT INTO invoices(number,year,serial,draft_id,original_id,payload,pdf,sha256,created) VALUES(?,?,?,?,?,?,?,?,?)',
                (number, year, serial, draft_id, original_id, json.dumps(payload, ensure_ascii=False), raw, hashlib.sha256(raw).hexdigest(), time.time()))
            conn.commit()
            return record.lastrowid
        finally:
            conn.close()

    def get(self, identity):
        if not str(identity).isdigit():
            raise ValueError('Rechnung nicht gefunden.')
        with self.db() as conn:
            row = conn.execute('SELECT * FROM invoices WHERE id=?', (int(identity),)).fetchone()
        if not row:
            raise ValueError('Rechnung nicht gefunden.')
        if not secrets.compare_digest(hashlib.sha256(row['pdf']).hexdigest(), row['sha256']):
            raise ValueError('Integritätsprüfung fehlgeschlagen. Rechnung nicht ausliefern; Sicherung prüfen.')
        return row

    def cancel(self, identity, reason):
        row = self.get(identity)
        data = json.loads(row['payload'])
        if data.get('cancellation_of'):
            raise ValueError('Eine Stornorechnung kann nicht erneut storniert werden.')
        payload = {k: data[k] for k in ('issuer', 'order')}
        payload['cancellation_of'] = data['number']
        payload['reason'] = text(reason, 300)
        return self._write(payload, original_id=row['id'])

    def listing(self):
        with self.db() as conn:
            return conn.execute('SELECT i.id,i.number,i.payload, EXISTS(SELECT 1 FROM invoices c WHERE c.original_id=i.id) AS cancelled FROM invoices i ORDER BY i.id DESC LIMIT 200').fetchall()


def render_pdf(payload, draft=False):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    fonts = Path(__file__).parent/'abrechnung'/'fonts'
    if not fonts.is_dir():
        fonts = Path(__file__).resolve().parents[1]/'abrechnung'/'fonts'
    for name, filename in [('ANInvoice','DejaVuSans.ttf'),('ANInvoiceBold','DejaVuSans-Bold.ttf')]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts/filename)))
    styles = getSampleStyleSheet()
    body = ParagraphStyle('InvoiceBody', fontName='ANInvoice',fontSize=10,leading=15,spaceAfter=7)
    title = ParagraphStyle('InvoiceTitle', parent=body,fontName='ANInvoiceBold',fontSize=22,leading=27,spaceAfter=16)
    small = ParagraphStyle('InvoiceSmall',parent=body,fontSize=8,leading=12)
    esc = html.escape
    para = lambda s, style=body: Paragraph(s,style)
    company = payload['issuer']; data = payload['order']; cancellation = bool(payload.get('cancellation_of'))
    kind = 'Stornorechnung' if cancellation else ('Vorausrechnung' if data['kind']=='advance' else 'Rechnung')
    label = 'ENTWURF – keine Rechnung, keine Zahlungsaufforderung' if draft else kind
    story = [para('ABRECHNUNGS-NAVI',small),para(esc(label),title),
        para('<br/>'.join(esc(company[k]) for k in ('name','address','city','email'))),Spacer(1,7*mm),
        para('<br/>'.join(esc(data[k]) for k in ('customer','address','city'))+'<br/>Deutschland'),Spacer(1,6*mm)]
    issued = payload.get('issued',today().isoformat())
    story.append(para(f'Rechnungsnummer: {esc(payload.get("number","noch nicht vergeben"))}<br/>Rechnungsdatum: {date.fromisoformat(issued).strftime("%d.%m.%Y")}<br/>Auftragsreferenz: {esc(data["reference"])}'))
    if cancellation:
        story.append(para(f'Stornierung der Rechnung {esc(payload["cancellation_of"])}<br/>Grund: {esc(payload["reason"])}'))
    prefix = 'Voraussichtliches Leistungsdatum' if data['kind']=='advance' else 'Leistungsdatum'
    story.append(para(f'{prefix}: {date.fromisoformat(data["service_date"]).strftime("%d.%m.%Y")}<br/>Nebenkostenabrechnung für das Abrechnungsjahr {data["year"]}; {data["apartments"]} Wohnung(en) in {data["houses"]} Haus/Häusern.'))
    sign = -1 if cancellation else 1
    rows = [[para('Leistung',small),para('Anzahl',small),para('Einzelpreis',small),para('Betrag',small)]]
    for label,qty,price in [('Erste Wohnung je Haus',data['houses'],8900),('Weitere Wohnung im selben Haus',data['apartments']-data['houses'],5900)]:
        if qty:
            rows.append([para(label,small),str(qty),money(sign*price),money(sign*qty*price)])
    rows.append([para('Gesamtbetrag',body),'','',money(sign*data['total_cents'])])
    table=Table(rows,colWidths=[86*mm,16*mm,30*mm,35*mm])
    table.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'ANInvoice'),('FONTSIZE',(0,0),(-1,-1),9),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7f1ee')),('VALIGN',(0,0),(-1,-1),'TOP'),('ALIGN',(1,1),(-1,-1),'RIGHT'),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),('LINEABOVE',(0,-1),(-1,-1),.6,colors.HexColor('#3f665c'))]))
    story += [table,Spacer(1,5*mm),para(NOTICE)]
    if company.get('tax_id'):
        story.append(para('Steuerkennung des Ausstellers: '+esc(company['tax_id']),small))
    if not draft and not cancellation:
        story.append(para('Zahlungsziel: '+date.fromisoformat(payload['due']).strftime('%d.%m.%Y')+'. Zahlung über den separat mitgeteilten Zahlungsweg. Bereits geleistete Zahlungen bitte berücksichtigen.'))
        if data['kind']=='advance':
            story.append(para('Vorausrechnung für die beauftragte Leistung. Bei einer späteren Schlussrechnung muss diese Vorausrechnung samt Zahlung angerechnet werden.',small))
    if cancellation:
        story.append(para('Diese Stornorechnung löst keine automatische Rückzahlung aus. Eine gegebenenfalls erforderliche Erstattung wird gesondert abgewickelt.',small))
    if draft:
        story.append(para('Entwurf zur internen Prüfung. Erst nach ausdrücklichem Festschreiben wird eine Rechnungsnummer vergeben.',small))
    stream=io.BytesIO()
    SimpleDocTemplate(stream,pagesize=(210*mm,297*mm),leftMargin=21*mm,rightMargin=21*mm,topMargin=18*mm,bottomMargin=18*mm,title=('Entwurf' if draft else kind),author=company['name']).build(story)
    return stream.getvalue()


def ledger(app):
    return Ledger(os.environ.get('AN_INVOICE_DIR',str(Path(app.DATA_DIR).parent/'invoices')),
                  os.environ.get('AN_INVOICE_ISSUER_FILE','/etc/an-upload/invoice-issuer.json'))


def page(app, content):
    return app.page('Rechnungen', '<style>.invoice-form label{display:block;margin:12px 0}.invoice-form input[type=date],.invoice-form select{display:block;width:100%;font:inherit;padding:11px;border:1px solid #dfe5e8;border-radius:10px;margin:4px 0 14px}</style><p><a href="/verwaltung">← Verwaltung</a> · <a href="'+BASE+'">Rechnungen</a></p>'+content)


def input_field(label,name,value='',kind='text'):
    return f'<label>{html.escape(label)}<input name="{name}" type="{kind}" value="{html.escape(str(value),quote=True)}" maxlength="180" required></label>'


def get(handler,app,path):
    store=ledger(app)
    try:
        if path == BASE:
            try:
                company=issuer(store.config_path)
                message='<p>Aussteller: '+html.escape(company['name'])+' · § 19 UStG</p>'
                if not company['tax_id']:
                    message+='<p>Ohne hinterlegte Steuerkennung sind nur Rechnungen bis einschließlich 250 € möglich.</p>'
            except ValueError as e:
                message='<p class="err">'+html.escape(str(e))+'</p>'
            fields=''.join([input_field('Kundenname / Firma','customer'),input_field('Straße und Hausnummer','address'),input_field('PLZ und Ort (Deutschland)','city'),input_field('Auftragsreferenz – keine Mieternamen','reference'),input_field('Wohnungen insgesamt','apartments',1,'number'),input_field('Häuser insgesamt','houses',1,'number'),input_field('Abrechnungsjahr','year',today().year-1,'number'),input_field('Leistungsdatum / erwartetes Datum','service_date',today().isoformat(),'date')])
            fields+='<label><input type="checkbox" name="country" value="DE" required> Die Rechnungsanschrift befindet sich in Deutschland.</label><label>Rechnungsart<select name="kind"><option value="service">Leistung bereits erbracht</option><option value="advance">Vorausrechnung</option></select></label>'
            rows=''
            for row in store.listing():
                data=json.loads(row['payload']);label='Storno' if data.get('cancellation_of') else ('storniert' if row['cancelled'] else 'ausgestellt')
                rows+=f'<li><a href="{BASE}/{row["id"]}">{html.escape(row["number"])}</a> · {html.escape(data["order"]["customer"])} · {label}</li>'
            return handler.send(200,page(app,'<div class="card"><h1>Rechnungen</h1>'+message+'<p>89 € je erster Wohnung pro Haus, 59 € je weiterer Wohnung. Keine gesonderte Umsatzsteuer. Hier nur Rechnungsdaten erfassen, keine Mieterbelege. Kein automatischer E-Mail-Versand.</p><h2>Neue Rechnung</h2><form class="invoice-form" method="post" action="'+BASE+'/entwurf">'+fields+'<button class="btn">Entwurf prüfen</button></form></div><div class="card"><h2>Ausgestellte Rechnungen</h2><ul>'+rows+'</ul><p>Festgeschriebene Rechnungen werden getrennt von den Mieterunterlagen aufbewahrt. Berichtigungen erfolgen durch Storno und neue Rechnung.</p></div>'))
        match=re.fullmatch(BASE+r'/entwurf/([a-f0-9]{40})(/pdf)?',path)
        if match:
            data=store.draft(match[1])
            if match[2]:
                return handler.send(200,render_pdf(data,True),'application/pdf',{'Content-Disposition':'attachment; filename="Rechnungsentwurf.pdf"'})
            item=data['order']
            preview='<p>'+ '<br/>'.join(html.escape(item[k]) for k in ('customer','address','city')) + '</p>'
            preview+='<p>Auftragsreferenz: '+html.escape(item['reference'])+f'<br/>{item["apartments"]} Wohnung(en) in {item["houses"]} Haus/Häusern · Abrechnungsjahr {item["year"]}<br/>'+('Voraussichtliches Leistungsdatum: ' if item['kind']=='advance' else 'Leistungsdatum: ')+date.fromisoformat(item['service_date']).strftime('%d.%m.%Y')+'</p>'
            fields=f'<input type="hidden" name="draft" value="{match[1]}"><label><input type="checkbox" name="confirm" value="yes" required> Empfänger, Auftrag, Leistungsdatum und Betrag geprüft. Rechnung jetzt verbindlich festschreiben.</label>'
            return handler.send(200,page(app,f'<div class="card"><h1>Rechnungsentwurf prüfen</h1><p>Gesamtbetrag: {money(item["total_cents"])}</p>{preview}<p>{NOTICE}</p><p><a href="{BASE}/entwurf/{match[1]}/pdf">PDF-Entwurf herunterladen</a></p><form class="invoice-form" method="post" action="{BASE}/ausstellen">{fields}<button class="btn">Rechnung festschreiben</button></form></div>'))
        match=re.fullmatch(BASE+r'/(\d+)(/pdf)?',path)
        if match:
            row=store.get(match[1]);data=json.loads(row['payload'])
            if match[2]:
                return handler.send(200,row['pdf'],'application/pdf',{'Content-Disposition':f'attachment; filename="{row["number"]}.pdf"'})
            body=f'<div class="card"><h1>{html.escape(row["number"])}</h1><p>{html.escape(data["order"]["customer"])}</p><p><a href="{BASE}/{row["id"]}/pdf">PDF herunterladen</a></p><p>Festgeschrieben am {data["issued"]}. Kein automatischer Versand und keine Zahlungsbestätigung.</p>'
            if not data.get('cancellation_of'):
                body+=f'<form class="invoice-form" method="post" action="{BASE}/storno"><input type="hidden" name="id" value="{row["id"]}">'+input_field('Stornogrund','reason')+'<label><input type="checkbox" name="confirm" value="yes" required> Gesamte Rechnung stornieren; keine automatische Erstattung.</label><button class="btn">Stornorechnung erstellen</button></form>'
            return handler.send(200,page(app,body+'</div>'))
        return handler.send(404,'Nicht gefunden')
    except (ValueError,sqlite3.IntegrityError) as e:
        return handler.send(400,page(app,'<p class="err">'+html.escape(str(e))+'</p>'))


def post(handler,app,path,g):
    store=ledger(app)
    try:
        if path==BASE+'/entwurf':
            key=store.make_draft({k:g(k) for k in ('customer','address','city','reference','country','apartments','houses','year','service_date','kind')})
            dest=BASE+'/entwurf/'+key
        elif path==BASE+'/ausstellen':
            if g('confirm')!='yes':
                raise ValueError('Ausstellung muss ausdrücklich bestätigt werden.')
            dest=BASE+'/'+str(store.issue(g('draft')))
        elif path==BASE+'/storno':
            if g('confirm')!='yes':
                raise ValueError('Storno muss ausdrücklich bestätigt werden.')
            dest=BASE+'/'+str(store.cancel(g('id'),g('reason')))
        else:
            return handler.send(404,'Nicht gefunden')
        return handler.send(303,'',extra={'Location':dest})
    except (ValueError,sqlite3.IntegrityError) as e:
        return handler.send(400,page(app,'<p class="err">'+html.escape(str(e))+'</p>'))
