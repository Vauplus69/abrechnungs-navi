#!/bin/bash
# Livegang schlanker Start. Macht zuerst eine Sicherung von public/.
# Zurueck: siehe Zeile ZURUECK am Ende der Ausgabe.
set -e
A=/opt/anspruchskompass
B=/root/sicherung-livegang-$(date +%F-%H%M)
mkdir -p "$B" && cp -a "$A/public" "$B/"
echo "Sicherung: $B"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
curl -fsSL -m 60 https://codeload.github.com/Vauplus69/abrechnungs-navi/tar.gz/anspruchskompass | tar xz -C "$T" --strip-components=1
L="$T/livegang"; P="$A/public"
# 1. Neue Startseite, Rechtstexte, robots, sitemap
cp "$L/index.html" "$P/index.html"
for f in impressum datenschutz cookies; do
  if [ -f "$P/$f.html" ]; then cp "$L/$f.html" "$P/$f.html"; echo "ersetzt: $f.html"; else echo "ACHTUNG: $f.html nicht in public, Route im Programm pruefen"; fi
done
cp "$L/robots.txt" "$P/robots.txt"; cp "$L/sitemap.xml" "$P/sitemap.xml"
# 2. Alte Abo-Seiten auf die Startseite umleiten
for f in premium agb widerruf vertrag-widerrufen kuendigen; do
  if [ -f "$P/$f.html" ]; then cp "$L/weiter.html" "$P/$f.html"; echo "umgeleitet: $f.html"; else echo "ACHTUNG: $f.html nicht in public, Route im Programm pruefen"; fi
done
# 3. Neu bauen
cd "$A" && docker compose build -q && docker compose up -d
sleep 5
for u in / /kompass /impressum /datenschutz /cookies /premium /rente.html /robots.txt; do
  printf "%-16s %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: anspruchs-kompass.de' http://127.0.0.1:8787$u)"
done
echo "ZURUECK: rm -rf $A/public && cp -a $B/public $A/ && cd $A && docker compose build -q && docker compose up -d"
