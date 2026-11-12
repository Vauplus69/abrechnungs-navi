import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { app, speicher, bestaetigung, mollieClient } from '../lib.mjs';

const RECHT = path.join(path.dirname(fileURLToPath(import.meta.url)), 'recht');

const offen = [];
function aufbau({ modus = 'live', key = 'live_abcdefghijklmnopqrstuvwxyz', mollieStatus = 'paid', betrag } = {}) {
  const ordner = fs.mkdtempSync(path.join(os.tmpdir(), 'akz-'));
  const laden = speicher(path.join(ordner, 'b.json'));
  const mails = [];
  const zahlungen = new Map();
  let nr = 0;
  const mollie = {
    async neueZahlung(d) {
      const id = 'tr_test' + (++nr) + 'abcd';
      zahlungen.set(id, { id, status: 'open', amount: d.amount, metadata: d.metadata, d });
      return { id, _links: { checkout: { href: 'https://www.mollie.com/checkout/select-method/' + id } } };
    },
    async zahlung(id) {
      const z = zahlungen.get(id);
      return { ...z, status: z.statusNeu || 'open', amount: betrag ? { currency: 'EUR', value: betrag } : z.amount, paidAt: '2026-11-12T08:00:00+00:00', method: 'paypal' };
    }
  };
  const sendeMail = async (m) => { await new Promise(r => setTimeout(r, 20)); mails.push(m); };
  const log = { log() {}, error() {} };
  const h = app({ modus, mollieKey: key, basis: 'https://anspruchs-kompass.de', rechtOrdner: RECHT }, { mollie, sendeMail, laden, log });
  const server = http.createServer(h);
  offen.push(server);
  return new Promise(r => server.listen(0, '127.0.0.1', () => {
    const basis = 'http://127.0.0.1:' + server.address().port + '/api/zahlung';
    r({
      server, laden, mails, zahlungen, ordner,
      bezahlen(id) { zahlungen.get(id).statusNeu = mollieStatus; },
      async rufe(methode, pfad, body, form) {
        const res = await fetch(basis + pfad, { method: methode, headers: { 'Content-Type': form ? 'application/x-www-form-urlencoded' : 'application/json' }, body: form || (body ? JSON.stringify(body) : undefined) });
        const t = await res.text(); let j = null; try { j = JSON.parse(t); } catch {}
        return { code: res.status, j, t };
      },
      zu() { server.closeAllConnections(); server.close(); }
    });
  }));
}

test.afterEach(() => { for (const s of offen.splice(0)) { s.closeAllConnections(); s.close(); } });

const GUT = { brief: 'paket', email: 'kunde@example.de', zustimmung: { vorlage: true, agb: true, widerruf: true } };

test('bereit: aus, test nur mit ?test=1, live fuer alle', async () => {
  for (const [modus, ohne, mit] of [['aus', false, false], ['test', false, true], ['live', true, true]]) {
    const a = await aufbau({ modus, key: 'test_abcdefghijklmnopqrstuvwxyz' });
    assert.equal((await a.rufe('GET', '/bereit')).j.aktiv, ohne, modus);
    const r = await fetch('http://127.0.0.1:' + a.server.address().port + '/api/zahlung/bereit?test=1');
    assert.equal((await r.json()).aktiv, mit, modus);
    a.zu();
  }
});

