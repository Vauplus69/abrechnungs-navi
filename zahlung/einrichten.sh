#!/bin/bash
# Richtet den Bezahl-Dienst fuer die Briefvorlagen ein (Mollie + Bestaetigungs-Mail).
# Startet im TESTBETRIEB: Kunden sehen davon nichts. Echt verkauft wird erst nach "ak-zahlung live".
# Macht vorher Sicherungen und nimmt bei Fehlern alles zurueck.
set -euo pipefail
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

# 2) Einstellungen-Datei. Schluessel und Mail-Passwort traegt Volker spaeter im Browser ein (Konsole kann nicht einfuegen).
neuer_code(){ CODE=$(shuf -i 100000-999999 -n 1); BIS=$(( $(date +%s) + 7200 )); }
if [ ! -f "$Z/.env" ]; then
  neuer_code
  umask 077
  cat > "$Z/.env" <<ENV
MODUS=aus
BASIS_URL=https://anspruchs-kompass.de
SMTP_HOST=smtps.udag.de
SMTP_PORT=465
SMTP_USER=kontakt@anspruchs-kompass.de
MAIL_VON=AnspruchsKompass <kontakt@anspruchs-kompass.de>
MAIL_KOPIE=kontakt@anspruchs-kompass.de
MAIL_PRUEFEN=1
EINRICHT_CODE=$CODE
EINRICHT_BIS=$BIS
ENV
fi
# Mail-Passwort fehlt: aus den Einstellungen der Webseite uebernehmen (die schickt schon Widerrufs-Mails). Wird nicht angezeigt.
if ! grep -q '^SMTP_PASS=.' "$Z/.env"; then
  W=$(grep -hE '^[[:space:]-]*[A-Z_]*(SMTP|MAIL)[A-Z_]*PASS[A-Z_]*[=:]' /opt/anspruchskompass/.env /opt/anspruchskompass/compose.yaml 2>/dev/null | head -1 || true)
  if [ -n "$W" ]; then
    WP=$(echo "$W" | sed -E 's/^[^=:]*[=:][[:space:]]*//; s/^["'"'"']//; s/["'"'"'][[:space:]]*$//')
    if [ -n "$WP" ] && [[ "$WP" != *'${'* ]]; then
      sed -i '/^SMTP_PASS=/d' "$Z/.env"; printf 'SMTP_PASS=%s\n' "$WP" >> "$Z/.env"
      echo "== Mail-Passwort aus den Einstellungen der Webseite uebernommen"
    fi
    unset W WP
  else
    echo "== Mail-Passwort nicht gefunden (kann spaeter im Browser eingetragen werden)"
  fi
fi
# Noch kein Schluessel eingetragen: frische Zahl, gilt 2 Stunden
if ! grep -q '^MOLLIE_KEY=' "$Z/.env"; then
  neuer_code
  sed -i '/^EINRICHT_CODE=/d;/^EINRICHT_BIS=/d' "$Z/.env"
  printf 'EINRICHT_CODE=%s\nEINRICHT_BIS=%s\n' "$CODE" "$BIS" >> "$Z/.env"
fi
chown 1000:1000 "$Z/.env"; chmod 600 "$Z/.env"

# 3) Bauen, pruefen, starten
cd "$Z"
docker compose build -q
echo "== Tests:"
docker compose run --rm --no-deps -T --entrypoint node zahlung --test test/zahlung.test.mjs 2>&1 | grep -E "^# (pass|fail)" | tr '\n' ' ' || true; echo
docker compose run --rm --no-deps -T --entrypoint node zahlung --test test/zahlung.test.mjs >/dev/null 2>&1 || { echo "ABBRUCH: Tests fehlgeschlagen. Am Server wurde nichts umgestellt."; exit 1; }
docker compose up -d --force-recreate
sleep 4
curl -sf http://127.0.0.1:8795/api/zahlung/gesund >/dev/null && echo "== Bezahl-Dienst laeuft" || { echo "ABBRUCH: Dienst startet nicht"; docker compose logs --tail 20; exit 1; }

# 4) Caddy: /api/zahlung/* an den Dienst weiterleiten (nur einmal)
# Nur Dateien, die Caddy wirklich laedt: die Hauptdatei und ihre import-Zeilen (keine Sicherungskopien).
C=""
cd /etc/caddy
for f in /etc/caddy/Caddyfile $(grep -E '^[[:space:]]*import[[:space:]]' /etc/caddy/Caddyfile | awk '{print $2}'); do
  for g in $f; do
    [ -f "$g" ] || continue
    if grep -qE "^[^#]*anspruchs-kompass\.de" "$g" && grep -qE "^[^#]*8787" "$g"; then C=$(readlink -f "$g"); break 2; fi
  done
done
cd "$Z"
[ -n "$C" ] || { echo "ABBRUCH: Caddy-Einstellung fuer anspruchs-kompass.de nicht gefunden. Dateien:"; ls /etc/caddy; grep -n import /etc/caddy/Caddyfile; exit 1; }
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
setze(){ grep -q "^$1=" .env && sed -i "s|^$1=.*|$1=$2|" .env || echo "$1=$2" >> .env; chown 1000:1000 .env; chmod 600 .env; }
neu(){ docker compose up -d --force-recreate >/dev/null; sleep 3; }
case "${1:-stand}" in
  aus|test) setze MODUS "$1"; neu; echo "Bezahlung jetzt: $1";;
  live)
    grep -q '^MOLLIE_KEY=live_' .env || { echo "Erst den echten Schluessel eintragen: ak-zahlung schluessel"; exit 1; }
    setze MODUS live; neu; echo "Bezahlung jetzt: LIVE (echte Zahlungen)";;
  schluessel)
    CODE=$(shuf -i 100000-999999 -n 1); setze EINRICHT_CODE "$CODE"; setze EINRICHT_BIS $(( $(date +%s) + 7200 )); neu
    echo; echo "Oeffne in deinem Browser:  https://anspruchs-kompass.de/api/zahlung/einrichten"
    echo "Deine Zahl:                $CODE      (gilt 2 Stunden)"; echo; exit 0;;
  stand) ;;
  *) echo "ak-zahlung aus | test | live | stand | schluessel"; exit 1;;
esac
echo "Modus: $(grep '^MODUS=' .env | cut -d= -f2), Schluessel: $(grep '^MOLLIE_KEY=' .env | cut -d= -f2 | cut -c1-5)..."
echo "Bestellungen bisher: $(grep -o '"status": "bezahlt"' daten/bestellungen.json 2>/dev/null | wc -l) bezahlt"
E
chmod 755 /usr/local/bin/ak-zahlung
echo
docker compose logs --no-log-prefix 2>/dev/null | grep -E "Mail-Anmeldung|Modus" | tail -2 || true
echo
if grep -q '^EINRICHT_CODE=' "$Z/.env"; then
  echo "======================================================="
  echo " FERTIG. Jetzt noch Schluessel und Passwort eintragen:"
  echo " Oeffne in deinem Browser:"
  echo "   https://anspruchs-kompass.de/api/zahlung/einrichten"
  echo " Deine Zahl:  $(grep '^EINRICHT_CODE=' "$Z/.env" | cut -d= -f2)    (gilt 2 Stunden)"
  echo "======================================================="
else
  echo "FERTIG. Modus: $(grep '^MODUS=' "$Z/.env" | cut -d= -f2)"
fi
echo "ZURUECK: cd $Z && docker compose down; Caddy-Datei aus $B zurueckkopieren und 'systemctl reload caddy'"
