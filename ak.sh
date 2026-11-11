#!/bin/bash
# AnspruchsKompass: neue Dateien als Vorschau ablegen. Bestehende Seiten bleiben unverändert.
set -u
cd "$(dirname "$0")"
PID=$(ss -ltnp 'sport = :8787' | grep -oP 'pid=\K[0-9]+' | head -1)
echo "Programm auf 8787: PID $PID"; ps -o args= -p "$PID"
CWD=$(readlink -f /proc/$PID/cwd); echo "Arbeitsordner: $CWD"
DIR=$(dirname "$(find "$CWD" /opt /srv /var/www -maxdepth 4 -name catalog.js -not -path '*/node_modules/*' 2>/dev/null | head -1)")
echo "Seitenordner: $DIR"
[ -f "$DIR/app.js" ] || { echo "FEHLER: Seitenordner nicht gefunden"; exit 1; }
SICH=/root/ak-sicherung-$(date +%Y%m%d-%H%M%S).tgz
tar czf "$SICH" -C "$DIR" . && echo "Sicherung: $SICH ($(du -h "$SICH" | cut -f1))"
for f in vorschau.html kompass.html kompass-start.js start.css start.js termin.html; do
  [ -e "$DIR/$f" ] && echo "WARNUNG: $f gab es schon, wird ueberschrieben"
done
cp -r bilder fonts vorschau.html kompass.html kompass-start.js start.css start.js termin.html "$DIR"/
chmod -R a+rX "$DIR/bilder" "$DIR/fonts"
OWN=$(stat -c %U:%G "$DIR/app.js"); chown -R "$OWN" "$DIR/bilder" "$DIR/fonts" "$DIR"/{vorschau.html,kompass.html,kompass-start.js,start.css,start.js,termin.html}
echo "Abgelegt in $DIR:"; ls -la "$DIR" | head -40
for p in / /vorschau /vorschau.html /kompass /kompass.html /termin /start.css /fonts/fonts.css /bilder/volker.jpg; do
  printf '%-18s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8787$p)"
done
echo FERTIG
