"""Fachliche Fehlerfälle: Eingabe muss vor PDF-Erstellung gesperrt werden."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rechner', ROOT/'abrechnung/rechner.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)

class Rechner(unittest.TestCase):
    def setUp(self):
        self.a = json.loads((ROOT/'abrechnung/beispiel.json').read_text())

    def rejected(self, change, text):
        change(self.a)
        with self.assertRaisesRegex(ValueError, text):
            r.berechne(self.a)

    def test_independent_sample_decimal_and_input_not_mutated(self):
        before=copy.deepcopy(self.a)
        es,_=r.berechne(self.a)
        for m,e in zip(self.a['mieter'],es):
            expected=[]
            for k in self.a['kosten']:
                if k['schluessel']=='verbrauch': ratio=Decimal(str(m['verbrauch'][k['name']]))/Decimal(231)
                elif k['schluessel']=='personen': ratio=Decimal(m['personentage'])/Decimal(1825)
                elif k['schluessel']=='einheiten': ratio=Decimal(1)/Decimal(3)
                else: ratio=Decimal(str(m['wohnflaeche']))/Decimal(210)
                expected.append((Decimal(str(k['betrag']))*ratio).quantize(Decimal('.01'),rounding='ROUND_HALF_UP'))
            total=sum(expected)+Decimal(str(m['heizkosten']))-(Decimal(str(m['co2_kosten_anteil']))/2).quantize(Decimal('.01'),rounding='ROUND_HALF_UP')
            self.assertEqual(Decimal(str(e['summe'])),total)
            self.assertEqual([Decimal(str(x['anteil'])) for x in e['posten'][:6]],expected)
        self.assertEqual(self.a,before)

    def test_missing_consumption(self):
        self.rejected(lambda a:a['mieter'][0]['verbrauch'].clear(),'Verbrauch')
    def test_negative_consumption(self):
        self.rejected(lambda a:a['mieter'][0]['verbrauch'].update({'Wasser und Abwasser':-10}),'nicht negative')
    def test_zero_consumption_is_valid_with_documented_rest(self):
        self.a['mieter'][0]['verbrauch']['Wasser und Abwasser']=0
        self.a['kosten'][1]['vermieter_rest']={'betrag':850.89,'grund':'TEST Vermieterverbrauch 142 m³','beleg':'TEST Zähler'}
        es,_=r.berechne(self.a)
        self.assertEqual(es[0]['posten'][1]['anteil'],0)
    def test_nonfinite_and_boolean(self):
        for value in [float('nan'),float('inf'),True,'NaN',None]:
            with self.subTest(value=value):
                a=copy.deepcopy(self.a);a['mieter'][0]['verbrauch']['Wasser und Abwasser']=value
                with self.assertRaises(ValueError):r.berechne(a)
    def test_unexplained_old_water_gap(self):
        self.rejected(lambda a:a['kosten'][1].update(verbrauch_gesamt=268),'ungeklärte')
    def test_documented_water_gap(self):
        self.a['kosten'][1].update(verbrauch_gesamt=268,vermieter_rest={'betrag':191.10,'grund':'TEST Vermieterverbrauch 37 m³','beleg':'TEST Zählerprotokoll'})
        _,notes=r.berechne(self.a)
        self.assertTrue(any('191,10' in n for n in notes))
    def test_fake_rest_or_missing_reference_rejected(self):
        for rest in [{'betrag':191.10,'grund':'','beleg':'TEST'}, {'betrag':1,'grund':'TEST','beleg':'TEST'}]:
            a=copy.deepcopy(self.a);a['kosten'][1].update(verbrauch_gesamt=268,vermieter_rest=rest)
            with self.assertRaises(ValueError):r.berechne(a)
    def test_overallocated_quantities_block_even_with_rounding(self):
        self.rejected(lambda a:a['kosten'][1].update(betrag=0,verbrauch_gesamt=230),'überschreiten')
    def test_outside_or_reversed_tenancy(self):
        for start,end in [('2026-01-01','2026-12-31'),('2025-12-31','2025-01-01'),('2024-12-01','2025-12-31')]:
            a=copy.deepcopy(self.a);a['mieter'][0].update(von=start,bis=end)
            with self.assertRaisesRegex(ValueError,'Nutzungszeitraum'):r.berechne(a)
    def test_short_co2_year_is_blocked(self):
        self.rejected(lambda a:(a['zeitraum'].update(bis='2025-06-30'),a['co2'].update(kg_co2_gesamt=3465)),'CO2.*Kalenderjahre')
    def test_leap_year_is_full_co2_year(self):
        self.a['zeitraum']={'von':'2024-01-01','bis':'2024-12-31'}
        es,_=r.berechne(self.a);self.assertEqual(es[0]['tage'],366)
    def test_co2_step_boundaries(self):
        for value,expected in [(0,0),(11.999,0),(12,.1),(17,.2),(22,.3),(27,.4),(32,.5),(37,.6),(42,.7),(47,.8),(52,.95),(100,.95)]:
            self.assertEqual(r.co2_vermieteranteil(Decimal(str(value))),expected)
    def test_zero_area_and_bad_money(self):
        self.rejected(lambda a:a['objekt'].update(wohnflaeche_gesamt=0),'Gesamtwohnfläche')
    def test_missing_heat_status(self):
        self.rejected(lambda a:a['mieter'][0].pop('heizkosten_status'),'heizkosten_status')
    def test_net_heating_no_double_deduction(self):
        before=r.berechne(self.a)[0][0]['summe']
        m=self.a['mieter'][0];m.update(heizkosten=1057.50,heizkosten_status='nach_co2_abzug',co2_vermieterabzug=48.10)
        es,notes=r.berechne(self.a)
        self.assertEqual(es[0]['summe'],before)
        self.assertEqual(len(es[0]['posten']),7)
        self.assertTrue(any('kein zweiter Abzug' in n for n in notes))
    def test_inconsistent_net_deduction(self):
        self.rejected(lambda a:a['mieter'][0].update(heizkosten_status='nach_co2_abzug',co2_vermieterabzug=0),'stimmt nicht')
    def test_old_ambiguous_heat_flag(self):
        self.rejected(lambda a:a['mieter'][0].update(co2_bereits_abgezogen=True),'Altes CO2')
    def test_no_co2_or_unverified_special_case(self):
        self.rejected(lambda a:a['co2'].update(wohngebaeude_regelfall_geprueft=False),'Regelfall')
    def test_missing_person_days(self):
        self.rejected(lambda a:a['objekt'].pop('personentage_gesamt'),'Personenschlüssel')
    def test_excluded_management_never_charged(self):
        before=r.berechne(self.a)[0]
        self.a['kosten'].append({'name':'Verwaltungskosten','betrag':300,'schluessel':'wohnflaeche'})
        with self.assertRaisesRegex(ValueError,'gesperrte Kostenart'):r.berechne(self.a)
        self.a['kosten'][-1]['umlegen']=False
        es,notes=r.berechne(self.a);self.assertEqual(before,es)
        self.assertTrue(any('Ausgeschlossen' in n for n in notes))
    def test_unreviewed_costs(self):
        self.rejected(lambda a:a['kosten'][0].update(umlage_geprueft=False),'Umlagefähigkeit')
    def test_no_pdf_on_bad_data(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.a['mieter'][0]['verbrauch'].clear();(p/'bad.json').write_text(json.dumps(self.a))
            with self.assertRaises(ValueError):r.main(p/'bad.json',p/'out')
            self.assertFalse((p/'out').exists())
    def test_sample_pdf_unicode_and_mock_label(self):
        es,_=r.berechne(self.a)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out.pdf';r.pdf(self.a,es[0],p);reader=PdfReader(p)
            text=''.join(page.extract_text() for page in reader.pages)
            self.assertIn('CO₂',text);self.assertIn('MUSTER',text);self.assertIn('TEST-Messdienst',text)
            self.assertTrue(any('/FontFile2' in f.get_object().get('/FontDescriptor',{}).get_object() for page in reader.pages for f in page['/Resources']['/Font'].values() if '/FontDescriptor' in f.get_object()))

    def test_http_workflow_with_calculated_pdf(self):
        from test_workflow import EndToEnd
        es,_=r.berechne(self.a)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'calculated.pdf';r.pdf(self.a,es[0],path)
            EndToEnd('test_gates_upload_publish_download_and_deletion').check_order(path.read_bytes())

if __name__=='__main__':unittest.main()
