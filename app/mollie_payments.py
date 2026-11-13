"""Prepared AN payment adapter. No activation, automatic retry or key discovery.

The caller persists the order and its payment reservation before create().
Callbacks carry only a payment ID; settlement always comes from Mollie GET.
This module does not issue invoices or grant access by itself.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

PROFILE = 'pfl_2fcc6rqot8'
ORIGIN = 'https://abrechnungs-navi.de'


def matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


class PaymentUncertain(RuntimeError):
    """Keep the reservation; reconcile before another attempt."""


def price(apartments, houses):
    if type(apartments) is not int or type(houses) is not int:
        raise ValueError('Wohnungen und Häuser müssen ganze Zahlen sein')
    if not 1 <= houses <= apartments <= 200:
        raise ValueError('Wohnungen oder Häuser ungültig')
    return houses * 8900 + (apartments - houses) * 5900


def cents(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d{2}', value):
        raise ValueError('Ungültiger Geldbetrag')
    try:
        return int(Decimal(value) * 100)
    except (InvalidOperation, ValueError):
        raise ValueError('Ungültiger Geldbetrag') from None


def validate_order(order):
    if not matches(r'AN-[a-f0-9]{32}', order.get('id', '')):
        raise ValueError('Ungültige Auftragskennung')
    expected = price(order.get('apartments'), order.get('houses'))
    if type(order.get('payment_attempt', 1)) is not int or not 1 <= order.get('payment_attempt', 1) <= 20:
        raise ValueError('Ungültiger Zahlungsversuch')
    if type(order.get('total_cents')) is not int or order['total_cents'] != expected:
        raise ValueError('Preis stimmt nicht mit dem Angebot überein')
    for flag in ('contract_accepted', 'avv_accepted', 'consumer_information_delivered'):
        if order.get(flag) is not True:
            raise ValueError('Dokumentierte Beauftragung unvollständig: ' + flag)
    for digest in ('offer_sha256', 'avv_sha256', 'consumer_information_sha256'):
        if not matches(r'[a-f0-9]{64}', order.get(digest, '')):
            raise ValueError('Vertragsfassung fehlt: ' + digest)
    return expected


def validate_payment(payment, order, mode):
    expected = validate_order(order)
    if not isinstance(payment, dict): raise ValueError('Ungültige Zahlungsantwort')
    if mode not in ('test', 'live') or payment.get('mode') != mode:
        raise ValueError('Falscher Zahlungsmodus')
    if payment.get('profileId') != PROFILE:
        raise ValueError('Falsches Zahlungsprofil')
    pid = order.get('payment_id', '')
    if not matches(r'tr_[A-Za-z0-9]+', pid) or payment.get('id') != pid:
        raise ValueError('Falsche Zahlungs-ID')
    metadata = payment.get('metadata')
    if not isinstance(metadata, dict) or metadata.get('brand') != 'abrechnungs-navi' or metadata.get('order_id') != order['id']:
        raise ValueError('Falsche Auftragszuordnung')
    if type(metadata.get('payment_attempt', 1)) is not int or metadata.get('payment_attempt', 1) != order.get('payment_attempt', 1):
        raise ValueError('Falscher Zahlungsversuch')
    amount = payment.get('amount', {})
    if not isinstance(amount, dict): raise ValueError('Ungültiger Zahlungsbetrag')
    if amount.get('currency') != 'EUR' or cents(amount.get('value')) != expected:
        raise ValueError('Falscher Betrag')
    # Refunds/chargebacks never silently leave an order payable/releasable.
    for field in ('amountRefunded', 'amountChargedBack'):
        if field in payment:
            money = payment[field]
            if not isinstance(money, dict) or money.get('currency') != 'EUR':
                raise ValueError('Ungültige Rückbuchungsangabe')
            if cents(money.get('value')):
                return False
    return payment.get('status') == 'paid'


def checkout_url(payment, required=True):
    try:
        checkout = payment.get('_links', {}).get('checkout', {}).get('href', '')
        if not checkout and not required: return None
        parsed = urlsplit(checkout)
        if parsed.scheme != 'https' or parsed.hostname not in ('www.mollie.com', 'mollie.com') or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError('Unexpected checkout')
        return checkout
    except (ValueError, TypeError, AttributeError):
        raise PaymentUncertain('Unerwarteter Zahlungslink; Reservierung prüfen') from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def protected_file(path, credential_directory=None):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode): raise ValueError('Zugangsdaten müssen reguläre Dateien sein')
    if not info.st_mode & 0o077: return path
    # systemd LoadCredential presents root-owned, group-readable files on a
    # sealed read-only mount. Never extend this exception to ordinary files.
    if credential_directory is not None:
        directory = Path(credential_directory)
        resolved = path.resolve(strict=True); parent = directory.resolve(strict=True)
        if parent.parent == Path('/run/credentials') and resolved.parent == parent and path.name in ('mollie-key','mollie-binding','smtp-password','extend-key'):
            dstat = parent.stat()
            if (info.st_uid == 0 and info.st_gid in (0, os.getegid()) and stat.S_IMODE(info.st_mode) == 0o440
                    and dstat.st_uid == 0 and not dstat.st_mode & 0o022
                    and os.statvfs(path).f_flag & os.ST_RDONLY and os.access(path, os.R_OK)):
                return path
    raise ValueError('Zugangsdaten benötigen 0600 oder versiegelte systemd-Credentials')


class MolliePayments:
    def __init__(self, key_path, mode, live_release=False, transport=None, binding_path=None, test_without_webhook=False, credential_directory=None):
        if mode not in ('test', 'live'):
            raise ValueError('Expliziter Zahlungsmodus erforderlich')
        if mode == 'live' and live_release is not True:
            raise ValueError('Echtbetrieb nicht freigegeben')
        if type(test_without_webhook) is not bool or test_without_webhook and mode != 'test':
            raise ValueError('Nur isolierte Testzahlungen dürfen ohne öffentlichen Webhook laufen')
        self.test_without_webhook = test_without_webhook
        path = protected_file(key_path, credential_directory)
        key = path.read_text().strip()
        self.binding = None
        self.scoped_access = matches(r'access_[A-Za-z0-9]+', key)
        if self.scoped_access:
            if binding_path is None:
                raise ValueError('Profil- und Modusnachweis für eingeschränktes Zugriffstoken erforderlich')
            proof = protected_file(binding_path, credential_directory)
            binding = json.loads(proof.read_text())
            if binding.get('brand') != 'abrechnungs-navi' or binding.get('profile_id') != PROFILE or binding.get('mode') != mode:
                raise ValueError('Profil-/Modusbindung stimmt nicht')
            if set(binding.get('permissions', [])) != {'payments.read', 'payments.write'}:
                raise ValueError('Es sind ausschließlich die zwei freigegebenen Zahlungsrechte zulässig')
            self.binding = binding
        elif not re.fullmatch(mode + r'_[A-Za-z0-9]+', key):
            raise ValueError('Schlüssel passt nicht zum Zahlungsmodus')
        self.mode, self._key = mode, key
        self.transport = transport or self._request
        self.profile_verified = False

    def _request(self, method, path, body=None, idempotency=None):
        if not (method == 'GET' and path in ('/profiles/me', '/payments?profileId=' + PROFILE + '&limit=1') or
                method == 'POST' and path == '/payments' or
                method == 'GET' and re.fullmatch(r'/payments/tr_[A-Za-z0-9]+', path)):
            raise ValueError('Unerlaubter API-Aufruf')
        headers = {'Authorization': 'Bearer ' + self._key, 'Content-Type': 'application/json'}
        if idempotency:
            headers['Idempotency-Key'] = idempotency
        req = Request('https://api.mollie.com/v2' + path, method=method,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers=headers)
        try:
            with build_opener(NoRedirect()).open(req, timeout=25) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise ValueError('Antwortlimit überschritten')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError('Ungültige Anbieterantwort')
                return result
        except Exception:
            raise PaymentUncertain('Zahlungsstatus unklar; erst anhand der gespeicherten Reservierung abgleichen') from None

    def verify_profile(self):
        if self.scoped_access:
            # payments-only tokens deliberately have no profiles.read access.
            # Their Dashboard binding is stored privately with the key; every
            # returned payment is still checked independently against PROFILE.
            if self.mode == 'live' and not (self.binding.get('live_profile_online_verified') is True or self.binding.get('website_review_complete') is True):
                raise ValueError('Mollie-Websiteprüfung noch nicht abgeschlossen')
            result = self.transport('GET', '/payments?profileId=' + PROFILE + '&limit=1')
            items = result.get('_embedded', {}).get('payments')
            if not isinstance(items, list) or any(p.get('profileId') != PROFILE or p.get('mode') != self.mode for p in items):
                raise ValueError('Zahlungsantwort verletzt Profil-/Modusbindung')
            self.profile_verified = True
            return
        profile = self.transport('GET', '/profiles/me')
        if profile.get('id') != PROFILE or profile.get('website', '').rstrip('/') != ORIGIN:
            raise ValueError('Zahlungsprofil gehört nicht zu Abrechnungs-Navi')
        if self.mode == 'live' and profile.get('status') != 'verified':
            raise ValueError('Mollie-Liveprofil noch nicht bestätigt')
        self.profile_verified = True

    def create(self, order):
        total = validate_order(order)
        if not self.profile_verified:
            raise ValueError('Zahlungsprofil zuerst prüfen')
        if order.get('payment_id'):
            raise ValueError('Vorhandene Zahlung abrufen, keine neue anlegen')
        body = {'amount': {'currency': 'EUR', 'value': f'{total // 100}.{total % 100:02d}'},
                'description': 'Abrechnungs-Navi ' + order['id'],
                'metadata': {'brand': 'abrechnungs-navi', 'order_id': order['id']},
                'redirectUrl': ORIGIN + '/zahlung/rueckkehr',
                'webhookUrl': ORIGIN + '/zahlung/webhook', 'locale': 'de_DE'}
        if self.test_without_webhook:
            body.pop('webhookUrl')
            body['description'] = 'TEST – keine echte Zahlung – ' + order['id']
        if order.get('offer_id'):
            if not matches(r'[a-f0-9]{40}', order['offer_id']):
                raise ValueError('Ungültiges Rückkehrziel')
            body['redirectUrl'] += '?auftrag=' + order['offer_id']
        if self.scoped_access:
            body['profileId'] = PROFILE
            # Dashboard advanced tokens are explicitly bound to their mode.
            # Do not send the organization-level testmode override for them.
        attempt = order.get('payment_attempt', 1)
        body['metadata']['payment_attempt'] = attempt
        idem = hashlib.sha256(('AN:' + self.mode + ':' + order['id'] + (':' + str(attempt) if attempt > 1 else '')).encode()).hexdigest()
        payment = self.transport('POST', '/payments', body, idem)
        pid = payment.get('id', '')
        if not re.fullmatch(r'tr_[A-Za-z0-9]+', pid):
            raise PaymentUncertain('Ungültige Zahlungs-ID; Reservierung prüfen')
        validate_payment(payment, {**order, 'payment_id': pid}, self.mode)
        checkout_url(payment)
        return payment

    def reconcile(self, payment_id, order):
        payment = self.retrieve(payment_id, order)
        return validate_payment(payment, order, self.mode)

    def retrieve(self, payment_id, order):
        if payment_id != order.get('payment_id') or not re.fullmatch(r'tr_[A-Za-z0-9]+', payment_id):
            raise ValueError('Unbekannte Zahlungs-ID')
        if not self.profile_verified:
            raise ValueError('Zahlungsprofil zuerst prüfen')
        payment = self.transport('GET', '/payments/' + payment_id)
        validate_payment(payment, order, self.mode)
        return payment
