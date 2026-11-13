"""Join source-checked facts into an unapproved calculation proposal.

No inferred allocation, missing advance payment, tenant or period is invented.
Unknown structures are routed to an exception queue before calculation.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal
import json
import re


class DossierBlocked(ValueError):
    pass


def obj(fields):
    return {'type': 'object', 'properties': {name: {'type': ['string', 'null'], 'description': description}
            for name, description in fields.items()}, 'additionalProperties': False}


SCHEMA = obj({'property_address': 'Property address, exactly as printed.',
              'year': 'The accounting year, exactly as printed; do not use invoice issue year instead.',
              'total_area': 'Total building residential floor area, exactly as printed.',
              'total_units': 'Total number of building residential units, exactly as printed.',
              'owner_name': 'The landlord name, exactly as printed.',
              'owner_address': 'The landlord postal address, exactly as printed.'})
for name, fields in {
    'tenants': {'name': 'Tenant name.', 'unit': 'Unit identifier.', 'area': 'Unit floor area.',
                'from': 'Beginning of occupation, literal date.', 'to': 'End of occupation if printed.'},
    'advances': {'name': 'Tenant name.', 'unit': 'Unit identifier.', 'amount': 'Total advance payments for this accounting period; no inferred monthly multiplication.',
                 'from': 'Beginning of advance payment period.', 'to': 'End of advance payment period.'},
    'costs': {'name': 'Cost category, literal label.', 'supplier': 'Invoice issuer.',
              'invoice': 'Unique invoice/reference number.', 'amount': 'Total amount relevant to this cost line, literal value.',
              'from': 'Beginning of billed service period.', 'to': 'End of billed service period.'},
    'allocations': {'cost_name': 'Cost category explicitly named in the lease allocation provision.',
                    'basis': 'Allocation basis explicitly stated for this category; do not infer legal rules.'}
}.items():
    SCHEMA['properties'][name] = {'type': ['array', 'null'], 'items': obj(fields)}


def number(value, *, integer=False):
    if not isinstance(value, str):
        raise DossierBlocked('Belegte Zahl fehlt')
    value = value.strip().replace('\u00a0', '').replace(' ', '')
    value = re.sub(r'(?:EUR|€|m²|m2)$', '', value).strip()
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d{1,2})?', value):
        raise DossierBlocked('Zahl nicht eindeutig: ' + value[:40])
    result = Decimal(value.replace('.', '').replace(',', '.'))
    if integer and result != result.to_integral_value():
        raise DossierBlocked('Ganzzahl erforderlich')
    return int(result) if integer else str(result)


def iso(value):
    if not isinstance(value, str):
        raise DossierBlocked('Belegter Zeitraum fehlt')
    value = value.strip()
    if re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', value):
        day, month, year = value.split('.'); value = year + '-' + month + '-' + day
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise DossierBlocked('Datum nicht eindeutig') from None


def assemble(checked_documents, order):
    """Standard annual, area/unit-based proposals; heating/consumption are exceptions.

    Every non-null leaf must already have passed extraction.audit_result.
    The coordinator additionally binds source file hashes before and after this call.
    """
    if not checked_documents:
        raise DossierBlocked('Unterlagen fehlen')
    year = order['year']; start, end = f'{year}-01-01', f'{year}-12-31'
    if type(year) is not int or not 2000 <= year <= date.today().year:
        raise DossierBlocked('Abrechnungsjahr ungültig')
    scalars = {}; rows = defaultdict(list); sources = []
    for document in checked_documents:
        if document.get('customer_release') is not False or document.get('human_final_review_required') is not True:
            raise DossierBlocked('Ungeprüftes Ausleseergebnis')
        sha = document.get('source_sha256', '')
        if not re.fullmatch(r'[a-f0-9]{64}', sha) or not isinstance(document.get('sources'), dict):
            raise DossierBlocked('Quellnachweis fehlt')
        value = document['value']; sources.append({'sha256': sha, 'fields': document['sources']})
        for key in ('property_address', 'year', 'total_area', 'total_units', 'owner_name', 'owner_address'):
            item = value.get(key)
            if item is None: continue
            if not isinstance(item, str) or not item.strip(): raise DossierBlocked('Feld nicht eindeutig: ' + key)
            normalized = number(item) if key == 'total_area' else number(item, integer=True) if key in ('year', 'total_units') else item.strip()
            if key in scalars and scalars[key] != normalized:
                raise DossierBlocked('Widersprüchliche Stammdaten: ' + key)
            scalars[key] = normalized
        for kind in ('tenants', 'advances', 'costs', 'allocations'):
            items = value.get(kind) or []
            if not isinstance(items, list): raise DossierBlocked('Ungültige Belegstruktur')
            for row in items:
                if not isinstance(row, dict): raise DossierBlocked('Ungültige Belegzeile')
                rows[kind].append((row, sha))
    required = {'property_address', 'year', 'total_area', 'total_units', 'owner_name', 'owner_address'}
    if required - scalars.keys():
        raise DossierBlocked('Belegte Stammdaten fehlen: ' + ', '.join(sorted(required - scalars.keys())))
    if scalars['year'] != year or scalars['property_address'] != order['property_address']:
        raise DossierBlocked('Unterlagen betreffen ein anderes Objekt oder Jahr')
    if scalars['total_units'] != order['apartments'] or scalars['total_units'] < 1:
        raise DossierBlocked('Wohnungen im Auftrag und Belegbestand stimmen nicht überein')
    if order['houses'] != 1:
        raise DossierBlocked('Mehrere Häuser benötigen getrennte Dossiers und Preiszuordnung')
    tenants = {}; areas = {}; advance = {}; allocations = {}
    for row, sha in rows['tenants']:
        name, unit = row.get('name'), row.get('unit')
        if not isinstance(name, str) or not name.strip() or not isinstance(unit, str) or not unit.strip():
            raise DossierBlocked('Mietpartei oder Wohnung nicht eindeutig')
        begin = max(start, iso(row['from']))
        finish = min(end, iso(row['to'])) if row.get('to') else end
        if begin > finish: continue
        key = (name.strip(), unit.strip(), begin, finish)
        item = {'name': key[0], 'wohnung': key[1], 'von': begin, 'bis': finish,
                'wohnflaeche': number(row.get('area')), 'heizkosten': None}
        if key in tenants and tenants[key] != item: raise DossierBlocked('Widersprüchliche Mietpartei')
        tenants[key] = item
        if key[1] in areas and areas[key[1]] != item['wohnflaeche']: raise DossierBlocked('Wohnungsfläche widersprüchlich')
        areas[key[1]] = item['wohnflaeche']
    if not tenants or len(areas) != scalars['total_units'] or sum(map(Decimal, areas.values())) != Decimal(scalars['total_area']):
        raise DossierBlocked('Wohnungsbestand oder Flächensumme unvollständig; Leerstand gesondert prüfen')
    for row, sha in rows['advances']:
        key = (row.get('name'), row.get('unit'), iso(row.get('from')), iso(row.get('to')))
        amount = number(row.get('amount'))
        if key in advance: raise DossierBlocked('Doppelte Vorauszahlungszuordnung')
        advance[key] = amount
    for key, tenant in tenants.items():
        if key not in advance: raise DossierBlocked('Belegte Vorauszahlung fehlt für eine Nutzungsperiode')
        tenant['vorauszahlungen'] = advance.pop(key)
    if advance: raise DossierBlocked('Nicht zugeordnete Vorauszahlungen')
    keys = {'Wohnfläche': 'wohnflaeche', 'Wohnflaeche': 'wohnflaeche', 'Wohneinheiten': 'einheiten'}
    for row, sha in rows['allocations']:
        name = row.get('cost_name'); basis = row.get('basis')
        if not isinstance(name, str) or not name.strip() or basis not in keys:
            raise DossierBlocked('Nicht automatisch unterstützter oder fehlender Verteilerschlüssel')
        if name in allocations and allocations[name] != keys[basis]:
            raise DossierBlocked('Widersprüchliche Verteilerschlüssel')
        allocations[name] = keys[basis]
    grouped = {}; invoices = set()
    for row, sha in rows['costs']:
        if iso(row.get('from')) != start or iso(row.get('to')) != end:
            raise DossierBlocked('Abweichenden Leistungszeitraum vor Berechnung prüfen')
        name = row.get('name')
        if not isinstance(name, str) or name not in allocations:
            raise DossierBlocked('Kostenposition ohne expliziten vertraglichen Schlüssel')
        if re.search(r'heiz|warmwasser|brennstoff|co.?2', name, re.I):
            raise DossierBlocked('Heiz-/CO2-Abrechnung benötigt Messdienst- und Sonderfallprüfung')
        supplier, invoice = row.get('supplier'), row.get('invoice')
        if not isinstance(supplier, str) or not supplier.strip() or not isinstance(invoice, str) or not invoice.strip():
            raise DossierBlocked('Rechnungsidentität fehlt')
        identity = (supplier, invoice, name)
        if identity in invoices: raise DossierBlocked('Doppelte Rechnung/Kostenposition')
        invoices.add(identity)
        amount = Decimal(number(row.get('amount')))
        if name not in grouped:
            grouped[name] = {'name': name, 'betrag': Decimal(0), 'schluessel': allocations[name],
                             'umlage_geprueft': False, 'references': []}
        grouped[name]['betrag'] += amount
        grouped[name]['references'].append({'source_sha256': sha, 'supplier': supplier, 'invoice': invoice})
    if not grouped: raise DossierBlocked('Kostenbelege fehlen')
    costs = []
    for item in grouped.values():
        item['betrag'] = str(item['betrag'])
        item['beleg'] = json.dumps(item.pop('references'), ensure_ascii=False)
        costs.append(item)
    return {'vermieter': {'name': scalars['owner_name'], 'anschrift': scalars['owner_address'], 'ort': ''},
            'objekt': {'anschrift': scalars['property_address'], 'wohnflaeche_gesamt': scalars['total_area'],
                       'einheiten_gesamt': scalars['total_units']},
            'zeitraum': {'von': start, 'bis': end}, 'kosten': costs,
            'mieter': list(tenants.values()), 'entwurf': True,
            'source_evidence': sources, 'human_final_review_required': True}
