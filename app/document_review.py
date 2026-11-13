"""Automatic internal PDF preparation and one source-bound human final approval.

The exact PDF reviewed by the operator is released unchanged. No synthetic
reviewer or prechecked allocation flag is stored to make the calculator run.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fingerprint(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


class ReviewBundle:
    def __init__(self, calculator_path):
        spec = importlib.util.spec_from_file_location('an_production_calculator', calculator_path)
        self.calculator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.calculator)

    def sources(self, files):
        result = []
        for file in files:
            path = Path(file['path'])
            if path.is_symlink() or not path.is_file():
                raise ValueError('Originaldatei fehlt oder ist eine Verknüpfung')
            actual = sha(path.read_bytes())
            if actual != file['sha256']:
                raise ValueError('Originaldatei verändert')
            result.append({'id': file['id'], 'sha256': actual})
        if not result or len({r['id'] for r in result}) != len(result):
            raise ValueError('Originalbestand fehlt oder enthält doppelte IDs')
        return sorted(result, key=lambda r: r['id'])

    def prepare(self, candidate, files, version, directory):
        if type(version) is not int or version < 1:
            raise ValueError('Dateiversion fehlt')
        if candidate.get('human_final_review_required') is not True:
            raise ValueError('Persönliche Schlussfreigabe erforderlich')
        if any(k.get('umlage_geprueft') is not False for k in candidate.get('kosten', [])):
            raise ValueError('Ungeprüfte Vorschläge dürfen keine menschliche Freigabe vortäuschen')
        sources = self.sources(files)
        cited = {entry['sha256'] for entry in candidate.get('source_evidence', [])}
        if cited != {entry['sha256'] for entry in sources}:
            raise ValueError('Quellbestand und belegte Eingaben stimmen nicht überein')
        entries, warnings = self.calculator.berechne(candidate, entwurf=True)
        dest = Path(directory)
        dest.mkdir(parents=True, exist_ok=False, mode=0o700)
        if not entries:
            raise ValueError('Keine Abrechnung berechnet')
        documents = []
        # Internal only: the review UI marks the bundle as NOT RELEASED. Render
        # the final-looking artifact once so approval binds its exact bytes.
        presentation = deepcopy(candidate)
        presentation.pop('entwurf', None)
        presentation.pop('testauftrag', None)
        for i, entry in enumerate(entries, 1):
            filename = f'abrechnung-{i:03d}.pdf'
            path = dest / filename
            self.calculator.pdf(presentation, entry, path)
            path.chmod(0o600)
            documents.append({'file': filename, 'sha256': sha(path.read_bytes()),
                              'total': str(entry['summe']), 'balance': str(entry['saldo'])})
        manifest = {'version': version, 'candidate_sha256': fingerprint(candidate),
                    'sources': sources, 'pdfs': documents, 'warnings': warnings,
                    'state': 'needs_final_review', 'created_at': time.time()}
        # Source files cannot change while PDFs are being produced unnoticed.
        if self.sources(files) != sources:
            raise ValueError('Quellbestand während der Berechnung verändert')
        self.save(dest / 'manifest.json', manifest)
        return manifest

    @staticmethod
    def save(path, value):
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temp.chmod(0o600)
        temp.replace(path)

    def inspect(self,directory,candidate,files,*,version,states=('needs_final_review','ready')):
        dest=Path(directory);manifest=json.loads((dest/'manifest.json').read_text())
        if manifest.get('version')!=version or manifest.get('state') not in states:
            raise ValueError('Entwurfsfassung nicht verfügbar')
        if manifest.get('candidate_sha256')!=fingerprint(candidate) or manifest.get('sources')!=self.sources(files):
            raise ValueError('Entwurf und Originalbestand stimmen nicht überein')
        for pdf in manifest.get('pdfs',[]):
            if not re.fullmatch(r'abrechnung-\d{3}\.pdf',pdf['file']):raise ValueError('Ungültiger PDF-Pfad')
            path=dest/pdf['file']
            if path.is_symlink() or sha(path.read_bytes())!=pdf['sha256']:raise ValueError('PDF-Integrität nicht bestätigt')
        if not manifest.get('pdfs'):raise ValueError('Kein Ergebnis vorhanden')
        return manifest

    def approve(self, directory, candidate, files, *, version, reviewer,
                original_visual_checked, pdf_visual_checked, allocation_checked):
        if type(version) is not int or version < 1:
            raise ValueError('Dateiversion fehlt')
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 150 or any(ord(c) < 32 for c in reviewer):
            raise ValueError('Tatsächlicher Prüfer fehlt')
        if not all(v is True for v in (original_visual_checked, pdf_visual_checked, allocation_checked)):
            raise ValueError('Original-, PDF- und Umlageprüfung müssen tatsächlich erfolgt sein')
        dest = Path(directory); path = dest / 'manifest.json'
        manifest = json.loads(path.read_text())
        if manifest.get('state') != 'needs_final_review' or manifest.get('version') != version:
            raise ValueError('Schlussfreigabe bereits erfolgt oder veraltete Dateiversion')
        if manifest['candidate_sha256'] != fingerprint(candidate) or manifest['sources'] != self.sources(files):
            raise ValueError('Eingaben oder Originale seit Erstellung verändert')
        for pdf in manifest['pdfs']:
            if not re.fullmatch(r'abrechnung-\d{3}\.pdf', pdf['file']):
                raise ValueError('Ungültiger PDF-Pfad')
            actual = dest / pdf['file']
            if actual.is_symlink() or sha(actual.read_bytes()) != pdf['sha256']:
                raise ValueError('Geprüftes PDF verändert')
        # The human has now supplied the formerly missing domain attestations.
        approved = deepcopy(candidate)
        for cost in approved['kosten']:
            cost['umlage_geprueft'] = True
        if approved.get('co2'):
            approved['co2']['wohngebaeude_regelfall_geprueft'] = True
        self.calculator.berechne(approved)
        manifest.update(state='ready', reviewed_at=time.time(), reviewer=reviewer.strip(),
                        original_visual_checked=True, pdf_visual_checked=True,
                        allocation_checked=True)
        self.save(path, manifest)
        return manifest

    def download(self, directory, filename):
        dest = Path(directory)
        manifest = json.loads((dest / 'manifest.json').read_text())
        if manifest.get('state') != 'ready':
            raise ValueError('Abrechnung noch nicht persönlich freigegeben')
        matches = [p for p in manifest['pdfs'] if p['file'] == filename]
        if len(matches) != 1 or not re.fullmatch(r'abrechnung-\d{3}\.pdf', filename):
            raise ValueError('Abrechnung nicht verfügbar')
        path = dest / filename
        if path.is_symlink(): raise ValueError('Ungültige PDF-Datei')
        raw = path.read_bytes()
        if sha(raw) != matches[0]['sha256']:
            raise ValueError('PDF-Integrität nicht bestätigt')
        return raw
