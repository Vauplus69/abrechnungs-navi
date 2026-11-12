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
  rechtOrdner: env.RECHT_ORDNER || '/recht'
};
const daten = env.DATEN || '/data';
fs.mkdirSync(daten, { recursive: true });

if (cfg.modus !== 'aus' && !/^(test|live)_\w{20,}$/.test(cfg.mollieKey)) {
  console.error('MOLLIE_KEY fehlt oder sieht falsch aus. Bezahlung bleibt aus.');
  cfg.modus = 'aus';
}

const transport = nodemailer.createTransport({
  host: env.SMTP_HOST || 'smtp.hostinger.com',
  port: Number(env.SMTP_PORT || 465),
  secure: Number(env.SMTP_PORT || 465) === 465,
  auth: { user: env.SMTP_USER, pass: env.SMTP_PASS }
});
const von = env.MAIL_VON || 'AnspruchsKompass <kontakt@anspruchs-kompass.de>';
const kopie = env.MAIL_KOPIE || '';

async function sendeMail({ an, betreff, text }) {
  await transport.sendMail({ from: von, to: an, bcc: kopie || undefined, replyTo: 'kontakt@anspruchs-kompass.de', subject: betreff, text });
}

const handler = app(cfg, { mollie: mollieClient({ key: cfg.mollieKey }), sendeMail, laden: speicher(daten + '/bestellungen.json') });
const port = Number(env.PORT || 8795);
http.createServer(handler).listen(port, '0.0.0.0', () => console.log('Bezahl-Dienst laeuft, Modus:', cfg.modus));

if (env.MAIL_PRUEFEN === '1') transport.verify().then(() => console.log('Mail-Anmeldung ok'), e => console.error('Mail-Anmeldung fehlgeschlagen:', e.message));
