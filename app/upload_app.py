#!/usr/bin/env python3
"""Abrechnungs-Navi: Unterlagen-Upload fuer Kunden + Verwaltung fuer den Inhaber.

Laeuft nur auf 127.0.0.1. Caddy leitet weiter und schuetzt /verwaltung mit Passwort.
Nur Python-Standardbibliothek, keine Zusatzpakete.
"""
import html
import json
import os
import re
import secrets
import shutil
import smtplib
import ssl
from collections import deque
from email.message import EmailMessage
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA_DIR = os.environ.get("AN_DATA_DIR", "/srv/an-upload/data")
PORT = int(os.environ.get("AN_PORT", "8790"))
MAX_FILE = 25 * 1024 * 1024          # 25 MB pro Datei
MAX_FILES = 150                       # pro Kunde
ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
LOCK = threading.Lock()
DB = os.path.join(DATA_DIR, "kunden.json")
KEEP_DAYS = 183                       # Dateien 6 Monate nach Auftragsende automatisch loeschen
ANFRAGEN = os.path.join(DATA_DIR, "anfragen.json")
SMTP_FILE = os.environ.get("AN_SMTP_FILE", "/etc/an-upload/smtp.conf")   # enthaelt nur das Mail-Passwort
SMTP_HOST, SMTP_PORT = "smtp.hostinger.com", 587   # 465 ist bei Hetzner gesperrt, 587 mit STARTTLS ist erlaubt
MAIL_ADDR = "kontakt@abrechnungs-navi.de"
EMAIL_RE = re.compile(r"^[^@\s<>]{1,64}@[^@\s<>]{1,150}\.[A-Za-z]{2,24}$")
RECENT = deque()                      # Zeitpunkte der letzten Anfragen (Schutz vor Massen-Spam)


# ---------- Datenhaltung ----------
def load():
    try:
        with open(DB, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(db):
    tmp = DB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DB)


def delete_at(c):
    """Zeitpunkt der automatischen Loeschung: 6 Monate nach Abschluss,
    bei nie abgeschlossenen Auftraegen 6 Monate nach Ablauf des Links."""
    return (c.get("done") or c["expires"]) + KEEP_DAYS * 86400


def load_anfragen():
    try:
        with open(ANFRAGEN, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_anfragen(lst):
    tmp = ANFRAGEN + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ANFRAGEN)


def send_mail(a):
    """Schickt die Anfrage an das eigene Postfach. Ohne hinterlegtes Passwort: nur speichern."""
    try:
        with open(SMTP_FILE, encoding="utf-8") as f:
            pw = f.read().strip()
    except OSError:
        return False
    if not pw:
        return False
    msg = EmailMessage()
    msg["Subject"] = f"Neue Anfrage: {a['name']} – {a['wohnungen']} Wohnung(en), Jahr {a['jahr']}"
    msg["From"] = f"Abrechnungs-Navi Webseite <{MAIL_ADDR}>"
    msg["To"] = MAIL_ADDR
    msg["Reply-To"] = a["email"]
    msg.set_content(
        f"Neue Anfrage über abrechnungs-navi.de\n\n"
        f"Name: {a['name']}\nE-Mail: {a['email']}\nWohnungen: {a['wohnungen']}\nAbrechnungsjahr: {a['jahr']}\n"
        f"Eingang: {datetime.fromtimestamp(a['zeit']):%d.%m.%Y %H:%M}\n\nNachricht:\n{a['nachricht'] or '-'}\n\n"
        f"Antworten: einfach auf diese Mail antworten (geht an den Kunden).\n")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(MAIL_ADDR, pw)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"Mail-Versand fehlgeschlagen: {type(e).__name__}", flush=True)
        return False


def mail_and_mark(a):
    ok = send_mail(a)
    with LOCK:
        lst = load_anfragen()
        for x in lst:
            if x["id"] == a["id"]:
                x["mail"] = ok
        save_anfragen(lst)


def send_withdrawal_confirmation(row):
    """Quittung nach ausdruecklich abgegebenem Widerruf; keine Werbemail."""
    try:
        pw = open(SMTP_FILE, encoding='utf-8').read().strip()
        msg = EmailMessage()
        msg['Subject'] = 'Eingang Ihres Widerrufs - Abrechnungs-Navi'
        msg['From'] = MAIL_ADDR
        msg['To'] = row['email']
        msg['Bcc'] = MAIL_ADDR
        stamp = datetime.fromtimestamp(row['time']).astimezone().isoformat(timespec='seconds')
        msg.set_content(f"Guten Tag {row['name']},\n\nIhr Widerruf ist am {stamp} eingegangen.\n"
                        f"Vertragsangabe: {row['vertrag']}\nEingangsnummer: {row['id']}\n\n"
                        'Diese Nachricht bestaetigt den Eingang Ihrer Widerrufserklaerung.\n\nVolker Cyrener\nAbrechnungs-Navi')
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(MAIL_ADDR,pw)
            smtp.send_message(msg)
        return True
    except Exception:
        print('Widerruf gespeichert; Mailquittung noch nicht zugestellt',flush=True)
        return False


def cleanup():
    """Loescht alle Kunden, deren Aufbewahrungsfrist abgelaufen ist, und alte Anfragen."""
    now = time.time()
    with LOCK:
        lst = load_anfragen()
        rest = [a for a in lst if a["zeit"] + KEEP_DAYS * 86400 > now]
        if len(rest) != len(lst):
            save_anfragen(rest)
        db = load()
        gone = [t for t, c in db.items() if delete_at(c) <= now]
        for t in gone:
            db.pop(t)
            shutil.rmtree(customer_dir(t), ignore_errors=True)
        if gone:
            save(db)
    if gone:
        print(f"Automatisch geloescht: {len(gone)} Kunde(n)", flush=True)


def cleanup_loop():
    while True:
        try:
            cleanup()
        except Exception as e:  # nie abstuerzen
            print(f"Fehler bei automatischer Loeschung: {e}", flush=True)
        time.sleep(3600)


def customer_dir(token):
    return os.path.join(DATA_DIR, "kunden", token)


def list_files(token):
    d = customer_dir(token)
    if not os.path.isdir(d):
        return []
    out = []
    for n in sorted(os.listdir(d)):
        p = os.path.join(d, n)
        if os.path.isfile(p):
            st = os.stat(p)
            out.append((n, st.st_size, st.st_mtime))
    return out


def safe_name(name):
    name = os.path.basename(name or "").strip()
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    stem = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._ -]", "_", stem)[:80].strip(" .") or "datei"
    return stem, ext


def fmt_size(n):
    return f"{n/1024/1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, n//1024)} KB"


