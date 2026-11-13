"""Authenticated customer upload and source-bound operator review for production agents."""
from http.cookies import SimpleCookie
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import urllib.parse

import invoicing
from checkout import Checkout
from automation_core import Automation

LABELS={'awaiting_upload':'Unterlagen hochladen','submitted':'Unterlagen eingereicht','queued':'Unterlagen eingereicht',
        'extracting':'Unterlagen werden ausgewertet','running':'Unterlagen werden geprüft',
        'waiting_start':'Wartet auf den zulässigen Leistungsbeginn',
        'waiting_confirmation':'Bitte Vertragsunterlagen herunterladen',
        'waiting_payment':'Zahlung oder Betriebsfreigabe wird geprüft','waiting_policy':'Betriebsfreigabe wird abgeschlossen',
        'needs_customer_input':'Bitte Angaben oder Unterlagen ergänzen','needs_final_review':'Entwurf in persönlicher Schlussprüfung',
        'internal_review':'Persönliche Prüfung erforderlich','released':'Abrechnung freigegeben','expired':'Kundenbereich abgelaufen'}


def install(app):
    Old=app.H
    def service():
        ledger=invoicing.ledger(app)
        Checkout(ledger,os.environ.get('AN_CHECKOUT_CONFIG','/etc/an-upload/checkout.json'))
        calculator=Path(__file__).parent/'abrechnung/rechner.py'
        if not calculator.is_file():calculator=Path(__file__).resolve().parents[1]/'abrechnung/rechner.py'
        return Automation(ledger,app.DATA_DIR,os.environ.get('AN_AUTOMATION_CONFIG','/etc/an-upload/automation.json'),
            calculator,operator_ready=lambda:not app.readiness())
    app.automation_service=service
    if hasattr(app,'cleanup'):
        previous_cleanup=app.cleanup
        def cleanup():
            previous_cleanup()
            ledger=invoicing.ledger(app)
            if not (ledger.folder/'invoices.sqlite3').exists():return
            try:service().expire()
            except Exception:
                target=Path(app.DATA_DIR)/'cleanup-health.json'
                try:health=json.loads(target.read_text())
                except (OSError,ValueError):health={}
                health['cleanup_error']=True
                temp=target.with_suffix('.tmp');temp.write_text(json.dumps(health));temp.replace(target)
                raise
        app.cleanup=cleanup
    if hasattr(app,'admin_page'):
        previous=app.admin_page
        def admin(*args,**kwargs):
            return previous(*args,**kwargs).replace('<h1>Auftragsfreigaben</h1>','<h1>Auftragsfreigaben</h1><p><a href="/verwaltung/agenten">Automatische Aufträge und Schlussprüfung</a></p>')
        app.admin_page=admin

    def page(title,body):
        return app.page(title,'<style>.auto label{display:block;margin:14px 0}.auto input:not([type=checkbox]){font:inherit;padding:10px;max-width:100%;display:block}.auto input[type=checkbox]{width:20px;height:20px;vertical-align:middle}.auto button{cursor:pointer}.auto blockquote{overflow-wrap:anywhere}.auto .state{background:#e8f1ec;padding:16px;border-radius:10px}.auto table{display:block;overflow-x:auto}.auto .warn{border:2px solid #ae6017;padding:16px;border-radius:10px}</style><main class="auto">'+body+'</main>')

    class Handler(Old):
        def auto_session(self):
            cookie=SimpleCookie()
            try:cookie.load(self.headers.get('Cookie',''))
            except Exception:return ''
            return cookie['an_auto'].value if 'an_auto' in cookie else ''

        def auto_send(self,status,body,mime='text/html; charset=utf-8',extra=None):
            return self.send(status,body,mime,{'Referrer-Policy':'no-referrer',
                'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",**(extra or {})})

        def auto_login_page(self,token,message=''):
            base='/kunden/'+token
            return page('Geschützter Kundenbereich','<h1>Geschützter Kundenbereich</h1><p>'+html.escape(message)+'</p><p>Fordern Sie einen einmaligen Code an. Er wird an die im Auftrag hinterlegte E-Mail-Adresse geschickt.</p><form method="post" action="'+base+'/code"><button class="btn">Zugangscode anfordern</button></form><form method="post" action="'+base+'/anmelden"><label>Einmaliger Zugangscode<input name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required></label><button class="btn">Kundenbereich öffnen</button></form>')

        def do_GET(self):
            path=urllib.parse.urlsplit(self.path).path
            checkout_entry=re.fullmatch(r'/bestellen/([a-f0-9]{40})/unterlagen',path)
            if checkout_entry:
                try:
                    auto=service();store=Checkout(auto.ledger,os.environ.get('AN_CHECKOUT_CONFIG','/etc/an-upload/checkout.json'))
                    session,_,_=self.checkout_session(store)
                    _,offer=store.offer(checkout_entry[1],session)
                    portal=auto.provision(offer['order']['reference'])
                    return self.auto_send(303,'',extra={'Location':'/kunden/'+portal['token']})
                except (ValueError,OSError,KeyError):return self.auto_send(409,page('Kundenbereich noch nicht bereit','<h1>Kundenbereich noch nicht bereit</h1><p>Zahlungsbestätigung oder Betriebsfreigabe steht noch aus. Es wurden keine Unterlagen an einen Auslesedienst übermittelt.</p>'))
            admin=re.fullmatch(r'/verwaltung/agenten(?:/(AN-[a-f0-9]{32})(?:/(original|pdf)/([A-Za-z0-9_.-]+))?)?',path)
            if admin:
                if not self.admin_auth():return
                try:return self.agent_admin(service(),*admin.groups())
                except (ValueError,OSError,KeyError):return self.auto_send(409,page('Prüfung nicht verfügbar','<h1>Prüffassung nicht verfügbar</h1><p>Der Belegstand hat sich geändert oder die Prüfung ist noch nicht abgeschlossen.</p>'))
            match=re.fullmatch(r'/kunden/([A-Za-z0-9_-]{32})(?:/(vertrag|ergebnis|datei/([a-f0-9]{32})))?',path)
            if not match:return super().do_GET()
            token,action,file_id=match.groups()
            try:
                auto=service();context=auto.get(token=token)
                if context['expires']<=auto.now():return self.auto_send(410,page('Kundenbereich abgelaufen','<h1>Kundenbereich abgelaufen</h1>'))
                if not auto.authenticated(token,self.auto_session()):return self.auto_send(200,self.auto_login_page(token))
                base='/kunden/'+token
                if action=='vertrag':
                    raw=auto.contract_packet(token)
                    result=self.auto_send(200,raw,'application/zip',{'Content-Disposition':'attachment; filename="Vertragsunterlagen.zip"'})
                    if self.command!='HEAD':auto.confirm_delivery(token)
                    return result
                if action=='ergebnis':
                    return self.auto_send(200,auto.result(token),'application/zip',{'Content-Disposition':'attachment; filename="Nebenkostenabrechnung.zip"'})
                files=auto.files(context['order_id'])
                if file_id:
                    found=next((f for f in files if f['id']==file_id),None)
                    if not found:raise ValueError('Datei nicht gefunden')
                    auto.verify_sources([found])
                    return self.auto_send(200,Path(found['path']).read_bytes(),'application/octet-stream',{'Content-Disposition':"attachment; filename*=UTF-8''"+urllib.parse.quote(found['name'])})
                body='<h1>Ihre Nebenkostenabrechnung</h1><p class="state">'+LABELS.get(context['state'],'Bearbeitungsstatus wird geprüft')+'</p>'
                body+='<p><a href="'+base+'/vertrag">Vertragsunterlagen und Vorausrechnung herunterladen</a></p>'
                if not context['confirmation_at']:body+='<p>Bitte speichern Sie zuerst Ihre Vertragsunterlagen. Vorher startet die Auswertung nicht.</p>'
                body+='<h2>Ihre Unterlagen</h2><ul>'
                for file in files:
                    body+='<li><a href="'+base+'/datei/'+file['id']+'">'+html.escape(file['name'])+'</a>'
                    if context['released_version'] is None:body+='<form method="post" action="'+base+'/entfernen"><input type="hidden" name="file_id" value="'+file['id']+'"><button>Datei aus diesem Belegstand entfernen</button></form>'
                    body+='</li>'
                body+='</ul>'
                if context['released_version'] is not None:
                    body+='<p><a class="btn" href="'+base+'/ergebnis">Geprüfte Abrechnung herunterladen</a></p>'
                else:
                    body+='<p>PDF, JPG, PNG oder WebP; höchstens 25 MB je Datei und 100 MB insgesamt. Bilder und nicht eindeutig auswertbare Fälle werden persönlich geprüft. Bitte entfernen Sie unnötige sensible Angaben.</p><label>Unterlagen auswählen<input id="auto-files" type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp"></label><p id="upload-message" role="status"></p>'
                    body+='<form method="post" action="'+base+'/einreichen"><input type="hidden" name="version" value="'+str(context['version'])+'"><button class="btn">Diesen Belegstand zur Auswertung einreichen</button></form><p>Ergänzungen machen eine bestehende Prüffassung ungültig. Reichen Sie den ergänzten Stand anschließend erneut ein.</p>'
                    body+='''<script>document.getElementById('auto-files').onchange=async function(){let box=document.getElementById('upload-message');this.disabled=true;try{for(let file of this.files){box.textContent='Wird hochgeladen: '+file.name;let r=await fetch(location.pathname+'/datei?name='+encodeURIComponent(file.name),{method:'PUT',body:file});if(!r.ok)throw new Error(await r.text());}location.reload();}catch(e){box.textContent=e.message;this.disabled=false;}};</script>'''
                body+='<p>Ihre Abrechnung wird erst nach persönlicher Prüfung freigegeben. Bitte senden Sie keine Belege per E-Mail.</p>'
                return self.auto_send(200,page('Kundenbereich',body))
            except (ValueError,OSError,KeyError):return self.auto_send(409,page('Kundenbereich prüfen','<h1>Aktion noch nicht möglich</h1><p>Bitte prüfen Sie Ihren Zugang oder den aktuellen Auftragsstatus.</p>'))

        do_HEAD=do_GET

        def auto_values(self):
            if not self.origin_ok():raise PermissionError('Ungültiger Ursprung')
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/x-www-form-urlencoded':raise ValueError('Formulardaten erforderlich')
            if self.headers.get('Content-Length')=='0':return {}
            values=urllib.parse.parse_qs(self.body(20000).decode('utf-8'),keep_blank_values=True,max_num_fields=12)
            if any(len(v)!=1 for v in values.values()):raise ValueError('Doppelte Formularfelder')
            return {k:v[0] for k,v in values.items()}

        def do_PUT(self):
            parsed=urllib.parse.urlsplit(self.path)
            match=re.fullmatch(r'/kunden/([A-Za-z0-9_-]{32})/datei',parsed.path)
            if not match:return super().do_PUT()
            try:
                if not self.origin_ok():return self.auto_send(403,'Ungültiger Ursprung','text/plain; charset=utf-8')
                if self.headers.get('Transfer-Encoding'):raise ValueError('Ungültige Übertragung')
                auto=service();token=match[1]
                if not auto.authenticated(token,self.auto_session()):return self.auto_send(403,'Zugang erforderlich','text/plain; charset=utf-8')
                names=urllib.parse.parse_qs(parsed.query,max_num_fields=1)
                if set(names)!={'name'} or len(names['name'])!=1:raise ValueError('Dateiname erforderlich')
                fid=auto.upload(token,names['name'][0],self.body(25*1024*1024))
                return self.auto_send(201,json.dumps({'file_id':fid}),'application/json')
            except (ValueError,OSError,KeyError):return self.auto_send(400,'Upload nicht möglich; Datei und Auftragsstatus prüfen','text/plain; charset=utf-8')

        def do_POST(self):
            path=urllib.parse.urlsplit(self.path).path
            admin=re.fullmatch(r'/verwaltung/agenten/(AN-[a-f0-9]{32})/freigeben',path)
            if admin:
                if not self.admin_auth():return
                try:
                    values=self.auto_values()
                    checks={k:values.get(k)=='yes' for k in ('original_visual_checked','pdf_visual_checked','allocation_checked')}
                    service().approve(admin[1],int(values.get('version','0')),values.get('manifest_sha256',''),checks)
                    return self.auto_send(303,'',extra={'Location':'/verwaltung/agenten/'+admin[1]})
                except PermissionError:return self.auto_send(403,'Ungültiger Ursprung','text/plain; charset=utf-8')
                except (ValueError,OSError,KeyError):return self.auto_send(409,'Freigabe nicht erfolgt; aktuelle Originale und PDF-Fassung prüfen','text/plain; charset=utf-8')
            match=re.fullmatch(r'/kunden/([A-Za-z0-9_-]{32})/(code|anmelden|entfernen|einreichen)',path)
            if not match:return super().do_POST()
            token,action=match.groups()
            try:
                values=self.auto_values();auto=service()
                if action=='code':
                    auto.request_code(token)
                    return self.auto_send(200,self.auto_login_page(token,'Die Code-Anforderung ist gespeichert. Prüfen Sie Ihr E-Mail-Postfach.'))
                if action=='anmelden':
                    session=auto.login(token,values.get('code',''))
                    return self.auto_send(303,'',extra={'Location':'/kunden/'+token,'Set-Cookie':'an_auto='+session+'; Secure; HttpOnly; SameSite=Strict; Path=/kunden/'+token+'; Max-Age=1800'})
                if not auto.authenticated(token,self.auto_session()):return self.auto_send(403,'Zugang erforderlich','text/plain; charset=utf-8')
                if action=='entfernen':auto.remove(token,values.get('file_id',''))
                elif action=='einreichen':
                    if int(values.get('version','-1'))!=auto.get(token=token)['version']:raise ValueError('Belegstand geändert')
                    auto.submit(token)
                return self.auto_send(303,'',extra={'Location':'/kunden/'+token})
            except PermissionError:return self.auto_send(403,'Ungültiger Ursprung','text/plain; charset=utf-8')
            except (ValueError,OSError,KeyError):return self.auto_send(409,page('Eingaben prüfen','<h1>Aktion nicht abgeschlossen</h1><p>Zugangscode, Unterlagen oder Auftragsstatus prüfen.</p>'))

        def agent_admin(self,auto,identity,kind,filename):
            if identity is None:
                with auto.ledger.db() as db:rows=[dict(r) for r in db.execute('SELECT * FROM auto_orders ORDER BY created DESC LIMIT 200')]
                body='<p><a href="/verwaltung">Verwaltung</a></p><h1>Automatische Aufträge</h1>'
                for row in rows:body+='<p><a href="/verwaltung/agenten/'+row['order_id']+'">'+html.escape(row['order_id'])+'</a> · '+LABELS.get(row['state'],row['state'])+'</p>'
                if not rows:body+='<p>Noch keine automatischen Aufträge vorhanden.</p>'
                return self.auto_send(200,page('Automatische Aufträge',body))
            context=auto.get(identity);files=auto.files(identity);job=auto.current_job(identity)
            if kind=='original':
                found=next((f for f in files if f['id']==filename),None)
                if not found:raise ValueError('Original nicht verfügbar')
                auto.verify_sources([found])
                return self.auto_send(200,Path(found['path']).read_bytes(),'application/pdf' if found['name'].lower().endswith('.pdf') else 'application/octet-stream',{'Content-Disposition':'inline'})
            manifest=None
            if job and job['bundle']:
                manifest=auto.review.inspect(job['bundle'],json.loads(job['candidate']),json.loads(job['files']),version=context['version'])
            if kind=='pdf':
                if not manifest or not re.fullmatch(r'abrechnung-\d{3}\.pdf',filename) or not any(f['file']==filename for f in manifest['pdfs']):raise ValueError('PDF nicht verfügbar')
                return self.auto_send(200,(Path(job['bundle'])/filename).read_bytes(),'application/pdf',{'Content-Disposition':'inline'})
            body='<p><a href="/verwaltung/agenten">Alle automatischen Aufträge</a></p><h1>Persönliche Schlussprüfung</h1><p>'+html.escape(identity)+'</p><p class="state">'+LABELS.get(context['state'],context['state'])+'</p><h2>Originalunterlagen</h2><ul>'
            for file in files:body+='<li><a href="/verwaltung/agenten/'+identity+'/original/'+file['id']+'">'+html.escape(file['name'])+'</a></li>'
            body+='</ul>'
            if manifest:
                candidate=json.loads(job['candidate'])
                body+='<div class="warn">Fassung '+str(context['version'])+' · '+('Bereits freigegeben' if context['released_version'] is not None else 'Noch nicht für den Kunden freigegeben')+'</div><h2>Abrechnungsentwürfe</h2><ul>'
                for pdf in manifest['pdfs']:body+='<li><a href="/verwaltung/agenten/'+identity+'/pdf/'+pdf['file']+'">'+html.escape(pdf['file'])+'</a></li>'
                body+='</ul><h2>Kosten und Verteilung</h2><table><tr><th>Kostenart</th><th>Betrag</th><th>Schlüssel</th></tr>'
                for cost in candidate['kosten']:body+='<tr>'+''.join('<td>'+html.escape(str(cost[k]))+'</td>' for k in ('name','betrag','schluessel'))+'</tr>'
                body+='</table><h2>Mietparteien und Vorauszahlungen</h2><table><tr><th>Mietpartei</th><th>Wohnung</th><th>Zeitraum</th><th>Fläche</th><th>Vorauszahlungen</th></tr>'
                for tenant in candidate['mieter']:body+='<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in (tenant['name'],tenant['wohnung'],tenant['von']+' – '+tenant['bis'],tenant['wohnflaeche'],tenant['vorauszahlungen']))+'</tr>'
                body+='</table><details><summary>Fundstellen in den Originalen</summary>'
                for source in candidate['source_evidence']:
                    for field,cites in source['fields'].items():
                        body+='<p>'+html.escape(field)+'</p>'
                        for cite in cites:body+='<blockquote>Seite '+str(cite['page'])+': '+html.escape(cite['text'])+'</blockquote>'
                body+='</details>'
                if context['released_version'] is None:
                    digest=hashlib.sha256((Path(job['bundle'])/'manifest.json').read_bytes()).hexdigest()
                    body+='<form method="post" action="/verwaltung/agenten/'+identity+'/freigeben"><input type="hidden" name="version" value="'+str(context['version'])+'"><input type="hidden" name="manifest_sha256" value="'+digest+'">'
                    for name,label in (('original_visual_checked','Originale vollständig und visuell geprüft'),('pdf_visual_checked','Alle fertigen PDFs visuell und rechnerisch geprüft'),('allocation_checked','Umlagefähigkeit, Zeitraum und vertragliche Verteilerschlüssel persönlich geprüft')):
                        body+='<label><input type="checkbox" name="'+name+'" value="yes" required>'+label+'</label>'
                    body+='<button class="btn">Diese geprüfte Fassung für den Kunden freigeben</button></form>'
            else:body+='<p>Es liegt noch keine freigabefähige Prüffassung vor. Bei Rückfragen wird der aktuelle Stand im Kundenbereich angezeigt.</p>'
            return self.auto_send(200,page('Schlussprüfung',body))
    app.H=Handler
