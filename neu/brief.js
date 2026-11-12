// Briefvorlagen: alles passiert im Browser, nichts wird verschickt oder gespeichert.
(function () {
  'use strict';
  var PREISE = { budget: 9.9, antrag: 9.9, hoeher: 9.9, paket: 17.9, umbau: 9.9, vermieter: 9.9, konto: 9.9, witwe: 9.9, kita: 9.9 };
  var TITEL = {
    budget: 'Budgetstand anfragen', antrag: 'Erstantrag auf Pflegeleistungen', hoeher: 'Pflegegrad überprüfen lassen',
    paket: 'Paket: Budgetstand + Pflegegrad überprüfen', umbau: 'Zuschuss für den Umbau beantragen',
    vermieter: 'Vermieter um Zustimmung bitten', konto: 'Rentenkonto klären lassen',
    witwe: 'Anrechnung bei der Witwenrente prüfen lassen', kita: 'Kita-Gebühren senken lassen'
  };
  var PFLEGE = ['budget', 'antrag', 'hoeher', 'paket', 'umbau'];
  var RENTE = ['konto', 'witwe'];
  var BEZAHLUNG_AKTIV = false; // wird erst nach Freigabe und Rechtsprüfung eingeschaltet

  var form = document.getElementById('angaben');
  var druck = document.getElementById('druck');
  var kaufen = document.getElementById('kaufen');
  var okAgb = document.getElementById('ok-agb');
  var okWid = document.getElementById('ok-widerruf');
  var okVor = document.getElementById('ok-vorlage');
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s || '').replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function absatz(s) { return esc(s).replace(/\n/g, '<br>'); }
  function euro(n) { return n.toFixed(2).replace('.', ',') + ' €'; }
  function wahl() { var r = document.querySelector('input[name=brief]:checked'); return r ? r.value : 'budget'; }
  function d() { var o = {}; new FormData(form).forEach(function (v, k) { o[k] = String(v).trim(); }); o.telefon = form.telefon.checked; return o; }
  function hat(w, liste) { return liste.indexOf(w) >= 0; }
  function vertretungMoeglich(w) { return w !== 'vermieter' && w !== 'kita'; }

  var start = new URLSearchParams(location.search).get('brief');
  if (start && PREISE[start]) { var el = document.querySelector('input[name=brief][value=' + start + ']'); if (el) el.checked = true; }

  function anpassen() {
    var w = wahl();
    document.querySelectorAll('[data-nur]').forEach(function (el) { el.hidden = el.getAttribute('data-nur').split(' ').indexOf(w) < 0; });
    document.querySelectorAll('[data-nicht]').forEach(function (el) { el.hidden = el.getAttribute('data-nicht').split(' ').indexOf(w) >= 0; });
    $('vertreter').hidden = !vertretungMoeglich(w) || d().wer !== 'vertretung';
    if (hat(w, PFLEGE)) {
      $('l-person').textContent = 'Um wen geht es? (die versicherte Person)';
      $('l-vnr').textContent = 'Versichertennummer';
      $('l-empf').textContent = 'An welche Pflegekasse?';
      $('h-empf').textContent = 'Die Pflegekasse gehört zur Krankenkasse. Die Anschrift steht auf Briefen der Kasse oder auf ihrer Internetseite.';
      $('l-empfname').textContent = 'Name der Pflegekasse';
    } else if (hat(w, RENTE)) {
      $('l-person').textContent = 'Deine Angaben';
      $('l-vnr').textContent = 'Rentenversicherungsnummer';
      $('l-empf').textContent = 'An welche Rentenversicherung?';
      $('h-empf').textContent = 'Name und Anschrift stehen oben auf deiner Renteninformation oder deinem Rentenbescheid, zum Beispiel Deutsche Rentenversicherung Rheinland.';
      $('l-empfname').textContent = 'Name der Rentenversicherung';
    } else if (w === 'vermieter') {
      $('l-person').textContent = 'Deine Angaben (Mieter)';
      $('l-empf').textContent = 'An wen geht der Brief?';
      $('h-empf').textContent = 'An deinen Vermieter oder die Hausverwaltung. Die Anschrift steht im Mietvertrag oder auf der Nebenkostenabrechnung.';
      $('l-empfname').textContent = 'Name des Vermieters oder der Hausverwaltung';
    } else {
      $('l-person').textContent = 'Deine Angaben (Mutter oder Vater)';
      $('l-empf').textContent = 'An wen geht der Antrag?';
      $('h-empf').textContent = 'Meist an das Jugendamt deiner Stadt, manchmal direkt an den Träger der Kita. Wer zuständig ist, steht auf dem Beitragsbescheid.';
      $('l-empfname').textContent = 'Jugendamt oder Kita-Träger';
    }
    $('auswahl').textContent = TITEL[w];
    $('preis').textContent = euro(PREISE[w]);
    kaufen.disabled = !(okVor.checked && okAgb.checked && okWid.checked);
  }
  document.addEventListener('change', anpassen);
  anpassen();

  function pflicht(w) {
    var namen = ['name', 'strasse', 'ort', 'empf', 'estrasse', 'eort'];
    if (w === 'budget' || w === 'hoeher' || w === 'paket' || w === 'umbau') namen.push('pg');
    if (w === 'hoeher' || w === 'paket') namen.push('grund');
    if (w === 'umbau' || w === 'vermieter') namen.push('massnahme', 'warum');
    if (w === 'witwe') namen.push('verst');
    if (w === 'kita') namen.push('kind', 'kitaname');
    if (vertretungMoeglich(w) && d().wer === 'vertretung') namen.push('vname', 'vanschrift');
    var fehlt = [];
    form.querySelectorAll('label').forEach(function (l) { l.classList.remove('br-fehlt'); });
    namen.forEach(function (n) {
      var f = form.elements[n];
      if (f && !f.value.trim()) { fehlt.push(f); f.closest('label').classList.add('br-fehlt'); }
    });
    if (fehlt.length) { fehlt[0].focus(); return false; }
    return true;
  }

  function datum(tage) { var x = new Date(); x.setDate(x.getDate() + (tage || 0)); return x.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' }); }
  function vertritt(a, w) { return vertretungMoeglich(w) && a.wer === 'vertretung'; }

  function kopf(a, w) {
    var abs = vertritt(a, w) ? a.vname + ', ' + a.vanschrift : a.name + ', ' + a.strasse + ', ' + a.ort;
    return '<div class="bf-abs">' + esc(abs) + '</div>' +
      '<div class="bf-an">' + esc(a.empf) + '<br>' + esc(a.estrasse) + '<br>' + esc(a.eort) + '</div>' +
      '<p class="bf-datum">' + esc(a.ort.replace(/^\d{5}\s*/, '')) + ', ' + datum() + '</p>';
  }
  function betreff(a, text, nummer) {
    return '<h2>' + text + '<br>Versicherte Person: ' + esc(a.name) + (a.geb ? ', geboren am ' + esc(a.geb) : '') +
      (a.vnr ? '<br>' + (nummer || 'Versichertennummer') + ': ' + esc(a.vnr) : '') + '</h2>';
  }
  function vertretung(a, w) {
    if (!vertritt(a, w)) return '';
    return '<p>Ich schreibe ' + (a.vart === 'betreuung' ? 'als gesetzlicher Betreuer' : 'mit Vorsorgevollmacht') + ' für ' + esc(a.name) + ', ' + esc(a.strasse) + ', ' + esc(a.ort) + '. ' +
      (a.vart === 'betreuung' ? 'Eine Kopie des Betreuerausweises' : 'Eine Kopie der Vollmacht') + ' liegt bei. Bitte schicken Sie Ihre Antwort an mich.</p>';
  }
  function anrufen(a) {
    var t = a.wer === 'vertretung' && a.vtel ? a.vtel : a.tel;
    return a.telefon && t ? '<p>Bitte vereinbaren Sie den Termin für die Begutachtung vorher telefonisch: ' + esc(t) + '.</p>' : '';
  }
  function schluss(a, w, anlagen) {
    var wer = vertritt(a, w) ? a.vname : a.name;
    var an = (anlagen || []).slice();
    if (vertritt(a, w)) an.push('Kopie ' + (a.vart === 'betreuung' ? 'Betreuerausweis' : 'Vorsorgevollmacht'));
    return '<p>Vielen Dank für Ihre Mühe.</p><p>Mit freundlichen Grüßen</p><div class="bf-unterschrift">' + esc(wer) + '</div>' +
      (an.length ? '<p style="margin-top:6mm;font-size:9pt">Anlage: ' + an.map(esc).join(', ') + '</p>' : '');
  }
  var ANREDE = '<p>Sehr geehrte Damen und Herren,</p>';

  var BRIEFE = {
    budget: function (a) {
      var j = new Date().getFullYear();
      return kopf(a, 'budget') + betreff(a, 'Bitte um schriftliche Übersicht meiner Pflegeleistungen ' + j) + ANREDE + vertretung(a, 'budget') +
        '<p>bei der versicherten Person ist Pflegegrad ' + esc(a.pg) + ' anerkannt. Bitte schicken Sie mir eine schriftliche Übersicht für das Jahr ' + j + ':</p>' +
        '<ul><li>Entlastungsbetrag: Wie viel ist bisher abgerechnet, wie viel ist noch frei? Gibt es noch übertragbare Beträge aus dem Vorjahr, und bis wann können sie genutzt werden?</li>' +
        '<li>Verhinderungspflege und Kurzzeitpflege: Wie viel vom gemeinsamen Jahresbetrag ist verbraucht, wie viel ist noch frei?</li>' +
        '<li>Pflegesachleistung und Pflegegeld: Welche Beträge wurden in diesem Jahr gezahlt oder abgerechnet?</li>' +
        '<li>Welche Rechnungen liegen Ihnen vor, sind aber noch nicht abgerechnet?</li></ul>' +
        '<p>Ich möchte die Leistungen sinnvoll planen und nichts verfallen lassen. Für eine Antwort innerhalb von drei Wochen bin ich Ihnen dankbar.</p>' + schluss(a, 'budget');
    },
    antrag: function (a) {
      var art = { geld: 'Pflegegeld', sach: 'Pflegesachleistung (Pflegedienst)', kombi: 'eine Kombination aus Pflegegeld und Pflegesachleistung', offen: 'die passenden Leistungen; die genaue Auswahl treffe ich nach der Beratung' }[a.art || 'geld'];
      return kopf(a, 'antrag') + betreff(a, 'Antrag auf Leistungen der Pflegeversicherung') + ANREDE + vertretung(a, 'antrag') +
        '<p>hiermit beantrage ich Leistungen der Pflegeversicherung für die oben genannte Person. Bitte werten Sie dieses Schreiben bereits als Antrag. Gewünscht ist vor allem ' + art + '.</p>' +
        '<p>Bitte beauftragen Sie die Begutachtung zur Feststellung des Pflegegrads. Falls Sie dafür noch ein eigenes Formular brauchen, schicken Sie es mir bitte zu. Die Leistungen beantrage ich ab dem Tag, an dem dieses Schreiben bei Ihnen eingeht.</p>' +
        anrufen(a) +
        '<p>Außerdem bitte ich um:</p><ul><li>eine kostenlose Pflegeberatung,</li><li>eine Kopie des Gutachtens nach der Begutachtung,</li><li>eine kurze Eingangsbestätigung dieses Antrags.</li></ul>' +
        '<p>Mir ist bekannt, dass über den Antrag in der Regel innerhalb von 25 Arbeitstagen entschieden werden soll.</p>' + schluss(a, 'antrag');
    },
    hoeher: function (a) {
      return kopf(a, 'hoeher') + betreff(a, 'Antrag auf Überprüfung des Pflegegrads (Höherstufung)') + ANREDE + vertretung(a, 'hoeher') +
        '<p>bei der versicherten Person ist derzeit Pflegegrad ' + esc(a.pg) + ' anerkannt. Der Hilfebedarf ist inzwischen deutlich größer geworden. Ich beantrage deshalb eine erneute Begutachtung und die Einstufung in einen höheren Pflegegrad.</p>' +
        '<p>Das hat sich verändert:</p><p>' + absatz(a.grund) + '</p>' + anrufen(a) +
        '<p>Bitte schicken Sie mir nach der Begutachtung eine Kopie des Gutachtens und bestätigen Sie mir kurz den Eingang dieses Antrags.</p>' + schluss(a, 'hoeher');
    },
    umbau: function (a) {
      return kopf(a, 'umbau') + betreff(a, 'Antrag auf Zuschuss für eine Maßnahme zur Verbesserung des Wohnumfelds (§ 40 Abs. 4 SGB XI)') + ANREDE + vertretung(a, 'umbau') +
        '<p>bei der versicherten Person ist Pflegegrad ' + esc(a.pg) + ' anerkannt. Ich beantrage einen Zuschuss für folgende Maßnahme in der Wohnung:</p>' +
        '<p>' + absatz(a.massnahme) + '</p>' +
        '<p>Die Maßnahme ist nötig, weil:</p><p>' + absatz(a.warum) + '</p>' +
        '<p>Der Umbau ermöglicht oder erleichtert die Pflege zu Hause und hilft, so selbstständig wie möglich zu bleiben.' +
        (a.kosten ? ' Die Kosten betragen laut beiliegendem Kostenvoranschlag ' + esc(a.kosten) + '.' : '') + '</p>' +
        '<p>Mit den Arbeiten beginne ich erst nach Ihrer Entscheidung. Falls Sie weitere Unterlagen brauchen, teilen Sie mir das bitte mit.</p>' +
        schluss(a, 'umbau', a.kosten ? ['Kostenvoranschlag'] : []);
    },
    vermieter: function (a) {
      return kopf(a, 'vermieter') + '<h2>Bitte um Erlaubnis für einen barrierereduzierenden Umbau in meiner Wohnung<br>Mieter: ' + esc(a.name) + ', ' + esc(a.strasse) + ', ' + esc(a.ort) + '</h2>' + ANREDE +
        '<p>ich möchte in meiner Wohnung folgenden Umbau durchführen lassen:</p><p>' + absatz(a.massnahme) + '</p>' +
        '<p>Der Umbau ist nötig, weil:</p><p>' + absatz(a.warum) + '</p>' +
        '<p>Nach § 554 BGB kann ich verlangen, dass Sie mir bauliche Veränderungen erlauben, die dem Gebrauch durch Menschen mit Behinderungen dienen. Die Arbeiten führt ein Fachbetrieb aus, die Kosten trage ich. Über einen möglichen Rückbau beim Auszug können wir gern sprechen.</p>' +
        '<p>Für Förderanträge brauche ich Ihre Zustimmung schriftlich. Bitte schicken Sie sie mir bis zum ' + datum(21) + '.</p>' +
        '<p>Mit freundlichen Grüßen</p><div class="bf-unterschrift">' + esc(a.name) + '</div>';
    },
    konto: function (a) {
      return kopf(a, 'konto') + betreff(a, 'Antrag auf Klärung meines Versicherungskontos', 'Versicherungsnummer') + ANREDE + vertretung(a, 'konto') +
        '<p>bitte prüfen Sie mein Versicherungskonto auf Vollständigkeit und schicken Sie mir einen aktuellen Versicherungsverlauf.</p>' +
        (a.luecken ? '<p>Folgende Zeiten fehlen möglicherweise oder sind unvollständig:</p><p>' + absatz(a.luecken) + '</p>' : '') +
        '<p>Falls Sie für die Klärung Ihr Formular „Antrag auf Kontenklärung“ (V0100) oder Nachweise brauchen, schicken Sie mir das Formular bitte zu und teilen Sie mir mit, welche Unterlagen fehlen.</p>' +
        schluss(a, 'konto');
    },
    witwe: function (a) {
      return kopf(a, 'witwe') + '<h2>Witwen- bzw. Witwerrente aus der Versicherung von ' + esc(a.verst) + (a.rz ? '<br>Rentenzeichen: ' + esc(a.rz) : '') + (a.vnr ? '<br>Meine Versicherungsnummer: ' + esc(a.vnr) : '') +
        '<br>Bitte um Überprüfung der Einkommensanrechnung</h2>' + ANREDE + vertretung(a, 'witwe') +
        '<p>ich beziehe eine Hinterbliebenenrente aus der Versicherung von ' + esc(a.verst) + '. Bitte prüfen Sie, ob mein eigenes Einkommen richtig angerechnet wird, und berücksichtigen Sie dabei den aktuellen Freibetrag.</p>' +
        (a.aenderung ? '<p>Folgendes hat sich geändert:</p><p>' + absatz(a.aenderung) + '</p>' : '') +
        '<p>Bitte schicken Sie mir einen Bescheid mit der Berechnung der Einkommensanrechnung. Falls Sie dafür Nachweise brauchen, teilen Sie mir bitte mit, welche.</p>' +
        schluss(a, 'witwe');
    },
    kita: function (a) {
      var g = a.kgrund || 'kiz';
      var text = g === 'ek'
        ? '<p>unser Einkommen ist gering beziehungsweise gesunken. Ich beantrage deshalb eine Ermäßigung oder den Erlass des Elternbeitrags nach den Regeln Ihrer Satzung. Nachweise über unser Einkommen lege ich bei. Falls Sie weitere Unterlagen oder ein eigenes Formular brauchen, teilen Sie mir das bitte mit.</p>'
        : '<p>wir beziehen ' + (g === 'kiz' ? 'Kinderzuschlag' : 'Wohngeld') + '. Nach § 90 Abs. 4 SGB VIII wird in diesem Fall kein Kostenbeitrag für die Kindertagesbetreuung erhoben. Ich beantrage deshalb den Erlass des Elternbeitrags ab sofort. Eine Kopie des aktuellen Bescheids liegt bei.</p>';
      return kopf(a, 'kita') + '<h2>Antrag auf Ermäßigung bzw. Erlass des Elternbeitrags<br>Kind: ' + esc(a.kind) + ', Kita: ' + esc(a.kitaname) + '</h2>' + ANREDE + text +
        '<p>Bitte schicken Sie mir einen schriftlichen Bescheid.</p>' +
        schluss(a, 'kita', [g === 'ek' ? 'Einkommensnachweise' : 'Kopie ' + (g === 'kiz' ? 'Bescheid Kinderzuschlag' : 'Wohngeldbescheid')]);
    }
  };

  function setzen(muster) {
    var w = wahl(), a = d();
    var liste = w === 'paket' ? ['budget', 'hoeher'] : [w];
    druck.innerHTML = liste.map(function (b) {
      return '<section class="bf">' + (muster ? '<div class="bf-muster">MUSTER</div>' : '') + BRIEFE[b](a) + '</section>';
    }).join('');
  }

  $('muster').addEventListener('click', function () {
    if (!pflicht(wahl())) return;
    setzen(true);
    window.print();
  });

  kaufen.addEventListener('click', function () {
    if (!pflicht(wahl())) return;
    if (!BEZAHLUNG_AKTIV) {
      $('kauf-hinweis').innerHTML = '<strong>Die Bezahlung ist in der Vorschau noch nicht eingeschaltet.</strong> Nutze bitte „Muster ansehen und drucken“.';
      return;
    }
    // Später: Zahlung über Mollie starten, nach Rückkehr Brief ohne Muster-Aufdruck setzen und drucken.
  });

  window.addEventListener('afterprint', function () { druck.innerHTML = ''; });
})();
