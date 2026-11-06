#!/usr/bin/env bash
# Richtet abrechnungs-navi.de auf diesem Server ein bzw. aktualisiert alles.
# Kann beliebig oft ausgefuehrt werden. Bestehende Seiten (AnspruchsKompass) bleiben unveraendert.
set -euo pipefail

SITE_DIR=/var/www/abrechnungs-navi
APP_DIR=/srv/an-upload/app
DATA_DIR=/srv/an-upload/data
CADDYFILE=/etc/caddy/Caddyfile
SNIPPET=/etc/caddy/abrechnungs-navi.caddy
AUTH=/etc/caddy/an-admin-auth.caddy
VERSION_FILE=/srv/an-upload/.version
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Automatischer Lauf: nur weitermachen, wenn es auf GitHub etwas Neues gibt
if [ "${1:-}" = "--auto" ]; then
  NEW=$(curl -fsS https://api.github.com/repos/Vauplus69/abrechnungs-navi/commits/main | python3 -c 'import sys,json;print(json.load(sys.stdin)["sha"])' 2>/dev/null || true)
  [ -n "$NEW" ] || exit 0
  if [ "$NEW" = "$(cat "$VERSION_FILE" 2>/dev/null)" ] && [ -x /srv/an-upload/venv/bin/python ] && [ -f "$APP_DIR/workflow.py" ] && [ -x /usr/local/bin/an-betriebsfreigabe ] && [ -f /etc/systemd/system/an-monitor.timer ] && [ -f "$APP_DIR/monitor.py" ] && [ -f "$APP_DIR/invoicing.py" ]; then exit 0; fi
  echo "Neue Fassung $NEW gefunden"
fi
NEW_SHA=$(curl -fsS https://api.github.com/repos/Vauplus69/abrechnungs-navi/commits/main | python3 -c 'import sys,json;print(json.load(sys.stdin)["sha"])' 2>/dev/null || true)

echo "== 1/6 Dateien von GitHub holen"
[ -n "$NEW_SHA" ] || { echo 'Commit konnte nicht bestimmt werden'; exit 1; }
curl -fsSL "https://codeload.github.com/Vauplus69/abrechnungs-navi/tar.gz/$NEW_SHA" | tar xz -C "$TMP"
SRC=$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -n1)

# Abhaengigkeiten und Syntax pruefen, bevor eine produktive Datei ersetzt wird.
if [ ! -x /srv/an-upload/venv/bin/python ]; then
  if ! python3 -m venv /srv/an-upload/venv; then
    apt-get update -qq
    apt-get install -y python3-venv
    python3 -m venv /srv/an-upload/venv
  fi
fi
/srv/an-upload/venv/bin/python -m pip install --disable-pip-version-check -r "$SRC/app/requirements.txt"
/srv/an-upload/venv/bin/python -m py_compile "$SRC/app/upload_app.py" "$SRC/app/workflow.py" "$SRC/app/monitor.py" "$SRC/app/invoicing.py" "$SRC/abrechnung/rechner.py"

# Nur Programm und oeffentliche Seiten sichern, keine Kundendaten oder Geheimnisse.
mkdir -p "$TMP/previous-app" "$TMP/previous-site"
[ ! -d "$APP_DIR" ] || cp -a "$APP_DIR/." "$TMP/previous-app/"
[ ! -d "$SITE_DIR" ] || cp -a "$SITE_DIR/." "$TMP/previous-site/"
rollback_app() {
  cp -a "$TMP/previous-app/." "$APP_DIR/"
  cp -a "$TMP/previous-site/." "$SITE_DIR/"
  systemctl restart an-upload || true
}

echo "== 2/6 Webseite"
mkdir -p "$SITE_DIR"
find "$SRC" -maxdepth 1 -type f \( -name '*.html' -o -name '*.pdf' -o -name '*.css' -o -name '*.js' -o -name '*.png' -o -name '*.jpg' -o -name '*.svg' -o -name '*.ico' -o -name '*.txt' -o -name '*.xml' \) -exec cp {} "$SITE_DIR"/ \;
chmod -R a+rX "$SITE_DIR"

echo "== 3/6 Upload-Programm"
id annavi >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin annavi
mkdir -p "$APP_DIR" "$DATA_DIR/kunden"
install -d -m 700 -o annavi -g annavi /srv/an-upload/invoices
cp "$SRC/app/"*.py "$APP_DIR/"
mkdir -p "$APP_DIR/abrechnung"
cp -a "$SRC/abrechnung/." "$APP_DIR/abrechnung/"
chown -R root:root "$APP_DIR"; chmod 755 "$APP_DIR"; chmod 644 "$APP_DIR/upload_app.py"
chown -R annavi:annavi "$DATA_DIR"; chmod 700 /srv/an-upload/data "$DATA_DIR/kunden"
chmod 755 /srv/an-upload
cp "$SRC/deploy/an-upload.service" /etc/systemd/system/an-upload.service
install -m 755 "$SRC/deploy/an-passwort" /usr/local/bin/an-passwort
install -m 755 "$SRC/deploy/an-mailpasswort" /usr/local/bin/an-mailpasswort
install -m 755 "$SRC/deploy/an-betriebsfreigabe" /usr/local/bin/an-betriebsfreigabe
install -m 755 "$SRC/deploy/an-backup" /usr/local/bin/an-backup
cp "$SRC/deploy/an-backup.service" "$SRC/deploy/an-backup.timer" "$SRC/deploy/an-monitor.service" "$SRC/deploy/an-monitor.timer" /etc/systemd/system/
mkdir -p /etc/an-upload; chown root:annavi /etc/an-upload; chmod 750 /etc/an-upload
if [ ! -e /etc/an-upload/invoice-issuer.json ]; then
  install -m 640 -o root -g annavi "$SRC/deploy/invoice-issuer.example.json" /etc/an-upload/invoice-issuer.json
fi
install -m 755 "$SRC/deploy/setup.sh" /usr/local/bin/an-aktualisieren
cp "$SRC/deploy/an-aktualisieren.service" "$SRC/deploy/an-aktualisieren.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now an-monitor.timer
systemctl enable --now an-aktualisieren.timer >/dev/null 2>&1
if [ -f /etc/an-upload/backup.env ]; then systemctl enable --now an-backup.timer; fi
systemctl enable --now an-upload >/dev/null 2>&1
systemctl restart an-upload

echo "== 4/6 Caddy-Einstellung sichern"
BACKUP="$CADDYFILE.bak-$(date +%Y%m%d-%H%M%S)"
cp "$CADDYFILE" "$BACKUP"
echo "Sicherung: $BACKUP"

echo "== 5/6 Caddy-Einstellung fuer abrechnungs-navi.de"
cp "$SRC/deploy/abrechnungs-navi.caddy" "$SNIPPET"
if [ ! -f "$AUTH" ]; then
  # Bis ein Passwort gesetzt ist, kommt niemand in die Verwaltung (zufaelliger, unbekannter Schluessel)
  RAND=$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)
  printf 'basicauth {\n\tvolker %s\n}\n' "$(caddy hash-password --plaintext "$RAND")" > "$AUTH"
  unset RAND
