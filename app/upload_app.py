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


if __name__ == "__main__":
    main()