# ---------- Seiten ----------
CSS = """
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
color:#14212b;background:#f6f8f7;line-height:1.55;font-size:17px}.wrap{max-width:820px;margin:0 auto;padding:32px 20px 60px}
.logo{font-weight:800;font-size:20px;margin-bottom:24px}.logo span{color:#1f6f5c}.card{background:#fff;border:1px solid #dfe5e8;
border-radius:16px;padding:28px;margin-bottom:20px}h1{font-size:28px;margin:0 0 10px}h2{font-size:20px;margin:0 0 12px}
.muted{color:#56656f}.btn{display:inline-block;background:#1f6f5c;color:#fff;border:0;border-radius:10px;padding:12px 20px;
font-size:16px;font-weight:600;cursor:pointer;text-decoration:none}.btn.red{background:#b23b3b}.btn.small{padding:6px 12px;font-size:14px}
.drop{border:2px dashed #9fbfb5;border-radius:14px;padding:34px;text-align:center;background:#f2f8f6;cursor:pointer}
.drop.over{background:#e3f1ec}input[type=text],input[type=number]{width:100%;padding:11px 13px;border:1px solid #dfe5e8;
border-radius:10px;font:inherit;margin:4px 0 14px}table{width:100%;border-collapse:collapse;font-size:15px}td,th{padding:8px 6px;
border-bottom:1px solid #eef1f2;text-align:left;vertical-align:top}.ok{color:#1f6f5c;font-weight:600}.err{color:#b23b3b;font-weight:600}
code{background:#eef1f2;padding:2px 6px;border-radius:6px;word-break:break-all;font-size:14px}a{color:#1f6f5c}
"""


def page(title, body):
    return f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>{html.escape(title)} – Abrechnungs-Navi</title><style>{CSS}</style></head>
<body><div class="wrap"><div class="logo">Abrechnungs<span>-</span>Navi</div>{body}</div></body></html>"""


def upload_page(token, c):
    files = list_files(token)
    rows = "".join(f"<li>{html.escape(n)} <span class='muted'>({fmt_size(s)})</span></li>" for n, s, _ in files)
    done = f"<h2>Bereits hochgeladen ({len(files)})</h2><ul>{rows}</ul>" if files else ""
    until = datetime.fromtimestamp(c["expires"]).strftime("%d.%m.%Y")
    return page("Unterlagen hochladen", f"""
<div class="card"><h1>Unterlagen hochladen</h1>
<p class="muted">Für: <b>{html.escape(c['name'])}</b> · Link gültig bis {until}</p>
<p>Bitte laden Sie Ihre Unterlagen als <b>Foto oder PDF</b> hoch: Rechnungen (Grundsteuer, Wasser, Müll, Versicherung,
Heizung usw.), die Nebenkosten-Regelung aus dem Mietvertrag und die Vorauszahlungen Ihrer Mieter.
Sie können mehrmals hochladen. Die Dateien sehen nur wir – Sie selbst sehen hier nur die Dateinamen.</p>
<div class="drop" id="drop"><b>Dateien hier ablegen</b><br><span class="muted">oder klicken zum Auswählen
(max. 25 MB pro Datei)</span><input type="file" id="f" multiple accept=".pdf,.jpg,.jpeg,.png,.heic,.heif,.webp,image/*,application/pdf" hidden></div>
<ul id="log"></ul></div>
<div class="card">{done or '<p class="muted">Noch keine Dateien hochgeladen.</p>'}</div>
<p class="muted" style="font-size:14px">Ihre Daten werden verschlüsselt übertragen und auf einem Server in Deutschland gespeichert.
<a href="/datenschutz.html">Datenschutzerklärung</a> · <a href="/impressum.html">Impressum</a></p>
<script>
const drop=document.getElementById('drop'),inp=document.getElementById('f'),log=document.getElementById('log');
drop.onclick=()=>inp.click();
drop.ondragover=e=>{{e.preventDefault();drop.classList.add('over')}};
drop.ondragleave=()=>drop.classList.remove('over');
drop.ondrop=e=>{{e.preventDefault();drop.classList.remove('over');send(e.dataTransfer.files)}};
inp.onchange=()=>send(inp.files);
async function send(files){{for(const file of files){{const li=document.createElement('li');li.textContent=file.name+' … wird hochgeladen';log.appendChild(li);
 try{{const r=await fetch('/hochladen/api/{token}?name='+encodeURIComponent(file.name),{{method:'PUT',body:file}});
 const t=await r.text();li.innerHTML=r.ok?'<span class="ok">✓</span> '+escapeHtml(file.name):'<span class="err">✗</span> '+escapeHtml(file.name)+': '+escapeHtml(t);}}
 catch(e){{li.innerHTML='<span class="err">✗</span> '+escapeHtml(file.name)+': Verbindung unterbrochen';}}}}
 setTimeout(()=>location.reload(),1500);}}
function escapeHtml(s){{const d=document.createElement('div');d.textContent=s;return d.innerHTML}}
</script>""")


def admin_page(db, msg="", base=""):
    rows = []
    for token, c in sorted(db.items(), key=lambda kv: -kv[1]["created"]):
        files = list_files(token)
        exp = datetime.fromtimestamp(c["expires"])
        if c.get("done"):
            status = f"<b>Auftrag abgeschlossen</b> am {datetime.fromtimestamp(c['done']):%d.%m.%Y} – Upload geschlossen"
        else:
            status = "Link abgelaufen" if exp < datetime.now() else f"Link gültig bis {exp:%d.%m.%Y}"
        status += f"<br>Automatische Löschung am {datetime.fromtimestamp(delete_at(c)):%d.%m.%Y}"
        if c.get("done"):
            toggle = (f"<form method='post' action='/verwaltung/offen'><input type='hidden' name='token' value='{token}'>"
                      f"<button class='btn small' style='background:#56656f'>Wieder öffnen</button></form>")
        else:
            toggle = (f"<form method='post' action='/verwaltung/fertig'><input type='hidden' name='token' value='{token}'>"
                      f"<button class='btn small'>Auftrag abgeschlossen</button></form>")
        flist = "".join(
            f"<div><a href='/verwaltung/datei/{token}/{urllib.parse.quote(n)}'>{html.escape(n)}</a> "
            f"<span class='muted'>({fmt_size(s)}, {datetime.fromtimestamp(m):%d.%m. %H:%M})</span></div>"
            for n, s, m in files) or "<span class='muted'>noch keine</span>"
        link = f"{base}/hochladen/{token}"
        rows.append(f"""<tr><td><b>{html.escape(c['name'])}</b><br><span class='muted'>{status}</span><br>
