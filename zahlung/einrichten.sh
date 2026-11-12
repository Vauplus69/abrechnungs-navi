#!/bin/bash
# Richtet den Bezahl-Dienst fuer die Briefvorlagen ein (Mollie + Bestaetigungs-Mail).
# Startet im TESTBETRIEB: Kunden sehen davon nichts. Echt verkauft wird erst nach "ak-zahlung live".
# Macht vorher Sicherungen und nimmt bei Fehlern alles zurueck.
set -euo pipefail
clear
Z=/opt/ak-zahlung
B=/root/sicherung-zahlung-$(date +%F-%H%M)
mkdir -p "$B"
echo "== Sicherung: $B"

# 1) Programm holen
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
curl -fsSL -m 60 https://codeload.github.com/Vauplus69/abrechnungs-navi/tar.gz/anspruchskompass | tar xz -C "$T" --strip-components=1
[ -d "$Z" ] && cp -a "$Z" "$B/ak-zahlung-vorher"
mkdir -p "$Z/daten"
for f in lib.mjs server.mjs package.json package-lock.json Dockerfile compose.yaml .dockerignore; do cp "$T/zahlung/$f" "$Z/$f"; done
rm -rf "$Z/test"; cp -a "$T/zahlung/test" "$Z/test"
cp "$T/zahlung/einrichten.sh" "$Z/einrichten.sh"
chown 1000:1000 "$Z/daten"; chmod 700 "$Z/daten"

# 2) Schluessel und Mail-Passwort (nur beim ersten Mal). Volker tippt sie selbst ein, sie werden nicht angezeigt.
if [ ! -f "$Z/.env" ]; then
  echo
  echo "Jetzt brauche ich zwei Dinge von dir. Beim Eintippen oder Einfuegen siehst du nichts, das ist richtig so."
  K=""
  until [[ "$K" =~ ^test_[A-Za-z0-9]{20,}$ ]]; do
    read -r -s -p "1) Test-Schluessel von Mollie (beginnt mit test_): " K </dev/tty; echo
    [[ "$K" =~ ^test_[A-Za-z0-9]{20,}$ ]] || echo "   Das sieht nicht wie ein Test-Schluessel aus. Bitte noch einmal."
  done
  P=""
  until [ -n "$P" ]; do read -r -s -p "2) Passwort des Postfachs kontakt@anspruchs-kompass.de: " P </dev/tty; echo; done
  umask 077
  cat > "$Z/.env" <<ENV
MODUS=test
MOLLIE_KEY=$K
BASIS_URL=https://anspruchs-kompass.de
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=465
SMTP_USER=kontakt@anspruchs-kompass.de
SMTP_PASS=$P
MAIL_VON=AnspruchsKompass <kontakt@anspruchs-kompass.de>
MAIL_KOPIE=kontakt@anspruchs-kompass.de
MAIL_PRUEFEN=1
ENV
  unset K P
  chmod 600 "$Z/.env"
fi

# 3) Bauen, pruefen, starten
cd "$Z"
docker compose build -q
echo "== Tests:"
docker compose run --rm --no-deps -T --entrypoint node zahlung --test test/zahlung.test.mjs 2>&1 | grep -E "^# (pass|fail)" | tr '\n' ' ' || true; echo
docker compose run --rm --no-deps -T --entrypoint node zahlung --test test/zahlung.test.mjs >/dev/null 2>&1 || { echo "ABBRUCH: Tests fehlgeschlagen. Am Server wurde nichts umgestellt."; exit 1; }
docker compose up -d
sleep 4
curl -sf http://127.0.0.1:8795/api/zahlung/gesund >/dev/null && echo "== Bezahl-Dienst laeuft" || { echo "ABBRUCH: Dienst startet nicht"; docker compose logs --tail 20; exit 1; }

# 4) Caddy: /api/zahlung/* an den Dienst weiterleiten (nur einmal)
C=$(grep -rlE "^[^#]*anspruchs-kompass\.de" /etc/caddy 2>/dev/null | head -1 || true)
[ -n "$C" ] || { echo "ABBRUCH: Caddy-Einstellung fuer anspruchs-kompass.de nicht gefunden."; exit 1; }
if grep -q "/api/zahlung/" "$C"; then
  echo "== Caddy-Weiterleitung ist schon da ($C)"
