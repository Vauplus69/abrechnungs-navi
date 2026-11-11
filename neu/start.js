(function () {
  var EIGEN = 3671;
  var KASSE = [0, 131, 805, 1319, 1855, 2096];
  var grad = 3;
  var fmt = function (n) { return n.toLocaleString('de-DE') + ' €'; };
  var $ = function (id) { return document.getElementById(id); };
  var rente = $('rente');
  var knoepfe = document.querySelectorAll('.grade button');

  function autoText(jahr) {
    if (jahr >= 27000) return 'Das ist ungefähr so viel wie ein neues Mittelklasse-Auto.';
    if (jahr >= 15000) return 'Das ist ungefähr so viel wie ein neuer Kleinwagen.';
    if (jahr >= 6000) return 'Das ist ungefähr so viel wie ein guter Gebrauchtwagen.';
    return 'Das ist ungefähr so viel wie ein alter Gebrauchtwagen.';
  }

  function zeichnen() {
    var r = Number(rente.value);
    var gedeckt = Math.min(r, EIGEN);
    var luecke = Math.max(EIGEN - r, 0);
    $('rente-text').textContent = fmt(r);
    $('pg1').hidden = grad !== 1;
    $('ergebnis').hidden = grad === 1;
    $('b-rente').style.width = Math.round(gedeckt / EIGEN * 100) + '%';
    $('b-luecke').style.width = Math.round(luecke / EIGEN * 100) + '%';
    $('balken').setAttribute('aria-label', 'Von 3.671 € deckt die Rente ' + fmt(gedeckt) + ', es fehlen ' + fmt(luecke) + ' im Monat.');
    $('jahr').textContent = fmt(luecke * 12);
    $('satz').textContent = (luecke === 0 ? 'Die Rente deckt den Eigenanteil im Durchschnitt.' : 'Das sind ' + fmt(luecke) + ' jeden Monat.') +
      ' Zusätzlich zahlt die Pflegekasse bei Pflegegrad ' + grad + ' bis zu ' + fmt(KASSE[grad]) + ' im Monat direkt an das Heim.';
    $('auto').hidden = luecke === 0;
    $('auto-text').textContent = autoText(luecke * 12);
    knoepfe.forEach(function (b) { b.setAttribute('aria-pressed', String(Number(b.dataset.grad) === grad)); });
  }

  knoepfe.forEach(function (b) { b.addEventListener('click', function () { grad = Number(b.dataset.grad); zeichnen(); }); });
  rente.addEventListener('input', zeichnen);
  zeichnen();
})();
