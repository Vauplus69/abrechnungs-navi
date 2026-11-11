// Kurz-Check Erbe & Nachlass. Alles bleibt im Browser, nichts wird gespeichert oder gesendet.
(function () {
  var form = document.getElementById('vs-check-form');
  var box = document.getElementById('vs-ergebnis');
  if (!form || !box) return;
  function esc(t) { var d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var f = new FormData(form);
    var t = f.get('testament'), k = f.get('kinder'), s = f.get('sorge'), i = f.get('immobilie');
    if (!t || !k || !i || (k === 'ja' && !s)) {
      box.innerHTML = '<p class="vs-marke">DEIN ERGEBNIS</p><p>Bitte beantworte alle Fragen.</p>';
      return;
    }
    var p = [], fehlt = 0;
    if (t === 'ja') p.push(['ok', 'Testament vorhanden. Prüfe, ob es noch zu deiner Familie und deinem Vermögen passt.']);
    else { fehlt++; p.push(['fehlt', 'Kein Testament: Dann gilt die gesetzliche Erbfolge. Dein Ehepartner erbt oft nur die Hälfte, den Rest teilen sich die Kinder.']); }
    if (k === 'ja') {
      if (s === 'ja') p.push(['ok', 'Sorgerechtsverfügung vorhanden. Deine Wunschperson für deine Kinder ist festgelegt.']);
      else { fehlt++; p.push(['fehlt', 'Keine Sorgerechtsverfügung: Fallen beide Eltern aus, bestimmt das Familiengericht, wer sich um deine Kinder kümmert.']); }
    }
    if (i === 'ja') { if (t !== 'ja') fehlt++; p.push([t === 'ja' ? 'ok' : 'fehlt', t === 'ja' ? 'Bei Haus oder Firma lohnt sich ein Blick, ob Erbschaftsteuer und Aufteilung gut geregelt sind.' : 'Haus oder Firma ohne Testament: Die Erben müssen alles gemeinsam entscheiden. Streit und Zwangsverkauf sind häufig.']); }
    var titel = fehlt === 0 ? 'Gut geregelt.' : fehlt === 1 ? 'Ein wichtiger Punkt fehlt noch.' : 'Hier fehlt noch Wichtiges.';
    var html = '<p class="vs-marke">DEIN ERGEBNIS</p><h3>' + esc(titel) + '</h3><ul>';
    p.forEach(function (x) { html += '<li class="' + x[0] + '">' + esc(x[1]) + '</li>'; });
    html += '</ul>' + (fehlt === 0
      ? '<p class="grau">Ein kurzer Blick alle paar Jahre lohnt sich, etwa nach Heirat, Geburt oder Hauskauf.</p>'
      : '<a class="knopf vs-knopf" href="/termin" target="_blank" rel="noopener">Gespräch mit Volker vereinbaren</a><p class="grau" style="margin-top:12px">Kostenlos und unverbindlich.</p>');
    box.innerHTML = html;
    if (window.innerWidth < 900) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  var kinder = form.querySelectorAll('input[name=kinder]');
  var sorgeFeld = document.getElementById('frage-sorge');
  kinder.forEach(function (r) { r.addEventListener('change', function () { sorgeFeld.hidden = r.value !== 'ja' || !r.checked; }); });
})();
