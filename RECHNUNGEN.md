# Rechnungserstellung in der Verwaltung

Aufruf: https://abrechnungs-navi.de/verwaltung/rechnungen (bestehender Verwaltungszugang und Authenticator).

1. Rechnungsempfänger, deutsche Rechnungsanschrift, Auftragsreferenz, Wohnungen/Häuser und Abrechnungsjahr eintragen. Keine Mieternamen oder Belege verwenden.
2. Erbrachte Leistung oder Vorausrechnung wählen und das passende Datum eintragen.
3. Entwurf öffnen und PDF prüfen. Der Entwurf hat noch keine Rechnungsnummer und löst keine Zahlung aus.
4. Nach ausdrücklicher Bestätigung festschreiben. Erst dann wird eine einmalige AN-Jahr-Nummer vergeben. Wiederholtes Absenden desselben Entwurfs erzeugt dieselbe Rechnung.
5. PDF herunterladen. Es erfolgt kein automatischer E-Mail-Versand und kein automatischer Mollie-Abgleich. Bestehende Zahlungsnachweise müssen gesondert geprüft werden.
6. Fehler über eine vollständige Stornorechnung korrigieren und gegebenenfalls eine neue Rechnung erstellen. Storno verändert das Original nicht und löst keine Erstattung aus. Vorausrechnungen bei einer späteren Schlussrechnung anrechnen; ein automatischer Verrechnungsablauf ist noch nicht enthalten.

Preise: 89 EUR erste Wohnung je Haus, 59 EUR jede weitere Wohnung. Steuerbefreiung nach § 19 UStG, kein gesonderter Umsatzsteuerausweis. Das Modul ist für inländische Empfänger und diesen Steuerstatus ausgelegt. Eine Änderung des Steuerstatus muss vor Ausstellung weiterer Rechnungen umgesetzt werden.

Ausstellerdaten: /etc/an-upload/invoice-issuer.json, root:annavi, 0640. Steuerkennung niemals im Git-Repository oder Chat hinterlegen. Ohne passende Steuerkennung blockiert das Modul die Ausstellung über 250 EUR; Entwürfe bleiben möglich. Bis 250 EUR werden die vereinfachten Kleinbetragsregeln mit Befreiungshinweis verwendet.

Rechnungen und PDF-Originale: /srv/an-upload/invoices/invoices.sqlite3, getrennt vom temporären Auftragsbestand. Festgeschriebene Dokumente sind über die Anwendung nicht überschreib- oder löschbar; SQLite-Trigger verhindern UPDATE/DELETE. PDF-Hash wird beim Abruf geprüft. Entwürfe sind 24 Stunden gültig. Die getrennte Rechnungssammlung ist in die bestehende verschlüsselte externe Sicherung aufgenommen. Keine automatische Löschung ausgestellter Rechnungen; Fristenkontrolle und gegebenenfalls längere gesetzliche Aufbewahrung liegen beim Betreiber. Integrität und Sicherungen sind regelmäßig zu kontrollieren; dies ist keine Zertifizierung einer vollständigen Buchhaltung.

Quellen: https://www.gesetze-im-internet.de/ustdv_1980/__33.html ; https://www.gesetze-im-internet.de/ustdv_1980/__34a.html ; https://www.gesetze-im-internet.de/ustg_1980/__14b.html
