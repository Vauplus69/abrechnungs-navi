// Wegweiser Wohnen im Alter. Grobe Orientierung, alles bleibt im Browser.
(function () {
  var form = document.getElementById('vs-check-form');
  var box = document.getElementById('vs-ergebnis');
  if (!form || !box) return;
  function esc(t) { var d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
  var hFeld = document.getElementById('frage-hindernis');
  form.querySelectorAll('input[name=wohnen]').forEach(function (r) {
    r.addEventListener('change', function () { if (r.checked) hFeld.hidden = r.value === 'heim'; });
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var f = new FormData(form);
    var wohnen = f.get('wohnen'), pg = f.get('pg'), hi = f.get('hindernis'), ek = f.get('einkommen'), gs = f.get('grundsicherung');
    var heim = wohnen === 'heim';
    if (!wohnen || !pg || !ek || !gs || (!heim && !hi)) {
      box.innerHTML = '<p class="vs-marke">DEIN ERGEBNIS</p><p>Bitte beantworte alle Fragen.</p>';
      return;
    }
    pg = Number(pg);
    var p = [];
    var knapp = ek !== 'ue2500';

    if (heim) {
      p.push(['Ein Heimplatz kostet in NRW im ersten Jahr im Schnitt 3.671 € im Monat aus eigener Tasche. Rechnet nach, wie lange Rente und Erspartes reichen.', 'Gespräch mit Volker']);
      if (pg < 2) p.push(['Mit Pflegegrad 1 zahlt die Pflegekasse im Heim nichts dazu. Lass prüfen, ob ein höherer Pflegegrad infrage kommt.', 'Pflegekasse']);
      if (knapp || gs === 'ja') {
        p.push(['Pflegewohngeld: übernimmt in NRW einen Teil der Heimkosten, wenn das Geld nicht reicht. Nur in geförderten Heimen, vorher im Heim nachfragen. Die Kinder zahlen dafür nichts.', 'Sozialamt von Kreis oder Stadt']);
        p.push(['Hilfe zur Pflege: Reicht es dann immer noch nicht, zahlt das Sozialamt den Rest. Von den Kindern wird erst ab 100.000 € Jahreseinkommen etwas verlangt.', 'Sozialamt von Kreis oder Stadt']);
      }
      if (knapp && gs === 'nein') p.push(['Wohngeld gibt es auch im Pflegeheim. Die Höhe hängt vom Einkommen und vom Ort des Heims ab.', 'Wohngeldstelle der Stadt']);
    } else {
      if (gs === 'ja') {
        p.push(['Bei Grundsicherung oder Bürgergeld sind die Wohnkosten schon enthalten, Wohngeld gibt es dann nicht. Prüfe, ob deine Miete oder deine Hauskosten voll anerkannt werden.', 'Sozialamt oder Jobcenter']);
      } else if (knapp) {
        p.push([wohnen === 'miete' ? 'Wohngeld: Zuschuss zur Miete. Gezahlt wird erst ab dem Monat des Antrags, also nicht warten.' : 'Lastenzuschuss: Wohngeld für Eigentümer, als Zuschuss zu den Wohnkosten. Gezahlt wird erst ab dem Monat des Antrags.', 'Wohngeldstelle der Stadt']);
      }
      if (hi === 'ja') {
        if (pg >= 1) p.push(['Umbau-Zuschuss: bis zu 4.180 € von der Pflegekasse, zum Beispiel für Dusche, Treppenlift oder breitere Türen. Unbedingt vor Beginn beantragen.', 'Pflegekasse']);
        else p.push(['Ohne Pflegegrad gibt es keinen Umbau-Zuschuss der Pflegekasse. Wird im Alltag schon Hilfe gebraucht, lohnt sich ein Antrag auf Pflegegrad.', 'Pflegekasse']);
        p.push(['KfW-Kredit für den Umbau: bis 50.000 € je Wohnung, über die eigene Bank und vor Beginn. ' + (wohnen === 'miete' ? 'Als Mieter vorher den Vermieter schriftlich fragen.' : 'Den KfW-Zuschuss gibt es 2026 nicht mehr.'), 'Hausbank']);
        if (gs === 'nein' && ek !== 'u1500') p.push(['Handwerker von der Steuer: 20 Prozent der Arbeitskosten, bis 1.200 € im Jahr. Rechnung aufheben und überweisen.', 'Steuererklärung']);
      }
      if (pg >= 2) p.push(['Wenn es allein schwerer wird: Betreutes Wohnen oder eine Pflege-WG sind Zwischenwege. In der Pflege-WG gibt es 224 € im Monat extra von der Pflegekasse.', 'Pflegekasse oder Pflegestützpunkt']);
      if (wohnen === 'eigentum') p.push(['Das eigene Haus im Alter: behalten, verkleinern, vermieten oder Geld daraus bekommen. Lass die Wege früh und in Ruhe durchrechnen.', 'Gespräch mit Volker']);
    }

    var n = p.length;
    var titel = n === 0 ? 'Nach deinen Angaben passt gerade nichts Zusätzliches.' : n === 1 ? 'Einen Punkt solltet ihr prüfen lassen.' : n + ' Punkte solltet ihr prüfen lassen.';
    var html = '<p class="vs-marke">DEIN ERGEBNIS</p><h3>' + esc(titel) + '</h3><p class="legende-wo"><span>→</span> prüfen lassen</p><ul>';
    p.forEach(function (x) { html += '<li class="pruef">' + esc(x[0]) + '<span class="wo">Wo: ' + esc(x[1]) + '</span></li>'; });
    html += '</ul><p class="grau" style="font-size:14px">Grobe Orientierung, keine Berechnung. Ob und wie viel du bekommst, entscheidet die jeweilige Stelle.</p>';
    html += '<a class="knopf vs-knopf" href="/termin" target="_blank" rel="noopener">Gespräch mit Volker vereinbaren</a>';
    box.innerHTML = html;
    if (window.innerWidth < 900) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
})();
