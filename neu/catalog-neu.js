(function(root){
const api={
  "year": 2026,
  "checked": "20.10.2026",
  "reviewRevision": "2026-10-20-02",
  "overviewSource": "https://www.bundesgesundheitsministerium.de/fileadmin/Dateien/3_Downloads/P/Pflegeversicherung_Leistungsbeitraege/Uebersicht_Leistungsbetraege_2026_VA.pdf",
  "entries": [
    {
      "id": "geld",
      "title": "Pflegegeld",
      "category": "Zuhause",
      "min": 2,
      "type": "Geldleistung",
      "rates": [
        0,
        0,
        347,
        599,
        800,
        990
      ],
      "unit": "monatlich",
      "amount": "347–990 € monatlich",
      "about": "Für Pflege zu Hause, die zum Beispiel Angehörige übernehmen. Die nötige Hilfe muss zuverlässig organisiert sein.",
      "condition": "Pflegegrad 2 bis 5 und verlässlich organisierte Pflege zu Hause. Pflegedienst und umgewandelte Sachleistungen können das Pflegegeld verringern. Bei Kurzzeit- oder Verhinderungspflege wird es grundsätzlich zur Hälfte für jeweils bis zu acht Wochen weitergezahlt. Beratung ist regelmäßig Pflicht.",
      "next": "Pflegekasse nach Pflegegeld, Beratungsterminen und passender Kombination fragen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__37.html",
      "relation": "kombination"
    },
    {
      "id": "sach",
      "title": "Ambulante Pflegesachleistungen",
      "category": "Zuhause",
      "min": 2,
      "type": "Sachleistung",
      "rates": [
        0,
        0,
        796,
        1497,
        1859,
        2299
      ],
      "unit": "monatlich, bis zu",
      "amount": "Bis zu 796–2.299 € monatlich",
      "about": "Ein zugelassener Pflegedienst hilft bei der Körperpflege, Betreuung oder im Haushalt. Die Kasse bezahlt die vereinbarte Hilfe.",
      "condition": "Pflegegrad 2–5. Das Geld wird nicht frei ausgezahlt. Ungenutzte Monatsbeträge kannst du nicht für später ansparen.",
      "next": "Angebot eines zugelassenen Dienstes und verbleibendes Pflegegeld gemeinsam prüfen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__36.html",
      "relation": "kombination"
    },
    {
      "id": "kombi",
      "title": "Kombinationsleistung",
      "category": "Zuhause",
      "min": 2,
      "type": "Kombination",
      "amount": "Anteiliges Pflegegeld + Sachleistung",
      "about": "Professionelle Hilfe und selbst organisierte Pflege können kombiniert werden.",
      "condition": "Kein extra Geldtopf. Wenn 50 % der Sachleistungen genutzt werden, bleiben grundsätzlich 50 % des Pflegegeldes. An das gewählte Verhältnis bist du grundsätzlich sechs Monate gebunden. Änderungen mit der Kasse abstimmen.",
      "next": "Von der Pflegekasse eine Beispielrechnung für die gewünschte Versorgung anfordern.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__38.html",
      "relation": "kombination"
    },
    {
      "id": "ent",
      "title": "Entlastungsbetrag",
      "category": "Zuhause",
      "min": 1,
      "type": "Kostenerstattung",
      "amount": "Bis zu 131 € monatlich",
      "about": "Für geeignete Alltagshilfe und weitere zugelassene Entlastungsangebote.",
      "condition": "Für passende Leistungen bei häuslicher Pflege, etwa anerkannte Alltagshilfe, Tages- oder Kurzzeitpflege. Bei Pflegegrad 2–5 darf damit beim Pflegedienst nicht die Hilfe bei der eigenen Körperpflege bezahlt werden; bei Pflegegrad 1 ist das möglich. Vorjahresreste grundsätzlich bis Ende Juni des Folgejahres nutzen.",
      "next": "Bestätigten Budgetstand und geeignete Angebote bei der Pflegekasse erfragen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__45b.html",
      "relation": "ent"
    },
    {
      "id": "umwandlung",
      "title": "Umwandlungsanspruch für Alltagshilfe",
      "category": "Zuhause",
      "min": 2,
      "type": "Budget anders nutzen",
      "amount": "Bis zu 40 % des Sachleistungsrahmens",
      "about": "Geld, das im Monat nicht für den Pflegedienst gebraucht wird, kann teilweise für anerkannte Alltagshilfe genutzt werden.",
      "condition": "Ab Pflegegrad 2 für nach Landesrecht anerkannte Angebote. Höchstens 40 % des monatlichen Sachleistungsrahmens, soweit nicht verbraucht. Kein Extra-Budget; die Nutzung zählt bei der Pflegegeld-Kombination mit. Erstattung gegen Belege; kein vorheriger Umwandlungsantrag nötig.",
      "next": "Vor Nutzung Auswirkungen auf Sachleistungen und Pflegegeld berechnen lassen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__45a.html",
      "relation": "kombination"
    },
    {
      "id": "verhinderung",
      "title": "Verhinderungspflege",
      "category": "Zuhause",
      "min": 2,
      "type": "Gemeinsames Budget",
      "amount": "Zusammen mit Kurzzeitpflege: bis zu 3.539 € jährlich",
      "about": "Ersatzpflege, wenn die normalerweise pflegende private Person vorübergehend verhindert ist.",
      "condition": "Ersatzpflege bis zu acht Wochen je Kalenderjahr, wenn die private Pflegeperson verhindert ist. Keine sechsmonatige Vorpflegezeit mehr. Bei nicht beruflicher Hilfe durch Verwandte oder Verschwägerte bis zum zweiten Grad oder Haushaltsmitglieder gilt regelmäßig die Grenze von zwei Monats-Pflegegeldern; belegte Zusatzkosten können dazukommen. Alles zusammen höchstens aus dem gemeinsamen Budget.",
      "next": "Keine Antragspflicht vor der Ersatzpflege. Für 2026 Erstattungsantrag mit Kostennachweisen spätestens bis 31.12.2027 einreichen. Bei stundenweiser Verhinderung unter acht Stunden am Tag wird Pflegegeld nicht gekürzt. Diese Tage zählen nicht zur Achtwochen-Grenze. Maßgeblich ist die Verhinderung der Pflegeperson, nicht nur die Einsatzzeit der Ersatzperson. Bei tageweiser Ersatzpflege bleibt grundsätzlich die Hälfte des Pflegegeldes; am ersten und letzten Tag wird es voll gezahlt.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__39.html",
      "relation": "shared",
      "sources": [
        "https://www.gesetze-im-internet.de/sgb_11/__39.html",
        "https://www.gesetze-im-internet.de/sgb_11/__42a.html",
        "https://www.gesetze-im-internet.de/sgb_11/__37.html",
        "https://gesund.bund.de/verhinderungspflege"
      ]
    },
    {
      "id": "kurzzeit",
      "title": "Kurzzeitpflege",
      "category": "Einrichtungen",
      "min": 2,
      "type": "Gemeinsames Budget",
      "amount": "Zusammen mit Verhinderungspflege: bis zu 3.539 € jährlich",
      "about": "Vorübergehende Versorgung in einer Pflegeeinrichtung, wenn die Pflege zu Hause nicht ausreichend möglich ist.",
      "condition": "Pflegegrad 2–5, bis zu acht Wochen je Kalenderjahr. Teilt sich 3.539 € mit der Verhinderungspflege. Unterkunft, Essen und Investitionskosten sind meist selbst zu zahlen; dafür kann der Entlastungsbetrag helfen. Bisheriges Pflegegeld wird grundsätzlich zur Hälfte bis zu acht Wochen weitergezahlt.",
      "next": "Platz, Zulassung, Eigenanteile und gemeinsames Restbudget bestätigen lassen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__42.html",
      "relation": "shared",
      "special": "Pflegegrad 1: Entlastungsbetrag gesondert prüfen.",
      "sources": [
        "https://www.gesetze-im-internet.de/sgb_11/__42.html",
        "https://www.gesetze-im-internet.de/sgb_11/__42a.html",
        "https://www.gesetze-im-internet.de/sgb_11/__37.html",
        "https://www.gesetze-im-internet.de/sgb_11/__45b.html"
      ]
    },
    {
      "id": "tages",
      "title": "Tages- und Nachtpflege",
      "category": "Einrichtungen",
      "min": 2,
      "type": "Sachleistung",
      "rates": [
        0,
        0,
        721,
        1357,
        1685,
        2085
      ],
      "unit": "monatlich, bis zu",
      "amount": "Bis zu 721–2.085 € monatlich",
      "about": "Zeitweise Betreuung und Pflege in einer Einrichtung ergänzt die häusliche Versorgung.",
      "condition": "Pflegegrad 2–5. Der Rahmen kommt grundsätzlich zusätzlich zu Pflegegeld oder ambulanten Sachleistungen dazu. Nötige Fahrten sind eingeschlossen. Unterkunft und Essen können Eigenanteile sein. Bei Pflege-WGs mit Wohngruppenzuschlag gelten zusätzliche Voraussetzungen.",
      "next": "Einrichtung nach Betreuung, Beförderung und vollständiger Kostenaufstellung fragen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__41.html"
    },
    {
      "id": "verbrauch",
      "search": "Handschuhe Einmalhandschuhe Desinfektion",
      "title": "Pflegehilfsmittel zum Verbrauch",
      "category": "Hilfsmittel",
      "min": 1,
      "type": "Kostenerstattung",
      "amount": "Bis zu 42 € monatlich",
      "about": "Zum Beispiel geeignete Einmalhandschuhe oder Desinfektionsmittel für die häusliche Pflege.",
      "condition": "Die Produkte müssen für die Pflege gebraucht werden. Das Geld gibt es nicht zur freien Verfügung. Ungenutzte Beträge werden nicht am Jahresende ausgezahlt.",
      "next": "Bedarf und Kostenübernahme vor Bestellung bei der Pflegekasse klären.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__40.html"
    },
    {
      "id": "technik",
      "title": "Technische Pflegehilfsmittel",
      "category": "Hilfsmittel",
      "min": 1,
      "type": "Sachleistung / Leihgabe",
      "amount": "Bedarfsabhängige Versorgung",
      "about": "Etwa ein Pflegebett oder Lagerungshilfen zur Erleichterung der Pflege.",
      "condition": "Die Kasse prüft, ob das Hilfsmittel nötig ist und wer es bezahlt. Oft wird es ausgeliehen. Erwachsene zahlen in der Regel 10 %, höchstens 25 € je Hilfsmittel. Ausnahmen sind möglich.",
      "next": "Hilfsmittel konkret benennen und Antrag beziehungsweise Empfehlung mit der Pflegekasse abstimmen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__40.html"
    },
    {
      "id": "notruf",
      "title": "Hausnotruf",
      "category": "Hilfsmittel",
      "min": 1,
      "type": "Technisches Pflegehilfsmittel",
      "amount": "Grundversorgung nach Bewilligung",
      "about": "Ein Notrufsystem kann schnelle Hilfe ermöglichen.",
      "condition": "Häufig möglich, wenn du einen Pflegegrad hast, ein Notfall jederzeit eintreten kann und du dann ohne das Gerät keine Hilfe rufen könntest. Meist lebst du überwiegend allein oder mit Personen, die selbst keinen Notruf auslösen können. Anerkannten Anbieter, Grundversorgung und Zusatzkosten vor Abschluss prüfen. Nicht Teil der 42 € für Verbrauchshilfsmittel.",
      "next": "Pflegekasse nach anerkannten Anbietern und übernommener Grundversorgung fragen.",
      "source": "https://gesund.bund.de/hausnotruf"
    },
    {
      "id": "umbau",
      "search": "Bad Dusche Treppenlift Rampe barrierefrei",
      "title": "Wohnumfeld verbessern",
      "category": "Wohnen",
      "min": 1,
      "type": "Zuschuss je Maßnahme",
      "amount": "Bis zu 4.180 € je Maßnahme",
      "about": "Zum Beispiel geeignete Anpassungen im Bad oder beim Wohnungszugang.",
      "condition": "Pflege muss ermöglicht, erleichtert oder Selbstständigkeit unterstützt werden. Mehrere gleichzeitig erforderliche Umbauten zählen nicht automatisch als getrennte Maßnahmen. Bei mehreren Berechtigten insgesamt höchstens 16.720 €.",
      "next": "Vor Beginn Antrag und Kostenvoranschlag einreichen; Bewilligung abwarten beziehungsweise Vorgehen abstimmen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__40.html"
    },
    {
      "id": "dipa",
      "title": "Digitale Pflegeanwendungen (DiPA)",
      "category": "Hilfsmittel",
      "min": 1,
      "type": "Genehmigte Pflege-App",
      "amount": "Bis zu 40 € monatlich",
      "about": "Geprüfte digitale Anwendungen können die häusliche Pflege unterstützen.",
      "condition": "Nur offiziell gelistete und von der Pflegekasse bewilligte Anwendungen. Informations- und Antragsverwaltungs-Apps zählen nicht allein deshalb als DiPA. Für AnspruchsKompass besteht keine solche Erstattungszusage.",
      "next": "Aktuelle Verzeichnisaufnahme und Bewilligung vor dem Kauf prüfen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__40b.html",
      "sources": [
        "https://www.gesetze-im-internet.de/sgb_11/__40a.html",
        "https://www.gesetze-im-internet.de/sgb_11/__40b.html"
      ]
    },
    {
      "id": "dipahelp",
      "title": "Unterstützung bei DiPA-Nutzung",
      "category": "Hilfsmittel",
      "min": 1,
      "type": "Ergänzende Leistung",
      "amount": "Bis zu 30 € monatlich",
      "about": "Ambulante Pflegeeinrichtungen können bei der Nutzung einer bewilligten DiPA unterstützen.",
      "condition": "Erforderliche Hilfe durch eine zugelassene ambulante Pflegeeinrichtung bei einer bewilligten DiPA. Eigener Höchstrahmen zusätzlich zur Anwendung, keine freie Auszahlung. Mehrkosten können bei dir bleiben.",
      "next": "Benötigte Hilfe und zugelassenen Leistungserbringer mit der Pflegekasse klären.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__40b.html",
      "sources": [
        "https://www.gesetze-im-internet.de/sgb_11/__39a.html",
        "https://www.gesetze-im-internet.de/sgb_11/__40b.html"
      ]
    },
    {
      "id": "wg",
      "title": "Wohngruppenzuschlag",
      "category": "Wohnen",
      "min": 1,
      "type": "Geld für einen bestimmten Zweck",
      "amount": "224 € monatlich",
      "about": "Für Menschen, die in einer passenden Pflege-WG leben und die Hilfe gemeinsam organisieren.",
      "condition": "Drei bis zwölf Bewohnerinnen und Bewohner; mindestens drei sind pflegebedürftig. Eine Person muss gemeinsam für übergreifende Aufgaben beauftragt sein. Das Angebot darf nicht weitgehend einer vollstationären Versorgung entsprechen. Zusätzliche Tagespflege erfordert einen besonderen Nachweis durch den Medizinischen Dienst.",
      "next": "Pflegekasse das konkrete Wohn- und Organisationsmodell vorlegen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__45f.html"
    },
    {
      "id": "wgstart",
      "title": "Anschubfinanzierung einer Pflege-WG",
      "category": "Wohnen",
      "min": 1,
      "type": "Einmaliger Zuschuss",
      "amount": "Bis zu 2.613 € pro berechtigter Person",
      "about": "Unterstützung beim Aufbau einer anspruchsberechtigten ambulant betreuten Wohngruppe.",
      "condition": "Für anspruchsberechtigte Mitgründer einer Pflege-WG zur passenden Umgestaltung der gemeinsamen Wohnung. Maximal 10.452 € je WG. Antrag innerhalb eines Jahres, nachdem die Voraussetzungen des Wohngruppenzuschlags vorliegen. Die Förderung endet, wenn der gesetzliche bundesweite Förderrahmen ausgeschöpft ist.",
      "next": "Gründung, Umbau, Einjahresfrist und noch verfügbare Förderung frühzeitig mit der Pflegekasse klären.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__45g.html"
    },
    {
      "id": "wohnform",
      "title": "Gemeinschaftliche Wohnform mit Versorgungsvertrag",
      "category": "Wohnen",
      "min": 1,
      "type": "Besondere Versorgungsform",
      "amount": "450 € monatlicher Pauschalzuschuss",
      "about": "Für spezielle Wohnformen mit Verträgen nach § 92c SGB XI.",
      "condition": "Nur mit besonderem Versorgungsvertrag nach § 92c. Ab Pflegegrad 2 können Sachleistungen und anteiliges Pflegegeld hinzukommen. Entlastungsbetrag, Verhinderungspflege und Wohngruppenzuschlag sind dabei keine zusätzlichen Standardtöpfe. Kurzzeitpflege ist hier auf die besondere gesetzliche Übergangssituation begrenzt.",
      "next": "Vor Einzug Pflegekasse den Vertrag und das gesamte Leistungspaket prüfen lassen. Diese Wohnform wird im Schnellrechner nicht individuell abgebildet.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__45h.html",
      "sources": [
        "https://www.gesetze-im-internet.de/sgb_11/__45h.html",
        "https://www.gesetze-im-internet.de/sgb_11/__92c.html"
      ]
    },
    {
      "id": "heim",
      "title": "Vollstationäre Pflege",
      "category": "Einrichtungen",
      "min": 1,
      "type": "Hilfe im Pflegeheim",
      "rates": [
        0,
        131,
        805,
        1319,
        1855,
        2096
      ],
      "unit": "monatlich",
      "amount": "131–2.096 € monatlich, je nach Pflegegrad",
      "about": "Die Pflegeversicherung beteiligt sich an der Versorgung im Pflegeheim.",
      "condition": "Pflegegrad 1: 131-€-Zuschuss. Ab Pflegegrad 2 gelten höhere Pauschalen. Unterkunft, Verpflegung, Investitionskosten und verbleibende Pflegekosten können Eigenanteile sein.",
      "next": "Lass dir schriftlich zeigen, was die Kasse zahlt und was du selbst bezahlen musst.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__43.html"
    },
    {
      "id": "heimzuschlag",
      "title": "Zuschlag zum Pflege-Eigenanteil im Heim",
      "category": "Einrichtungen",
      "min": 2,
      "type": "Prozentualer Zuschlag",
      "amount": "15 %, 30 %, 50 % oder 75 %",
      "about": "Der Zuschlag steigt mit der Dauer der vollstationären Versorgung.",
      "condition": "Pflegegrad 2–5: 15 % bis einschließlich zwölf Monate, 30 % bei mehr als zwölf, 50 % bei mehr als 24 und 75 % bei mehr als 36 Monaten. Auch angefangene Bezugsmonate zählen. Nur bestimmte Pflege-Eigenanteile werden gesenkt, nicht Unterkunft, Essen oder die ganze Heimrechnung.",
      "next": "Anrechenbare Aufenthaltsdauer und Zuschlagsberechnung prüfen lassen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__43c.html"
    },
    {
      "id": "behinderten",
      "title": "Pflege in besonderen Einrichtungen der Eingliederungshilfe",
      "category": "Einrichtungen",
      "min": 2,
      "type": "Fester Zuschuss",
      "amount": "15 % der maßgeblichen Vergütung, höchstens 278 € monatlich",
      "about": "Sonderregelung für bestimmte vollstationäre Einrichtungen oder gleichgestellte Räumlichkeiten.",
      "condition": "Die Regel gilt nur für bestimmte Wohnangebote für Menschen mit Behinderung. Die Einrichtung und die Kasse müssen prüfen, welche Hilfen zusammenpassen.",
      "next": "§-43a-Zuordnung mit Einrichtung und Kasse klären. Für Tage mit Pflege zu Hause kann daneben anteiliges Pflegegeld infrage kommen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__43a.html",
      "sources": [
        "https://www.gesetze-im-internet.de/sgb_11/__43a.html",
        "https://www.gesetze-im-internet.de/sgb_11/__38.html"
      ]
    },
    {
      "id": "aktivierung",
      "title": "Zusätzliche Betreuung und Aktivierung",
      "category": "Einrichtungen",
      "min": 1,
      "type": "Zusätzliches Angebot",
      "amount": "Betreuung statt Geldpauschale",
      "about": "Zusätzliche Aktivierungs- und Betreuungsangebote in stationären Pflegeeinrichtungen.",
      "condition": "Kein persönliches frei auszahlbares Budget. Zusätzlich zur notwendigen Versorgung durch die Einrichtung.",
      "next": "Einrichtung nach konkreten Angeboten und zuständigen Betreuungskräften fragen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__43b.html"
    },
    {
      "id": "rehapflege",
      "title": "Versorgung während Reha oder Vorsorge der Pflegeperson",
      "category": "Angehörige",
      "min": 1,
      "type": "Situationsbezogene Versorgung",
      "amount": "Kostenübernahme nach Einzelfall",
      "about": "Wenn die Pflegeperson selbst eine Vorsorge- oder Rehabilitationsleistung nutzt, kann die Versorgung der pflegebedürftigen Person organisiert werden.",
      "condition": "Nur bei passender stationärer Vorsorge oder Reha der Pflegeperson und gesicherter Mitversorgung. Ein vorrangiger Anspruch gegen die Krankenkasse wird geprüft. Pflege, Unterkunft, Essen und notwendige Fahrkosten können umfasst sein. Häusliche Leistungen einschließlich Pflegegeld ruhen während dieser besonderen Versorgung grundsätzlich.",
      "next": "Mitversorgung oder Ersatzort vor der Maßnahme mit Pflegekasse und Reha-Träger planen. Notwendige besondere Beförderung vorher beantragen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__42b.html"
    },
    {
      "id": "rente",
      "title": "Rentenbeiträge für Pflegepersonen",
      "category": "Angehörige",
      "min": 2,
      "type": "Soziale Absicherung",
      "amount": "Beiträge zur Rentenversicherung",
      "about": "Wer jemanden zu Hause pflegt und das nicht beruflich tut, kann dadurch seine spätere Rente verbessern.",
      "condition": "Meist musst du mindestens zehn Stunden pro Woche an mindestens zwei Tagen pflegen und darfst höchstens 30 Stunden pro Woche arbeiten. Weitere Bedingungen werden geprüft. Die Beiträge gehen an die Rentenversicherung.",
      "next": "Fragebogen zur sozialen Sicherung bei der Pflegekasse anfordern.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__44.html"
    },
    {
      "id": "pauschbetrag",
      "title": "Pflege-Pauschbetrag (Steuer)",
      "category": "Angehörige",
      "min": 2,
      "type": "Steuervorteil über das Finanzamt",
      "amount": "600–1.800 € im Jahr weniger zu versteuern",
      "about": "Wer einen Angehörigen zu Hause selbst pflegt, kann in der Steuererklärung einen festen Betrag abziehen, ohne Belege zu sammeln. Das ist keine Leistung der Pflegekasse, sondern läuft über das Finanzamt.",
      "condition": "Du pflegst persönlich und unentgeltlich, in deiner Wohnung oder in der Wohnung der gepflegten Person. Pflegegrad 2: 600 €, Pflegegrad 3: 1.100 €, Pflegegrad 4 oder 5 oder Merkzeichen H: 1.800 € im Jahr. Pflegen mehrere Personen, wird der Betrag geteilt. Wenn du das Pflegegeld für dich behältst, kann der Betrag entfallen. Er lohnt sich nur, wenn du Einkommensteuer zahlst.",
      "next": "In der Steuererklärung bei den außergewöhnlichen Belastungen eintragen und den Pflegegrad-Bescheid bereithalten. Bei Fragen hilft eine Steuerberatung.",
      "source": "https://www.gesetze-im-internet.de/estg/__33b.html"
    },
    {
      "id": "unfall",
      "title": "Gesetzlicher Unfallversicherungsschutz",
      "category": "Angehörige",
      "min": 2,
      "type": "Soziale Absicherung",
      "amount": "Beitragsfreier Schutz bei versicherten Tätigkeiten",
      "about": "Unter Voraussetzungen besteht Schutz bei Unfällen im Zusammenhang mit nicht erwerbsmäßiger Pflege.",
      "condition": "Nicht berufliche Pflege zu Hause ab Pflegegrad 2, mindestens zehn Stunden pro Woche an regelmäßig mindestens zwei Tagen; Zeiten für mehrere Pflegebedürftige können zusammenzählen. Schutz nur bei versicherten Tätigkeiten, keine zusätzliche Geldpauschale.",
      "next": "Versicherungsschutz und zuständigen Unfallversicherungsträger klären.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__44.html",
      "sources": [
        "https://www.gesetze-im-internet.de/sgb_11/__19.html",
        "https://www.gesetze-im-internet.de/sgb_11/__44.html",
        "https://www.gesetze-im-internet.de/sgb_7/__2.html"
      ]
    },
    {
      "id": "arbeitslos",
      "title": "Arbeitslosenversicherung für Pflegepersonen",
      "category": "Angehörige",
      "min": 2,
      "type": "Soziale Absicherung",
      "amount": "Beitragszahlung bei erfüllten Voraussetzungen",
      "about": "Wer für die Pflege aus dem Beruf ausscheidet, kann unter Voraussetzungen weiter abgesichert sein.",
      "condition": "Pflege ab Pflegegrad 2 zu Hause, mindestens zehn Wochenstunden an regelmäßig zwei Tagen. Unmittelbar davor musst du grundsätzlich arbeitslosenversichert gewesen sein oder eine laufende Entgeltersatzleistung nach dem SGB III bezogen haben. Weitere Ausschlüsse werden geprüft.",
      "next": "Frage die Pflegekasse, ob sie Beiträge für dich übernimmt.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__44.html",
      "sources": [
        "https://www.gesetze-im-internet.de/sgb_11/__44.html",
        "https://www.gesetze-im-internet.de/sgb_3/__26.html"
      ]
    },
    {
      "id": "akut",
      "title": "Pflegeunterstützungsgeld",
      "category": "Angehörige",
      "min": 0,
      "type": "Lohnersatz",
      "amount": "Bis zu zehn Arbeitstage je Kalenderjahr und pflegebedürftiger Person",
      "about": "Für Beschäftigte, die in einer akuten Pflegesituation die Versorgung naher Angehöriger organisieren müssen.",
      "condition": "Akute Pflegesituation eines nahen Angehörigen; Pflegegrad muss noch nicht feststehen. Nur bei entgangenem Arbeitsentgelt ohne vorrangige Entgeltfortzahlung. Mehrere Angehörige teilen sich bis zu zehn Arbeitstage pro Jahr und pflegebedürftiger Person.",
      "next": "Arbeitgeber sofort informieren. Antrag unverzüglich bei der Pflegeversicherung der betroffenen Person stellen und ärztlichen Nachweis oder Bescheinigung einer Pflegefachperson beifügen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__44a.html"
    },
    {
      "id": "pflegezeit",
      "title": "Versicherungszuschüsse während Pflegezeit",
      "category": "Angehörige",
      "min": 0,
      "type": "Versicherungszuschuss",
      "amount": "Abhängig von Versicherung und Beiträgen",
      "about": "Bei Pflegezeit können Zuschüsse zur Kranken- und Pflegeversicherung infrage kommen.",
      "condition": "Auf Antrag bei vollständiger Freistellung nach Pflegezeitgesetz oder Reduzierung auf eine geringfügige Beschäftigung. Beitragsfreie Familienversicherung geht vor. Höhe und weitere Voraussetzungen hängen von deiner Versicherung ab; kein voller Lohnersatz. Auch eine passende Freistellung zur Sterbebegleitung ohne anerkannten Pflegegrad gesondert prüfen.",
      "next": "Vor Freistellung Krankenversicherung und Pflegekasse nach Absicherung und Antrag fragen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__44a.html",
      "sources": [
        "https://www.gesetze-im-internet.de/sgb_11/__44a.html",
        "https://www.gesetze-im-internet.de/pflegezg/__3.html"
      ]
    },
    {
      "id": "beratung",
      "title": "Individuelle Pflegeberatung & Versorgungsplan",
      "category": "Beratung",
      "min": 0,
      "type": "Kostenfreie Beratung",
      "amount": "Beratung statt Geldbetrag",
      "about": "Ansprüche und passende Versorgung gemeinsam mit einer Pflegeberatung ordnen.",
      "condition": "Auch im Zusammenhang mit der Antragstellung. Angehörige können mit Zustimmung der pflegebedürftigen Person einbezogen werden.",
      "next": "Termin bei Pflegekasse oder Pflegestützpunkt vereinbaren; bei Bedarf einen Versorgungsplan anfordern.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__7a.html"
    },
    {
      "id": "besuch",
      "title": "Beratungseinsatz zu Hause",
      "category": "Beratung",
      "min": 1,
      "type": "Beratung / Qualitätssicherung",
      "amount": "Kostenübernahme nach Regelung",
      "about": "Praktische Unterstützung und Beratung zur häuslichen Pflegesituation.",
      "condition": "Bei Bezug von Pflegegeld ist für Pflegegrad 2–5 einmal je Halbjahr eine Beratung Pflicht. Mit Pflegegrad 4 oder 5 ist zusätzlich vierteljährliche Beratung möglich. Bei Pflegegrad 1 oder Sachleistungsbezug ist halbjährliche Beratung freiwillig möglich. Fehlende Pflichtberatung kann das Pflegegeld gefährden.",
      "next": "Pflegekasse nach nächstem erforderlichen Termin und zugelassenen Beratenden fragen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__37.html"
    },
    {
      "id": "kurs",
      "title": "Pflegekurse & Schulung zu Hause",
      "category": "Beratung",
      "min": 0,
      "type": "Kostenfreie Schulung",
      "amount": "Schulung statt Geldbetrag",
      "about": "Angehörige und ehrenamtlich Pflegende lernen hilfreiche Handgriffe und erhalten Unterstützung.",
      "condition": "Keine frei auszahlbare Prämie. Auch individuelle Schulung im häuslichen Umfeld kann möglich sein.",
      "next": "Pflegekasse nach passenden Kursen und häuslicher Anleitung fragen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__45.html"
    },
    {
      "id": "persbudget",
      "title": "Persönliches Budget",
      "category": "Beratung",
      "min": 1,
      "type": "Andere Leistungsform",
      "amount": "Individuell vereinbart",
      "about": "Bestimmte Hilfen mehrerer Stellen können gemeinsam geplant und als Persönliches Budget organisiert werden.",
      "condition": "Keine zusätzliche Förderung und keine doppelte Leistung. Nur bestimmte Leistungen sind budgetfähig. Sachleistungen für Pflegedienste und Tagespflege werden dabei als Gutscheine für zugelassene Anbieter bereitgestellt, nicht frei ausgezahlt.",
      "next": "Bei Pflegeberatung oder zuständigem Rehabilitationsträger nach Umsetzung fragen.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__35a.html"
    },
    {
      "id": "vergleich",
      "title": "Anbietervergleich, Qualität & Selbsthilfe",
      "category": "Beratung",
      "min": 0,
      "type": "Information & Unterstützung",
      "amount": "Kein persönliches Geldbudget",
      "about": "Pflegekassen helfen mit Informationen über Angebote, Preise, Qualität und Selbsthilfe.",
      "condition": "Regionale Verfügbarkeit und tatsächliche Kosten unterscheiden sich. Förderungen für Selbsthilfestrukturen sind kein individuelles Auszahlungsguthaben.",
      "next": "Aktuelle Vergleichslisten und Kontakte vor Ort anfordern.",
      "source": "https://www.gesetze-im-internet.de/sgb_11/__7.html"
    }
  ]
};
root.AKCatalog=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
