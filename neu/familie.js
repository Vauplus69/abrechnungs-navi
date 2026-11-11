// Wegweiser Familie & Zuschuesse. Grobe Orientierung, alles bleibt im Browser.
(function () {
  var form = document.getElementById('vs-check-form');
  var box = document.getElementById('vs-ergebnis');
  if (!form || !box) return;
  function esc(t) { var d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
  var allein = form.querySelectorAll('input[name=allein]');
  var uFeld = document.getElementById('frage-unterhalt');
  allein.forEach(function (r) { r.addEventListener('change', function () { if (r.checked) uFeld.hidden = r.value !== 'ja'; }); });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var f = new FormData(form);
    var kinder = Number(f.get('kinder')), al = f.get('allein'), uh = f.get('unterhalt'), ek = f.get('einkommen'), bg = f.get('buergergeld'), wohnen = f.get('wohnen');
    if (isNaN(kinder) || !al || !ek || !bg || !wohnen || (al === 'ja' && kinder > 0 && !uh)) {
      box.innerHTML = '<p class="vs-marke">DEIN ERGEBNIS</p><p>Bitte beantworte alle Fragen.</p>';
      return;
    }
    var p = [];
    var stufe = { u600: 0, u900: 1, u2500: 2, u4000: 3, ue4000: 4 }[ek];
    var mindest = al === 'ja' ? 1 : 2; // 600 bzw. 900 Euro brutto
    var kizMoeglich = false, wgMoeglich = false;

    if (kinder > 0) p.push(['ok', 'Kindergeld: 259 € je Kind im Monat. Läuft es schon für alle Kinder?', 'Familienkasse']);

    if (bg === 'ja') {
      if (kinder > 0) p.push(['pruef', 'Bildung und Teilhabe: Schulbedarf (195 € im Jahr 2026), Mittagessen, Ausflüge und Klassenfahrten.', 'Jobcenter']);
      p.push(['pruef', 'Lass prüfen, ob Kinderzuschlag und Wohngeld zusammen besser sind als Bürgergeld. Dafür sind sie gedacht.', 'Familienkasse und Wohngeldstelle']);
    } else {
      if (kinder > 0) {
        if (stufe >= mindest && (stufe <= 3 || kinder >= 3)) {
          kizMoeglich = true;
          p.push(['pruef', 'Kinderzuschlag: bis zu ' + (kinder * 297).toLocaleString('de-DE') + ' € im Monat (297 € je Kind), zusätzlich zum Kindergeld.', 'Familienkasse']);
        } else if (stufe < mindest) {
          p.push(['pruef', 'Für den Kinderzuschlag braucht ihr ein Mindesteinkommen (' + (al === 'ja' ? '600' : '900') + ' € brutto). Lass prüfen, welche Hilfe stattdessen passt.', 'Jobcenter oder Wohngeldstelle']);
        }
      }
      if (stufe <= 3) {
        wgMoeglich = true;
        p.push(['pruef', wohnen === 'miete' ? 'Wohngeld: Zuschuss zur Miete. Gezahlt wird erst ab dem Monat des Antrags, also nicht warten.' : 'Lastenzuschuss: Wohngeld für Eigentümer, als Zuschuss zu den Wohnkosten. Gezahlt wird erst ab dem Monat des Antrags.', 'Wohngeldstelle der Stadt']);
      }
      if (kinder > 0 && (kizMoeglich || wgMoeglich)) {
        p.push(['pruef', 'Bildung und Teilhabe: Schulbedarf (195 € im Jahr 2026), Mittagessen, Ausflüge und Klassenfahrten. Gibt es auch mit Kinderzuschlag oder Wohngeld.', 'Stadt oder Kreis']);
        if (kizMoeglich) p.push(['pruef', 'Kita-Gebühren: Viele Städte erlassen oder senken sie bei Kinderzuschlag.', 'Jugendamt oder Kita-Träger']);
      }
    }
    if (al === 'ja' && kinder > 0 && uh === 'nein') {
      p.push(['pruef', 'Unterhaltsvorschuss: 227 € (bis 5 Jahre), 299 € (6 bis 11) oder 394 € (12 bis 17) im Monat je Kind, wenn der andere Elternteil nicht oder zu wenig zahlt.', 'Jugendamt']);
    }

    var offen = p.filter(function (x) { return x[0] === 'pruef'; }).length;
    var titel = offen === 0 ? 'Nach deinen Angaben passt gerade nichts Zusätzliches.' : offen === 1 ? 'Eine Leistung könnte für euch infrage kommen.' : offen + ' Leistungen könnten für euch infrage kommen.';
    var html = '<p class="vs-marke">DEIN ERGEBNIS</p><h3>' + esc(titel) + '</h3><p class="legende-fa"><span class="pf">→</span> könnte infrage kommen, prüfen lassen &nbsp; <span class="hk">✓</span> hast du vermutlich schon</p><ul>';
    p.forEach(function (x) { html += '<li class="' + x[0] + '">' + esc(x[1]) + '<span class="wo">Antrag bei: ' + esc(x[2]) + '</span></li>'; });
    html += '</ul><p class="grau" style="font-size:14px">Grobe Orientierung, keine Berechnung. Ob und wie viel du bekommst, entscheidet die jeweilige Stelle.</p>';
    html += '<a class="knopf vs-knopf" href="/termin" target="_blank" rel="noopener">Gespräch mit Volker vereinbaren</a>';
    box.innerHTML = html;
    if (window.innerWidth < 900) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
})();
