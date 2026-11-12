#!/bin/bash
# Spielt die neue Startseite (livegang/index.html) ein. Macht vorher eine Sicherung.
set -euo pipefail
A=/opt/anspruchskompass
B=/root/sicherung-startseite-$(date +%F-%H%M)
mkdir -p "$B" && cp -a "$A/public/index.html" "$B/index.html"
echo "== Sicherung der alten Startseite: $B/index.html"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
curl -fsSL -m 60 https://codeload.github.com/Vauplus69/abrechnungs-navi/tar.gz/anspruchskompass | tar xz -C "$T" --strip-components=1
grep -q 'class="themenleiste"' "$T/livegang/index.html" || { echo "ABBRUCH: neue Startseite nicht gefunden, nichts geaendert."; exit 1; }
cp "$T/livegang/index.html" "$A/public/index.html"
cp "$T/neu/start.css" "$A/public/start.css"
cd "$A" && docker compose build -q && docker compose up -d
sleep 5
C=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: anspruchs-kompass.de' http://127.0.0.1:8787/)
if [ "$C" = 200 ] && curl -s -H 'Host: anspruchs-kompass.de' http://127.0.0.1:8787/ | grep -q themenleiste; then
  echo "== Startseite mit Themen-Leiste ist LIVE (200)"
else
  echo "FEHLER (Antwort $C) - alte Startseite wird zurueckgeholt"
  cp "$B/index.html" "$A/public/index.html"; docker compose build -q && docker compose up -d
  exit 1
fi
echo "ZURUECK: cp $B/index.html $A/public/index.html && cd $A && docker compose build -q && docker compose up -d"
