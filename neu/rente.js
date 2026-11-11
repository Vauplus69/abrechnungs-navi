// Wegweiser Rente. Grobe Orientierung, alles bleibt im Browser.
(function () {
  var form = document.getElementById('vs-check-form');
  var box = document.getElementById('vs-ergebnis');
  if (!form || !box) return;
  function esc(t) { var d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
  var gFeld = document.getElementById('frage-gesund');
  form.querySelectorAll('input[name=rente]').forEach(function (r) {
    r.addEventListener('change', function () { if (r.checked) gFeld.hidden = r.value === 'ja'; });
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var f = new FormData(form);
    var rente = f.get('rente'), ek = f.get('einkommen'), jahre = f.get('jahre'), fam = f.get('familie'), ges = f.get('gesund');
    var inRente = rente === 'ja';
    if (!rente || !ek || !jahre || !fam || (!inRente && !ges)) {
      box.innerHTML = '<p class="vs-marke">DEIN ERGEBNIS</p><p>Bitte beantworte alle Fragen.</p>';
      return;
    }
    var p = [];
    var stufe = { u1000: 0, u1500: 1, u2000: 2, ue2000: 3 }[ek];

    if (inRente && stufe === 0) p.push(['Grundsicherung im Alter: 563 € im Monat plus angemessene Miete und Heizung, abzüglich deiner Rente. Bei unter 1.000 € lohnt sich die Prüfung fast immer. Die Kinder zahlen erst ab 100.000 € Jahreseinkommen.', 'Sozialamt']);
    if (inRente && stufe <= 1) p.push(['Wohngeld: Zuschuss zur Miete oder zu den Hauskosten. Grundsicherung und Wohngeld gibt es nicht zusammen. Lass prüfen, was mehr bringt.', 'Wohngeldstelle der Stadt']);
    if (jahre !== 'u33' && stufe <= 1) p.push([inRente ? 'Grundrente: Steht im Rentenbescheid ein Grundrentenzuschlag? Mit 33 Jahren bleiben außerdem bis zu 281,50 € der Rente bei Grundsicherung und Wohngeld frei.' : 'Grundrente: Mit 33 Jahren Arbeit, Kindererziehung oder Pflege kann später ein Zuschlag kommen. Prüfe, ob alle Zeiten in deinem Rentenkonto stehen.', 'Rentenversicherung']);
    if (jahre === 'weiss') p.push(['Rentenkonto prüfen: Fehlen Zeiten, etwa für Kinder, Pflege oder Ausbildung, fehlt später Rente. Lücken lassen sich oft noch schließen.', 'Rentenversicherung, kostenlos']);
    if (fam === 'witwe') {
      p.push(['Witwenrente: Ist sie beantragt? Seit Juli 2026 bleiben 1.122,53 € eigenes Einkommen frei. Prüfe, ob die Anrechnung im Bescheid stimmt.', 'Rentenversicherung']);
      p.push(['Waisenrente: Gibt es Kinder unter 18, oder bis 27 in Ausbildung oder Studium? Sie bekommen 10 % der Rente des Verstorbenen.', 'Rentenversicherung']);
    }
    if (fam === 'paar') p.push(['Was bleibt, wenn einer von euch stirbt? Meist 55 % der Rente des Partners, und eigenes Einkommen wird angerechnet. Rechnet aus, ob es dann noch reicht.', 'Gespräch mit Volker']);
    if (!inRente && ges !== 'ja') {
      p.push([ges === 'nein' ? 'Erwerbsminderungsrente: Wer weniger als 3 Stunden am Tag arbeiten kann, bekommt die volle Rente. Oft kommt vorher eine Reha.' : 'Erwerbsminderungsrente: Wer nur noch 3 bis 6 Stunden am Tag arbeiten kann, bekommt die halbe Rente. Dazuverdienen ist möglich.', 'Rentenversicherung']);
      p.push(['Die Erwerbsminderungsrente ist meist viel niedriger als das Gehalt. Lass ausrechnen, wie viel dann fehlt.', 'Gespräch mit Volker']);
    }
    if (!inRente) p.push(['Rentenlücke: Schau in deine Renteninformation und rechne nach, wie viel nach Abzügen bleibt. Je früher du die Lücke kennst, desto leichter lässt sie sich schließen.', 'der-rentenheld.de oder Gespräch mit Volker']);

    var n = p.length;
    var titel = n === 0 ? 'Nach deinen Angaben passt gerade nichts Zusätzliches.' : n === 1 ? 'Einen Punkt solltest du prüfen lassen.' : n + ' Punkte solltest du prüfen lassen.';
    var html = '<p class="vs-marke">DEIN ERGEBNIS</p><h3>' + esc(titel) + '</h3><p class="legende-rt"><span>→</span> prüfen lassen</p><ul>';
    p.forEach(function (x) { html += '<li class="pruef">' + esc(x[0]) + '<span class="wo">Wo: ' + esc(x[1]) + '</span></li>'; });
    html += '</ul><p class="grau" style="font-size:14px">Grobe Orientierung, keine Berechnung. Ob und wie viel du bekommst, entscheidet die jeweilige Stelle.</p>';
    html += '<a class="knopf vs-knopf" href="/termin" target="_blank" rel="noopener">Gespräch mit Volker vereinbaren</a>';
    box.innerHTML = html;
    if (window.innerWidth < 900) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
})();
