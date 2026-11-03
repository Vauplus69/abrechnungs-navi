# Abrechnungs Navi Betriebsstand

Fassung 4 vom 03.11.2026. Keine externe KI fuer Kundenbelege. Keine Werbung oder Zahlung wird durch das Deployment gestartet.

## Freigaben vor Kundenbetrieb

Der neue Ablauf nimmt erst Unterlagen an, wenn die Betreiberfreigabe vollstaendig ist. Das ist absichtlich keine aus dem Quellcode abgeleitete Tatsachenbestaetigung.

- Vollstaendiger AV-Vertrag mit realem Rechenzentrum, Dienstleisterkette und Restfristen.
- Nachweis von Festplattenverschluesselung und Anbieter-MFA durch den Inhaber.
- Verschluesselte externe Sicherung und dokumentierter Wiederherstellungstest.
- Persoenliche Einrichtung des zweiten Verwaltungsfaktors auf dem Server.

`an-betriebsfreigabe` erfragt diese persoenlichen Bestaetigungen, prueft die aktuelle Sicherungsmarke und richtet nach Bestaetigung den Authenticator-Faktor ein. Es speichert ausschliesslich lokale Konfiguration. Keine Zugangsdaten ins oeffentliche Repository laden.

## Externe Sicherung

Restic benoetigt einen bereits vereinbarten externen Sicherungsort. Es wird kein kostenpflichtiger Speicher automatisch bestellt. Root hinterlegt `RESTIC_REPOSITORY` und `RESTIC_PASSWORD_FILE` in `/etc/an-upload/backup.env` (Datei nur root-lesbar). Das Passwort steht ausschliesslich in der angegebenen lokalen Passwortdatei. Anbieter, Land, Auftragsverarbeitung und Fristen sind vor Verwendung im AV-Vertrag zu erfassen.

`an-backup` sichert einen konsistenten Stand verschluesselt extern und bereinigt Sicherungen nach 30 Tagen. Enthalten sind Auftragsdaten, AN-Programm und Seiten, eigene Dienstdefinitionen sowie die AN-Konfiguration einschliesslich SMTP-Zugang, Verwaltungs-Passworthash und Authenticator. Der Restic-Entschluesselungsschluessel ist ausgeschlossen und muss separat sicher aufbewahrt werden. Der Storage-Box-Zugang muss bei einem Serververlust ebenfalls unabhaengig verfuegbar sein. Es handelt sich nicht um ein vollstaendiges Serverabbild. `an-backup.timer` laeuft taeglich. Ein erfolgreicher Sicherungslauf ersetzt keinen Wiederherstellungstest. Externe Gesamtausfaelle sind in der dokumentierten Risikobewertung zu beruecksichtigen. Weitere Anwendungen auf dem Server werden nicht in diese Sicherung aufgenommen.

## Ablauf

Siehe `VORLAGEN.md` und `abrechnung/ABLAUF.md`. Neue Uploads erfordern belegte Beauftragung, AV-Vertrag, Zahlung und zulaessigen Beginn. Der Inhaber prueft den tatsaechlichen Zahlungseingang bei Mollie. Kein Zahlungsstatus wird aus einem Kundenaufruf abgeleitet.

Kunden erhalten Link und Zugangscode getrennt. Das Ergebnis wird in der Verwaltung hochgeladen und nach menschlicher Pruefung und Kundeninformation freigegeben. Ab erster Bereitstellung bleibt die 30-Tage-Loeschfrist fest. Ein Kundenabruf ist nur nach Anmeldung moeglich. Notwendige Sitzungscookies werden im Datenschutz beschrieben.

Bestandsdaten behalten ihre alten Aufbewahrungsfristen. Alte Upload-Links sind fuer den neuen Ablauf nicht freigegeben; eine Migration erfordert die Pruefung des Einzelfalls. Vor einer Migration darf keine vorhandene Frist stillschweigend verkuerzt werden.

## Tests und Deployment

`python -m unittest discover -s tests -v` prueft lokal mit erfundenen Daten und simuliertem Mailversand unter anderem die Freigabesperren, PDF-Inhaltspruefung, Downloadschutz, unveraenderliche Frist, tatsaechliche Serverloeschung und die zweistufige Widerrufsfunktion. Ein solcher Test ist kein Nachweis des Eingangs echter Mails.

Der Server bezieht main alle zehn Minuten. Der Installer prueft Abhaengigkeiten und Syntax vor dem Dateitausch. Caddy wird validiert und die Anwendung auf aktiven Dienststatus geprueft. Bei Fehlern werden vorherige Programme und oeffentliche Dateien wiederhergestellt. Kundendaten werden nicht in die Programmsicherung kopiert.

`/systemstatus` zeigt nur die Programmfassung und die Freigabe neuer Uploads, keine Zugangsdaten oder Kundendaten.

## Noch separat nachzuweisen

Live-Installation, echte Mailzustellung nach konkreter Testfreigabe, Mollie-Profil/Zahlungsarten ohne echte Testzahlung, vollstaendige Betreiberangaben, lokale Geraetesicherheit, externe Sicherung und echter Wiederherstellungstest. Rechtsdienstleistungsgrenze und passende Berufshaftpflicht sind keine Softwaretests.