<code>{html.escape(link)}</code></td><td>{flist}</td><td>{toggle}<br>
<form method="post" action="/verwaltung/loeschen" onsubmit="return this.querySelector('input[name=ok]').checked">
<input type="hidden" name="token" value="{token}"><label style="font-size:13px"><input type="checkbox" name="ok"> sicher</label><br>
<button class="btn red small">Kunde + Dateien löschen</button></form></td></tr>""")
    table = ("<table><tr><th>Kunde / Upload-Link</th><th>Dateien</th><th></th></tr>" + "".join(rows) + "</table>") if rows \
        else "<p class='muted'>Noch keine Kunden angelegt.</p>"
    note = f"<div class='card'><span class='ok'>{msg}</span></div>" if msg else ""
    anfr = load_anfragen()
    n30 = sum(1 for a in anfr if a["zeit"] > time.time() - 30 * 86400)
    arows = "".join(
        f"<tr><td>{datetime.fromtimestamp(a['zeit']):%d.%m. %H:%M}</td><td><b>{html.escape(a['name'])}</b><br>"
        f"<a href='mailto:{html.escape(a['email'])}'>{html.escape(a['email'])}</a></td>"
        f"<td>{a['wohnungen']} WE · {html.escape(str(a['jahr']))}<br><span class='muted'>{html.escape(a['nachricht'][:300])}</span></td>"
        f"<td>{'✓ Mail' if a.get('mail') else '<span class=muted>nur hier</span>'}</td></tr>"
        for a in sorted(anfr, key=lambda x: -x["zeit"])[:50])
    anfragen_html = (f"<div class='card'><h2>Anfragen über das Formular</h2><p><b>{n30}</b> in den letzten 30 Tagen · "
                     f"<b>{len(anfr)}</b> insgesamt (Anfragen werden nach 6 Monaten automatisch gelöscht)</p>"
                     + (f"<table><tr><th>Eingang</th><th>Kunde</th><th>Angaben</th><th></th></tr>{arows}</table>" if arows
                        else "<p class='muted'>Noch keine Anfragen.</p>") + "</div>")
    return page("Verwaltung", f"""{note}{anfragen_html}
<div class="card"><h1>Neuen Upload-Link anlegen</h1>
<form method="post" action="/verwaltung/neu"><label>Name des Kunden (z. B. „Müller, Bahnhofstr. 3“)</label>
<input type="text" name="name" required maxlength="100"><label>Link gültig für Tage</label>
<input type="number" name="tage" value="30" min="1" max="365"><button class="btn">Link anlegen</button></form></div>
<p class="muted" style="font-size:14px">Nach „Auftrag abgeschlossen“ ist der Upload geschlossen. Die Dateien werden 6 Monate danach
automatisch gelöscht. Wird ein Auftrag nie abgeschlossen, löscht der Server 6 Monate nach Ablauf des Links.</p>
<div class="card"><h2>Kunden</h2>{table}</div>""")


# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    server_version = "AN/1"

    def log_message(self, fmt, *args):  # keine IP-Adressen ins Journal
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0][:40]))

    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def base_url(self):
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "abrechnungs-navi.de"
        return f"https://{host}"

    def valid_customer(self, token):
        if not TOKEN_RE.match(token or ""):
            return None
        c = load().get(token)
        if not c or c["expires"] < time.time() or c.get("done"):
            return None
        return c

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/hochladen/") and not path.startswith("/hochladen/api/"):
            token = path.split("/")[2] if len(path.split("/")) > 2 else ""
            c = self.valid_customer(token)
            if not c:
                return self.send(404, page("Link ungültig", "<div class='card'><h1>Link ungültig oder abgelaufen</h1>"
                                 "<p>Bitte fordern Sie einen neuen Link an: kontakt@abrechnungs-navi.de</p></div>"))
            return self.send(200, upload_page(token, c))
        if path in ("/verwaltung", "/verwaltung/"):
            return self.send(200, admin_page(load(), base=self.base_url()))
        if path.startswith("/verwaltung/datei/"):
            parts = path.split("/")
            if len(parts) != 5 or not TOKEN_RE.match(parts[3]):
                return self.send(404, "Nicht gefunden", "text/plain; charset=utf-8")
            name = os.path.basename(urllib.parse.unquote(parts[4]))
            p = os.path.join(customer_dir(parts[3]), name)
            if not os.path.isfile(p):
                return self.send(404, "Nicht gefunden", "text/plain; charset=utf-8")
            with open(p, "rb") as f:
                data = f.read()
            disp = "attachment; filename*=UTF-8''" + urllib.parse.quote(name)
            return self.send(200, data, "application/octet-stream", {"Content-Disposition": disp})
        return self.send(404, "Nicht gefunden", "text/plain; charset=utf-8")

    do_HEAD = do_GET

    def do_PUT(self):
        path = urllib.parse.urlparse(self.path)
        parts = path.path.split("/")
        if len(parts) != 4 or parts[1] != "hochladen" or parts[2] != "api":
            return self.send(404, "Nicht gefunden", "text/plain; charset=utf-8")
        token = parts[3]
        c = self.valid_customer(token)
        if not c:
            return self.send(403, "Link ungültig oder abgelaufen", "text/plain; charset=utf-8")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return self.send(400, "Leere Datei", "text/plain; charset=utf-8")
        if length > MAX_FILE:
            return self.send(413, "Datei zu groß (max. 25 MB)", "text/plain; charset=utf-8")
        name = urllib.parse.parse_qs(path.query).get("name", ["datei"])[0]
        stem, ext = safe_name(name)
        if ext not in ALLOWED_EXT:
            return self.send(415, "Nur PDF oder Fotos erlaubt", "text/plain; charset=utf-8")
        d = customer_dir(token)
        with LOCK:
            os.makedirs(d, mode=0o700, exist_ok=True)
            if len(list_files(token)) >= MAX_FILES:
                return self.send(429, "Zu viele Dateien – bitte melden Sie sich bei uns", "text/plain; charset=utf-8")
            final = os.path.join(d, stem + ext)
            i = 2
            while os.path.exists(final):
                final = os.path.join(d, f"{stem} ({i}){ext}")
                i += 1
            tmp = final + ".part"
            open(tmp, "wb").close()
        remaining = length
        with open(tmp, "wb") as f:
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        if remaining:
            os.remove(tmp)
            return self.send(400, "Übertragung abgebrochen", "text/plain; charset=utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, final)
        return self.send(201, "OK", "text/plain; charset=utf-8")

    def anfrage(self):
        length = min(int(self.headers.get("Content-Length", "0") or 0), 20000)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        g = lambda k, n: (form.get(k, [""])[0]).strip()[:n]
        if g("website", 50):                       # Falle fuer Spam-Programme: so tun, als ob alles gut ging
            return self.send(303, "", extra={"Location": "/danke.html"})
        name, email, jahr, nachricht = g("name", 100), g("email", 150), g("jahr", 10), g("nachricht", 2000)
        try:
            we = max(1, min(200, int(g("wohnungen", 5))))
        except ValueError:
            we = 0
        if not name or not EMAIL_RE.match(email) or not we:
            return self.send(400, page("Bitte prüfen", "<div class='card'><h1>Da fehlt noch etwas</h1><p>Bitte geben Sie "
                             "Ihren Namen, eine gültige E-Mail-Adresse und die Anzahl der Wohnungen an.</p>"
                             "<p><a class='btn' href='/#kontakt'>Zurück zum Formular</a></p></div>"))
        now = time.time()
        with LOCK:
            while RECENT and RECENT[0] < now - 3600:
                RECENT.popleft()
            if len(RECENT) >= 30:
                return self.send(429, page("Später erneut", "<div class='card'><h1>Gerade sehr viele Anfragen</h1>"
                                 f"<p>Bitte schreiben Sie uns direkt an {MAIL_ADDR}.</p></div>"))
            RECENT.append(now)
            a = {"id": secrets.token_hex(8), "zeit": now, "name": name, "email": email, "wohnungen": we,
                 "jahr": jahr or "?", "nachricht": nachricht, "mail": False}
            lst = load_anfragen()
            lst.append(a)
            save_anfragen(lst)
        threading.Thread(target=mail_and_mark, args=(a,), daemon=True).start()
        return self.send(303, "", extra={"Location": "/danke.html"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/anfrage":
            return self.anfrage()
        if not path.startswith("/verwaltung/"):
            return self.send(404, "Nicht gefunden", "text/plain; charset=utf-8")
        length = min(int(self.headers.get("Content-Length", "0") or 0), 10000)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        with LOCK:
            db = load()
            if path == "/verwaltung/neu":
                name = (form.get("name", [""])[0]).strip()[:100]
                try:
                    days = max(1, min(365, int(form.get("tage", ["30"])[0])))
                except ValueError:
                    days = 30
                if not name:
                    return self.send(400, admin_page(db, base=self.base_url()))
                token = secrets.token_urlsafe(24)
                now = time.time()
                db[token] = {"name": name, "created": now, "expires": now + days * 86400}
                save(db)
                msg = f"Link für „{html.escape(name)}“ angelegt – unten kopieren und dem Kunden schicken."
            elif path == "/verwaltung/loeschen":
                token = form.get("token", [""])[0]
                if TOKEN_RE.match(token) and token in db and form.get("ok"):
                    name = db.pop(token)["name"]
                    save(db)
                    shutil.rmtree(customer_dir(token), ignore_errors=True)
                    msg = f"„{html.escape(name)}“ und alle Dateien gelöscht."
                else:
                    msg = "Nichts gelöscht (bitte Häkchen „sicher“ setzen)."
            elif path in ("/verwaltung/fertig", "/verwaltung/offen"):
                token = form.get("token", [""])[0]
                if TOKEN_RE.match(token) and token in db:
                    c = db[token]
                    if path.endswith("fertig"):
                        c["done"] = time.time()
                        msg = (f"„{html.escape(c['name'])}“ abgeschlossen. Automatische Löschung am "
                               f"{datetime.fromtimestamp(delete_at(c)):%d.%m.%Y}.")
                    else:
                        c.pop("done", None)
                        c["expires"] = max(c["expires"], time.time() + 14 * 86400)
                        msg = f"„{html.escape(c['name'])}“ wieder geöffnet (Link mind. 14 Tage gültig)."
                    save(db)
                else:
                    msg = "Kunde nicht gefunden."
            else:
                return self.send(404, "Nicht gefunden", "text/plain; charset=utf-8")
        self.send(200, admin_page(load(), msg, base=self.base_url()))


def main():
    os.makedirs(os.path.join(DATA_DIR, "kunden"), mode=0o700, exist_ok=True)
    threading.Thread(target=cleanup_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"Abrechnungs-Navi Upload läuft auf 127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()


# BEGIN GENERATED WORKFLOW - source: app/workflow.py
"""Auftragsablauf: Freigaben, geschuetzter Abruf, feste Loeschfristen.