test('start: Preis kommt vom Server, nicht vom Browser', async () => {
  const a = await aufbau();
  const r = await a.rufe('POST', '/start', { ...GUT, preis: '0.01' });
  assert.equal(r.code, 200);
  assert.match(r.j.checkout, /^https:\/\/www\.mollie\.com\//);
  const z = [...a.zahlungen.values()][0];
  assert.deepEqual(z.amount, { currency: 'EUR', value: '17.90' });
  assert.equal(z.d.redirectUrl, 'https://anspruchs-kompass.de/brief.html?bestellung=' + r.j.bestellung);
  assert.equal(z.d.webhookUrl, 'https://anspruchs-kompass.de/api/zahlung/webhook');
  a.zu();
});

test('start: lehnt fehlende Haken, falsche Mail, unbekannte Vorlage ab', async () => {
  const a = await aufbau();
  assert.equal((await a.rufe('POST', '/start', { ...GUT, zustimmung: { vorlage: true, agb: true } })).code, 400);
  assert.equal((await a.rufe('POST', '/start', { ...GUT, email: 'keine-mail' })).code, 400);
  assert.equal((await a.rufe('POST', '/start', { ...GUT, brief: 'toString' })).code, 400);
  assert.equal((await a.rufe('POST', '/start', 'kaputt')).code, 400);
  assert.equal(a.zahlungen.size, 0);
  a.zu();
});

test('start: aus = keine Zahlung; Testbetrieb mit Live-Schluessel = keine Zahlung', async () => {
  const a = await aufbau({ modus: 'aus' });
  assert.equal((await a.rufe('POST', '/start', GUT)).code, 403);
  a.zu();
  const b = await aufbau({ modus: 'test', key: 'live_abcdefghijklmnopqrstuvwxyz' });
  assert.equal((await b.rufe('POST', '/start', { ...GUT, test: true })).code, 503);
  assert.equal(b.zahlungen.size, 0);
  b.zu();
});

test('status: offen, dann bezahlt; Mail genau einmal trotz gleichzeitiger Rueckmeldungen', async () => {
  const a = await aufbau();
  const s = await a.rufe('POST', '/start', GUT);
  const id = s.j.bestellung;
  assert.equal((await a.rufe('GET', '/status?b=' + id)).j.status, 'offen');
  assert.equal(a.mails.length, 0);
  const mid = [...a.zahlungen.keys()][0];
  a.bezahlen(mid);
  const [r1, , r3] = await Promise.all([
    a.rufe('GET', '/status?b=' + id),
    a.rufe('POST', '/webhook', null, 'id=' + mid),
    a.rufe('GET', '/status?b=' + id)
  ]);
  assert.equal(r1.j.status, 'bezahlt');
  assert.equal(r1.j.brief, 'paket');
  assert.equal(r3.j.status, 'bezahlt');
  await a.rufe('GET', '/status?b=' + id);
  assert.equal(a.mails.length, 1);
  assert.equal(a.mails[0].an, 'kunde@example.de');
  const gespeichert = a.laden.hole(id);
  assert.ok(gespeichert.mail.gesendet);
  assert.equal(gespeichert.zahlart, 'paypal');
  // Gespeichert wird nichts aus dem Brief selbst
  assert.deepEqual(Object.keys(gespeichert).sort(), ['bezahlt', 'brief', 'email', 'erstellt', 'id', 'mail', 'mollieId', 'nummer', 'preis', 'status', 'test', 'zahlart', 'zustimmung']);
  a.zu();
});

test('status: falscher Betrag wird nicht freigeschaltet', async () => {
  const a = await aufbau({ betrag: '0.01' });
  const s = await a.rufe('POST', '/start', GUT);
  a.bezahlen([...a.zahlungen.keys()][0]);
  const r = await a.rufe('GET', '/status?b=' + s.j.bestellung);
  assert.equal(r.code, 502);
  assert.equal(a.mails.length, 0);
  a.zu();
});

test('status: abgebrochene Zahlung', async () => {
  const a = await aufbau({ mollieStatus: 'canceled' });
  const s = await a.rufe('POST', '/start', GUT);
  a.bezahlen([...a.zahlungen.keys()][0]);
  assert.equal((await a.rufe('GET', '/status?b=' + s.j.bestellung)).j.status, 'abgebrochen');
  assert.equal((await a.rufe('GET', '/status?b=unbekannt')).code, 404);
  a.zu();
});

test('webhook: unbekannte oder kaputte Nummer wird still angenommen', async () => {
  const a = await aufbau();
  assert.equal((await a.rufe('POST', '/webhook', null, 'id=tr_gibtsnicht1')).code, 200);
  assert.equal((await a.rufe('POST', '/webhook', null, 'id=../../x')).code, 200);
  a.zu();
});

test('Mail: Bestaetigung enthaelt Zustimmung, Erloeschen, Kleinunternehmer, AGB und Widerrufsbelehrung', () => {
  const b = { id: 'abc', nummer: 'AK-261112-ABC123', brief: 'paket', preis: '17.90', email: 'k@example.de', erstellt: Date.parse('2026-11-12T07:59:00Z'), bezahlt: Date.parse('2026-11-12T08:00:00Z'), zustimmung: { zeit: Date.parse('2026-11-12T07:59:00Z') } };
  const m = bestaetigung(b, { basis: 'https://anspruchs-kompass.de', rechtOrdner: RECHT });
  assert.match(m.betreff, /AK-261112-ABC123/);
  assert.match(m.text, /17,90 €/);
  assert.match(m.text, /12\.11\.2026, 09:00 Uhr/);
  assert.match(m.text, /§ 19 Abs\. 1 UStG/);
  assert.match(m.text, /Widerrufsrecht dadurch erlischt/);
  assert.match(m.text, /Ich stimme ausdrücklich zu/);
  assert.match(m.text, /Allgemeine Geschäftsbedingungen mit Kundeninformationen/);
  assert.match(m.text, /Mollie B\.V\./);
  assert.match(m.text, /Widerrufsbelehrung/);
  assert.match(m.text, /Muster-Widerrufsformular/);
  assert.doesNotMatch(m.text, /&#?[a-z0-9]+;|<\/?[a-z]|Startseite · Impressum/);
});

test('Mollie-Anbindung: richtige Anfrage', async () => {
  const anfragen = [];
  const fetchFn = async (url, o) => { anfragen.push({ url, o }); return new Response(JSON.stringify({ id: 'tr_x', status: 'open' }), { status: 201 }); };
  const m = mollieClient({ key: 'test_k', fetchFn });
  await m.neueZahlung({ a: 1 });
  await m.zahlung('tr_x');
  assert.equal(anfragen[0].url, 'https://api.mollie.com/v2/payments');
  assert.equal(anfragen[0].o.headers.Authorization, 'Bearer test_k');
  assert.equal(anfragen[1].url, 'https://api.mollie.com/v2/payments/tr_x');
  const f = mollieClient({ key: 'x', fetchFn: async () => new Response('{"detail":"Bad key"}', { status: 401 }) });
  await assert.rejects(f.zahlung('tr_x'), /401: Bad key/);
});