fi
sed -i "s/basic_auth/basicauth/" "$AUTH"   # aeltere Caddy-Fassung auf dem Server
chmod 640 "$AUTH"; chgrp caddy "$AUTH" 2>/dev/null || true
python3 - "$CADDYFILE" "$SNIPPET" <<'PY'
import sys, re
path, snippet = sys.argv[1], sys.argv[2]
s = open(path, encoding="utf-8").read()
# alten, direkt angehaengten Block (erste Fassung) entfernen
s = re.sub(r"\n*abrechnungs-navi\.de \{.*?\n\}\n*www\.abrechnungs-navi\.de \{\n\tredir https://abrechnungs-navi\.de\{uri\} permanent\n\}\n?", "\n", s, flags=re.S)
line = f"import {snippet}"
if line not in s:
    s = s.rstrip("\n") + f"\n\n{line}\n"
open(path, "w", encoding="utf-8").write(s)
PY

echo "== 6/6 Pruefen und neu laden"
if caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1; then
  systemctl reload caddy
  sleep 1
  if ! systemctl is-active --quiet an-upload || ! curl -fsS http://127.0.0.1:8790/systemstatus | python3 -c 'import json,sys; assert json.load(sys.stdin)["version"] == "4-2026-11-03"'; then
    echo 'FEHLER: Anwendung startet nicht. Vorige Programmfassung wiederherstellen.'
    cp "$BACKUP" "$CADDYFILE"
    rollback_app
    systemctl reload caddy
    exit 1
  fi
  [ -n "$NEW_SHA" ] && echo "$NEW_SHA" > "$VERSION_FILE"
  echo "FERTIG. AnspruchsKompass laeuft unveraendert weiter."
else
  echo "FEHLER in der Einstellung - stelle Sicherung wieder her."
  caddy validate --config "$CADDYFILE" --adapter caddyfile 2>&1 | tail -5 || true
  cp "$BACKUP" "$CADDYFILE"
  rollback_app
  exit 1
fi
