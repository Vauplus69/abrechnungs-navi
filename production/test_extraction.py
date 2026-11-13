import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from extraction import ExtractEU, ExtractionBlocked, audit_result
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfWriter


def pdf():
    stream = io.BytesIO(); canvas = Canvas(stream)
    canvas.drawString(50, 750, 'Gesamtkosten: 355,00 EUR')
    canvas.save(); return stream.getvalue()


def response():
    return {'id': 'exr_Synthetic', 'status': 'PROCESSED', 'file': {'id': 'file_Synthetic'},
            'output': {'value': {'amount': '355,00'}, 'metadata': {'amount': {
                'ocrConfidence': 0.99, 'citations': [{'fileId': 'file_Synthetic',
                'page': {'number': 1}, 'referenceText': 'Gesamtkosten: 355,00 EUR'}]}}}}


def approval():
    return dict(brand='abrechnungs-navi', region='eu1', contract_verified=True,
                subprocessors_verified=True, retention_verified=True,
                customer_avv_allows_extraction=True, provider_evidence_sha256='a'*64)


class Extract(unittest.TestCase):
    def test_known_run_resumes_by_get_without_another_upload_or_run(self):
        calls=[]
        def api(method,path,body=None,content_type=None):
            calls.append((method,path))
            if path=='/files/upload':return {'id':'file_Synthetic'}
            if method=='POST':return {'id':'exr_Synthetic','status':'PROCESSING'}
            return response()
        with tempfile.TemporaryDirectory() as folder:
            client=self.client(Path(folder),api);raw=pdf()
            with patch('document_extraction.time.monotonic',side_effect=[0,181]),self.assertRaises(ExtractionBlocked):
                client.extract(raw)
            result=client.extract(raw)
            self.assertEqual(result['source_sha256'],__import__('hashlib').sha256(raw).hexdigest())
            self.assertEqual(calls,[('POST','/files/upload'),('POST','/extract_runs'),('GET','/extract_runs/exr_Synthetic')])
    def test_source_bound_value_and_final_review_remain_required(self):
        checked = audit_result(pdf(), response(), 'file_Synthetic')
        self.assertEqual(checked['value'], {'amount': '355,00'})
        self.assertTrue(checked['human_final_review_required'])
        self.assertFalse(checked['customer_release'])

    def test_wrong_file_page_quote_and_value_block(self):
        for mutation in ('file', 'page', 'quote', 'value', 'score', 'metadata'):
            run = response(); cite = run['output']['metadata']['amount']['citations'][0]
            if mutation == 'file': run['file']['id'] = 'file_Other'
            if mutation == 'page': cite['page']['number'] = 2
            if mutation == 'quote': cite['referenceText'] = 'invented'
            if mutation == 'value': run['output']['value']['amount'] = '999,00'
            if mutation == 'score': run['output']['metadata']['amount']['ocrConfidence'] = 0.8
            if mutation == 'metadata': run['output']['metadata'] = {}
            with self.subTest(mutation=mutation), self.assertRaises(ExtractionBlocked):
                audit_result(pdf(), run, 'file_Synthetic')

    def test_scan_without_independent_text_blocks(self):
        writer = PdfWriter(); writer.add_blank_page(width=500, height=800)
        stream = io.BytesIO(); writer.write(stream)
        with self.assertRaises(ExtractionBlocked):
            audit_result(stream.getvalue(), response(), 'file_Synthetic')

    def client(self, root, transport, a=None, budget=2, schema=None):
        key = root/'key'; key.write_text('SYNTHETICnotARealKey'); key.chmod(0o600)
        return ExtractEU(key, a or approval(), root/'state', schema or {
            'type': 'object', 'properties': {'amount': {'type': ['string', 'null']}}}, budget, transport)

    def test_cache_does_not_resubmit_and_tracks_provider_deletion(self):
        calls = []
        def api(method, path, body=None, content_type=None):
            calls.append((method, path))
            return {'id': 'file_Synthetic'} if path == '/files/upload' else response()
        with tempfile.TemporaryDirectory() as folder:
            client = self.client(Path(folder), api)
            raw = pdf(); first = client.extract(raw); second = client.extract(raw)
            self.assertEqual(first, second); self.assertEqual(len(calls), 2)
            self.assertTrue(first['provider_deletion_pending'])

    def test_uncertain_submission_keeps_reservation(self):
        calls = []
        def api(*args): calls.append(args); raise RuntimeError('synthetic transport failure')
        with tempfile.TemporaryDirectory() as folder:
            client = self.client(Path(folder), api); raw = pdf()
            with self.assertRaises(RuntimeError): client.extract(raw)
            with self.assertRaises(ExtractionBlocked): client.extract(raw)
            self.assertEqual(len(calls), 1)

    def test_budget_is_reserved_before_upload(self):
        calls = []
        def api(method, path, *args):
            calls.append(path)
            return {'id': 'file_Synthetic'} if path == '/files/upload' else response()
        with tempfile.TemporaryDirectory() as folder:
            client = self.client(Path(folder), api, budget=1)
            client.extract(pdf())
            # Another byte-distinct source must use a new reservation.
            with self.assertRaises(ExtractionBlocked): client.extract(pdf())
            self.assertEqual(len(calls), 2)

    def test_each_provider_approval_is_required(self):
        for field in ('contract_verified', 'subprocessors_verified', 'retention_verified', 'customer_avv_allows_extraction'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                a = approval(); a[field] = False
                with self.assertRaises(ExtractionBlocked):
                    self.client(Path(folder), lambda *args: self.fail('network must not run'), a)


if __name__ == '__main__': unittest.main(verbosity=2)
