// Briefe an die Pflegekasse: alles passiert im Browser, nichts wird verschickt oder gespeichert.
(function () {
  'use strict';
  var PREISE = { budget: 9.9, antrag: 9.9, hoeher: 9.9, paket: 17.9 };
  var TITEL = { budget: 'Budgetstand anfragen', antrag: 'Erstantrag auf Pflegeleistungen', hoeher: 'Pflegegrad überprüfen lassen', paket: 'Paket: Budgetstand + Pflegegrad überprüfen' };
  var BEZAHLUNG_AKTIV = false; // wird erst nach Freigabe und Rechtsprüfung eingeschaltet

  var form = document.getElementById('angaben');
  var druck = document.getElementById('druck');
  var kaufen = document.getElementById('kaufen');
  var okAgb = document.getElementById('ok-agb');
  var okWid = document.getElementById('ok-widerruf');

  function esc(s) { return String(s || '').replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function euro(n) { return n.toFixed(2).replace('.', ',') + ' €'; }
  function wahl() { var r = document.querySelector('input[name=brief]:checked'); return r ? r.value : 'budget'; }
  function d() { var o = {}; new FormData(form).forEach(function (v, k) { o[k] = String(v).trim(); }); o.telefon = form.telefon.checked; return o; }

  // Start mit ?brief=antrag usw.
  var start = new URLSearchParams(location.search).get('brief');
  if (start && PREISE[start]) { var el = document.querySelector('input[name=brief][value=' + start + ']'); if (el) el.checked = true; }

  function anpassen() {
    var w = wahl();
    document.querySelectorAll('[data-nur]').forEach(function (el) { el.hidden = el.getAttribute('data-nur').split(' ').indexOf(w) < 0; });
    document.getElementById('vertreter').hidden = d().wer !== 'vertretung';
    document.getElementById('auswahl').textContent = TITEL[w];
    document.getElementById('preis').textContent = euro(PREISE[w]);
    kaufen.disabled = !(okAgb.checked && okWid.checked);
  }
  document.addEventListener('change', anpassen);
  anpassen();

  function pflicht(w) {
    var namen = ['name', 'strasse', 'ort', 'kasse', 'kstrasse', 'kort'];
    if (w !== 'antrag') namen.push('pg');
    if (w === 'hoeher' || w === 'paket') namen.push('grund');
    if (d().wer === 'vertretung') namen.push('vname', 'vanschrift');
    var fehlt = [];
    form.querySelectorAll('label').forEach(function (l) { l.classList.remove('br-fehlt'); });
    namen.forEach(function (n) {
      var f = form.elements[n];
      if (f && !f.value.trim()) { fehlt.push(f); f.closest('label').classList.add('br-fehlt'); }
    });
    if (fehlt.length) { fehlt[0].focus(); return false; }
    return true;
  }

  function heute() { return new Date().toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' }); }

  function kopf(a) {
    var abs = a.wer === 'vertretung' ? a.vname + ', ' + a.vanschrift : a.name + ', ' + a.strasse + ', ' + a.ort;
    return '<div class="bf-abs">' + esc(abs) + '</div>' +
      '<div class="bf-an">' + esc(a.kasse) + '<br>' + esc(a.kstrasse) + '<br>' + esc(a.kort) + '</div>' +
      '<p class="bf-datum">' + esc(a.ort.replace(/^\d{5}\s*/, '') || '') + ', ' + heute() + '</p>';
  }
  function betreff(a, text) {
    return '<h2>' + text + '<br>Versicherte Person: ' + esc(a.name) + (a.geb ? ', geboren am ' + esc(a.geb) : '') +
      (a.vnr ? '<br>Versichertennummer: ' + esc(a.vnr) : '') + '</h2>';
  }
  function vertretung(a) {
    if (a.wer !== 'vertretung') return '';
    return '<p>Ich schreibe ' + (a.vart === 'betreuung' ? 'als gesetzlicher Betreuer' : 'mit Vorsorgevollmacht') + ' für ' + esc(a.name) + ', ' + esc(a.strasse) + ', ' + esc(a.ort) + '. ' +
      (a.vart === 'betreuung' ? 'Eine Kopie des Betreuerausweises' : 'Eine Kopie der Vollmacht') + ' liegt bei. Bitte schicken Sie Ihre Antwort an mich.</p>';
  }
  function anrufen(a) {
    var t = a.wer === 'vertretung' && a.vtel ? a.vtel : a.tel;
    return a.telefon && t ? '<p>Bitte vereinbaren Sie den Termin für die Begutachtung vorher telefonisch: ' + esc(t) + '.</p>' : '';
  }
  function schluss(a) {
    var wer = a.wer === 'vertretung' ? a.vname : a.name;
    return '<p>Vielen Dank für Ihre Mühe.</p><p>Mit freundlichen Grüßen</p><div class="bf-unterschrift">' + esc(wer) + '</div>' +
      (a.wer === 'vertretung' ? '<p style="margin-top:6mm;font-size:9pt">Anlage: Kopie ' + (a.vart === 'betreuung' ? 'Betreuerausweis' : 'Vorsorgevollmacht') + '</p>' : '');
  }

  var BRIEFE = {
    budget: function (a) {
      var j = new Date().getFullYear();
      return kopf(a) + betreff(a, 'Bitte um schriftliche Übersicht meiner Pflegeleistungen ' + j) + '<p>Sehr geehrte Damen und Herren,</p>' + vertretung(a) +
        '<p>bei der versicherten Person ist Pflegegrad ' + esc(a.pg) + ' anerkannt. Bitte schicken Sie mir eine schriftliche Übersicht für das Jahr ' + j + ':</p>' +
        '<ul><li>Entlastungsbetrag: Wie viel ist bisher abgerechnet, wie viel ist noch frei? Gibt es noch übertragbare Beträge aus dem Vorjahr, und bis wann können sie genutzt werden?</li>' +
        '<li>Verhinderungspflege und Kurzzeitpflege: Wie viel vom gemeinsamen Jahresbetrag ist verbraucht, wie viel ist noch frei?</li>' +
        '<li>Pflegesachleistung und Pflegegeld: Welche Beträge wurden in diesem Jahr gezahlt oder abgerechnet?</li>' +
        '<li>Welche Rechnungen liegen Ihnen vor, sind aber noch nicht abgerechnet?</li></ul>' +
        '<p>Ich möchte die Leistungen sinnvoll planen und nichts verfallen lassen. Für eine Antwort innerhalb von drei Wochen bin ich Ihnen dankbar.</p>' + schluss(a);
    },
    antrag: function (a) {
      var art = { geld: 'Pflegegeld', sach: 'Pflegesachleistung (Pflegedienst)', kombi: 'eine Kombination aus Pflegegeld und Pflegesachleistung', offen: 'die passenden Leistungen; die genaue Auswahl treffe ich nach der Beratung' }[a.art || 'geld'];
      return kopf(a) + betreff(a, 'Antrag auf Leistungen der Pflegeversicherung') + '<p>Sehr geehrte Damen und Herren,</p>' + vertretung(a) +
        '<p>hiermit beantrage ich Leistungen der Pflegeversicherung für die oben genannte Person. Bitte werten Sie dieses Schreiben bereits als Antrag. Gewünscht ist vor allem ' + art + '.</p>' +
        '<p>Bitte beauftragen Sie die Begutachtung zur Feststellung des Pflegegrads. Falls Sie dafür noch ein eigenes Formular brauchen, schicken Sie es mir bitte zu. Die Leistungen beantrage ich ab dem Tag, an dem dieses Schreiben bei Ihnen eingeht.</p>' +
        anrufen(a) +
        '<p>Außerdem bitte ich um:</p><ul><li>eine kostenlose Pflegeberatung,</li><li>eine Kopie des Gutachtens nach der Begutachtung,</li><li>eine kurze Eingangsbestätigung dieses Antrags.</li></ul>' +
        '<p>Mir ist bekannt, dass über den Antrag in der Regel innerhalb von 25 Arbeitstagen entschieden werden soll.</p>' + schluss(a);
    },
    hoeher: function (a) {
      return kopf(a) + betreff(a, 'Antrag auf Überprüfung des Pflegegrads (Höherstufung)') + '<p>Sehr geehrte Damen und Herren,</p>' + vertretung(a) +
        '<p>bei der versicherten Person ist derzeit Pflegegrad ' + esc(a.pg) + ' anerkannt. Der Hilfebedarf ist inzwischen deutlich größer geworden. Ich beantrage deshalb eine erneute Begutachtung und die Einstufung in einen höheren Pflegegrad.</p>' +
        '<p>Das hat sich verändert:</p><p>' + esc(a.grund).replace(/\n/g, '<br>') + '</p>' +
        anrufen(a) +
        '<p>Bitte schicken Sie mir nach der Begutachtung eine Kopie des Gutachtens und bestätigen Sie mir kurz den Eingang dieses Antrags.</p>' + schluss(a);
    }
  };

  function setzen(muster) {
    var w = wahl(), a = d();
    var liste = w === 'paket' ? ['budget', 'hoeher'] : [w];
    druck.innerHTML = liste.map(function (b) {
      return '<section class="bf">' + (muster ? '<div class="bf-muster">MUSTER</div>' : '') + BRIEFE[b](a) + '</section>';
    }).join('');
  }

  document.getElementById('muster').addEventListener('click', function () {
    if (!pflicht(wahl())) return;
    setzen(true);
    window.print();
  });

  kaufen.addEventListener('click', function () {
    if (!pflicht(wahl())) return;
    if (!BEZAHLUNG_AKTIV) {
      document.getElementById('kauf-hinweis').innerHTML = '<strong>Die Bezahlung ist in der Vorschau noch nicht eingeschaltet.</strong> Nutze bitte „Muster ansehen und drucken“.';
      return;
    }
    // Später: Zahlung über Mollie starten, nach Rückkehr Brief ohne Muster-Aufdruck setzen und drucken.
  });

  window.addEventListener('afterprint', function () { druck.innerHTML = ''; });
})();
