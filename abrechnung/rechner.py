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
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Schrift mit ², ₂ und € – DejaVu, sonst Liberation; notfalls Standardschrift
FONT, FONT_B = "Helvetica", "Helvetica-Bold"
for reg, bold in [("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                  ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                   "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")]:
    if os.path.exists(reg) and os.path.exists(bold):
        pdfmetrics.registerFont(TTFont("AN", reg))
        pdfmetrics.registerFont(TTFont("AN-B", bold))
        pdfmetrics.registerFontFamily("AN", normal="AN", bold="AN-B", italic="AN", boldItalic="AN-B")
        FONT, FONT_B = "AN", "AN-B"
        break

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
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if x < 0 else "") + s + " €"


def num(x, nk=2):
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


def berechne(auftrag):
    z_von, z_bis = auftrag["zeitraum"]["von"], auftrag["zeitraum"]["bis"]
    z_tage = tage(z_von, z_bis)
    obj = auftrag["objekt"]
    hinweise, ergebnisse = [], []

    # Gesamtwerte je Schlüssel (für das ganze Jahr, alle Einheiten inkl. Leerstand)
    gesamt = {"wohnflaeche": obj["wohnflaeche_gesamt"], "einheiten": obj["einheiten_gesamt"],
              "personen": obj.get("personen_gesamt")}

    for k in auftrag["kosten"]:
        name = k["name"].lower()
        if any(w in name for w in VERDAECHTIG):
            hinweise.append(f"PRÜFEN: „{k['name']}“ ist oft nicht umlagefähig (§ 2 BetrKV).")
        if k["schluessel"] not in SCHLUESSEL:
            raise ValueError(f"Unbekannter Schlüssel bei {k['name']}: {k['schluessel']}")
        if k["schluessel"] == "personen" and not gesamt["personen"]:
            raise ValueError("Für den Schlüssel 'personen' fehlt objekt.personen_gesamt")
        if k["schluessel"] == "verbrauch" and not k.get("verbrauch_gesamt"):
            raise ValueError(f"Für {k['name']} fehlt verbrauch_gesamt")

    co2 = auftrag.get("co2")
    if co2:
        kg_m2 = co2["kg_co2_gesamt"] / obj["wohnflaeche_gesamt"]
        v_anteil = co2_vermieteranteil(kg_m2)
        co2["kg_pro_m2"], co2["vermieteranteil"] = kg_m2, v_anteil

    summe_umgelegt = {k["name"]: 0.0 for k in auftrag["kosten"]}
    for m in auftrag["mieter"]:
        m_von, m_bis = m.get("von", z_von), m.get("bis", z_bis)
        m_tage = ueberlappung(z_von, z_bis, m_von, m_bis)
        zeitanteil = m_tage / z_tage
        posten = []
        for k in auftrag["kosten"]:
            s = k["schluessel"]
            if s == "direkt":
                anteil_wert = m.get("direkt", {}).get(k["name"], 0.0)
                betrag = anteil_wert
                text = "direkt zugeordnet"
            elif s == "verbrauch":
                v = m.get("verbrauch", {}).get(k["name"], 0.0)
                betrag = k["betrag"] * v / k["verbrauch_gesamt"]
                text = f"{num(v)} von {num(k['verbrauch_gesamt'])} {k.get('einheit', '')}".strip()
            else:
                g = gesamt[s]
                eigen = {"wohnflaeche": m.get("wohnflaeche"), "personen": m.get("personen"), "einheiten": 1}[s]
                if eigen is None:
                    raise ValueError(f"Bei {m['name']} fehlt der Wert für {s}")
                betrag = k["betrag"] * eigen / g * zeitanteil
                einheit = SCHLUESSEL[s][1]
                text = f"{num(eigen)} von {num(g)} {einheit}"
                if zeitanteil < 1:
                    text += f", {m_tage} von {z_tage} Tagen"
            betrag = round(betrag, 2)
            summe_umgelegt[k["name"]] += betrag
            posten.append({"name": k["name"], "gesamt": k["betrag"], "schluessel": SCHLUESSEL[s][0],
                           "berechnung": text, "anteil": betrag})

        heiz = m.get("heizkosten")  # Betrag laut Messdienst
        co2_erstattung = 0.0
        if heiz is not None:
            posten.append({"name": "Heiz- und Warmwasserkosten (laut Abrechnung Messdienst)", "gesamt": None,
                           "schluessel": "Verbrauch", "berechnung": "laut Messdienst", "anteil": round(heiz, 2)})
            if co2 and m.get("co2_kosten_anteil") is not None:
                co2_erstattung = round(m["co2_kosten_anteil"] * co2["vermieteranteil"], 2)
                if co2_erstattung:
                    posten.append({"name": f"abzüglich Vermieteranteil CO₂-Kosten ({int(co2['vermieteranteil']*100)} %)",
                                   "gesamt": None, "schluessel": "CO2KostAufG",
                                   "berechnung": f"{num(co2['kg_pro_m2'], 1)} kg CO₂/m²/Jahr",
                                   "anteil": -co2_erstattung})

        summe = round(sum(p["anteil"] for p in posten), 2)
        vz = round(m.get("vorauszahlungen", 0.0), 2)
        saldo = round(summe - vz, 2)
        if vz and abs(saldo) / vz > 0.25:
            hinweise.append(f"HINWEIS: {m['name']}: Abweichung zu den Vorauszahlungen {int(abs(saldo)/vz*100)} % "
                            f"– ggf. Anpassung der Vorauszahlung vorschlagen.")
        ergebnisse.append({"mieter": m, "tage": m_tage, "zeitanteil": zeitanteil, "posten": posten,
                           "summe": summe, "vorauszahlungen": vz, "saldo": saldo})

    # Kontrolle: was nicht auf Mieter verteilt wurde, trägt der Vermieter (Leerstand, Eigennutzung)
    for k in auftrag["kosten"]:
        rest = round(k["betrag"] - summe_umgelegt[k["name"]], 2)
        if rest < -0.05:
            hinweise.append(f"FEHLER: „{k['name']}“: Mieter zahlen {eur(-rest)} mehr als die Gesamtkosten!")
        elif rest > 0.05:
            hinweise.append(f"Info: „{k['name']}“: {eur(rest)} nicht umgelegt (Leerstand/Eigennutzung, trägt Vermieter).")
    if co2:
        hinweise.append(f"Info: CO₂-Ausstoß {num(co2['kg_pro_m2'], 1)} kg/m²/Jahr → Vermieter trägt "
                        f"{int(co2['vermieteranteil']*100)} % der CO₂-Kosten.")
    return ergebnisse, hinweise


def pdf(auftrag, e, pfad):
    st = getSampleStyleSheet()
    klein = ParagraphStyle("klein", parent=st["Normal"], fontName=FONT, fontSize=8.5, leading=11)
    norm = ParagraphStyle("norm", parent=st["Normal"], fontName=FONT, fontSize=10, leading=13.5)
    h1 = ParagraphStyle("h1", parent=st["Heading1"], fontName=FONT_B, fontSize=15, spaceAfter=4)
    vm, m, obj = auftrag["vermieter"], e["mieter"], auftrag["objekt"]
    z = auftrag["zeitraum"]
    fmt = lambda d: date.fromisoformat(d).strftime("%d.%m.%Y")
    story = [
        Paragraph(f"{vm['name']} · {vm['anschrift']}", klein), Spacer(1, 6 * mm),
        Paragraph(f"{m['name']}<br/>{m.get('anschrift', obj['anschrift'])}", norm), Spacer(1, 10 * mm),
        Paragraph(f"Betriebskostenabrechnung {fmt(z['von'])} – {fmt(z['bis'])}", h1),
        Paragraph(f"Objekt: {obj['anschrift']} · Wohnung: {m.get('wohnung', '')} · "
                  f"Ihr Nutzungszeitraum: {fmt(m.get('von', z['von']))} – {fmt(m.get('bis', z['bis']))} ({e['tage']} Tage)", norm),
        Spacer(1, 5 * mm),
    ]
    rows = [["Kostenart", "Gesamtkosten", "Verteilung", "Ihr Anteil"]]
    for p in e["posten"]:
        rows.append([Paragraph(p["name"], klein), eur(p["gesamt"]) if p["gesamt"] is not None else "",
                     Paragraph(f"{p['schluessel']}: {p['berechnung']}", klein), eur(p["anteil"])])
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
    story += [Spacer(1, 4 * mm), Paragraph(
        "Gesamtwerte des Hauses: Wohnfläche "
        f"{num(obj['wohnflaeche_gesamt'])} m², {obj['einheiten_gesamt']} Wohneinheiten"
        + (f", {num(obj['personen_gesamt'],0)} Personen" if obj.get("personen_gesamt") else "") + ". "
        "Sie können die Rechnungen und Belege zu dieser Abrechnung einsehen; auf Wunsch stellen wir sie Ihnen "
        "elektronisch zur Verfügung (§ 556 Abs. 4 BGB). Einwendungen gegen die Abrechnung teilen Sie bitte "
        "spätestens bis zum Ablauf des zwölften Monats nach Zugang mit (§ 556 Abs. 3 BGB).", klein),
        Spacer(1, 3 * mm), Paragraph(f"{vm['ort']}, {date.today().strftime('%d.%m.%Y')} · {vm['name']}", klein)]
    SimpleDocTemplate(pfad, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                      bottomMargin=16 * mm, title="Betriebskostenabrechnung", author=vm["name"]).build(story)


def main(eingabe, ausgabe):
    with open(eingabe, encoding="utf-8") as f:
        auftrag = json.load(f)
    os.makedirs(ausgabe, exist_ok=True)
    ergebnisse, hinweise = berechne(auftrag)
    zeilen = [f"Prüfbericht – {auftrag['objekt']['anschrift']} – {auftrag['zeitraum']['von']} bis {auftrag['zeitraum']['bis']}", ""]
    for e in ergebnisse:
        name = e["mieter"]["name"]
        datei = os.path.join(ausgabe, "Abrechnung_" + "".join(c if c.isalnum() else "_" for c in name) + ".pdf")
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
    main(sys.argv[1], sys.argv[2])
