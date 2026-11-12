// Startet den kleinen Bezahl-Dienst. Einstellungen kommen aus der Datei .env (nur root kann sie lesen).
import http from 'node:http';
import fs from 'node:fs';
import nodemailer from 'nodemailer';
import { app, mollieClient, speicher } from './lib.mjs';

const env = process.env;
const cfg = {
  modus: ['aus', 'test', 'live'].includes(env.MODUS) ? env.MODUS : 'aus',
  mollieKey: env.MOLLIE_KEY || '',
  basis: env.BASIS_URL || 'https://anspruchs-kompass.de',
  rechtOrdner: env.RECHT_ORDNER || '/recht',
  einrichtCode: /^\d{6}$/.test(env.EINRICHT_CODE || '') ? env.EINRICHT_CODE : null,
  einrichtBis: Number(env.EINRICHT_BIS || 0) * 1000,
  smtpPassDa: !!env.SMTP_PASS
};
const daten = env.DATEN || '/data';
fs.mkdirSync(daten, { recursive: true });

if (cfg.modus !== 'aus' && !/^(test|live)_[A-Za-z0-9]{20,}$/.test(cfg.mollieKey)) {
  console.error('MOLLIE_KEY fehlt oder sieht falsch aus. Bezahlung bleibt aus.');
  cfg.modus = 'aus';
}

function neuerTransport(pass) {
  return nodemailer.createTransport({
    host: env.SMTP_HOST || 'smtp.hostinger.com',
    port: Number(env.SMTP_PORT || 465),
    secure: Number(env.SMTP_PORT || 465) === 465,
    auth: { user: env.SMTP_USER || 'kontakt@anspruchs-kompass.de', pass }
  });
}
let transport = neuerTransport(env.SMTP_PASS);
const von = env.MAIL_VON || 'AnspruchsKompass <kontakt@anspruchs-kompass.de>';
const kopie = env.MAIL_KOPIE || '';

async function sendeMail({ an, betreff, text }) {
  await transport.sendMail({ from: von, to: an, bcc: kopie || undefined, replyTo: 'kontakt@anspruchs-kompass.de', subject: betreff, text });
}

// Einstellungen-Datei (/opt/ak-zahlung/.env), wird bei der Einrichtung im Browser fortgeschrieben.
const ENV_DATEI = env.ENV_DATEI || '/app/einstellungen.env';
const einrichtung = {
  async pruefeMollie(key) {
    try { await mollieClient({ key }).methoden(); return true; } catch (e) { console.error('Schluesselpruefung:', e.message); return false; }
  },
  async pruefeMail(pass) { await neuerTransport(pass).verify(); },
  async speichere({ key, pass, modus }) {
    let t = fs.readFileSync(ENV_DATEI, 'utf8').split('\n').filter(l => !/^(EINRICHT_CODE|EINRICHT_BIS|MOLLIE_KEY|MODUS)=/.test(l) && !(pass && /^SMTP_PASS=/.test(l)));
    t = t.filter((l, i) => l || i < t.length - 1);
    t.push('MODUS=' + modus, 'MOLLIE_KEY=' + key);
    if (pass) t.push('SMTP_PASS=' + pass);
    fs.writeFileSync(ENV_DATEI, t.join('\n') + '\n');
    if (pass) transport = neuerTransport(pass);
  }
};

const handler = app(cfg, { mollie: mollieClient({ key: () => cfg.mollieKey }), sendeMail, laden: speicher(daten + '/bestellungen.json'), einrichtung });
const port = Number(env.PORT || 8795);
http.createServer(handler).listen(port, '0.0.0.0', () => console.log('Bezahl-Dienst laeuft, Modus:', cfg.modus));

if (env.MAIL_PRUEFEN === '1' && env.SMTP_PASS) transport.verify().then(() => console.log('Mail-Anmeldung ok'), e => console.error('Mail-Anmeldung fehlgeschlagen:', e.message));
