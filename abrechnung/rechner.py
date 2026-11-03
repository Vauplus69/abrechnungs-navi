#!/usr/bin/env python3
"""Abrechnungs-Navi: Rechenwerk für die Nebenkostenabrechnung.

Eingabe:  eine JSON-Datei mit Objekt, Zeitraum, Kosten und Mietern (siehe beispiel.json)
Ausgabe:  je Mieter eine PDF-Abrechnung + ein Prüfbericht (pruefbericht.txt) für die Durchsicht

Aufruf:   python3 rechner.py auftrag.json ausgabe-ordner/

Hinweise:
- Rechnet nach den Angaben im Auftrag. Ob eine Kostenart umlagefähig und im Mietvertrag
  vereinbart ist, prüft der Mensch bei der Durchsicht (der Prüfbericht weist auf Auffälliges hin).
- Heizkosten werden aus der Abrechnung des Messdienstes übernommen (Betrag je Mieter).
- CO2-Kosten: Stufenmodell nach Anlage zum CO2KostAufG (Wohngebäude).
"""
import json
import os
import sys
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from copy import deepcopy
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Mitgelieferte Unicode-Schriften: identische Ausgabe unter macOS und Linux.
FONT, FONT_B = "AN", "AN-B"
FONT_DIR = Path(__file__).resolve().parent / "fonts"
for name, filename in [(FONT, "DejaVuSans.ttf"), (FONT_B, "DejaVuSans-Bold.ttf")]:
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / filename)))
pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_B, italic=FONT, boldItalic=FONT_B)

SCHLUESSEL = {
    "wohnflaeche": ("Wohnfläche", "m²"),
    "personen": ("Personen", "Pers."),
    "einheiten": ("Wohneinheiten", "WE"),
    "verbrauch": ("Verbrauch", ""),
    "direkt": ("direkte Zuordnung", ""),
}

# Anlage zum CO2KostAufG: (Grenze in kg CO2/m²/a, Vermieteranteil)
CO2_STUFEN = [(12, 0.00), (17, 0.10), (22, 0.20), (27, 0.30), (32, 0.40),
              (37, 0.50), (42, 0.60), (47, 0.70), (52, 0.80), (float("inf"), 0.95)]

# Wörter, die auf nicht umlagefähige Kosten hindeuten (nur Hinweis für die Durchsicht)
VERDAECHTIG = ["verwaltung", "instandhaltung", "instandsetzung", "reparatur", "bankgebühr", "kontoführung",
               "porto", "rücklage", "erhaltung", "darlehen", "zins", "mahnung", "rechtsanwalt"]


def eur(x):
    x = Decimal(str(x))
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if x < 0 else "") + s + " €"


def num(x, nk=2):
    x = Decimal(str(x))
    if float(x).is_integer() and nk == 2:
        nk = 0
    return f"{x:,.{nk}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tage(von, bis):
    return (date.fromisoformat(bis) - date.fromisoformat(von)).days + 1


def ueberlappung(a_von, a_bis, b_von, b_bis):
    von, bis = max(a_von, b_von), min(a_bis, b_bis)
    return max(0, tage(von, bis)) if von <= bis else 0


def co2_vermieteranteil(kg_pro_m2):
    for grenze, anteil in CO2_STUFEN:
        if kg_pro_m2 < grenze:
            return anteil
    return 0.95


def zahl(value, label, positiv=False):
    if isinstance(value, bool):
        raise ValueError(f"{label}: Zahl erforderlich")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label}: gültige Zahl erforderlich") from None
    if not result.is_finite() or result < 0 or (positiv and result == 0):
        raise ValueError(f"{label}: endliche {'positive' if positiv else 'nicht negative'} Zahl erforderlich")
    return result


