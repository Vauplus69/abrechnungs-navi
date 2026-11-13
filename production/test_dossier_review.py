from copy import deepcopy
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from dossier import DossierBlocked, assemble, number
from review import ReviewBundle
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def facts():
    return {'property_address': 'TEST Haus 1', 'year': '2025', 'total_area': '100,00',
            'total_units': '2', 'owner_name': 'TEST Eigentümer', 'owner_address': 'TEST Weg 1',
            'tenants': [{'name': 'TEST A', 'unit': 'EG', 'area': '40,00', 'from': '01.01.2025', 'to': None},
                        {'name': 'TEST B', 'unit': 'OG', 'area': '60,00', 'from': '01.01.2025', 'to': None}],
            'advances': [{'name': 'TEST A', 'unit': 'EG', 'amount': '100,00', 'from': '01.01.2025', 'to': '31.12.2025'},
                         {'name': 'TEST B', 'unit': 'OG', 'amount': '100,00', 'from': '01.01.2025', 'to': '31.12.2025'}],
            'costs': [{'name': 'Grundsteuer', 'supplier': 'TEST Stadt', 'invoice': 'TEST-1', 'amount': '300,00',
                       'from': '01.01.2025', 'to': '31.12.2025'},
                      {'name': 'Gebäudeversicherung', 'supplier': 'TEST Versicherung', 'invoice': 'TEST-2',
                       'amount': '200,00', 'from': '01.01.2025', 'to': '31.12.2025'}],
            'allocations': [{'cost_name': 'Grundsteuer', 'basis': 'Wohnfläche'},
                            {'cost_name': 'Gebäudeversicherung', 'basis': 'Wohnfläche'}]}


def checked(value=None, sha='a'*64):
    return {'source_sha256': sha, 'value': value or facts(), 'sources': {},
            'customer_release': False, 'human_final_review_required': True}


ORDER = {'year': 2025, 'property_address': 'TEST Haus 1', 'apartments': 2, 'houses': 1}


class Dossier(unittest.TestCase):
    def test_multiple_units_and_costs_need_only_final_review(self):
        candidate = assemble([checked()], ORDER)
        self.assertEqual(len(candidate['mieter']), 2)
        self.assertEqual(len(candidate['kosten']), 2)
        self.assertTrue(all(c['umlage_geprueft'] is False for c in candidate['kosten']))
        self.assertTrue(candidate['entwurf'])

    def test_german_decimal_values_and_ambiguous_formats(self):
        self.assertEqual(number('1.234,56 EUR'), '1234.56')
        for value in ('1.20', '1e4', '-1,00', 'NaN', '1.234,567', None):
            with self.subTest(value=value), self.assertRaises(DossierBlocked): number(value)

    def test_missing_advances_duplicate_invoice_and_wrong_property_block(self):
        for kind in ('advance', 'duplicate', 'property', 'year', 'allocation', 'area', 'period', 'heating'):
            value = facts()
            if kind == 'advance': value['advances'].pop()
            if kind == 'duplicate': value['costs'].append(deepcopy(value['costs'][0]))
            if kind == 'property': value['property_address'] = 'Other property'
            if kind == 'year': value['year'] = '2024'
            if kind == 'allocation': value['allocations'].pop()
            if kind == 'area': value['tenants'][0]['area'] = '50,00'
            if kind == 'period': value['costs'][0]['to'] = '30.11.2025'
            if kind == 'heating':
                value['costs'][0]['name'] = 'Heizkosten'; value['allocations'][0]['cost_name'] = 'Heizkosten'
            with self.subTest(kind=kind), self.assertRaises(DossierBlocked): assemble([checked(value)], ORDER)

    def test_conflicting_document_facts_and_unsupported_houses_block(self):
        second = facts(); second['total_area'] = '101,00'
        with self.assertRaises(DossierBlocked): assemble([checked(), checked(second, 'b'*64)], ORDER)
        with self.assertRaises(DossierBlocked): assemble([checked()], {**ORDER, 'houses': 2})


class FinalReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.original = self.root/'source.pdf'; self.original.write_bytes(b'SYNTHETIC SOURCE CONTENT')
        self.files = [{'id': 'source-1', 'path': str(self.original),
                       'sha256': hashlib.sha256(self.original.read_bytes()).hexdigest()}]
        self.candidate = assemble([checked(sha=self.files[0]['sha256'])], ORDER)
        self.review = ReviewBundle(ROOT/'abrechnung/rechner.py')
        self.folder = self.root/'bundle'

    def tearDown(self): self.tmp.cleanup()

    def approve(self, **overrides):
        values = dict(version=1, reviewer='SYNTHETISCHER TESTPRÜFER', original_visual_checked=True,
                      pdf_visual_checked=True, allocation_checked=True)
        values.update(overrides)
        return self.review.approve(self.folder, self.candidate, self.files, **values)

    def test_automatic_pdf_preparation_does_not_forge_review(self):
        before = deepcopy(self.candidate)
        with self.assertRaises(ValueError): self.review.calculator.berechne(self.candidate)
        bundle = self.review.prepare(self.candidate, self.files, 1, self.folder)
        self.assertEqual(self.candidate, before)
        self.assertEqual(bundle['state'], 'needs_final_review')
        self.assertEqual(len(bundle['pdfs']), 2)
        with self.assertRaises(ValueError): self.review.download(self.folder, 'abrechnung-001.pdf')
        raw = (self.folder/'abrechnung-001.pdf').read_bytes()
        body = ''.join(p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages)
        self.assertIn('200,00', body)  # 40 percent of 500 EUR
        self.assertIn('100,00', body)  # 100 EUR advances and 100 EUR balance
        self.assertFalse(self.candidate['kosten'][0]['umlage_geprueft'])
        self.approve()
        self.assertEqual(self.review.download(self.folder, 'abrechnung-001.pdf'), raw)

    def test_missing_checks_and_stale_versions_are_rejected(self):
        self.review.prepare(self.candidate, self.files, 1, self.folder)
        for changes in ({'original_visual_checked': False}, {'pdf_visual_checked': False},
                        {'allocation_checked': False}, {'reviewer': ''}, {'version': 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.approve(**changes)

    def test_changed_original_candidate_and_pdf_are_rejected(self):
        self.review.prepare(self.candidate, self.files, 1, self.folder)
        original = self.original.read_bytes(); self.original.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.approve()
        self.original.write_bytes(original)
        old = self.candidate['mieter'][0]['vorauszahlungen']; self.candidate['mieter'][0]['vorauszahlungen'] = '0'
        with self.assertRaises(ValueError): self.approve()
        self.candidate['mieter'][0]['vorauszahlungen'] = old
        (self.folder/'abrechnung-001.pdf').write_bytes(b'%PDF changed')
        with self.assertRaises(ValueError): self.approve()


if __name__ == '__main__': unittest.main(verbosity=2)
