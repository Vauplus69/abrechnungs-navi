// Bezahlung der Briefvorlagen ueber Mollie und Bestaetigungs-Mail nach dem Kauf.
// Die Angaben fuer den Brief bleiben im Browser. Hier landen nur:
// Bestellnummer, gewaehlte Vorlage, Preis, E-Mail-Adresse, Zustimmungen mit Zeitpunkt, Zahlungsstand.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export const PREISE = { budget: '9.90', antrag: '9.90', hoeher: '9.90', paket: '17.90', umbau: '9.90', vermieter: '9.90', konto: '9.90', witwe: '9.90', kita: '9.90' };
export const TITEL = {
  budget: 'Briefvorlage: Budgetstand anfragen',
  antrag: 'Briefvorlage: Erstantrag auf Pflegeleistungen',
  hoeher: 'Briefvorlage: Pflegegrad überprüfen lassen',
  paket: 'Paket aus zwei Briefvorlagen: Budgetstand anfragen + Pflegegrad überprüfen lassen',
  umbau: 'Briefvorlage: Zuschuss für den Umbau beantragen',
  vermieter: 'Briefvorlage: Vermieter um Zustimmung zum Umbau bitten',
  konto: 'Briefvorlage: Rentenkonto klären lassen',
  witwe: 'Briefvorlage: Anrechnung bei der Witwenrente prüfen lassen',
  kita: 'Briefvorlage: Kita-Gebühren senken lassen'
};
// Wortlaut der Haken auf der Kaufseite. Wird mit Zeitpunkt zur Bestellung gespeichert und in der Mail bestaetigt.
export const ZUSTIMMUNG = {
  vorlage: 'Mir ist klar: Ich bekomme eine allgemeine Vorlage, ausgefüllt mit meinen Angaben. Mein Fall wird nicht geprüft.',
  agb: 'Ich habe die Bedingungen für den Briefkauf gelesen.',
  widerruf: 'Ich stimme ausdrücklich zu, dass ihr vor Ablauf der Widerrufsfrist mit der Bereitstellung der Vorlage beginnt. Mir ist bekannt, dass ich dadurch mein Widerrufsrecht verliere.'
};