def cent(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def geld(value, label):
    result = zahl(value, label)
    if result != cent(result):
        raise ValueError(f"{label}: höchstens zwei Nachkommastellen")
    return result


def belegt(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: Beleg-/Prüfreferenz erforderlich")


def berechne(auftrag):
    # Keine abgeleiteten Werte in den Eingabedaten speichern.
    auftrag = deepcopy(auftrag)
    z_von, z_bis = auftrag["zeitraum"]["von"], auftrag["zeitraum"]["bis"]
    start, end = date.fromisoformat(z_von), date.fromisoformat(z_bis)
    if end < start or tage(z_von, z_bis) > 366:
        raise ValueError("Abrechnungszeitraum ungültig oder länger als ein Jahr")
    z_tage = tage(z_von, z_bis)
    obj = auftrag["objekt"]
    area = zahl(obj["wohnflaeche_gesamt"], "Gesamtwohnfläche", True)
    units = zahl(obj["einheiten_gesamt"], "Wohneinheiten", True)
    if units != units.to_integral_value():
        raise ValueError("Wohneinheiten müssen ganzzahlig sein")
    if not auftrag["mieter"]:
        raise ValueError("Keine Mietparteien vorhanden")
    hinweise, ergebnisse = [], []
    tenants = auftrag["mieter"]
    ids = [(m["name"], m.get("wohnung", ""), m.get("von", z_von)) for m in tenants]
    if len(set(ids)) != len(ids):
        raise ValueError("Doppelte Mietpartei/Nutzungsperiode")
    for m in tenants:
        m_von, m_bis = m.get("von", z_von), m.get("bis", z_bis)
        date.fromisoformat(m_von); date.fromisoformat(m_bis)
        if m_von < z_von or m_bis > z_bis or m_von > m_bis:
            raise ValueError(f"{m['name']}: Nutzungszeitraum muss innerhalb der Abrechnungsperiode liegen")
        zahl(m["wohnflaeche"], f"{m['name']}: Wohnfläche", True)
        geld(m["vorauszahlungen"], f"{m['name']}: Vorauszahlungen")
        if "co2_bereits_abgezogen" in m:
            raise ValueError("Altes CO2-Kennzeichen unzulässig; heizkosten_status und Messdienstbeleg angeben")
    costs = []
    names = set()
    for k in auftrag["kosten"]:
        name = k["name"]
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("Kostenbezeichnungen müssen eindeutig und nicht leer sein")
        names.add(name)
        geld(k["betrag"], name)
        if k.get("umlegen") is False:
            hinweise.append(f"Ausgeschlossen: {name} ({eur(k['betrag'])}), keine Belastung der Mieter.")
            continue
        if any(w in name.lower() for w in VERDAECHTIG):
            raise ValueError(f"{name}: gesperrte Kostenart; separat fachlich klären und nicht umlegen")
        if k.get("umlage_geprueft") is not True:
            raise ValueError(f"{name}: Umlagefähigkeit und vertraglicher Schlüssel nicht bestätigt")
        belegt(k.get("beleg"), name)
        if k["schluessel"] not in SCHLUESSEL:
            raise ValueError(f"Unbekannter Schlüssel bei {name}")
        costs.append(k)
    co2 = auftrag.get("co2")
    if co2:
        # Verkürzte/abweichende CO2-Zeiträume erst nach separater Fachberechnung.
        if start.month != 1 or start.day != 1 or end != date(start.year, 12, 31):
            raise ValueError("CO2: automatischer Rechner unterstützt nur vollständige Kalenderjahre; verkürzten/abweichenden Zeitraum fachlich separat berechnen")
        belegt(co2.get("beleg"), "CO2-Gebäudewerte")
        if co2.get("wohngebaeude_regelfall_geprueft") is not True:
            raise ValueError("CO2: Wohngebäude-Regelfall ohne Sonderbegrenzungen muss fachlich bestätigt sein")
        co2["kg_pro_m2"] = zahl(co2["kg_co2_gesamt"], "CO2-Ausstoß") / area
        co2["vermieteranteil"] = Decimal(str(co2_vermieteranteil(co2["kg_pro_m2"])))
    person_days = any(k["schluessel"] == "personen" for k in costs)
    if person_days:
        if "personentage_gesamt" not in obj:
            raise ValueError("Personenschlüssel erfordert belegte personentage_gesamt und Personentage jeder Mietpartei")
        total_person_days = zahl(obj["personentage_gesamt"], "Personentage gesamt", True)
        belegt(obj.get("personentage_beleg"), "Personentage")
        for m in tenants:
            zahl(m.get("personentage"), f"{m['name']}: Personentage")
    sums = {k["name"]: Decimal(0) for k in costs}
    quantities = {k["name"]: Decimal(0) for k in costs}
    for m in tenants:
        m_tage = tage(m.get("von", z_von), m.get("bis", z_bis))
        zeitanteil = Decimal(m_tage) / Decimal(z_tage)
        posten = []
        for k in costs:
            name, key = k["name"], k["schluessel"]
            total = geld(k["betrag"], name)
            if key == "direkt":
                value = geld(m.get("direkt", {}).get(name), f"{m['name']}: {name} direkte Zuordnung")
                text = "direkt zugeordnet (belegt)"
            elif key == "verbrauch":
                own = zahl(m.get("verbrauch", {}).get(name), f"{m['name']}: {name} Verbrauch")
                denominator = zahl(k.get("verbrauch_gesamt"), name + " Gesamtverbrauch", True)
                quantities[name] += own
                value = total * own / denominator
                text = f"{num(own)} von {num(denominator)} {k.get('einheit', '')}".strip()
            elif key == "personen":
                own = zahl(m["personentage"], "Personentage")
                quantities[name] += own
                value = total * own / total_person_days
                text = f"{num(own)} von {num(total_person_days)} Personentagen"
            else:
                own = zahl(m["wohnflaeche"], "Wohnfläche", True) if key == "wohnflaeche" else Decimal(1)
                denominator = area if key == "wohnflaeche" else units
                quantities[name] += own * zeitanteil
                value = total * own / denominator * zeitanteil
                text = f"{num(own)} von {num(denominator)} {SCHLUESSEL[key][1]}"
                if zeitanteil < 1:
                    text += f", {m_tage} von {z_tage} Tagen"
            value = cent(value)
            sums[name] += value
            posten.append({"name": name, "gesamt": float(total), "schluessel": SCHLUESSEL[key][0],
                           "berechnung": text, "anteil": float(value)})
        if m.get("heizkosten") is not None:
            heat = geld(m["heizkosten"], "Heizkosten")
            status = m.get("heizkosten_status")
            if status not in ("vor_co2_abzug", "nach_co2_abzug"):
                raise ValueError("Messdienst: heizkosten_status vor_co2_abzug oder nach_co2_abzug erforderlich")
            belegt(m.get("messdienst_beleg"), "Messdienst")
            if not co2:
                raise ValueError("Heizkosten: CO2-Grundlagen fehlen; Sonderfälle separat prüfen")
            gross_co2 = geld(m.get("co2_kosten_anteil"), "CO2-Kostenanteil vor Abzug")
            deduction = cent(gross_co2 * co2["vermieteranteil"])
            if status == "vor_co2_abzug" and gross_co2 > heat:
                raise ValueError("CO2-Kosten übersteigen Heizkosten")
            posten.append({"name": "Heiz- und Warmwasserkosten (laut Messdienst)", "gesamt": None,
                           "schluessel": "Messdienst", "berechnung": "vor CO₂-Vermieterabzug" if status == "vor_co2_abzug" else "nach CO₂-Vermieterabzug", "anteil": float(heat)})
            if status == "vor_co2_abzug" and deduction:
                posten.append({"name": f"abzüglich Vermieteranteil CO₂-Kosten ({int(co2['vermieteranteil']*100)} %)",
                               "gesamt": None, "schluessel": "CO2KostAufG",
                               "berechnung": f"{num(co2['kg_pro_m2'], 1)} kg CO₂/m²/Jahr", "anteil": -float(deduction)})
            if status == "nach_co2_abzug":
                actual = geld(m.get("co2_vermieterabzug"), "Messdienst CO2-Vermieterabzug")
                if actual != deduction:
                    raise ValueError("Messdienst CO2-Abzug stimmt nicht mit berechnetem Anteil überein")
                hinweise.append(f"{m['name']}: CO2-Vermieteranteil {eur(float(actual))} bereits im Messdienstbetrag abgezogen; kein zweiter Abzug.")
        total = sum((Decimal(str(p["anteil"])) for p in posten), Decimal(0))
        advance = geld(m["vorauszahlungen"], "Vorauszahlungen")
        ergebnisse.append({"mieter": m, "tage": m_tage, "zeitanteil": float(zeitanteil), "posten": posten,
                           "summe": float(total), "vorauszahlungen": float(advance), "saldo": float(total-advance),
                           "co2": deepcopy(co2)})
    for k in costs:
        name, key = k["name"], k["schluessel"]
        total = geld(k["betrag"], name)
        # Höchstens ein halber Cent Rundung je Mietpartei, keine stillen Datenreste.
        tolerance = Decimal("0.005") * len(tenants)
        rest = total - sums[name]
        if key == "verbrauch":
            denominator = zahl(k["verbrauch_gesamt"], name, True)
        elif key == "personen":
            denominator = total_person_days
        elif key == "wohnflaeche":
            denominator = area
        elif key == "einheiten":
            denominator = units
        else:
            denominator = None
        if denominator is not None and quantities[name] > denominator + Decimal("0.00000001"):
            raise ValueError(f"{name}: zugeordnete Mengen/Zeitanteile überschreiten den Gesamtwert")
        unallocated = k.get("vermieter_rest")
        expected = Decimal(0)
        if unallocated is not None:
            expected = geld(unallocated.get("betrag"), name + " Vermieterrest")
            belegt(unallocated.get("grund"), name + " Restursache")
            belegt(unallocated.get("beleg"), name + " Restnachweis")
        if abs(rest - expected) > tolerance:
            raise ValueError(f"{name}: ungeklärte Kostendifferenz {eur(float(rest))}; belegten Vermieterrest oder Eingabedaten korrigieren")
        if denominator is not None and quantities[name] < denominator - Decimal("0.00000001") and unallocated is None:
            raise ValueError(f"{name}: ungeklärte Mengen-/Zeitdifferenz; belegte Zuordnung erforderlich")
        if unallocated:
            hinweise.append(f"{name}: Vermieterrest {eur(float(expected))}; {unallocated['grund']}; Beleg: {unallocated['beleg']}.")
        elif rest:
            hinweise.append(f"{name}: Rundungsdifferenz {eur(float(rest))}; keine automatische Nachbelastung.")
    if co2:
        hinweise.append(f"CO₂-Ausstoß {num(co2['kg_pro_m2'], 1)} kg/m²/Jahr; Vermieteranteil {int(co2['vermieteranteil']*100)} %; Beleg: {co2['beleg']}.")
    return ergebnisse, hinweise


def pdf(auftrag, e, pfad):
    st = getSampleStyleSheet()
    klein = ParagraphStyle("klein", parent=st["Normal"], fontName=FONT, fontSize=8.5, leading=11)
    norm = ParagraphStyle("norm", parent=st["Normal"], fontName=FONT, fontSize=10, leading=13.5)
    h1 = ParagraphStyle("h1", parent=st["Heading1"], fontName=FONT_B, fontSize=15, spaceAfter=4)
    vm, m, obj = auftrag["vermieter"], e["mieter"], auftrag["objekt"]
    esc = lambda value: escape(str(value))
    z = auftrag["zeitraum"]
    fmt = lambda d: date.fromisoformat(d).strftime("%d.%m.%Y")
    story = [
        Paragraph(f"{esc(vm['name'])} · {esc(vm['anschrift'])}", klein), Spacer(1, 6 * mm),
        Paragraph(f"{esc(m['name'])}<br/>{esc(m.get('anschrift', obj['anschrift']))}", norm), Spacer(1, 10 * mm),
        Paragraph(f"Betriebskostenabrechnung {fmt(z['von'])} – {fmt(z['bis'])}", h1),
        Paragraph(f"Objekt: {esc(obj['anschrift'])} · Wohnung: {esc(m.get('wohnung', ''))} · "
                  f"Ihr Nutzungszeitraum: {fmt(m.get('von', z['von']))} – {fmt(m.get('bis', z['bis']))} ({e['tage']} Tage)", norm),
        Spacer(1, 5 * mm),
    ]
    if auftrag.get("testauftrag") is True:
        story.insert(0, Paragraph("MUSTER - keine echte Abrechnung", h1))
    rows = [["Kostenart", "Gesamtkosten", "Verteilung", "Ihr Anteil"]]
    for p in e["posten"]:
        rows.append([Paragraph(esc(p["name"]), klein), eur(p["gesamt"]) if p["gesamt"] is not None else "",
                     Paragraph(f"{esc(p['schluessel'])}: {esc(p['berechnung'])}", klein), eur(p["anteil"])])
    rows += [["Summe Ihrer Kosten", "", "", eur(e["summe"])],
             ["abzüglich Ihrer Vorauszahlungen", "", "", eur(-e["vorauszahlungen"])],
             ["Nachzahlung" if e["saldo"] > 0 else "Guthaben", "", "", eur(abs(e["saldo"]))]]
    t = Table(rows, colWidths=[62 * mm, 28 * mm, 58 * mm, 26 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), FONT_B, 9), ("FONT", (0, 1), (-1, -1), FONT, 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e3f1ec")), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#1f6f5c")),
        ("LINEABOVE", (0, -3), (-1, -3), 0.6, colors.black),
        ("FONT", (0, -1), (-1, -1), FONT_B, 10), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f6f8f7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -4), [colors.white, colors.HexColor("#fafbfb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [t, Spacer(1, 6 * mm)]
    if e["saldo"] > 0:
        story.append(Paragraph(f"Bitte überweisen Sie die Nachzahlung von <b>{eur(e['saldo'])}</b> innerhalb von 30 Tagen "
                               f"nach Erhalt dieser Abrechnung auf das Ihnen bekannte Konto.", norm))
    else:
        story.append(Paragraph(f"Ihr Guthaben von <b>{eur(abs(e['saldo']))}</b> wird Ihnen erstattet.", norm))
    if e.get("co2") and m.get("heizkosten") is not None:
        c = e["co2"]
        info = (f"CO₂-Grundlagen: {num(c['kg_co2_gesamt'])} kg im Kalenderjahr, "
                f"{num(obj['wohnflaeche_gesamt'])} m², {num(c['kg_pro_m2'], 2)} kg/m²/Jahr. "
                f"CO₂-Kosten Ihrer Einheit vor Aufteilung: {eur(m['co2_kosten_anteil'])}. "
                f"Vermieteranteil {int(c['vermieteranteil']*100)} %, Mieteranteil {100-int(c['vermieteranteil']*100)} %. "
                + ("Der Vermieteranteil ist im übernommenen Messdienstbetrag bereits abgezogen. "
                   if m['heizkosten_status'] == 'nach_co2_abzug' else "Der Vermieteranteil wird oben einmalig abgezogen. ")
                + f"Grundlagen: {c['beleg']}; {m['messdienst_beleg']}.")
        story += [Spacer(1, 4 * mm), Paragraph(esc(info), klein)]
    story += [Spacer(1, 4 * mm), Paragraph(
        "Gesamtwerte des Hauses: Wohnfläche "
        f"{num(obj['wohnflaeche_gesamt'])} m², {obj['einheiten_gesamt']} Wohneinheiten"
        + (f", {num(obj['personen_gesamt'],0)} Personen" if obj.get("personen_gesamt") else "") + ". "
        "Sie können die Rechnungen und Belege zu dieser Abrechnung einsehen; auf Wunsch stellen wir sie Ihnen "
        "elektronisch zur Verfügung (§ 556 Abs. 4 BGB). Einwendungen gegen die Abrechnung teilen Sie bitte "
        "spätestens bis zum Ablauf des zwölften Monats nach Zugang mit (§ 556 Abs. 3 BGB).", klein),
        Spacer(1, 3 * mm), Paragraph(f"{esc(vm['ort'])}, {date.today().strftime('%d.%m.%Y')} · {esc(vm['name'])}", klein)]
    SimpleDocTemplate(str(pfad), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                      bottomMargin=16 * mm, title="Betriebskostenabrechnung", author=vm["name"]).build(story)


def main(eingabe, ausgabe):
    with open(eingabe, encoding="utf-8") as f:
        auftrag = json.load(f)
    ergebnisse, hinweise = berechne(auftrag)
    os.makedirs(ausgabe, exist_ok=True)
    zeilen = [f"Prüfbericht – {auftrag['objekt']['anschrift']} – {auftrag['zeitraum']['von']} bis {auftrag['zeitraum']['bis']}", ""]
    for index, e in enumerate(ergebnisse, 1):
        name = e["mieter"]["name"]
        datei = os.path.join(ausgabe, f"Abrechnung_{index:02}_" + "".join(c if c.isalnum() else "_" for c in name) + ".pdf")
        pdf(auftrag, e, datei)
        art = "Nachzahlung" if e["saldo"] > 0 else "Guthaben"
        zeilen.append(f"{name}: Kosten {eur(e['summe'])}, Vorauszahlung {eur(e['vorauszahlungen'])}, {art} {eur(abs(e['saldo']))}")
    zeilen += ["", "Hinweise für die Durchsicht:"] + (["- " + h for h in hinweise] or ["- keine"])
    zeilen += ["", "Vor Freigabe prüfen: Kostenarten im Mietvertrag vereinbart? Belege vollständig? Schlüssel wie vereinbart?"]
    with open(os.path.join(ausgabe, "pruefbericht.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")
    print("\n".join(zeilen))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Aufruf: python3 rechner.py auftrag.json ausgabe-ordner/")
    try:
        main(sys.argv[1], sys.argv[2])
    except (ValueError, KeyError, TypeError) as error:
        sys.exit(f"Abrechnung gesperrt: {error}")
