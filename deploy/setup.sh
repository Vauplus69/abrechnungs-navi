#!/usr/bin/env bash
# Richtet abrechnungs-navi.de auf diesem Server ein bzw. aktualisiert die Dateien.
# Kann beliebig oft ausgeführt werden. Bestehende Seiten (AnspruchsKompass) bleiben unverändert.
set -euo pipefail

SITE_DIR=/var/www/abrechnungs-navi
CADDYFILE=/etc/caddy/Caddyfile
TMP=$(mktemp -d)

echo "== 1/4 Dateien von GitHub holen"
curl -fsSL https://codeload.github.com/Vauplus69/abrechnungs-navi/tar.gz/main | tar xz -C "$TMP"
SRC=$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -n1)
mkdir -p "$SITE_DIR"
# Nur Webseiten-Dateien veröffentlichen, keine Skripte
find "$SRC" -maxdepth 1 -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.png' -o -name '*.jpg' -o -name '*.svg' -o -name '*.ico' -o -name 'robots.txt' \) -exec cp {} "$SITE_DIR"/ \;
chmod -R a+rX "$SITE_DIR"
rm -rf "$TMP"
ls -l "$SITE_DIR"

echo "== 2/4 Caddy-Einstellung sichern"
BACKUP="$CADDYFILE.bak-$(date +%Y%m%d-%H%M%S)"
cp "$CADDYFILE" "$BACKUP"
echo "Sicherung: $BACKUP"

echo "== 3/4 Seite in Caddy eintragen (falls noch nicht vorhanden)"
if grep -q '^abrechnungs-navi.de' "$CADDYFILE"; then
  echo "abrechnungs-navi.de ist schon eingetragen - nichts zu tun."
else
  cat >> "$CADDYFILE" <<'EOF'

abrechnungs-navi.de {
	root * /var/www/abrechnungs-navi
	encode gzip
	file_server
	header {
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		X-Frame-Options DENY
	}
}

www.abrechnungs-navi.de {
	redir https://abrechnungs-navi.de{uri} permanent
}
EOF
  echo "Eingetragen."
fi

echo "== 4/4 Prüfen und neu laden"
if caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1; then
  systemctl reload caddy
  echo "FERTIG: Caddy neu geladen. AnspruchsKompass läuft unverändert weiter."
else
  echo "FEHLER in der Einstellung - stelle Sicherung wieder her."
  cp "$BACKUP" "$CADDYFILE"
  caddy validate --config "$CADDYFILE" --adapter caddyfile || true
  exit 1
fi