Keine KI, keine Zahlungsausloesung, kein automatischer Kundenmailversand.
Bestehende Altdaten bleiben bis zu ihrer bisherigen Frist erhalten.
"""
import base64
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import time
import urllib.parse

DAY = 86400
VERSION = '4-2026-11-03'


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt + ':' + digest


def password_ok(password, stored):
    try:
        return hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored)
    except (ValueError, TypeError):
        return False


def totp(secret, now=None):
    key = base64.b32decode(secret.strip().upper() + '=' * ((-len(secret.strip())) % 8))
    digest = hmac.new(key, struct.pack('>Q', int(now or time.time()) // 30), hashlib.sha1).digest()
    start = digest[-1] & 15
    return f'{(struct.unpack(">I", digest[start:start+4])[0] & 0x7fffffff) % 1000000:06d}'


def allowed_file(name, data):
    """Prueft Dateiinhalte; PDF-Aktionen und eingebettete Dateien sind gesperrt."""
    from pypdf import PdfReader
    from PIL import Image
    ext = Path(name).suffix.lower()
    if ext == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise ValueError('Kein gueltiges PDF')
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ValueError('Bitte ein unverschluesseltes Beleg-PDF hochladen')
        if len(reader.pages) > 500:
            raise ValueError('PDF hat mehr als 500 Seiten')
        # Auch indirekte/komprimierte Objekte pruefen, statt nur nach Rohtext zu suchen.
        forbidden = {'/JS', '/JavaScript', '/OpenAction', '/AA', '/Launch', '/EmbeddedFiles',
                     '/RichMedia', '/XFA', '/SubmitForm', '/ImportData', '/GoToR', '/URI'}
        visited = set()
        def walk(obj, depth=0):
            if depth > 100:
                raise ValueError('PDF-Struktur zu komplex')
            if hasattr(obj, 'get_object'):
                obj = obj.get_object()
            marker = id(obj)
            if marker in visited:
                return
            visited.add(marker)
            if isinstance(obj, dict):
                if forbidden.intersection(map(str, obj)):
                    raise ValueError('PDF enthaelt aktive Inhalte, Links oder eingebettete Dateien')
                for v in obj.values():
                    walk(v, depth+1)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    walk(v, depth+1)
        walk(reader.trailer)
        return
    formats = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP'}
    if ext not in formats:
        raise ValueError('Bitte PDF, JPG, PNG oder WEBP verwenden; HEIC vorher als JPG exportieren')
    Image.MAX_IMAGE_PIXELS = 40_000_000
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != formats[ext]:
                raise ValueError('Dateiinhalt passt nicht zur Endung')
            if image.width * image.height > 40_000_000:
                raise ValueError('Bild zu gross')
            image.verify()
    except Exception as exc:
        raise ValueError('Bild ungueltig oder zu gross') from exc


def install(app):
    """Erweitert den bestehenden, nur an localhost gebundenen Server."""
    old_cleanup, old_delete, old_admin, OldH = app.cleanup, app.delete_at, app.admin_page, app.H
    from datetime import datetime
    from zoneinfo import ZoneInfo
    class BerlinDateTime(datetime):
        @classmethod
        def fromtimestamp(cls, value, tz=None):
            return super().fromtimestamp(value, tz or ZoneInfo('Europe/Berlin'))
        @classmethod
        def now(cls, tz=None):
            return super().now(tz or ZoneInfo('Europe/Berlin'))
    app.datetime = BerlinDateTime
    app.LOCK = __import__('threading').RLock()
    app.ALLOWED_EXT = {'.pdf', '.jpg', '.jpeg', '.png', '.webp'}
    sessions, attempts, pending_enrollment = {}, {}, {}
    cfg_path = os.environ.get('AN_OPERATOR_FILE', '/etc/an-upload/operator.json')
    otp_path = os.environ.get('AN_TOTP_FILE') or ('/etc/an-upload/totp.secret' if Path('/etc/an-upload/totp.secret').exists() else str(Path(app.DATA_DIR)/'security/totp.secret'))
    backup_marker = os.environ.get('AN_BACKUP_MARKER', '/etc/an-upload/backup-last-success')
    audit_path = Path(app.DATA_DIR) / 'audit.jsonl'
    withdrawal_path = Path(app.DATA_DIR) / 'widerrufe.json'

    def config():
        try:
            return json.loads(Path(cfg_path).read_text())
        except (OSError, ValueError):
            return {}

    def readiness():
        cfg = config()
        required = ['provider_annex_complete', 'disk_encryption_verified',
                    'provider_mfa_verified', 'restore_tested_at', 'backup_location',
                    'backup_retention_days', 'backup_tested_at', 'avv_sha256']
        missing = [k for k in required if not cfg.get(k)]
        for k in ('restore_tested_at', 'backup_tested_at'):
            try:
                if time.time() - float(cfg.get(k, 0)) > 183 * DAY:
                    missing.append(k + '_expired')
            except (ValueError, TypeError):
                missing.append(k + '_invalid')
        if not Path(otp_path).is_file():
            missing.append('admin_second_factor')
        try:
            if time.time()-float(Path(backup_marker).read_text()) > 26*3600:
                missing.append('backup_stale')
        except (OSError, ValueError):
            missing.append('backup_missing')
        return sorted(set(missing))

    def audit(event, order='', **extra):
        # Keine Namen, Links, IP-Adressen, Beleginhalte oder Zugangsdaten.
        row = {'time': time.time(), 'event': event, 'order': order, **extra}
        with app.LOCK:
            with audit_path.open('a') as f:
                f.write(json.dumps(row) + '\n')

    def delete_at(c):
        if c.get('workflow') != VERSION:
            return old_delete(c)
        return c.get('delete_at') or c['expires'] + 30 * DAY
    app.delete_at = delete_at

    def cleanup():
        with app.LOCK:
            db = app.load()
            for token, c in list(db.items()):
                if delete_at(c) > time.time():
                    continue
                root = Path(app.customer_dir(token))
                try:
                    if root.exists():
                        shutil.rmtree(root)  # Fehler nicht als erfolgreiche Loeschung verschlucken.
                    audit('server_deleted', c.get('order','legacy'))
                    del db[token]
                except OSError:
                    audit('deletion_failed', c.get('order','legacy'))
            app.save(db)
            rows=app.load_anfragen()
            app.save_anfragen([a for a in rows if a['zeit']+183*DAY>time.time()])
            if withdrawal_path.exists():
                rows=json.loads(withdrawal_path.read_text())
                temp=withdrawal_path.with_suffix('.tmp')
                temp.write_text(json.dumps([r for r in rows if r['time']+183*DAY>time.time()]))
                os.replace(temp,withdrawal_path)
            if audit_path.exists():
                rows = [json.loads(line) for line in audit_path.read_text().splitlines() if line]
                rows = [r for r in rows if r['time'] > time.time() - 183 * DAY]
                temp = audit_path.with_suffix('.tmp')
                temp.write_text(''.join(json.dumps(r) + '\n' for r in rows))
                os.replace(temp, audit_path)
    app.cleanup = cleanup

    def form(action, fields, label):
        return f'<form method="post" action="{action}">{fields}<button class="btn">{label}</button></form>'

    def admin_page(db, msg='', base=''):
        esc = app.html.escape
        warning = ', '.join(readiness())
        top = f'<div class="card"><h1>Auftragsfreigaben</h1><p>{esc(msg)}</p>'
        top += ('<p class="err">Neue Auftraege gesperrt. Betreiberpruefung offen: ' + esc(warning) + '</p>'
                if warning else '<p class="ok">Betreiberfreigabe dokumentiert.</p>')
        fields = '<label>Kundenname<input name="name" required maxlength="100"></label>'
        fields += '<label>Angebotsnummer<input name="order" required maxlength="80"></label>'
        fields += '<label>Vertrag geschlossen am (deutsche Ortszeit)<input name="contract_at" type="datetime-local" required></label>'
        for key, label in [('avv','Vollstaendiger AV-Vertrag mit Anlagen beiderseits nachweisbar geschlossen'),
                           ('paid','Zahlung im Mollie-Konto bestaetigt (nicht nur Rueckleitungsseite)'),
                           ('early','Ausdrueckliches Verlangen nach vorzeitigem Beginn und Kenntnisbestaetigung liegen vor')]:
            fields += f'<label><input type="checkbox" name="{key}" value="yes"> {label}</label>'
        fields += '<label>Nachweisreferenz (keine Mieterdaten)<input name="evidence" required maxlength="120"></label>'
        top += form('/verwaltung/neu', fields, 'Auftrag freigeben') + '</div>'
        for token, c in db.items():
            if c.get('workflow') != VERSION:
                top += '<div class="card"><h2>Bestandsauftrag</h2><p>' + esc(c['name']) + '</p><p>Keine automatische Umstellung der bisherigen Frist. Migration erst nach dokumentierter Kundenabstimmung.</p></div>'
                continue
            hidden = f'<input type="hidden" name="token" value="{token}">'
            link = f'{base}/hochladen/{token}'
            top += f'<div class="card"><h2>{esc(c["name"])}</h2><p>Auftrag {esc(c["order"])} | Loeschung: {app.datetime.fromtimestamp(delete_at(c)):%d.%m.%Y %H:%M}</p><code>{esc(link)}</code>'
            top += '<p>Zugangscode wird getrennt uebermittelt. Kein Versand von Belegen per E-Mail. Keine KI.</p>'
            top += '<ul>' + ''.join(f'<li><a href="/verwaltung/datei/{token}/{urllib.parse.quote(n)}">{esc(n)}</a></li>' for n, _, _ in app.list_files(token)) + '</ul>'
            top += f'<form method="post" action="/verwaltung/ergebnis/{token}" enctype="application/pdf"><p>Ergebnisbereitstellung ueber den Dateiwaehler:</p></form>'
            top += f'<input type="file" class="result" data-token="{token}" accept="application/pdf"><p>Erst nach menschlicher Pruefung freigeben.</p>'
            top += form('/verwaltung/fertig', hidden + '<label><input name="reviewed" type="checkbox" required value="yes"> Inhalt und Zahlen menschlich geprueft</label><label><input name="notice" type="checkbox" required value="yes"> Kunde ueber Bereitstellung und konkreten Loeschtermin informiert</label>', 'Ergebnis bereitstellen')
            top += form('/verwaltung/code', hidden, 'Zugangscode erneuern')
            top += '</div>'
        top += '''<script>document.querySelectorAll('.result').forEach(e=>e.onchange=async()=>{if(!e.files[0])return;let r=await fetch('/verwaltung/ergebnis/'+e.dataset.token,{method:'PUT',body:e.files[0]});alert(await r.text());if(r.ok)location.reload();});</script>'''
        # Anfragen bleiben sichtbar; die alten Kundenaktionen werden nicht erneut eingeblendet.
        anfr = app.load_anfragen()
        top += '<div class="card"><h2>Formularanfragen</h2>'
        top += ''.join(f'<p>{esc(a["name"])} | {esc(a["email"])} | {esc(a["nachricht"])} | Mail: {bool(a.get("mail"))}</p>' for a in anfr[-50:]) + '</div>'
        if withdrawal_path.exists():
            top += '<div class="card"><h2>Eingegangene Widerrufe</h2>'
            top += ''.join(f'<p>{esc(r["name"])} | {esc(r["vertrag"])} | {esc(r["id"])} | Mailquittung: {bool(r.get("mail"))}</p>' for r in json.loads(withdrawal_path.read_text())) + '</div>'
        return app.page('Verwaltung',top)
    app.admin_page = admin_page

    class H(OldH):
        def log_message(self, fmt, *args):
            pass  # Auch gekuerzte Pfade koennen Zugangstoken verraten.

        def send(self, code, body, ctype='text/html; charset=utf-8', extra=None):
            headers = {'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'}
            headers.update(extra or {})
            return super().send(code, body, ctype, headers)

        def base_url(self):
            return 'https://abrechnungs-navi.de'

        def session(self, role, token=''):
            cookie = self.headers.get('Cookie', '')
            match = re.search(r'(?:^|;\s*)an_session=([A-Za-z0-9_-]+)', cookie)
            data = sessions.get(match.group(1)) if match else None
            if data and data['until'] > time.time() and data['role'] == role and data['token'] == token:
                return data
            return None

        def set_session(self, role, token=''):
            key = secrets.token_urlsafe(32)
            sessions[key] = {'role': role, 'token': token, 'until': time.time()+1800,
                             'csrf': secrets.token_urlsafe(24)}
            return {'Set-Cookie': f'an_session={key}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=1800'}

        def origin_ok(self):
            origin = self.headers.get('Origin')
            return origin == 'https://abrechnungs-navi.de' or (os.environ.get('AN_TESTING') == '1' and origin == 'http://127.0.0.1')

        def body(self, maximum=20000):
            try:
                n = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise ValueError('Ungueltige Groesse')
            if n < 1 or n > maximum:
                raise ValueError('Anfrage zu gross oder leer')
            data = self.rfile.read(n)
            if len(data) != n:
                raise ValueError('Uebertragung unvollstaendig')
            return data

        def admin_auth(self):
            if not self.session('admin'):
                body = '<div class="card"><h1>Zweiter Anmeldefaktor</h1>'
                if not Path(otp_path).exists():
                    import qrcode
                    if not pending_enrollment or time.time()-pending_enrollment['time']>600:
                        pending_enrollment.update(secret=base64.b32encode(secrets.token_bytes(20)).decode().rstrip('='),time=time.time())
                    uri='otpauth://totp/Abrechnungs-Navi:volker?secret='+pending_enrollment['secret']+'&issuer=Abrechnungs-Navi'
                    picture=io.BytesIO();qrcode.make(uri).save(picture,format='PNG')
                    encoded=base64.b64encode(picture.getvalue()).decode()
                    body += '<p>Einmalige Einrichtung: Scannen Sie den QR-Code mit Ihrer Authenticator-App und tragen Sie den aktuellen sechsstelligen Code ein. Den QR-Code vertraulich behandeln.</p>'
                    body += '<img alt="QR-Code fuer Ihre Authenticator-App" width="260" height="260" src="data:image/png;base64,'+encoded+'">'
                    body += form('/verwaltung/einrichtung','<label>Aktueller Code aus der Authenticator-App<input name="otp" inputmode="numeric" required autocomplete="one-time-code"></label>','Zweiten Faktor aktivieren')
                else:
                    body += form('/verwaltung/anmelden','<label>Code aus der Authenticator-App<input name="otp" inputmode="numeric" required autocomplete="one-time-code"></label>','Anmelden')
                self.send(401, app.page('Anmeldung', body+'</div>'))
                return False
            return True

        def customer(self, token):
            if not app.TOKEN_RE.fullmatch(token):
                return None
            c = app.load().get(token)
            if not c or c.get('workflow') != VERSION or delete_at(c) <= time.time():
                return None
            if not c.get('done') and c['expires'] <= time.time():
                return None
            return c

        def valid_customer(self, token):
            c = self.customer(token)
            return c if c and not c.get('done') and not readiness() and self.session('customer', token) else None

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path
            if path == '/systemstatus':
                return self.send(200,json.dumps({'version':VERSION,'uploads_freigegeben':not bool(readiness())}),'application/json')
            if path == '/verwaltung' or path.startswith('/verwaltung/'):
                if not self.admin_auth():
                    return
                return super().do_GET()
            if path.startswith('/hochladen/'):
                parts = path.strip('/').split('/')
                token = parts[1] if len(parts) >= 2 else ''
                c = self.customer(token)
                if not c:
                    return self.send(404, app.page('Link nicht verfuegbar','<h1>Link ungueltig oder abgelaufen</h1><p>Bitte wenden Sie sich an kontakt@abrechnungs-navi.de.</p>'))
                if not self.session('customer', token):
                    return self.send(200, app.page('Zugangscode', '<div class="card"><h1>Geschuetzter Kundenbereich</h1>'+form(f'/hochladen/{token}/anmelden','<label>Separat erhaltener Zugangscode<input name="code" type="password" required autocomplete="off"></label>','Oeffnen')+'</div>'))
                if len(parts) == 4 and parts[2] == 'datei':
                    name = urllib.parse.unquote(parts[3])
                    if Path(name).name != name or name.startswith('.') or name.endswith('.part') or name == 'ergebnis-entwurf.pdf':
                        return self.send(404, 'Nicht gefunden')
                    if name == 'ergebnis.pdf' and not c.get('done'):
                        return self.send(404, 'Noch nicht freigegeben')
                    f = Path(app.customer_dir(token))/name
                    if not f.is_file():
                        return self.send(404, 'Nicht gefunden')
                    audit('download', c['order'])
                    return self.send(200,f.read_bytes(),'application/octet-stream',{'Content-Disposition': "attachment; filename*=UTF-8''"+urllib.parse.quote(name)})
                if len(parts) != 2:
                    return self.send(404,'Nicht gefunden')
                if not c.get('done') and readiness():
                    return self.send(503,app.page('Annahme pausiert','<h1>Upload voruebergehend pausiert</h1><p>Der Anbieter schliesst die Betriebspruefung ab. Bitte noch keine Unterlagen senden.</p>'))
                if c.get('done'):
                    until = app.datetime.fromtimestamp(delete_at(c)).strftime('%d.%m.%Y %H:%M')
                    links = ''.join(f'<li><a href="/hochladen/{token}/datei/{urllib.parse.quote(n)}">{app.html.escape(n)}</a></li>' for n,_,_ in app.list_files(token) if not n.startswith('.') and not n.endswith('.part') and n!='ergebnis-entwurf.pdf')
                    return self.send(200,app.page('Abrechnung herunterladen',f'<div class="card"><h1>Ihre Abrechnung und Unterlagen</h1><p>Bitte bis {until} herunterladen. Danach werden die aktiven Daten geloescht. Vertraglich vereinbarte Sicherungsrestfristen bleiben unberuehrt.</p><ul>{links}</ul></div>'))
                body = app.upload_page(token,c).replace('Die Dateien sehen nur wir – Sie selbst sehen hier nur die Dateinamen.','Waerend der Bearbeitung sehen Sie die Dateinamen. Nach Freigabe koennen Sie die Abrechnung und Ihre Unterlagen herunterladen. Bitte entfernen Sie unnoetige Kontodaten, Unterschriften und sensible Angaben.')
                body = body.replace('.heic,.heif,','').replace('image/*,','')
                body = body.replace('auf einem Server in Deutschland gespeichert','am im AV-Vertrag festgelegten Serverstandort gespeichert')
                return self.send(200,body)
            return super().do_GET()
        do_HEAD = do_GET

        def do_PUT(self):
            if not self.origin_ok():
                return self.send(403,'Ungueltiger Ursprung')
            path = urllib.parse.urlsplit(self.path)
            is_result = path.path.startswith('/verwaltung/ergebnis/')
            token = path.path.split('/')[-1]
            if is_result:
                if not self.admin_auth():
                    return
                c = self.customer(token)
            else:
                if not path.path.startswith('/hochladen/api/'):
                    return self.send(404,'Nicht gefunden')
                c = self.valid_customer(token)
            if not c or (c.get('done') and not is_result):
                return self.send(403,'Upload geschlossen oder nicht freigegeben')
            try:
                data = self.body(app.MAX_FILE)
                rawname = 'ergebnis.pdf' if is_result else urllib.parse.parse_qs(path.query).get('name',['datei'])[0]
                stem, ext = app.safe_name(rawname)
                if not is_result and stem.lower().startswith('ergebnis'):
                    raise ValueError('Dieser Dateiname ist reserviert')
                allowed_file(stem+ext,data)
            except Exception as exc:
                audit('upload_rejected',c['order'])
                return self.send(400,'Datei abgelehnt: '+str(exc)[:150],'text/plain; charset=utf-8')
            with app.LOCK:
                # Nach dem Einlesen erneut pruefen: keine Auferstehung nach Loeschung/Freigabe.
                current = app.load().get(token)
                if not current or (current.get('done') and not is_result) or delete_at(current) <= time.time():
                    return self.send(403,'Upload geschlossen')
                if is_result and current.get('done'):
                    # Korrekturen zuerst als Entwurf, nie ungeprueft publizieren.
                    name='ergebnis-entwurf.pdf'
                    temp=Path(app.customer_dir(token))/('.'+secrets.token_hex(12)+'.part')
                    temp.write_bytes(data);os.chmod(temp,0o600)
                    os.replace(temp,Path(app.customer_dir(token))/name)
                    audit('correction_draft',c['order'])
                    return self.send(201,'Korrektur als Entwurf gespeichert. Nach Pruefung separat freigeben.','text/plain; charset=utf-8')
                folder = Path(app.customer_dir(token));folder.mkdir(mode=0o700,parents=True,exist_ok=True)
                if not is_result and len(app.list_files(token)) >= app.MAX_FILES:
                    return self.send(429,'Dateilimit erreicht')
                name = stem+ext
                if not is_result:
                    i=2
                    while (folder/name).exists():
                        name=f'{stem} ({i}){ext}';i+=1
                temp = folder/('.'+secrets.token_hex(12)+'.part')
                with temp.open('xb') as stream:
                    stream.write(data);stream.flush();os.fsync(stream.fileno())
                os.chmod(temp,0o600);os.replace(temp,folder/name)
                audit('result_uploaded' if is_result else 'upload',c['order'])
            return self.send(201,'Datei gespeichert','text/plain; charset=utf-8')

        def do_POST(self):
            path = urllib.parse.urlsplit(self.path).path
            if not self.origin_ok():
                return self.send(403,'Ungueltiger Ursprung')
            if path == '/anfrage':
                try:
                    n=int(self.headers.get('Content-Length','0'))
                    if not 0<n<=20000:return self.send(400,'Ungueltige Anfragegroesse')
                    return super().do_POST()
                except ValueError:return self.send(400,'Ungueltige Eingabe')
            try:
                data = urllib.parse.parse_qs(self.body().decode('utf-8'))
            except (ValueError, UnicodeError):
                return self.send(400,'Ungueltige Eingabe')
            g=lambda key:data.get(key,[''])[0].strip()
            if path == '/verwaltung/einrichtung':
                now=time.time()
                recent=[t for t in attempts.get('enrollment',[]) if t>now-900]
                if len(recent)>=5:return self.send(429,'Bitte 15 Minuten warten')
                if Path(otp_path).exists():return self.send(409,'Zweiter Faktor bereits eingerichtet')
                if not pending_enrollment or now-pending_enrollment['time']>600:
                    return self.send(400,'Einrichtung abgelaufen; Verwaltung erneut oeffnen')
                if not any(hmac.compare_digest(g('otp'),totp(pending_enrollment['secret'],now+offset)) for offset in (-30,0,30)):
                    attempts['enrollment']=recent+[now];return self.send(403,'Code ungueltig')
                with app.LOCK:
                    location=Path(otp_path);location.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                    try:
                        fd=os.open(location,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    except FileExistsError:return self.send(409,'Bereits eingerichtet')
                    with os.fdopen(fd,'w') as stream:stream.write(pending_enrollment['secret'])
                    pending_enrollment.clear()
                audit('admin_mfa_enrolled')
                return self.send(303,'',extra={'Location':'/verwaltung',**self.set_session('admin')})
            if path in ('/widerruf','/widerruf/pruefen'):
                if g('website'):
                    return self.send(200,'Eingang erfasst')
                if not g('name') or not app.EMAIL_RE.fullmatch(g('email')) or not g('vertrag'):
                    return self.send(400,'Bitte Name, E-Mail, Vertragsangabe und Bestaetigung ausfuellen')
                if path.endswith('/pruefen'):
                    fields=''.join(f'<input type="hidden" name="{key}" value="{app.html.escape(g(key),quote=True)}">' for key in ('name','email','vertrag'))
                    fields+='<input type="hidden" name="confirm" value="yes">'
                    review=f'<h1>Widerruf pruefen</h1><p>Name: {app.html.escape(g("name"))}<br>Vertrag: {app.html.escape(g("vertrag"))}<br>Eingangsbestaetigung an: {app.html.escape(g("email"))}</p>'
                    return self.send(200,app.page('Widerruf bestaetigen',review+form('/widerruf',fields,'Widerruf bestaetigen')))
                if g('confirm') != 'yes':return self.send(400,'Bestaetigung fehlt')
                # Vor der Uebermittlungsmail dauerhaft speichern; keine automatische Verweigerung.
                row={'id':secrets.token_hex(10),'time':time.time(),'name':g('name')[:100],
                     'email':g('email')[:150],'vertrag':g('vertrag')[:300]}
                with app.LOCK:
                    rows=json.loads(withdrawal_path.read_text()) if withdrawal_path.exists() else []
                    if sum(r['time'] > time.time()-3600 for r in rows)>=30:
                        return self.send(429,'Bitte Widerruf per E-Mail an kontakt@abrechnungs-navi.de senden.')
                    rows.append(row);tmp=withdrawal_path.with_suffix('.tmp');tmp.write_text(json.dumps(rows));os.replace(tmp,withdrawal_path)
                # E-Mail-Quittung ist ein externer Vorgang: Versand nur bei expliziter Betreiberfreigabe.
                confirmed=app.send_withdrawal_confirmation(row)
                row['mail']=confirmed
                with app.LOCK:
                    rows=json.loads(withdrawal_path.read_text())
                    for entry in rows:
                        if entry['id']==row['id']:entry['mail']=confirmed
                    tmp=withdrawal_path.with_suffix('.tmp');tmp.write_text(json.dumps(rows));os.replace(tmp,withdrawal_path)
                return self.send(200,app.page('Widerruf eingegangen',f'<h1>Ihr Widerruf ist eingegangen</h1><p>Eingangsnummer {row["id"]}. '+('Eine Eingangsbestaetigung wurde per E-Mail versandt.' if confirmed else 'Die E-Mail-Bestaetigung konnte noch nicht versandt werden. Bitte speichern Sie diese Seite; bei Bedarf schreiben Sie an kontakt@abrechnungs-navi.de.')+'</p>'))
            if path == '/verwaltung/anmelden':
                now=time.time();key='admin'
                recent=[t for t in attempts.get(key,[]) if t>now-900]
                if len(recent)>=5:return self.send(429,'Bitte 15 Minuten warten')
                try:
                    secret=Path(otp_path).read_text().strip()
                    valid=any(hmac.compare_digest(g('otp'),totp(secret,now+offset)) for offset in (-30,0,30))
                except (OSError,ValueError):valid=False
                if not valid:
                    attempts[key]=recent+[now];return self.send(403,'Code ungueltig')
                # TOTP nicht innerhalb desselben Zeitfensters wiederverwendbar.
                if attempts.get('used_otp')==g('otp'):return self.send(403,'Code bereits verwendet')
                attempts['used_otp']=g('otp');attempts[key]=[]
                return self.send(303,'',extra={'Location':'/verwaltung',**self.set_session('admin')})
            match=re.fullmatch(r'/hochladen/([A-Za-z0-9_-]+)/anmelden',path)
            if match:
                token=match.group(1);c=self.customer(token);now=time.time()
                recent=[t for t in attempts.get(token,[]) if t>now-900]
                if len(recent)>=5:return self.send(429,'Bitte 15 Minuten warten')
                if not c or not password_ok(g('code'),c.get('access_hash','')):
                    attempts[token]=recent+[now];return self.send(403,'Zugang nicht moeglich')
                attempts[token]=[]
                return self.send(303,'',extra={'Location':'/hochladen/'+token,**self.set_session('customer',token)})
            if not path.startswith('/verwaltung/'):
                return self.send(404,'Nicht gefunden')
            if not self.admin_auth():return
            with app.LOCK:
                db=app.load();token=g('token');c=db.get(token);message=''
                if path == '/verwaltung/neu':
                    if readiness():return self.send(503,'Betreiberfreigabe fehlt: '+', '.join(readiness()))
                    try:
                        value=g('contract_at')
                        if 'T' in value:
                            from datetime import datetime
                            from zoneinfo import ZoneInfo
                            contract_at=datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Europe/Berlin')).timestamp()
                        else:contract_at=float(value)
                    except ValueError:return self.send(400,'Vertragsdatum fehlt')
                    if contract_at>time.time() or contract_at<time.time()-366*DAY:return self.send(400,'Vertragsdatum pruefen')
                    if not g('name') or not g('order') or not g('evidence') or g('avv')!='yes' or g('paid')!='yes':
                        return self.send(400,'Auftrag, AV-Vertrag, Nachweis und Zahlung muessen bestaetigt sein')
                    if g('early')!='yes' and time.time()<contract_at+14*DAY:
                        return self.send(409,'Ohne vorzeitigen Leistungsbeginn erst nach Ablauf der 14 Tage freigeben')
                    token=secrets.token_urlsafe(24);code=secrets.token_urlsafe(12);now=time.time()
                    db[token]={'workflow':VERSION,'name':g('name')[:100],'order':g('order')[:80],
                        'created':now,'expires':now+30*DAY,'access_hash':password_hash(code),
                        'contract_at':contract_at,'early':g('early')=='yes','avv':config()['avv_sha256'],
                        'evidence':g('evidence')[:120],'ai':False}
                    app.save(db);audit('order_released',db[token]['order'])
                    message='Zugangscode (nur jetzt sichtbar; getrennt vom Link uebermitteln): '+code
                elif path=='/verwaltung/fertig' and c and c.get('workflow')==VERSION:
                    if c.get('done'):
                        draft=Path(app.customer_dir(token))/'ergebnis-entwurf.pdf'
                        if not draft.exists():return self.send(409,'Bereits bereitgestellt; Loeschtermin bleibt unveraendert')
                        if g('reviewed')!='yes' or g('notice')!='yes':return self.send(400,'Pruefung und Kundeninformation bestaetigen')
                        os.replace(draft,Path(app.customer_dir(token))/'ergebnis.pdf')
                        audit('correction_released',c['order'])
                        return self.send(200,app.admin_page(db,'Korrektur bereitgestellt. Bisheriger Loeschtermin bleibt fest.',self.base_url()))
                    if g('reviewed')!='yes' or g('notice')!='yes' or not (Path(app.customer_dir(token))/'ergebnis.pdf').is_file():
                        return self.send(400,'Ergebnis, menschliche Freigabe und Kundeninformation fehlen')
                    now=time.time();c['done']=now;c['delete_at']=now+30*DAY
                    app.save(db);audit('result_released',c['order']);message='Bereitgestellt. Loeschtermin ist fest.'
                elif path=='/verwaltung/code' and c and c.get('workflow')==VERSION:
                    code=secrets.token_urlsafe(12);c['access_hash']=password_hash(code);app.save(db)
                    for key in list(sessions):
                        if sessions[key]['token']==token:del sessions[key]
                    audit('access_rotated',c['order']);message='Neuer Zugangscode (getrennt uebermitteln): '+code
                else:return self.send(400,'Aktion nicht verfuegbar; Bestandsdaten bleiben unveraendert')
            return self.send(200,app.admin_page(app.load(),message,base=self.base_url()))
    app.H=H
    app.readiness=readiness
    app.workflow_audit=audit


# END GENERATED WORKFLOW

if __name__ == "__main__":
    # Erster Lauf ueber den alten Updater: eigenstaendig und ohne Zusatzimporte startbar.
    # Nach Installation der isolierten Pakete verwendet derselbe Dienst automatisch die venv.
    runtime = "/srv/an-upload/venv/bin/python"
    if os.path.isfile(runtime) and sys.prefix != "/srv/an-upload/venv":
        os.execv(runtime, [runtime, os.path.abspath(__file__)])
    install(sys.modules[__name__])
    main()