else
  cp -a "$C" "$B/$(basename "$C")"
  python3 - "$C" <<'PY'
import sys, re
f = sys.argv[1]; z = open(f).read().split('\n')
# Block finden, der an die App auf 8787 weiterleitet, und dessen Kopfzeile
i = next(n for n, l in enumerate(z) if '8787' in l and not l.lstrip().startswith('#'))
while i >= 0 and not (re.match(r'^\S.*\{\s*$', z[i]) and 'anspruchs-kompass.de' in z[i]): i -= 1
assert i >= 0, 'Kopfzeile nicht gefunden'
z[i+1:i+1] = ['\thandle /api/zahlung/* {', '\t\treverse_proxy 127.0.0.1:8795', '\t}']
open(f, 'w').write('\n'.join(z))
PY
  zurueck(){ echo "FEHLER - Caddy-Einstellung zurueckgesetzt"; cp -a "$B/$(basename "$C")" "$C"; systemctl reload caddy || true; exit 1; }
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 || zurueck
  systemctl reload caddy || zurueck
  sleep 2
  echo "== Caddy-Weiterleitung eingerichtet ($C)"
fi
R=$(curl -s -m 10 --resolve anspruchs-kompass.de:443:127.0.0.1 https://anspruchs-kompass.de/api/zahlung/gesund || true)
echo "$R" | grep -q '"ok":true' && echo "== Von aussen erreichbar: ja ($R)" || { echo "ACHTUNG: von aussen nicht erreichbar: $R"; [ -f "$B/$(basename "$C")" ] && { cp -a "$B/$(basename "$C")" "$C"; systemctl reload caddy; echo "Caddy zurueckgesetzt."; }; exit 1; }
for u in / /brief.html /kompass; do printf "%-14s %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code}' --resolve anspruchs-kompass.de:443:127.0.0.1 https://anspruchs-kompass.de$u)"; done

# 5) Hilfsbefehl zum Umschalten
cat > /usr/local/bin/ak-zahlung <<'E'
#!/bin/bash
# ak-zahlung aus | test | live | stand | schluessel
set -e
Z=/opt/ak-zahlung; cd "$Z"
setze(){ sed -i "s|^$1=.*|$1=$2|" .env; }
case "${1:-stand}" in
  aus|test) setze MODUS "$1"; docker compose up -d --force-recreate >/dev/null; echo "Bezahlung jetzt: $1";;
  live)
    grep -q '^MOLLIE_KEY=live_' .env || { echo "Erst den Live-Schluessel eintragen: ak-zahlung schluessel"; exit 1; }
    setze MODUS live; docker compose up -d --force-recreate >/dev/null; echo "Bezahlung jetzt: LIVE (echte Zahlungen)";;
  schluessel)
    read -r -s -p "Neuer Schluessel von Mollie (test_... oder live_...): " K </dev/tty; echo
    [[ "$K" =~ ^(test|live)_[A-Za-z0-9]{20,}$ ]] || { echo "Das sieht nicht wie ein Mollie-Schluessel aus."; exit 1; }
    setze MOLLIE_KEY "$K"; [[ "$K" == test_* ]] && setze MODUS test
    docker compose up -d --force-recreate >/dev/null; echo "Schluessel gespeichert (${K:0:5}...).";;
  stand) ;;
  *) echo "ak-zahlung aus | test | live | stand | schluessel"; exit 1;;
esac
sleep 3
echo "Modus: $(grep '^MODUS=' .env | cut -d= -f2), Schluessel: $(grep '^MOLLIE_KEY=' .env | cut -d= -f2 | cut -c1-5)..."
echo "Bestellungen bisher: $(grep -o '"status": "bezahlt"' daten/bestellungen.json 2>/dev/null | wc -l) bezahlt"
docker compose logs --tail 5 --no-log-prefix 2>/dev/null | grep -E "Mail|Modus|Fehler" || true
E
chmod 755 /usr/local/bin/ak-zahlung
echo
docker compose logs --no-log-prefix 2>/dev/null | grep -E "Mail-Anmeldung|Modus" | tail -2 || true
echo
echo "FERTIG. Testbetrieb laeuft. Zum Ausprobieren: https://anspruchs-kompass.de/brief.html?test=1"
echo "ZURUECK: cd $Z && docker compose down; Caddy-Datei aus $B zurueckkopieren und 'systemctl reload caddy'"
