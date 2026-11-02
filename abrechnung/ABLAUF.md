# Abrechnungs-Navi – Ablauf mit KI-Helfern (Plan)

Dieser Ordner wird **nicht** auf die Webseite kopiert. Hier liegt nur das Rechenwerk.

## Ablauf je Auftrag

1. **Belege einsammeln:** Der Vermieter lädt über seinen Upload-Link hoch (liegt auf dem Server unter `/srv/an-upload/data/kunden/<link>`).
2. **Helfer 1 – Belege lesen:** liest jede Rechnung, holt Betrag, Zeitraum und Kostenart heraus und schreibt alles in eine `auftrag.json` (Aufbau wie `beispiel.json`). Unklare Belege werden markiert, nicht geraten.
3. **Helfer 2 – Rechnen:** `python3 rechner.py auftrag.json ausgabe/` erstellt je Mieter eine PDF-Abrechnung und einen `pruefbericht.txt`.
4. **Helfer 3 – Zweitprüfung „aus Sicht der Mieter“:** prüft die PDFs gegen die Belege und den Prüfbericht (umlagefähig? Schlüssel wie im Mietvertrag? Summen stimmen?).
5. **Volker – Freigabe:** schaut Prüfbericht und PDFs durch, gibt frei oder korrigiert.
6. **Versand:** Erst nach Freigabe gehen die PDFs an den Vermieter. Der Vermieter schickt sie an seine Mieter.
7. **Abschluss:** In der Verwaltung „Auftrag abgeschlossen“ klicken. Nach 6 Monaten löscht der Server automatisch.

## Vor dem ersten echten Einsatz nötig

- KI-Dienst in die Datenschutzerklärung aufnehmen und dafür einen Vertrag zur Auftragsverarbeitung abschließen.
- Einmal mit echten (geschwärzten) Unterlagen testen.
- Anwalt-Check: Erstellen der Abrechnung ohne Rechtsberatung (Rechtsdienstleistungsgesetz).
