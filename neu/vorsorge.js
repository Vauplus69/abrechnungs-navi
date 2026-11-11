// Kurz-Check Vorsorge-Papiere. Alles bleibt im Browser, nichts wird gespeichert oder gesendet.
(function () {
  var form = document.getElementById('vs-check-form');
  var box = document.getElementById('vs-ergebnis');
  if (!form || !box) return;

  function esc(t) { var d = document.createElement('div'); d.textContent = t; return d.innerHTML; }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var f = new FormData(form);
    var v = f.get('vollmacht'), p = f.get('verfuegung'), o = f.get('ort');
    if (!v || !p || !o) {
      box.innerHTML = '<p class="vs-marke">DEIN ERGEBNIS</p><p>Bitte beantworte alle drei Fragen.</p>';
      return;
    }
    var punkte = [];
    var fehlt = 0;
    if (v === 'ja') punkte.push(['ok', 'Vorsorgevollmacht vorhanden. Prüfe, ob sie noch aktuell ist und Bank und Gesundheit abdeckt.']);
    else { fehlt++; punkte.push(['fehlt', v === 'nein' ? 'Keine Vorsorgevollmacht: Im Ernstfall müsste ein Gericht einen Betreuer bestimmen.' : 'Unklar, ob es eine Vorsorgevollmacht gibt. Das sollte schnell geklärt werden.']); }
    if (p === 'ja') punkte.push(['ok', 'Patientenverfügung vorhanden. Gut ist, wenn sie konkrete Situationen beschreibt.']);
    else { fehlt++; punkte.push(['fehlt', 'Keine Patientenverfügung: Deine Familie müsste über Behandlungen entscheiden, ohne deinen Willen zu kennen.']); }
    if (o === 'ja') punkte.push(['ok', 'Deine Angehörigen wissen, wo die Papiere liegen.']);
    else { fehlt++; punkte.push(['fehlt', 'Im Notfall findet niemand die Papiere. Eine Notfallkarte im Portemonnaie hilft.']); }

    var titel = fehlt === 0 ? 'Gut vorgesorgt.' : fehlt === 1 ? 'Fast geschafft, ein Punkt fehlt.' : 'Hier fehlt noch Wichtiges.';
    var html = '<p class="vs-marke">DEIN ERGEBNIS</p><h3>' + esc(titel) + '</h3><ul>';
    punkte.forEach(function (x) { html += '<li class="' + x[0] + '">' + esc(x[1]) + '</li>'; });
    html += '</ul>';
    html += fehlt === 0
      ? '<p class="grau">Ein kurzer Blick, ob alles noch passt, lohnt sich alle paar Jahre.</p>'
      : '<a class="knopf vs-knopf" href="/termin" target="_blank" rel="noopener">Gespräch mit Volker vereinbaren</a><p class="grau" style="margin-top:12px">Kostenlos und unverbindlich.</p>';
    box.innerHTML = html;
    if (window.innerWidth < 900) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
})();
