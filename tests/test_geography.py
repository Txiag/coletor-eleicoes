import io
import json
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apuracao.api.geography import associate_features, get_geography
from scripts.prepare_geography import parse_crosswalk


class GeographyTests(unittest.TestCase):
    def test_collector_prepares_missing_maps_and_reuses_downloads_after_restart(self):
        from apuracao.collector.service import run

        csv = ('SG_UF;CD_MUNICIPIO_IBGE;CD_MUNICIPIO_TSE;NM_MUNICIPIO_IBGE;'
               'DT_GERACAO;HH_GERACAO;CD_UF_IBGE;NM_UF\n'
               'AC;1200104;01058;Brasiléia;27/09/2026;09:00:12;12;Acre\n')
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('municipio_tse_ibge.csv', csv.encode('cp1252'))

        def geometry(code):
            return json.dumps({'type': 'FeatureCollection', 'features': [
                {'properties': {'codarea': code}, 'geometry': None}
            ]}).encode()

        responses = [archive.getvalue(), geometry('12'), geometry('1200104')]
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder) / 'geography'
            config = {'database': Path(folder) / 'results.sqlite3', 'timeout_seconds': 1}
            with patch('scripts.prepare_geography.ASSET_DIR', assets), \
                 patch('scripts.prepare_geography.UFS', {'ac'}), \
                 patch('scripts.prepare_geography.urllib.request.urlopen',
                       side_effect=lambda *args, **kwargs: io.BytesIO(responses.pop(0))) as download:
                self.assertEqual(run(config, once=True), 0)
                municipality = json.loads((assets / 'ac.geojson').read_text())['features'][0]
                self.assertEqual(municipality['properties']['id'], '01058')
                self.assertEqual(download.call_count, 3)
                original = (assets / 'ac.geojson').stat().st_mtime_ns
                self.assertEqual(run(config, once=True), 0)
                self.assertEqual((assets / 'ac.geojson').stat().st_mtime_ns, original)
                (assets / 'ac.geojson').unlink()
                self.assertEqual(run(config, once=True), 0)
                self.assertEqual(json.loads((assets / 'ac.geojson').read_text())['features'][0], municipality)
                self.assertEqual(download.call_count, 3)

    def test_crosswalk_preserves_unicode_and_rejects_conflicting_identity(self):
        header = 'SG_UF;CD_MUNICIPIO_IBGE;CD_MUNICIPIO_TSE;NM_MUNICIPIO_IBGE;DT_GERACAO;HH_GERACAO;CD_UF_IBGE;NM_UF\n'
        row = 'AC;1200104;01058;Brasiléia;27/09/2026;09:00:12;12;Acre\n'
        crosswalk, _ = parse_crosswalk((header + row).encode('cp1252'))
        self.assertEqual(crosswalk['ac:1200104']['tse_code'], '01058')
        self.assertEqual(crosswalk['ac:1200104']['name'], 'Brasiléia')
        with self.assertRaises(ValueError):
            parse_crosswalk((header + row + row.replace('01058', '99999')).encode('cp1252'))

    def test_explicit_crosswalk_does_not_guess_unknown_or_different_state(self):
        collection = {"type": "FeatureCollection", "features": [
            {"properties": {"codarea": code}, "geometry": None} for code in ["1200138", "1200179"]
        ]}
        crosswalk = {"ac:1200138": {"tse_code": "01007", "name": "Bujari"},
                     "ce:1200179": {"tse_code": "99999", "name": "Outra UF"}}
        result = associate_features(collection, "ac", crosswalk)
        self.assertEqual(result["features"][0]["properties"]["id"], "01007")
        self.assertIsNone(result["features"][1]["properties"]["id"])
        self.assertEqual(len(result["features"]), 2)
        self.assertIsNotNone(result["reason"])

    def test_missing_or_corrupt_assets_fall_back_without_network(self):
        with tempfile.TemporaryDirectory() as folder, patch("apuracao.api.geography.ASSET_DIR", Path(folder)):
            self.assertFalse(get_geography("ac")["available"])
            Path(folder, "ac.geojson").write_text("broken", encoding="utf-8")
            self.assertFalse(get_geography("ac")["available"])
            self.assertEqual(get_geography("../../secret")["features"], [])
            self.assertFalse(get_geography("zz")["available"])
