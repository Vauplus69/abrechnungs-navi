/* Preisberechnung bleibt im Browser; es werden keine Eingaben übertragen. */
(function () {
  'use strict';

  function berechnePreis(wohnungen, haeuser) {
    if (!/^\d+$/.test(String(wohnungen)) || !/^\d+$/.test(String(haeuser))) return null;
    const w = Number(wohnungen), h = Number(haeuser);
    if (!Number.isSafeInteger(w) || !Number.isSafeInteger(h) || w < 1 || w > 200 || h < 1 || h > w) return null;
    return {wohnungen: w, haeuser: h, weitere: w - h, gesamt: h * 89 + (w - h) * 59};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {berechnePreis};
  if (typeof document === 'undefined') return;

  const wohnungen = document.getElementById('preis-wohnungen');
  const haeuser = document.getElementById('preis-haeuser');
  const gesamt = document.getElementById('preis-gesamt');
  const aufteilung = document.getElementById('preis-aufteilung');
  const fehler = document.getElementById('rechner-fehler');
  const uebernehmen = document.getElementById('preis-uebernehmen');
  const euro = new Intl.NumberFormat('de-DE', {style: 'currency', currency: 'EUR', maximumFractionDigits: 0});

  function aktualisieren() {
    const p = berechnePreis(wohnungen.value, haeuser.value);
    fehler.hidden = Boolean(p);
    uebernehmen.disabled = !p;
    wohnungen.setAttribute('aria-invalid', String(!p));
    haeuser.setAttribute('aria-invalid', String(!p));
    if (!p) {
      fehler.textContent = 'Bitte geben Sie ganze Zahlen zwischen 1 und 200 ein. Die Anzahl der Häuser darf nicht größer sein als die Anzahl der Wohnungen.';
      gesamt.textContent = 'Bitte Angaben prüfen';
      aufteilung.textContent = '';
      return null;
    }
    fehler.textContent = '';
    gesamt.textContent = euro.format(p.gesamt);
    aufteilung.textContent = p.haeuser + (p.haeuser === 1 ? ' erste Wohnung' : ' erste Wohnungen') + ' × 89 €' + (p.weitere ? ' + ' + p.weitere + (p.weitere === 1 ? ' weitere Wohnung' : ' weitere Wohnungen') + ' × 59 €' : '');
    return p;
  }
  if (wohnungen && haeuser && gesamt && aufteilung && fehler && uebernehmen) {
    uebernehmen.hidden = false;
    wohnungen.addEventListener('input', aktualisieren);
    haeuser.addEventListener('input', aktualisieren);
    uebernehmen.addEventListener('click', function () {
      const p = aktualisieren();
      if (!p) return;
      const anzahl = document.getElementById('f-we');
      const nachricht = document.getElementById('f-text');
      const notiz = '[Preisrechner] ' + p.wohnungen + (p.wohnungen === 1 ? ' Wohnung in ' : ' Wohnungen in ') + (p.haeuser === 1 ? 'einem Haus' : p.haeuser + ' Häusern') + ': ' + euro.format(p.gesamt) + ' für ein Abrechnungsjahr.';
      const text = nachricht.value.replace(/^\[Preisrechner\][^\n]*(?:\n)?/, '');
      // Keine Kundennotiz abschneiden; die Übernahme ist keine Anfrage und kein Auftrag.
      if (text.length + notiz.length + 1 > nachricht.maxLength) {
        fehler.hidden = false;
        fehler.textContent = 'Die Nachricht im Anfrageformular ist zu lang für die Preisnotiz. Bitte kürzen Sie diese zuerst. Ihre Eingaben bleiben erhalten.';
        return;
      }
      anzahl.value = String(p.wohnungen);
      nachricht.value = notiz + (text ? '\n' + text : '');
      document.getElementById('kontakt').scrollIntoView({behavior: 'auto', block: 'start'});
      document.getElementById('f-name').focus({preventScroll: true});
    });
    aktualisieren();
  }

  // Nur vom Betreiber dokumentiert freigegebene Originalstimmen eintragen.
  // Leere Liste: kein sichtbarer Bewertungsbereich und keine erfundenen Sterne.
  const daten = document.getElementById('freigegebene-bewertungen');
  const bereich = document.getElementById('kundenstimmen');
  const liste = document.getElementById('kundenstimmen-liste');
  if (daten && bereich && liste) {
    try {
      const stimmen = JSON.parse(daten.textContent);
      if (!Array.isArray(stimmen)) return;
      stimmen.filter(s => s && s.freigegeben === true && typeof s.text === 'string' && s.text.trim() && typeof s.name === 'string' && s.name.trim()).forEach(s => {
        const karte = document.createElement('figure');
        karte.className = 'card customer-quote';
        const zitat = document.createElement('blockquote');
        zitat.textContent = s.text;
        const name = document.createElement('figcaption');
        name.textContent = s.name;
        karte.append(zitat, name);
        liste.append(karte);
      });
      bereich.hidden = !liste.children.length;
    } catch (_) {
      bereich.hidden = true;
    }
  }
}());
