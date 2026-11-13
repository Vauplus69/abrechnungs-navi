"""Production orchestration: payment-bound portal, immutable source versions and draft-only agents."""
from datetime import date, datetime, timedelta, time as daytime
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import time
import zipfile
from zoneinfo import ZoneInfo

from document_dossier import assemble, DossierBlocked
from document_extraction import ExtractionBlocked
from document_review import ReviewBundle, fingerprint
from notice_agent import Notifications, otp
from payment_flow import PaymentFlow

DAY=86400


def configuration(path):
    cfg=json.loads(Path(path).read_text())
    if cfg.get('brand')!='abrechnungs-navi' or cfg.get('region')!='eu1' or cfg.get('enabled') is not True:
        raise ValueError('Automatische Bearbeitung noch nicht freigegeben')
    if any(not re.fullmatch(r'[a-f0-9]{64}',cfg.get(k,'')) for k in ('avv_sha256','terms_sha256','consumer_information_sha256')):
        raise ValueError('Freigegebene Vertragsfassungen fehlen')
    if cfg.get('release_mode','manual')!='manual':
        raise ValueError('Für die Anfangsphase ist persönliche Schlussfreigabe erforderlich')
    return cfg


def conservative_start(accepted_at, service_date):
    """Approved German consumer policy: wait across the union of state holidays.

    This intentionally postpones rather than shortens an uncertain local deadline.
    It does not assert validity of a notice or replace contract/provider approval.
    """
    zone=ZoneInfo('Europe/Berlin'); base=datetime.fromtimestamp(accepted_at,zone).date()
    last=base+timedelta(days=14)
    def holidays(year):
        a=year%19;b=year//100;c=year%100;d=b//4;e=b%4;f=(b+8)//25;g=(b-f+1)//3
        h=(19*a+b-d-g+15)%30;i=c//4;k=c%4;l=(32+2*e+2*i-h-k)%7;m=(a+11*h+22*l)//451
        easter=date(year,(h+l-7*m+114)//31,(h+l-7*m+114)%31+1)
        dates={date(year,month,day) for month,day in ((1,1),(1,6),(3,8),(5,1),(8,8),(8,15),(9,20),(10,3),(10,31),(11,1),(12,25),(12,26))}
        dates.update(easter+timedelta(days=n) for n in (-2,1,39,50,60))
        penance=date(year,11,22)
        while penance.weekday()!=2: penance-=timedelta(days=1)
        dates.add(penance); return dates
    while last.weekday()>=5 or last in holidays(last.year): last+=timedelta(days=1)
    earliest=datetime.combine(last+timedelta(days=1),daytime(),zone).timestamp()
    requested=datetime.combine(date.fromisoformat(service_date),daytime(),zone).timestamp()
    return max(earliest,requested)


class Automation:
    def __init__(self, ledger, data_dir, config_path, calculator_path, *, operator_ready=lambda:False, clock=None):
        self.ledger=ledger;self.data=Path(data_dir);self.root=self.data/'automation'
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.config_path=Path(config_path);self.review=ReviewBundle(calculator_path)
        self.operator_ready=operator_ready;self.now=clock or time.time
        self.payments=PaymentFlow(ledger);self.notices=Notifications(ledger)
        from checkout_notices import CheckoutNotices
        self.checkout_notices=CheckoutNotices(ledger)
        with ledger.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS auto_orders(
                order_id TEXT PRIMARY KEY,token TEXT UNIQUE NOT NULL,state TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,expires REAL NOT NULL,
                not_before REAL NOT NULL,confirmation_at REAL,withdrawn INTEGER NOT NULL DEFAULT 0,
                released_version INTEGER,last_code TEXT);
              CREATE TABLE IF NOT EXISTS auto_files(
                id TEXT PRIMARY KEY,order_id TEXT NOT NULL,name TEXT NOT NULL,path TEXT NOT NULL,
                sha256 TEXT NOT NULL,size INTEGER NOT NULL,active INTEGER NOT NULL DEFAULT 1);
              CREATE TABLE IF NOT EXISTS auto_challenges(
                order_id TEXT PRIMARY KEY,nonce TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,
                failures INTEGER NOT NULL DEFAULT 0,used INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS auto_sessions(
                id TEXT PRIMARY KEY,order_id TEXT NOT NULL,expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS auto_jobs(
                id INTEGER PRIMARY KEY,order_id TEXT NOT NULL,version INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,files TEXT NOT NULL,checked TEXT NOT NULL DEFAULT '[]',
                state TEXT NOT NULL,due REAL NOT NULL,lease REAL,token TEXT,bundle TEXT,
                candidate TEXT,code TEXT,UNIQUE(order_id,version));
              CREATE TABLE IF NOT EXISTS auto_page_budget(id TEXT PRIMARY KEY,budget_id TEXT NOT NULL,pages INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS auto_provider_deletions(id TEXT PRIMARY KEY,file_id TEXT,run_id TEXT,state TEXT NOT NULL,created REAL NOT NULL);
            ''')

    def secret(self):
        path=self.ledger.folder/'automation.secret'
        if not path.exists():
            try:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as stream:
                    stream.write(secrets.token_bytes(32));stream.flush();os.fsync(stream.fileno())
            except FileExistsError: pass
        from mollie_payments import protected_file
        raw=protected_file(path).read_bytes()
        if len(raw)!=32: raise ValueError('Portal-Sitzungsschlüssel ungültig')
        return raw

    def get(self, identity=None, token=None):
        if identity is not None and not re.fullmatch(r'AN-[a-f0-9]{32}',identity): raise ValueError('Ungültiger Auftrag')
        if token is not None and not re.fullmatch(r'[A-Za-z0-9_-]{32}',token): raise ValueError('Ungültiger Kundenbereich')
        with self.ledger.db() as db:
            row=db.execute('SELECT p.*,o.payload AS offer FROM auto_orders p JOIN checkout_acceptances a ON a.order_id=p.order_id '
                'JOIN checkout_offers o ON o.id=a.offer_id WHERE '+('p.order_id=?' if identity else 'p.token=?'),(identity or token,)).fetchone()
        if row is None: raise ValueError('Kundenbereich nicht verfügbar')
        value=dict(row);offer=json.loads(value.pop('offer'))
        return {**value,'email':offer['email'],'name':offer['order']['customer'],'order':offer['order'],'property_address':offer['property_address']}

    def gate(self, identity, *, processing=False):
        cfg=configuration(self.config_path)
        if not self.operator_ready(): raise ValueError('Betreiberfreigabe noch offen')
        accepted=self.payments.accepted(identity)
        if any(accepted[k]!=cfg[k] for k in ('avv_sha256','terms_sha256','consumer_information_sha256')):
            raise ValueError('Vertragsfassungen nicht für diese Verarbeitung freigegeben')
        self.payments.require_paid(identity)
        withdrawals=self.data/'widerrufe.json'
        if withdrawals.exists():
            if any(identity in str(row.get('vertrag','')) for row in json.loads(withdrawals.read_text())):
                raise ValueError('Widerrufsmeldung zu diesem Auftrag muss geprüft werden')
        try: portal=self.get(identity)
        except ValueError: portal=None
        if portal and (portal['withdrawn'] or portal['expires']<=self.now()): raise ValueError('Auftrag geschlossen oder widerrufen')
        if processing:
            if cfg.get('automatic_start_policy_approved') is not True: raise ValueError('Automatischer Leistungsbeginn noch nicht freigegeben')
            if not portal or not portal['confirmation_at'] or self.now()<portal['not_before']:
                raise ValueError('Vertragsbestätigung oder zulässiger Leistungsbeginn fehlt')
        return cfg

    def provision(self, identity):
        self.gate(identity)
        accepted=self.payments.accepted(identity)
        with self.ledger.db() as db:
            offer=json.loads(db.execute('SELECT o.payload FROM checkout_offers o JOIN checkout_acceptances a ON a.offer_id=o.id WHERE a.order_id=?',(identity,)).fetchone()[0])
            start=conservative_start(accepted['accepted_at'],offer['order']['service_date'])
            db.execute('INSERT OR IGNORE INTO auto_orders(order_id,token,state,created,expires,not_before) VALUES(?,?,?,?,?,?)',
                (identity,secrets.token_urlsafe(24),'awaiting_upload',self.now(),self.now()+30*DAY,
                 start))
            db.execute('UPDATE auto_orders SET expires=MAX(expires,?) WHERE order_id=? AND version=0 AND released_version IS NULL',
                (min(max(self.now()+30*DAY,start+30*DAY),self.now()+90*DAY),identity))
        self.notices.enqueue(identity,'upload_available','1')
        return self.get(identity)

    def provision_due(self):
        with self.ledger.db() as db:
            identities=[r[0] for r in db.execute("SELECT order_id FROM payment_orders WHERE state='paid' AND requires_check=0 AND order_id NOT IN (SELECT order_id FROM auto_orders) LIMIT 20")]
        for identity in identities:
            try:self.provision(identity)
            except ValueError:continue

    def request_code(self, token):
        context=self.get(token=token)
        if context['expires']<=self.now(): raise ValueError('Kundenbereich abgelaufen')
        self.secret()
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT * FROM auto_challenges WHERE order_id=?',(context['order_id'],)).fetchone()
            if previous and self.now()-previous['created']<60: return
            count=db.execute("SELECT COUNT(*) FROM notification_events WHERE order_id=? AND event='access_code' AND created>?",(context['order_id'],time.time()-3600)).fetchone()[0]
            if count>=5: raise ValueError('Bitte vor einer erneuten Code-Anforderung warten')
            nonce=secrets.token_hex(16)
            db.execute('INSERT OR REPLACE INTO auto_challenges VALUES(?,?,?,?,0,0)',(context['order_id'],nonce,self.now(),self.now()+600))
        self.notices.enqueue(context['order_id'],'access_code',nonce,{'nonce':nonce})

    def login(self, token, code):
        context=self.get(token=token)
        if not re.fullmatch(r'\d{6}',code) or context['expires']<=self.now(): raise ValueError('Zugang nicht möglich')
        key=self.secret()
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            challenge=db.execute('SELECT * FROM auto_challenges WHERE order_id=?',(context['order_id'],)).fetchone()
            if not challenge or challenge['used'] or challenge['expires']<=self.now() or challenge['failures']>=5:
                raise ValueError('Code ungültig oder abgelaufen')
            if not hmac.compare_digest(code,otp(key,context['order_id'],challenge['nonce'])):
                db.execute('UPDATE auto_challenges SET failures=failures+1 WHERE order_id=?',(context['order_id'],))
                valid=False
            else:
                valid=True;db.execute('UPDATE auto_challenges SET used=1 WHERE order_id=?',(context['order_id'],))
                session=secrets.token_urlsafe(32)
                db.execute('INSERT INTO auto_sessions VALUES(?,?,?)',(hashlib.sha256(session.encode()).hexdigest(),context['order_id'],self.now()+1800))
        if not valid: raise ValueError('Code ungültig oder abgelaufen')
        return session

    def authenticated(self, token, session):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',session or ''): return False
        context=self.get(token=token)
        with self.ledger.db() as db:
            return bool(db.execute('SELECT 1 FROM auto_sessions WHERE id=? AND order_id=? AND expires>?',
                (hashlib.sha256(session.encode()).hexdigest(),context['order_id'],self.now())).fetchone()) and context['expires']>self.now()

    def files(self, identity):
        with self.ledger.db() as db: return [dict(r) for r in db.execute('SELECT * FROM auto_files WHERE order_id=? AND active=1 ORDER BY id',(identity,))]

    def upload(self, token, name, raw):
        context=self.get(token=token);self.gate(context['order_id'])
        if context['released_version'] is not None: raise ValueError('Freigegebener Auftrag ist für Uploads geschlossen')
        if not isinstance(name,str) or Path(name).name!=name or len(name)>180 or any(ord(c)<32 for c in name): raise ValueError('Ungültiger Dateiname')
        from upload_app import allowed_file
        allowed_file(name,raw)
        sha=hashlib.sha256(raw).hexdigest()
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT * FROM auto_orders WHERE order_id=?',(context['order_id'],)).fetchone()
            if current['released_version'] is not None or current['expires']<=self.now(): raise ValueError('Upload geschlossen')
            old=db.execute('SELECT id FROM auto_files WHERE order_id=? AND sha256=? AND active=1',(context['order_id'],sha)).fetchone()
            if old:return old['id']
            count,size=db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM auto_files WHERE order_id=? AND active=1',(context['order_id'],)).fetchone()
            if count>=150 or size+len(raw)>100*1024*1024: raise ValueError('Datei- oder Gesamtgrößenlimit erreicht')
            fid=secrets.token_hex(16);folder=self.root/context['order_id'][3:]/'originals'
            folder.mkdir(parents=True,exist_ok=True,mode=0o700);path=folder/(fid+Path(name).suffix.lower())
            with path.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            path.chmod(0o600)
            db.execute('INSERT INTO auto_files VALUES(?,?,?,?,?,?,1)',(fid,context['order_id'],name,str(path),sha,len(raw)))
            db.execute("UPDATE auto_orders SET version=version+1,state='awaiting_upload',last_code=NULL WHERE order_id=?",(context['order_id'],))
        return fid

    def remove(self, token, file_id):
        context=self.get(token=token);self.gate(context['order_id'])
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT released_version FROM auto_orders WHERE order_id=?',(context['order_id'],)).fetchone()
            if current['released_version'] is not None: raise ValueError('Auftrag geschlossen')
            if db.execute('UPDATE auto_files SET active=0 WHERE id=? AND order_id=? AND active=1',(file_id,context['order_id'])).rowcount!=1:
                raise ValueError('Datei nicht gefunden')
            db.execute("UPDATE auto_orders SET version=version+1,state='awaiting_upload' WHERE order_id=?",(context['order_id'],))

    def submit(self, token):
        context=self.get(token=token);self.gate(context['order_id'])
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            context=dict(db.execute('SELECT * FROM auto_orders WHERE order_id=?',(context['order_id'],)).fetchone())
            if context['released_version'] is not None: raise ValueError('Auftrag bereits freigegeben')
            files=[dict(r) for r in db.execute('SELECT * FROM auto_files WHERE order_id=? AND active=1 ORDER BY id',(context['order_id'],))]
            if not files: raise ValueError('Bitte zuerst Unterlagen hochladen')
            self.verify_sources(files)
            inserted=db.execute('INSERT OR IGNORE INTO auto_jobs(order_id,version,fingerprint,files,state,due) VALUES(?,?,?,?,?,?)',
                (context['order_id'],context['version'],fingerprint(files),json.dumps(files),'queued',self.now()))
            if inserted.rowcount:
                db.execute("UPDATE auto_orders SET state='submitted' WHERE order_id=?",(context['order_id'],))
        self.notices.enqueue(context['order_id'],'received',str(context['version']))
        return context['version']

    @staticmethod
    def verify_sources(files):
        for item in files:
            path=Path(item['path'])
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
                raise ValueError('Originalbestand verändert')

    def confirm_delivery(self, token):
        context=self.get(token=token)
        with self.ledger.db() as db:
            db.execute('UPDATE auto_orders SET confirmation_at=COALESCE(confirmation_at,?) WHERE order_id=?',(self.now(),context['order_id']))

    def contract_packet(self, token):
        context=self.get(token=token)
        with self.ledger.db() as db:
            accepted=db.execute('SELECT * FROM checkout_acceptances WHERE order_id=?',(context['order_id'],)).fetchone()
            docs=db.execute('SELECT * FROM checkout_documents WHERE offer_id=?',(accepted['offer_id'],)).fetchall()
            link=db.execute('SELECT invoice_id FROM checkout_invoice_links WHERE order_id=?',(context['order_id'],)).fetchone()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('Auftragsbestaetigung.json',accepted['payload'])
            archive.writestr('Auftragsbestaetigung.txt','Abrechnungs-Navi\nAuftrag '+context['order_id']+'\nIhre angenommenen Vertragsunterlagen und die Vorausrechnung liegen unverändert bei. Diese Bestätigung ist kein Zahlungs- oder Leistungsnachweis.\n')
            for doc in docs:
                if hashlib.sha256(doc['raw']).hexdigest()!=doc['sha256']:raise ValueError('Vertragsunterlage verändert')
                archive.writestr(doc['kind']+('.pdf' if doc['mime']=='application/pdf' else '.txt'),doc['raw'])
            archive.writestr('Vorausrechnung.pdf',self.ledger.get(link['invoice_id'])['pdf'])
        return stream.getvalue()

    def current_job(self, identity):
        context=self.get(identity)
        with self.ledger.db() as db:
            row=db.execute('SELECT * FROM auto_jobs WHERE order_id=? AND version=?',(identity,context['version'])).fetchone()
        return dict(row) if row else None

    def claim(self):
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM auto_jobs WHERE (state IN ('queued','extracting','waiting_start','waiting_confirmation','waiting_payment','waiting_policy') AND due<=?) OR (state='running' AND lease<?) ORDER BY id LIMIT 1",(self.now(),self.now())).fetchone()
            if not row:return None
            token=secrets.token_hex(16)
            db.execute("UPDATE auto_jobs SET state='running',token=?,lease=? WHERE id=?",(token,self.now()+900,row['id']))
        return {**dict(row),'token':token}

    def save_state(self, job, state, *, code=None, due=None, checked=None, candidate=None, bundle=None):
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT * FROM auto_orders WHERE order_id=?',(job['order_id'],)).fetchone()
            if not current or current['version']!=job['version'] or current['released_version'] is not None or current['expires']<=self.now():
                state='superseded'
            changed=db.execute('UPDATE auto_jobs SET state=?,code=?,due=?,checked=COALESCE(?,checked),candidate=COALESCE(?,candidate),bundle=COALESCE(?,bundle),lease=NULL WHERE id=? AND token=?',
                (state,code,due or self.now(),json.dumps(checked) if checked is not None else None,
                 json.dumps(candidate,ensure_ascii=False) if candidate is not None else None,str(bundle) if bundle else None,job['id'],job['token'])).rowcount
            if changed and state!='superseded':
                db.execute('UPDATE auto_orders SET state=?,last_code=? WHERE order_id=?',(state,code,job['order_id']))
        return state

    def process_one(self, extractor):
        job=self.claim()
        if job is None:return False
        identity=job['order_id'];files=json.loads(job['files'])
        try:
            context=self.get(identity)
            if context['version']!=job['version'] or context['released_version'] is not None:
                self.save_state(job,'superseded');return True
            try:cfg=self.gate(identity)
            except ValueError:
                self.save_state(job,'waiting_payment',due=self.now()+60);return True
            if not context['confirmation_at']:
                self.save_state(job,'waiting_confirmation',due=self.now()+60);return True
            if self.now()<context['not_before']:
                self.save_state(job,'waiting_start',due=context['not_before']);return True
            approval=cfg.get('provider_approval',{})
            if cfg.get('automatic_start_policy_approved') is not True or any(approval.get(k) is not True for k in
                    ('contract_verified','subprocessors_verified','retention_verified','customer_avv_allows_extraction')):
                self.save_state(job,'waiting_policy',code='provider_policy',due=self.now()+300);return True
            if not re.fullmatch(r'[a-f0-9]{64}',approval.get('provider_evidence_sha256','')):
                self.save_state(job,'waiting_policy',code='provider_policy',due=self.now()+300);return True
            if fingerprint(files)!=job['fingerprint'] or fingerprint(self.files(identity))!=job['fingerprint']:
                raise ValueError('Belegstand verändert')
            self.verify_sources(files)
            checked=json.loads(job['checked'])
            if len(checked)<len(files):
                source=files[len(checked)]
                if Path(source['path']).suffix.lower()!='.pdf':
                    self.save_state(job,'internal_review',code='unsupported_file')
                    self.notices.enqueue(identity,'processing_error',str(job['version']));return True
                self.gate(identity,processing=True)
                raw=Path(source['path']).read_bytes()
                self.reserve_pages(identity,source['sha256'],raw,cfg)
                client=extractor(identity,cfg) if callable(extractor) else extractor
                self.gate(identity,processing=True)
                result=client.extract(raw)
                if result.get('source_sha256')!=source['sha256'] or result.get('customer_release') is not False or result.get('human_final_review_required') is not True:
                    raise ValueError('Auslesung nicht an Original gebunden')
                self.verify_sources(files);checked.append(result)
                self.save_state(job,'extracting',checked=checked);return True
            self.gate(identity,processing=True)
            order={**context['order'],'property_address':context['property_address']}
            try:candidate=assemble(checked,order)
            except DossierBlocked as error:
                message=str(error)
                codes=[]
                if message.startswith('Belegte Vorauszahlung fehlt'):codes=['advances']
                elif message.startswith('Belegte Stammdaten fehlen'):codes=['master_data']
                elif message.startswith('Unterlagen betreffen ein anderes'):codes=['scope']
                state=self.save_state(job,'needs_customer_input' if codes else 'internal_review',code=codes[0] if codes else 'domain_review')
                if state!='superseded':
                    self.notices.enqueue(identity,'missing_inputs' if codes else 'processing_error',str(job['version']),{'codes':codes})
                return True
            self.verify_sources(files)
            folder=self.root/identity[3:]/('draft-'+str(job['version'])+'-'+job['fingerprint'][:12])
            if folder.exists():
                self.review.inspect(folder,candidate,files,version=job['version'],states=('needs_final_review',))
            else:self.review.prepare(candidate,files,job['version'],folder)
            self.gate(identity,processing=True)
            state=self.save_state(job,'needs_final_review',candidate=candidate,bundle=folder)
            if state!='superseded':self.notices.enqueue(identity,'review_needed',str(job['version']))
        except (ValueError,KeyError,OSError,ExtractionBlocked):
            state=self.save_state(job,'internal_review',code='source_or_provider_review')
            if state!='superseded':self.notices.enqueue(identity,'processing_error',str(job['version']))
        return True

    def reserve_pages(self,identity,sha,raw,cfg):
        from pypdf import PdfReader
        count=len(PdfReader(io.BytesIO(raw),strict=True).pages)
        limit=cfg.get('max_pages_total');budget=cfg.get('budget_id','')
        if type(limit) is not int or not 1<=limit<=10000 or not re.fullmatch(r'[a-f0-9]{64}',budget):
            raise ValueError('Freigegebenes Gesamtbudget fehlt')
        from document_dossier import SCHEMA
        from document_extraction import extraction_config
        key=hashlib.sha256((identity+':'+sha+':'+budget+':'+fingerprint(extraction_config(SCHEMA))).encode()).hexdigest()
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM auto_page_budget WHERE id=?',(key,)).fetchone():return
            used=db.execute('SELECT COALESCE(SUM(pages),0) FROM auto_page_budget WHERE budget_id=?',(budget,)).fetchone()[0]
            if not 1<=count<=500 or used+count>limit:raise ValueError('Freigegebenes Gesamtbudget erschöpft')
            db.execute('INSERT INTO auto_page_budget VALUES(?,?,?)',(key,budget,count))

    def queue_checked_provider_deletions(self):
        """Only durable, independently checked results may lose their remote copy."""
        import sqlite3
        from contextlib import closing
        with self.ledger.db() as db:
            orders=[r['order_id'] for r in db.execute('SELECT order_id FROM auto_orders')]
        for identity in orders:
            if not re.fullmatch(r'AN-[a-f0-9]{32}',identity):raise ValueError('Ungültiger Auftrag')
            folder=self.root/identity[3:]
            if folder.is_symlink():raise ValueError('Ungültiger Datenpfad')
            cache=folder/'provider'/'extract-ledger.sqlite'
            if not cache.exists():continue
            with closing(sqlite3.connect('file:'+str(cache)+'?mode=ro',uri=True,timeout=5)) as provider:
                refs=provider.execute("SELECT key,file_id,run_id,result FROM runs WHERE state='checked'").fetchall()
            for key,fid,rid,result in refs:
                if not re.fullmatch(r'file_[A-Za-z0-9]+',fid or '') or not re.fullmatch(r'exr_[A-Za-z0-9]+',rid or ''):raise ValueError('Ungültiger Anbieterbezug')
                checked=json.loads(result)
                if checked.get('provider_file_id')!=fid or checked.get('provider_run_id')!=rid:raise ValueError('Lokaler Ergebnisbezug fehlt')
                deletion=hashlib.sha256((identity+':'+key).encode()).hexdigest()
                with self.ledger.db() as db:
                    db.execute('INSERT OR IGNORE INTO auto_provider_deletions VALUES(?,?,?,?,?)',(deletion,fid,rid,'pending',self.now()))

    def expire(self):
        with self.ledger.db() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM auto_orders WHERE expires<=?',(self.now(),))]
        for row in rows:
            folder=self.root/row['order_id'][3:]
            if not re.fullmatch(r'AN-[a-f0-9]{32}',row['order_id']) or folder.is_symlink():raise ValueError('Ungültiger Auftragsdatenpfad')
            # Keep minimal vendor deletion references before removing the
            # local cache. Never turn local deletion into a vendor-deletion claim.
            cache=folder/'provider'/'extract-ledger.sqlite'
            if cache.exists():
                import sqlite3
                from contextlib import closing
                with closing(sqlite3.connect('file:'+str(cache)+'?mode=ro',uri=True,timeout=5)) as provider:
                    references=provider.execute('SELECT key,file_id,run_id FROM runs').fetchall()
                with self.ledger.db() as db:
                    for key,fid,rid in references:
                        if fid and not re.fullmatch(r'file_[A-Za-z0-9]+',fid):raise ValueError('Ungültiger Anbieterbezug')
                        if rid and not re.fullmatch(r'exr_[A-Za-z0-9]+',rid):raise ValueError('Ungültiger Anbieterbezug')
                        identity=hashlib.sha256((row['order_id']+':'+key).encode()).hexdigest()
                        db.execute('INSERT OR IGNORE INTO auto_provider_deletions VALUES(?,?,?,?,?)',
                            (identity,fid,rid,'pending' if fid else 'provider_lookup_required',self.now()))
            with self.ledger.db() as db:
                db.execute("UPDATE auto_orders SET state='expired' WHERE order_id=?",(row['order_id'],))
                db.execute("UPDATE auto_jobs SET state='expired',token=NULL,lease=NULL WHERE order_id=?",(row['order_id'],))
            if folder.exists():shutil.rmtree(folder)
            with self.ledger.db() as db:
                db.execute("UPDATE auto_orders SET state='expired',last_code=NULL WHERE order_id=?",(row['order_id'],))
                db.execute("UPDATE auto_jobs SET files='[]',checked='[]',candidate=NULL,bundle=NULL,state='expired' WHERE order_id=?",(row['order_id'],))
                db.execute('DELETE FROM auto_files WHERE order_id=?',(row['order_id'],))
                db.execute('DELETE FROM auto_sessions WHERE order_id=?',(row['order_id'],))
                db.execute('DELETE FROM auto_challenges WHERE order_id=?',(row['order_id'],))
                db.execute('DELETE FROM notification_deliveries WHERE event_id IN (SELECT id FROM notification_events WHERE order_id=?)',(row['order_id'],))
                db.execute("UPDATE notification_events SET state='obsolete',payload='{}' WHERE order_id=? AND state='queued'",(row['order_id'],))

    def approve(self, identity, version, expected_manifest, checks):
        cfg=self.gate(identity,processing=True);job=self.current_job(identity)
        if not job or job['version']!=version or not job['bundle'] or job['state'] not in ('needs_final_review','released'):
            raise ValueError('Kein aktueller Entwurf vorhanden')
        if not all(checks.get(k) is True for k in ('original_visual_checked','pdf_visual_checked','allocation_checked')):
            raise ValueError('Persönliche Original-, PDF- und Umlageprüfung erforderlich')
        path=Path(job['bundle'])/'manifest.json'
        current=self.get(identity)
        if current['released_version']==version and job['state']=='released':
            self.review.inspect(job['bundle'],json.loads(job['candidate']),json.loads(job['files']),version=version,states=('ready',))
            return
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_manifest:
            raise ValueError('Entwurf verändert; bitte erneut prüfen')
        files=json.loads(job['files']);candidate=json.loads(job['candidate'])
        reviewer=cfg.get('reviewer_name')
        if not isinstance(reviewer,str) or not reviewer.strip():raise ValueError('Prüferzuordnung fehlt')
        with self.ledger.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT * FROM auto_orders WHERE order_id=?',(identity,)).fetchone()
            if current['version']!=version or current['withdrawn'] or current['expires']<=self.now():raise ValueError('Belegstand nicht mehr freigabefähig')
            actual=[dict(r) for r in db.execute('SELECT * FROM auto_files WHERE order_id=? AND active=1 ORDER BY id',(identity,))]
            if fingerprint(actual)!=job['fingerprint']:raise ValueError('Belegstand verändert')
            manifest=json.loads(path.read_text())
            if manifest['state']=='ready':
                self.review.inspect(job['bundle'],candidate,files,version=version,states=('ready',))
                if manifest.get('reviewer')!=reviewer:raise ValueError('Freigabezuordnung verändert')
            else:self.review.approve(job['bundle'],candidate,files,version=version,reviewer=reviewer,**checks)
            if current['released_version'] is None:
                db.execute("UPDATE auto_orders SET released_version=?,state='released',expires=? WHERE order_id=?",(version,self.now()+30*DAY,identity))
                db.execute("UPDATE auto_jobs SET state='released' WHERE id=?",(job['id'],))
        self.notices.enqueue(identity,'ready',str(version))

    def result(self, token):
        context=self.get(token=token);self.gate(context['order_id'],processing=True)
        job=self.current_job(context['order_id'])
        if context['released_version']!=context['version'] or not job or job['state']!='released':raise ValueError('Ergebnis noch nicht freigegeben')
        candidate=json.loads(job['candidate']);files=json.loads(job['files'])
        manifest=self.review.inspect(job['bundle'],candidate,files,version=context['version'],states=('ready',))
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for pdf in manifest['pdfs']:archive.writestr(pdf['file'],self.review.download(job['bundle'],pdf['file']))
        return stream.getvalue()

    def notification_secret(self,record):
        payload=json.loads(record['payload'])
        if record['event'] in ('order_confirmation','invoice_available') or payload.get('scope')=='checkout':
            return self.checkout_notices.secret()
        return self.secret()

    def notice_context(self, record):
        payload=json.loads(record['payload'])
        if record['event'] in ('order_confirmation','invoice_available') or record['event']=='access_code' and payload.get('scope')=='checkout':
            if not self.operator_ready():return 'defer',{}
            try:configuration(self.config_path)
            except (ValueError,OSError,KeyError):return 'defer',{}
            return self.checkout_notices.notice_context(record)
        if record['event']=='payment_action_required':
            if not self.operator_ready():return 'defer',{}
            try:configuration(self.config_path)
            except (ValueError,OSError,KeyError):return 'defer',{}
            return self.payments.problem_notice_context(record)
        try:context=self.get(record['order_id'])
        except ValueError:return 'obsolete',{}
        if context['expires']<=self.now():return 'obsolete',context
        event=record['event'];version=record['version']
        if event=='access_code':
            with self.ledger.db() as db:challenge=db.execute('SELECT * FROM auto_challenges WHERE order_id=?',(record['order_id'],)).fetchone()
            if not challenge or challenge['nonce']!=version or challenge['used'] or challenge['expires']<=self.now():return 'obsolete',context
            return 'send',context
        if event=='upload_available':
            try:self.gate(record['order_id'])
            except ValueError:return 'defer',context
            return 'send',context
        if version!=str(context['version']):return 'obsolete',context
        allowed={'received':('submitted','queued','extracting','waiting_start','waiting_confirmation','waiting_payment','waiting_policy','needs_customer_input','needs_final_review','internal_review'),
                 'missing_inputs':('needs_customer_input',),'review_needed':('needs_final_review',),
                 'processing_error':('internal_review',),'ready':('released',)}
        if context['state'] not in allowed.get(event,()):return 'obsolete',context
        if event in ('received','missing_inputs','ready'):
            try:self.gate(record['order_id'])
            except ValueError:return 'defer',context
        if event=='ready':
            if context['released_version']!=context['version']:return 'obsolete',context
            try:self.result(context['token'])
            except ValueError:return 'defer',context
        return 'send',context
