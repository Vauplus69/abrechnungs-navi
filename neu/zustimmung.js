// Vorschau des Zustimmungs-Ablaufs. Speichert und versendet nichts.
(function () {
  var $ = function (s) { return document.querySelector(s); };
  var wege = ['selbst', 'hilfe', 'vertretung', 'unklar'];
  var weg = null;
  function zeige(id) {
    ['schritt-1', 'schritt-3'].concat(wege.map(function (w) { return 'weg-' + w; })).forEach(function (x) {
      document.getElementById(x).hidden = x !== id;
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
    var h = document.querySelector('#' + id + ' h1, #' + id + ' h2'); if (h) { h.setAttribute('tabindex', '-1'); h.focus(); }
  }
  document.querySelectorAll('[data-weg]').forEach(function (b) {
    b.addEventListener('click', function () { weg = b.dataset.weg; zeige('weg-' + weg); pruefe(); });
  });
  // Knoepfe erst aktiv, wenn alles bestaetigt ist
  function pruefe() {
    var k = document.querySelector('[data-weiter="selbst"]'); k.disabled = !$('#ok-selbst').checked;
    var g = document.querySelector('input[name=grundlage]:checked');
    ['vollmacht', 'betreuung', 'ehegatte'].forEach(function (x) { document.getElementById('umfang-' + x).hidden = !g || g.value !== x; });
    $('#wahrheit').hidden = !g || g.value === 'ehegatte';
    var umfangOk = g && g.value !== 'ehegatte' && document.querySelector('#umfang-' + g.value + ' .umfang').checked;
    var v = document.querySelector('[data-weiter="vertretung"]');
    v.disabled = !(g && (g.value === 'ehegatte' || (umfangOk && $('#ok-wahr').checked)));
    v.textContent = g && g.value === 'ehegatte' ? 'Vorerst nur auf diesem Gerät' : 'Weiter';
  }
  document.addEventListener('change', pruefe);
  var jetzt = function () { return new Date().toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' }); };
  function zeile(a, b) { var tr = document.createElement('tr'); var th = document.createElement('th'); th.textContent = a; var td = document.createElement('td'); td.textContent = b; tr.append(th, td); return tr; }
  document.querySelectorAll('[data-weiter]').forEach(function (b) {
    b.addEventListener('click', function () {
      var p = $('#protokoll'); p.innerHTML = '';
      var titel = 'Das halten wir fest', text = '', rows = [];
      if (b.dataset.weiter === 'selbst') {
        text = 'Du stimmst für dich selbst zu. Ab jetzt kannst du dein Pflegebudget speichern.';
        rows = [['Wer stimmt zu', 'Du selbst (Kontoinhaber)'], ['Für wen', 'Für dich selbst'], ['Zweck', 'Pflegebudget führen, Briefe vorbereiten'], ['Textfassung', 'Einwilligung Pflegeangaben, Fassung 2026-11'], ['Grundlage', 'Eigene ausdrückliche Einwilligung'], ['Zeitpunkt', jetzt()], ['Widerruf', 'Jederzeit im Konto']];
      } else if (b.dataset.weiter === 'hilfe') {
        var vn = $('#vorname').value.trim() || 'die Person';
        titel = 'Warten auf die Zustimmung';
        text = 'Sobald ' + vn + ' zugestimmt hat, kannst du die Angaben speichern. Bis dahin bleiben sie auf diesem Gerät.';
        rows = [['Wer stimmt zu', vn + ' selbst (per Link oder Unterschrift)'], ['Wer hilft', 'Du (Kontoinhaber)'], ['Zweck', 'Pflegebudget führen, Briefe vorbereiten'], ['Textfassung', 'Einwilligung für Angehörige, Fassung 2026-11'], ['Grundlage', 'Ausdrückliche Einwilligung der betroffenen Person'], ['Status', 'Offen seit ' + jetzt()], ['Widerruf', 'Jederzeit durch ' + vn + ' oder dich']];
      } else {
        var g = document.querySelector('input[name=grundlage]:checked').value;
        if (g === 'ehegatte') {
          titel = 'Vorerst nur auf diesem Gerät';
          text = 'Deine Eingaben werden nicht an unseren Server übertragen. Du kannst den Pflege-Check trotzdem nutzen.';
          rows = [['Grundlage', 'Ehegatten-Notvertretung, reicht für Speicherung nicht'], ['Gespeichert auf dem Server', 'Nichts'], ['Zeitpunkt', jetzt()]];
        } else {
          text = 'Du handelst als Vertreter. Wir speichern keine Kopie deiner Vollmacht oder deines Betreuerausweises.';
          rows = [['Wer bestätigt', 'Du (Kontoinhaber) als Vertreter'], ['Für wen', 'Die vertretene Person'], ['Zweck', 'Pflegebudget führen, Briefe vorbereiten'], ['Textfassung', 'Erklärung zur Vertretung, Fassung 2026-11'], ['Grundlage', g === 'vollmacht' ? 'Vorsorgevollmacht, umfasst Gesundheit und Behörden' : 'Rechtliche Betreuung, passender Aufgabenkreis'], ['Zeitpunkt', jetzt()], ['Widerruf', 'Jederzeit im Konto; die Person kann sich auch direkt an uns wenden']];
        }
      }
      $('#ergebnis-titel').textContent = titel; $('#ergebnis-text').textContent = text;
      rows.forEach(function (r) { p.append(zeile(r[0], r[1])); });
      zeige('schritt-3');
    });
  });
  document.querySelector('[data-neu]').addEventListener('click', function () { location.reload(); });
  pruefe();
})();
