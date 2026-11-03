# Geprüfter manueller Rechner

Stand 03.11.2026: Eingabeformat nach Musterprüfung verschärft. Alte Auftragsdateien
werden nicht automatisch ergänzt oder freigegeben. Der Rechner versendet keine
Mails, erzeugt keine Zahlungen und gibt kein Ergebnis im Kundenportal frei.

## Pflichtprüfung

- Jede umzulegende Kostenposition: `umlage_geprueft: true` und nicht leere
  `beleg`-Referenz. Die Bestätigung umfasst Kostenart und vereinbarten Schlüssel.
- Nicht umzulegende Positionen mit `umlegen: false` ausdrücklich ausschließen.
  Verwaltung/Instandhaltung usw. sind bei Umlage gesperrt, auch bei Bestätigung.
- Jede Mietpartei: Wohnfläche, Nutzungsdaten innerhalb der Abrechnungsperiode,
  Vorauszahlungen und expliziter Verbrauch für jede Verbrauchskostenart.
  Echte Null ist erlaubt; fehlender Wert ist keine Null. Negative/NaN/unendliche
  Werte sind unzulässig. Geldbeträge höchstens zwei Nachkommastellen.
- Personenschlüssel: `objekt.personentage_gesamt`, `objekt.personentage_beleg`
  und `mieter[].personentage`. Personenwechsel und Teiljahre anhand tatsächlicher
  Belegung dokumentieren. Kein unveränderlicher Kopfzahl-Nenner bei Wechseln.
- Gesamte Mengen/Zeitanteile dürfen nicht überbelegt sein. Positive Differenzen
  benötigen bei der jeweiligen Kostenposition `vermieter_rest` mit `betrag`,
  `grund` und `beleg`. Dies bedeutet ausdrücklich eine belegte Vermieterlast,
  keine geschätzte Umverteilung auf Mieter. Fehlende Vormieter/Verbrauchswerte
  zuerst vervollständigen. Nur unvermeidliche Cent-Rundungen werden toleriert.
- Heizkosten ausschließlich mit `messdienst_beleg`,
  `heizkosten_status: vor_co2_abzug` oder `nach_co2_abzug` und
  `co2_kosten_anteil` (CO2-Kosten der Mietpartei VOR Aufteilung).
  Bei `nach_co2_abzug` zusätzlich `co2_vermieterabzug`; der Betrag muss dem
  berechneten Abzug entsprechen und wird nicht erneut abgezogen.
- CO2-Gebäudedaten: `kg_co2_gesamt`, `beleg`,
  `wohngebaeude_regelfall_geprueft: true`. Letzteres bestätigt fachlich, dass
  der Wohngebäude-Regelfall ohne Sonderbegrenzungen gilt. Bei abweichenden
  Gebäuden, gesetzlichen Begrenzungen, Eigenversorgung oder fehlender Grundlage
  nicht bestätigen, sondern separat fachlich bearbeiten.

## Bewusste Grenze

Automatische CO2-Berechnung nur für vollständige Kalenderjahre, einschließlich
Schaltjahr. Verkürzte oder abweichende Perioden werden gesperrt statt mit
falschen Jahresstufen gerechnet. § 5 CO2KostAufG verlangt bei kürzeren Perioden
angepasste Stufengrenzen; solche Fälle sind separat fachlich zu berechnen:
https://www.gesetze-im-internet.de/co2kostaufg/__5.html

## Muster und Ausgabe

`beispiel.json` ist ein NEUER vollständig erfundener Ganzjahresfall. Alle drei
Wohnungen ganzjährig bewohnt; Wasser 231 m³ entspricht der Summe 142+51+38.
Personentage 1825 entsprechen (3+1+1)*365. Keine echten Rechnungen oder Namen.
Der widersprüchliche alte Musterfall ist im Git-Verlauf und im Prüfbericht
historisch erhalten. Daraus wurden keine fehlenden echten Werte abgeleitet.

`python abrechnung/rechner.py abrechnung/beispiel.json /geschuetzter/testordner`

Erst nach erfolgreicher Gesamtprüfung entstehen PDFs. Dateien haben eindeutige
laufende Nummern. Unicode-Schriften samt Lizenz werden mitgeliefert; fehlende
Schrift ist ein Fehler, kein stiller Helvetica-Fallback. Text wird vor dem
PDF-Markup maskiert. `testauftrag: true` kennzeichnet jede PDF sichtbar als Muster.
Ausgaben mit Personenbezug gehören niemals ins öffentliche Webverzeichnis.

Prüfen: `python -m unittest discover -s tests -v` (inklusive echtem berechneten
Muster-PDF im isolierten lokalen HTTP-Auftragsablauf, ohne echte Mails).
Die Softwareprüfung ersetzt nicht die Beleg-, Mietvertrags- und Endkontrolle.

## Installation

Der Installer hinterlegt den Rechner und die Schriften unter
`/srv/an-upload/app/abrechnung`; ReportLab ist fest in requirements.txt erfasst.
Dieser AN-Programmordner ist bereits Bestandteil der verschlüsselten Sicherung.
Keine Änderung der öffentlichen Uploadsperre und keine automatische
Zahlungs-/Ergebnisfreigabe.