const MAIL_RE = /^[^\s@<>()",;:]{1,64}@[A-Za-z0-9.-]{1,200}\.[A-Za-z]{2,24}$/;

export function euro(wert) { return wert.replace('.', ',') + ' €'; }

export function zeit(ms) {
  return new Date(ms).toLocaleString('de-DE', { timeZone: 'Europe/Berlin', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) + ' Uhr';
}

// ---------- Speicher: eine JSON-Datei, sicher geschrieben ----------
export function speicher(datei) {
  let daten = {};
  try { daten = JSON.parse(fs.readFileSync(datei, 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  function sichern() {
    const tmp = datei + '.neu';
    fs.writeFileSync(tmp, JSON.stringify(daten, null, 1), { mode: 0o600 });
    fs.renameSync(tmp, datei);
  }
  return {
    hole(id) { return Object.prototype.hasOwnProperty.call(daten, id) ? daten[id] : null; },
    perMollie(mid) { return Object.values(daten).find(b => b.mollieId === mid) || null; },
    setze(b) { daten[b.id] = b; sichern(); return b; },
    alle() { return Object.values(daten); }
  };
}

// ---------- Mollie ----------
export function mollieClient({ key, basis = 'https://api.mollie.com/v2', fetchFn = fetch }) {
  async function rufe(methode, pfad, body) {
    const r = await fetchFn(basis + pfad, {
      method: methode,
      headers: { Authorization: 'Bearer ' + (typeof key === 'function' ? key() : key), 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(15000)
    });
    const text = await r.text();
    let json = null; try { json = JSON.parse(text); } catch { /* leer */ }
    if (!r.ok) { const e = new Error('Mollie ' + r.status + ': ' + (json && (json.detail || json.title) || text.slice(0, 200))); e.status = r.status; throw e; }
    return json;
  }
  return {
    neueZahlung: (daten) => rufe('POST', '/payments', daten),
    zahlung: (id) => rufe('GET', '/payments/' + encodeURIComponent(id)),
    methoden: () => rufe('GET', '/methods')
  };
}

// ---------- Bestaetigungs-Mail ----------
function htmlZuText(html) {
  return html
    .replace(/<(script|style|head)[\s\S]*?<\/\1>/gi, '')
    .replace(/<\/(p|h1|h2|h3|li|div|tr)>/gi, '\n').replace(/<br\s*\/?>/gi, '\n').replace(/<li[^>]*>/gi, '- ')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ').replace(/&auml;/g, 'ä').replace(/&ouml;/g, 'ö').replace(/&uuml;/g, 'ü')
    .replace(/&Auml;/g, 'Ä').replace(/&Ouml;/g, 'Ö').replace(/&Uuml;/g, 'Ü').replace(/&szlig;/g, 'ß')
    .replace(/&bdquo;/g, '„').replace(/&ldquo;/g, '“').replace(/&rdquo;/g, '”').replace(/&quot;/g, '"').replace(/&sect;/g, '§')
    .replace(/&ndash;/g, '–').replace(/&mdash;/g, '—').replace(/&euro;/g, '€').replace(/&shy;/g, '').replace(/&#39;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n))).replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    .replace(/[ \t]+/g, ' ').replace(/\n[ \t]+/g, '\n').replace(/\n{2,}(- |_)/g, '\n$1').replace(/\n{3,}/g, '\n\n')
    .trim().replace(/\n[^\n]*Startseite · Impressum[^\n]*$/, '').trim();
}

export function rechtstext(ordner, datei) {
  try {
    const html = fs.readFileSync(path.join(ordner, datei), 'utf8');
    const t = htmlZuText(html.replace(/[\s\S]*?<(main|article|body)[^>]*>/i, ''));
    return t.length > 200 ? t : null;
  } catch { return null; }
}

export function bestaetigung(b, { basis, rechtOrdner }) {
  const agb = rechtstext(rechtOrdner, 'bedingungen-brief.html');
  const wid = rechtstext(rechtOrdner, 'widerruf.html');
  const z = b.zustimmung;
  const zeilen = [
    'Hallo,',
    '',
    'vielen Dank für deine Bestellung bei AnspruchsKompass. Deine Zahlung ist angekommen. Hier ist deine Bestätigung zum Aufheben.',
    '',
    'DEINE BESTELLUNG',
    'Bestellnummer: ' + b.nummer,
    'Bestellt am: ' + zeit(b.erstellt),
    'Bezahlt am: ' + zeit(b.bezahlt),
    'Inhalt: ' + TITEL[b.brief],
    'Preis: ' + euro(b.preis) + ' (Endpreis, bezahlt über Mollie)',
    'Keine Umsatzsteuer, da Kleinunternehmer nach § 19 Abs. 1 UStG.',
    '',
    'So bekommst du deine Vorlage',
    'Die Vorlage steht auf der Seite bereit, auf die du nach dem Bezahlen zurückgekommen bist. Dort kannst du sie drucken oder als PDF speichern.',
    'Falls das Fenster schon zu ist: ' + basis + '/brief.html?bestellung=' + b.id,
    'Mit diesem Link kannst du deine Angaben noch einmal eintragen und die bezahlte Vorlage erneut drucken.',
    '',
    'DEINE ZUSTIMMUNGEN BEIM KAUF (' + zeit(z.zeit) + ')',
    '- ' + ZUSTIMMUNG.vorlage,
    '- ' + ZUSTIMMUNG.agb,
    '- ' + ZUSTIMMUNG.widerruf,
    '',
    'Bestätigung zum Widerrufsrecht: Du hast ausdrücklich zugestimmt, dass wir vor Ablauf der Widerrufsfrist mit der Bereitstellung der Vorlage beginnen, und bestätigt, dass dir bekannt ist, dass dein Widerrufsrecht dadurch erlischt. Mit der Bereitstellung der Vorlage ist dein Widerrufsrecht erloschen.',
    '',
    'Wichtig: Die Vorlage ist ein allgemeiner Text. Wir prüfen deinen Fall nicht und sagen nicht, ob dir eine Leistung zusteht.',
    '',
    'Viele Grüße',
    'Volker Cyrener',
    '',
    '--',
    'AnspruchsKompass · Volker Cyrener · Horster Weg 9 · 46499 Hamminkeln',
    'Telefon +49155-66619027 · kontakt@anspruchs-kompass.de · ' + basis,
    'Impressum: ' + basis + '/impressum',
    '',
    '========================================',
    'BEDINGUNGEN FÜR DEN BRIEFKAUF (Vertragstext)',
    '========================================',
    agb || ('Abrufbar unter ' + basis + '/bedingungen-brief.html'),
    '',
    '========================================',
    'WIDERRUFSBELEHRUNG',
    '========================================',
    wid || ('Abrufbar unter ' + basis + '/widerruf')
  ];
  return {
    betreff: 'Deine Bestellung ' + b.nummer + ' bei AnspruchsKompass',
    text: zeilen.join('\n')
  };
}

// ---------- Anwendung ----------
export function app(cfg, { mollie, sendeMail, laden, einrichtung = null, jetzt = Date.now, log = console }) {
  const basis = cfg.basis.replace(/\/$/, '');
  const sperren = new Map();
  const zaehler = new Map();

  function aktiv(test) {
    if (cfg.modus === 'live') return true;
    if (cfg.modus === 'test') return !!test;
    return false;
  }

  function begrenzt(ip) {
    const t = jetzt(), fenster = 3600000;
    const liste = (zaehler.get(ip) || []).filter(x => t - x < fenster);
    liste.push(t); zaehler.set(ip, liste);
    if (zaehler.size > 5000) zaehler.clear();
    return liste.length > 20;
  }

  function neueNummer() {
    const d = new Date(jetzt()).toISOString().slice(2, 10).replace(/-/g, '');
    return 'AK-' + d + '-' + crypto.randomBytes(3).toString('hex').toUpperCase();
  }

  // Mail genau einmal schicken, auch wenn Rueckmeldung von Mollie und Rueckkehr des Kunden gleichzeitig kommen.
  async function mailEinmal(b) {
    if (b.mail) return;
    if (sperren.has(b.id)) return sperren.get(b.id);
    const p = (async () => {
      const m = bestaetigung(b, { basis, rechtOrdner: cfg.rechtOrdner });
      try {
        await sendeMail({ an: b.email, betreff: m.betreff, text: m.text });
        b.mail = { gesendet: jetzt() };
      } catch (e) {
        log.error('Bestaetigungs-Mail fehlgeschlagen', b.nummer, e.message);
        b.mailFehler = (b.mailFehler || 0) + 1;
      }
      laden.setze(b);
    })().finally(() => sperren.delete(b.id));
    sperren.set(b.id, p);
    return p;
  }

  async function abgleichen(b) {
    if (b.status === 'bezahlt') { await mailEinmal(b); return b; }
    const z = await mollie.zahlung(b.mollieId);
    if (!z || z.metadata?.bestellung !== b.id) throw new Error('Zahlung passt nicht zur Bestellung');
    const alt = b.status;
    if (z.status === 'paid') {
      if (z.amount?.value !== b.preis || z.amount?.currency !== 'EUR') throw new Error('Betrag passt nicht');
      b.status = 'bezahlt'; b.bezahlt = Date.parse(z.paidAt) || jetzt(); b.zahlart = z.method || null;
    } else if (['canceled', 'expired', 'failed'].includes(z.status)) {
      b.status = 'abgebrochen';
    } else {
      b.status = 'offen';
    }
    if (b.status !== alt) laden.setze(b);
    if (b.status === 'bezahlt') await mailEinmal(b);
    return b;
  }

  function antwort(res, code, obj) {
    const body = JSON.stringify(obj);
    res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' });
    res.end(body);
  }

  async function koerper(req, max = 4096) {
    let n = 0; const teile = [];
    for await (const c of req) { n += c.length; if (n > max) throw Object.assign(new Error('zu gross'), { code: 413 }); teile.push(c); }
    return Buffer.concat(teile).toString('utf8');
  }

  // ---------- Einrichtung im Browser: Schluessel und Mail-Passwort eingeben ----------
  // Nur mit der Zahl, die beim Einrichten auf dem Server angezeigt wird. Gilt begrenzt, hoechstens 5 Fehlversuche.
  let fehlversuche = 0;
  function einrichtOffen() { return !!(einrichtung && cfg.einrichtCode && jetzt() < (cfg.einrichtBis || 0) && fehlversuche < 5); }
  function seite(res, code, titel, inhalt) {
    res.writeHead(code, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex', 'Referrer-Policy': 'no-referrer' });
    res.end('<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>' + titel + '</title>' +
      '<style>body{font:18px/1.5 system-ui,sans-serif;max-width:560px;margin:40px auto;padding:0 16px;color:#12324A;background:#F6F3EC}label{display:block;font-weight:700;margin:18px 0 4px}input{width:100%;box-sizing:border-box;font:inherit;padding:12px;border:2px solid #B8C4CE;border-radius:10px}button{margin-top:24px;font:inherit;font-weight:700;padding:14px 22px;border:0;border-radius:10px;background:#12324A;color:#fff;cursor:pointer}small{font-weight:400;color:#556}.f{background:#FDE2DD;padding:10px 14px;border-radius:10px}.ok{background:#E8F4EC;padding:14px;border-radius:10px}</style></head><body><h1>' + titel + '</h1>' + inhalt + '</body></html>');
  }
  function formular(meldung) {
    return (meldung ? '<p class="f">' + meldung + '</p>' : '') +
      '<form method="post" autocomplete="off">' +
      '<label>Zahl aus der Konsole<input name="code" inputmode="numeric" required></label>' +
      '<label>Schlüssel von Mollie <small>(beginnt mit test_ oder live_)</small><input name="key" required spellcheck="false"></label>' +
      '<label>Passwort von kontakt@anspruchs-kompass.de' + (cfg.smtpPassDa ? ' <small>(leer lassen, wenn es gleich bleibt)</small>' : '') + '<input name="pass" type="password"' + (cfg.smtpPassDa ? '' : ' required') + '></label>' +
      '<button>Speichern und prüfen</button></form>';
  }
  async function einrichten(req, res) {
    if (!einrichtOffen()) return seite(res, 403, 'Einrichtung geschlossen', '<p>Diese Seite ist gerade nicht freigeschaltet. Tippe auf dem Server <b>ak-zahlung schluessel</b>, dann bekommst du eine neue Zahl.</p>');
    if (req.method === 'GET') return seite(res, 200, 'Bezahlung einrichten', '<p>Trag hier die Zahl aus der Konsole, deinen Schlüssel von Mollie und das Mail-Passwort ein. Einfügen mit Strg + V geht hier.</p>' + formular(''));
    const f = new URLSearchParams(await koerper(req, 4096));
    const code = String(f.get('code') || '').replace(/\D/g, '');
    const key = String(f.get('key') || '').replace(/\s+/g, '');
    const pass = String(f.get('pass') || '');
    const a = Buffer.from(code.padEnd(12, 'x')), b = Buffer.from(String(cfg.einrichtCode).padEnd(12, 'x'));
    if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) { fehlversuche++; return seite(res, 400, 'Bezahlung einrichten', formular('Die Zahl stimmt nicht. Schau bitte noch einmal in die Konsole.')); }
    if (!/^(test|live)_[A-Za-z0-9]{20,}$/.test(key)) return seite(res, 400, 'Bezahlung einrichten', formular('Der Schlüssel sieht nicht richtig aus. Er beginnt mit test_ oder live_ und ist etwa 30 Zeichen lang.'));
    if (!await einrichtung.pruefeMollie(key)) return seite(res, 400, 'Bezahlung einrichten', formular('Mollie kennt diesen Schlüssel nicht. Kopier ihn bitte noch einmal aus deinem Mollie-Konto.'));
    if (pass || !cfg.smtpPassDa) {
      try { await einrichtung.pruefeMail(pass); }
      catch { return seite(res, 400, 'Bezahlung einrichten', formular('Mit diesem Passwort klappt die Anmeldung beim Postfach nicht. Bitte prüf es noch einmal.')); }
    }
    const modus = key.startsWith('test_') ? 'test' : 'aus';
    await einrichtung.speichere({ key, pass: pass || null, modus });
    cfg.mollieKey = key; cfg.modus = modus; cfg.einrichtCode = null; cfg.smtpPassDa = true;
    log.log('Einrichtung gespeichert, Modus:', modus);
    return seite(res, 200, 'Gespeichert', '<p class="ok"><b>Fertig.</b> Schlüssel und Passwort sind geprüft und gespeichert.</p>' +
      (modus === 'test' ? '<p>Der Testbetrieb läuft. Probier jetzt einen Testkauf: <a href="/brief.html?test=1">anspruchs-kompass.de/brief.html?test=1</a></p>' : '<p>Das war der echte Schlüssel. Die Bezahlung ist noch aus. Eingeschaltet wird sie erst mit deinem Ja.</p>'));
  }

  return async function (req, res) {
    const url = new URL(req.url, 'http://x');
    const p = url.pathname.replace(/^\/api\/zahlung/, '');
    const ip = String(req.headers['x-forwarded-for'] || req.socket.remoteAddress || '').split(',')[0].trim();
    try {
      if (p === '/einrichten' && (req.method === 'GET' || req.method === 'POST')) return await einrichten(req, res);
      if (req.method === 'GET' && p === '/gesund') return antwort(res, 200, { ok: true, modus: cfg.modus });

      if (req.method === 'GET' && p === '/bereit') {
        return antwort(res, 200, { aktiv: aktiv(url.searchParams.get('test') === '1'), test: cfg.modus === 'test' });
      }

      if (req.method === 'POST' && p === '/start') {
        let e; try { e = JSON.parse(await koerper(req)); } catch (x) { return antwort(res, x.code || 400, { fehler: 'Ungültige Anfrage.' }); }
        if (!aktiv(e.test === true)) return antwort(res, 403, { fehler: 'Die Bezahlung ist noch nicht eingeschaltet.' });
        if (begrenzt(ip)) return antwort(res, 429, { fehler: 'Zu viele Versuche. Bitte versuch es in einer Stunde noch einmal.' });
        const brief = String(e.brief || '');
        const email = String(e.email || '').trim();
        if (!Object.hasOwn(PREISE, brief)) return antwort(res, 400, { fehler: 'Unbekannte Vorlage.' });
        if (!MAIL_RE.test(email) || email.length > 254) return antwort(res, 400, { fehler: 'Bitte prüfe deine E-Mail-Adresse.' });
        const z = e.zustimmung || {};
        if (z.vorlage !== true || z.agb !== true || z.widerruf !== true) return antwort(res, 400, { fehler: 'Bitte setze alle drei Haken.' });
        if (cfg.modus === 'test' && !String(cfg.mollieKey).startsWith('test_')) return antwort(res, 503, { fehler: 'Testbetrieb braucht den Test-Schlüssel von Mollie.' });

        const b = {
          id: crypto.randomBytes(16).toString('base64url'),
          nummer: neueNummer(),
          brief, preis: PREISE[brief], email,
          zustimmung: { vorlage: true, agb: true, widerruf: true, zeit: jetzt(), wortlaut: ZUSTIMMUNG },
          erstellt: jetzt(), status: 'neu', test: cfg.modus === 'test'
        };
        const z2 = await mollie.neueZahlung({
          amount: { currency: 'EUR', value: b.preis },
          description: 'AnspruchsKompass ' + b.nummer,
          redirectUrl: basis + '/brief.html?bestellung=' + b.id,
          webhookUrl: basis + '/api/zahlung/webhook',
          locale: 'de_DE',
          metadata: { bestellung: b.id, nummer: b.nummer }
        });
        const checkout = z2?._links?.checkout?.href;
        if (!z2?.id || !checkout || !/^https:\/\/[a-z0-9.-]*mollie\.com\//.test(checkout)) throw new Error('Mollie-Antwort ohne Bezahlseite');
        b.mollieId = z2.id; b.status = 'offen';
        laden.setze(b);
        log.log('Bestellung angelegt', b.nummer, brief, b.test ? '(Test)' : '');
        return antwort(res, 200, { checkout, bestellung: b.id });
      }

      if (req.method === 'GET' && p === '/status') {
        const b = laden.hole(String(url.searchParams.get('b') || ''));
        if (!b || !b.mollieId) return antwort(res, 404, { fehler: 'Bestellung nicht gefunden.' });
        await abgleichen(b);
        return antwort(res, 200, { status: b.status, brief: b.brief, nummer: b.nummer, mail: !!b.mail, test: !!b.test });
      }

      if (req.method === 'POST' && p === '/webhook') {
        const id = new URLSearchParams(await koerper(req, 1024)).get('id') || '';
        const b = /^tr_[A-Za-z0-9]{4,40}$/.test(id) ? laden.perMollie(id) : null;
        if (b) await abgleichen(b);
        res.writeHead(200); return res.end('ok');
      }

      return antwort(res, 404, { fehler: 'Nicht gefunden.' });
    } catch (x) {
      log.error('Fehler', req.method, p, x.message);
      if (!res.headersSent) antwort(res, x.code === 413 ? 413 : 502, { fehler: 'Das hat gerade nicht geklappt. Bitte versuch es gleich noch einmal.' });
    }
  };
}
