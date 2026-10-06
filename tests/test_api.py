from apuracao.official_store import save_response
import tempfile, unittest
from pathlib import Path
from fastapi.testclient import TestClient
from apuracao.database import connect
from apuracao.api import create_app

class ApiTest(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = connect(Path(self.folder.name) / 'result.sqlite3')
        self.addCleanup(self.db.close)
        with self.db:
            self.db.execute("INSERT INTO datasets VALUES('test','http://example/oficial','ele2026',3220,'official')")
        import json
        catalog = {'pl': [{'cd': '3220', 'c': 'ele2026', 'e': [
            {'cd': str(election), 'nm': str(election), 't': '1', 'tp': '1',
             'abr': [{'cd': 'br', 'cp': [{'cd': str(office)} for office in offices]}]}
            for election, offices in [(6257, [1]), (6259, [3, 5, 6, 7, 8]), (6261, [25])]
        ]}]}
        url = 'http://example/oficial/comum/config/ele-c.json'
        with self.db:
            self.db.execute('insert into sources(url,name) values(?,?)', (url, 'EA11'))
            save_response(self.db, url, '2026-10-04T20:00:00Z', 'fixture', json.dumps(catalog))
        area = {'f': 'o', 'abr': [{'cd': 'ac', 'ds': 'Acre', 'mu': [
            {'cd': '01074', 'nm': 'Município de teste', 'z': ['0004']},
            {'cd': '01120', 'nm': 'Outro município', 'z': ['0004']}]}]}
        with self.db:
            url = 'http://example/oficial/ele2026/6257/config/mun-e006257-cm.json'
            self.db.execute('INSERT INTO sources(url,name) VALUES(?,?)', (url, 'EA12'))
            save_response(self.db, url, '2026-10-04T20:00:00Z', 'fixture', json.dumps(area))
        self.client = TestClient(create_app(Path(self.folder.name) / 'result.sqlite3'))
        self.params = dict(dataset='test', election=6257, office=1)

    def dashboard(self, **kw):
        r = self.client.get('/api/dashboard', params={**self.params, **kw})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_missing_database_and_validation(self):
        missing = Path(self.folder.name) / 'missing.sqlite3'
        self.assertEqual(TestClient(create_app(missing)).get('/api/metadata').status_code, 503)
        self.assertFalse(missing.exists())
        self.assertEqual(self.client.get('/api/dashboard', params={**self.params, 'office': 999}).status_code, 404)
        self.assertEqual(self.client.get('/api/dashboard', params={**self.params, 'zone': '0004'}).status_code, 422)
        self.assertEqual(self.client.get('/api/options', params={**self.params, 'level': 'zone'}).status_code, 422)

    def save_official(self, payload, area='br', fetched_at='2026-10-04T20:00:00Z'):
        import json
        import hashlib
        election = int(payload['ele'])
        office = int(payload['carg'][0]['cd'])
        url = f'http://example/oficial/ele2026/{election}/dados/{area[:2]}/{area}-c{office:04d}-e{election:06d}-u.json'
        with self.db:
            self.db.execute("insert or ignore into sources(url,name) values(?, 'EA20')", (url,))
            save_response(self.db, url, fetched_at, hashlib.sha256(json.dumps(payload).encode()).hexdigest(), json.dumps(payload))

    def test_candidate_scope_search_denominator_pagination_and_party(self):
        payload = {'ele': '6257', 't': '1', 'f': 'o', 'tpabr': 'uf', 'cdabr': 'ac',
            'and': 'p', 'dv': 's', 'v': {'tv': '100', 'vnom': '100', 'vvc': '100'},
            'carg': [{'cd': '1', 'agr': [{'par': [
                {'n': '90', 'sg': 'A', 'tvtn': '70', 'cand': [{'n': '90', 'nmu': 'Ana', 'vap': '70', 'pvapn': '70'}]},
                {'n': '91', 'sg': 'B', 'tvtn': '30', 'cand': [{'n': '91', 'nmu': 'Bia', 'vap': '30', 'pvapn': '30'}]}
            ]}]}]}
        self.save_official(payload, 'ac')
        first = self.dashboard(uf='ac', page_size=1)
        self.assertEqual(first['candidates']['items'][0]['name'], 'Ana')
        self.assertEqual(first['candidates']['remaining'], {'count': 1, 'votes': 30, 'percentage': 30})
        second = self.dashboard(uf='ac', page_size=1, candidate_page=2)
        self.assertEqual(second['candidates']['items'][0]['name'], 'Bia')
        search = self.dashboard(uf='ac', search='bia')['candidates']
        self.assertEqual((search['total'], search['denominator'], search['items'][0]['percentage']), (1, 100, 30))
        territory = self.dashboard(candidate='90', candidate_scope='br')['territories']['items'][0]
        self.assertEqual((territory['candidate_votes'], territory['leader']['number'], territory['margin']), (70, '90', 40))
        other_scope = self.dashboard(candidate='90', candidate_scope='ac')['territories']['items'][0]
        self.assertIsNone(other_scope['candidate_votes'])

    def test_regional_progress_weights_sections_and_requires_every_state(self):
        payload = {'ele': '6257', 't': '1', 'f': 'o', 'tpabr': 'uf',
                   'and': 'p', 'dv': 's', 'v': {'tv': '100'},
                   'carg': [{'cd': '1'}], 'dt': '04/10/2026', 'ht': '17:00:00'}
        for uf, totalized, total in [('pr', 10, 10), ('rs', 0, 30), ('zz', 900, 900)]:
            self.save_official({**payload, 'cdabr': uf, 's': {'st': str(totalized), 'ts': str(total)}}, uf)
        with self.db:
            self.db.execute("insert into sources(url,name,error) values(?, 'EA20', 'HTTP 403')",
                            ('http://example/oficial/ele2026/6257/dados/sc/sc-c0001-e006257-u.json',))
        regions = self.dashboard(source='official').get('regions')
        self.assertIsNotNone(regions, 'A API deve entregar o progresso regional oficial.')
        south = next(r for r in regions if r['id'] == 'sul')
        self.assertEqual(south['status'], 'incomplete')
        self.assertEqual(south['missing_ufs'], ['sc'])

        self.assertEqual(south['error_ufs'], ['sc'])
        self.assertIsNone(south['percentage'])
        self.assertIsNone(south['total'])

        self.save_official({**payload, 'cdabr': 'sc', 'ht': '17:05:00', 's': {'st': '10', 'ts': '10'}}, 'sc')
        south = next(r for r in self.dashboard(source='official')['regions'] if r['id'] == 'sul')
        self.assertEqual((south['totalized'], south['total'], south['percentage']), (20, 50, 40))
        self.assertEqual(south['status'], 'available')
        self.assertEqual(south['updated_at'], '2026-10-04T17:00:00-03:00')
        self.assertEqual(south['collected_at'], '2026-10-04T20:00:00Z')
        local = self.dashboard(source='official', uf='pr', municipality='12345')
        self.assertEqual(next(r for r in local['regions'] if r['id'] == 'sul')['percentage'], 40)
        with self.db:
            self.db.execute("update sources set error='HTTP 429' where url like '%/sc-c0001-%'")
        south = next(r for r in self.dashboard(source='official')['regions'] if r['id'] == 'sul')
        self.assertEqual(south['percentage'], 40)
        self.assertEqual(south['error_ufs'], ['sc'])

        with self.assertRaises(ValueError):
            self.save_official({**payload, 'cdabr': 'sc', 't': '2', 's': {'st': '10', 'ts': '10'}}, 'sc')
        south = next(r for r in self.dashboard(source='official')['regions'] if r['id'] == 'sul')
        self.assertEqual(south['percentage'], 40)
        self.assertEqual(south['missing_ufs'], [])

    def test_regional_ranking_weights_votes_and_waits_for_missing_states(self):
        def save(uf, ana, bia, at='2026-10-04T20:00:00Z'):
            total = ana + bia
            self.save_official({'ele': '6257', 't': '1', 'f': 'o', 'tpabr': 'uf', 'cdabr': uf,
                'and': 'p', 'dv': 's', 'v': {'tv': str(total), 'vnom': str(total), 'vvc': str(total)},
                's': {'st': '5', 'ts': '10'}, 'dt': '04/10/2026', 'ht': '17:00:00',
                'carg': [{'cd': '1', 'agr': [{'par': [
                    {'n': '90', 'sg': 'A', 'tvtn': str(ana), 'cand': [{'n': '90', 'nmu': 'Ana', 'vap': str(ana)}]},
                    {'n': '91', 'sg': 'B', 'tvtn': str(bia), 'cand': [{'n': '91', 'nmu': 'Bia', 'vap': str(bia)}]},
                ]}]}]}, uf, at)

        def south(**filters):
            return next(r for r in self.dashboard(source='official', **filters)['regions'] if r['id'] == 'sul')

        save('pr', 90, 10)
        save('rs', 10, 90)
        self.assertEqual(south()['ranking']['status'], 'incomplete')
        self.assertEqual(south()['ranking']['items'], [])
        save('sc', 100, 700)
        ranking = south()['ranking']
        self.assertEqual([(c['name'], c['votes'], c['percentage']) for c in ranking['items']], [('Bia', 800, 80), ('Ana', 200, 20)])
        self.assertEqual(south()['percentage'], 50)
        save('sc', 800, 0, '2026-10-04T20:10:00Z')
        self.assertEqual(south()['ranking']['items'][0]['name'], 'Ana')
        self.assertEqual(south(uf='pr')['ranking']['items'][0]['votes'], 900)

    def test_consolidated_results_replace_votes_and_candidate_names(self):
        from copy import deepcopy
        payload = {'ele': '6257', 't': '1', 'f': 'o', 'tpabr': 'br', 'cdabr': 'br',
            'and': 'p', 'dv': 's', 'dt': '04/10/2026', 'ht': '17:00:00',
            'v': {'tv': '10', 'vnom': '10', 'vvc': '10'}, 's': {'st': '1', 'ts': '2'},
            'carg': [{'cd': '1', 'agr': [{'par': [{'n': '90', 'sg': 'A', 'tvtn': '10',
                'cand': [{'n': '90', 'nmu': 'Ana', 'vap': '10', 'pvapn': '100'}]}]}]}]}
        self.save_official(payload)
        self.save_official({**payload, 'tpabr': 'uf', 'cdabr': 'ac'}, 'ac')
        newer = deepcopy(payload)
        newer['v'].update(tv='20', vnom='20', vvc='20')
        newer['s']['st'] = '2'
        newer['carg'][0]['agr'][0]['par'][0].update(tvtn='20')
        newer['carg'][0]['agr'][0]['par'][0]['cand'][0]['vap'] = '20'
        self.save_official(newer, fetched_at='2026-10-04T20:10:00Z')
        self.save_official({**newer, 'tpabr': 'uf', 'cdabr': 'ac'}, 'ac', '2026-10-04T20:10:00Z')
        self.save_official({**newer, 'tpabr': 'mu', 'cdabr': '01074'}, 'ac01074', '2026-10-04T20:10:00Z')
        with self.db:
            self.db.execute("update sources set error='HTTP 429',checked_at='2026-10-04T20:11:00Z'")
        current = self.dashboard(source='official')
        self.assertEqual(current['summary']['nominal_votes'], 20)
        from unittest.mock import patch
        from apuracao import official
        dataset = dict(self.db.execute("SELECT * FROM datasets WHERE id='test'").fetchone())
        self.assertTrue(official.catalog(self.db, dataset)['pl'])
        with patch('apuracao.official.latest', side_effect=AssertionError('Votos devem vir das tabelas estruturadas')):
            result = official.result(self.db, dataset, 6257, 1)
            self.assertEqual(result['votes'], 20)
        self.assertEqual(current['source']['totalized_sections'], 2)
        municipality = self.dashboard(source='official', uf='ac', municipality='01074')
        self.assertEqual(municipality['map_territory']['winner']['name'], 'Ana')
        self.assertEqual(municipality['map_territory']['winner']['votes'], 20)
        for endpoint in ('dashboard', 'map'):
            response = self.client.get('/api/' + endpoint, params={**self.params, 'at': '2026-10-04T20:00:00Z'})
            self.assertEqual(response.status_code, 422)
        renamed = deepcopy(newer)
        renamed['carg'][0]['agr'][0]['par'][0]['cand'][0]['nmu'] = 'Ana atualizada'
        self.save_official(renamed, fetched_at='2026-10-04T20:30:00Z')
        self.assertEqual(official.result(self.db, dataset, 6257, 1)['candidates'][0]['name'], 'Ana atualizada')

    def test_regional_progress_respects_office_scope_and_precount_zero(self):
        payload = {'ele': '6259', 't': '1', 'f': 'o', 'tpabr': 'uf', 'cdabr': 'df',
                   'and': 'n', 'v': {'tv': '0'}, 's': {'st': '0', 'ts': '10'},
                   'carg': [{'cd': '8'}]}
        self.save_official(payload, 'df')
        regions = self.dashboard(source='official', election=6259, office=8)['regions']
        center = next(r for r in regions if r['id'] == 'centro-oeste')
        self.assertEqual(center['expected_ufs'], ['df'])
        self.assertEqual((center['percentage'], center['total']), (0, 10))
        self.assertTrue(all(r['status'] == 'not_applicable' for r in regions if r['id'] != 'centro-oeste'))
        payload['s'] = {'st': '0', 'ts': '0'}
        self.save_official(payload, 'df')
        center = next(r for r in self.dashboard(source='official', election=6259, office=8)['regions'] if r['id'] == 'centro-oeste')
        self.assertIsNone(center['percentage'])
        self.assertEqual(center['status'], 'pending')

    def test_official_precount_release_identity_and_party_totals(self):
        payload = {'ele': '6257', 't': '1', 'f': 'o', 'tpabr': 'br', 'cdabr': 'br', 'and': 'n', 'dv': 's', 'v': {'tv': '0', 'vnom': '0', 'vb': '0', 'tvn': '0'}, 's': {'st': '0', 'ts': '2'}, 'carg': [{'cd': '1', 'agr': [{'par': [{'n': '90', 'sg': 'A', 'tvtn': '0', 'cand': [{'n': '90', 'nmu': 'Ana', 'vap': '0', 'pvapn': '0', 'st': ''}]}]}]}]}
        self.save_official(payload)
        p = self.dashboard(source='official')
        self.assertIsNone(p['summary']['votes'])
        self.assertIsNone(p['candidates']['items'][0]['votes'])
        payload.update({'and': 'p', 'dt': '04/10/2026', 'ht': '17:00:00'})
        payload['v'].update(tv='152', vvc='150', vnom='100', vb='2')
        party = payload['carg'][0]['agr'][0]['par'][0]
        party['tvtn'] = '100'
        party['cand'][0].update(vap='100', pvapn='66.666')
        self.save_official(payload)
        p = self.dashboard(source='official')
        self.assertEqual(p['summary']['votes'], 152)
        self.assertEqual(p['summary']['nominal_votes'], 100)
        self.assertEqual(p['candidates']['items'][0]['votes'], 100)
        self.assertEqual(p['candidates']['items'][0]['percentage'], 66.666)
        self.assertEqual(p['candidates']['denominator'], 150)
        self.assertEqual(p['candidates']['remaining'], {'count': 0, 'votes': 0, 'percentage': 0})
        self.assertEqual(p['candidates']['denominator_label'], 'votos a votáveis concorrentes')
        party['cand'][0]['pvapn'] = '66,666666667'
        self.save_official(payload)
        p = self.dashboard(source='official')
        self.assertEqual(p['candidates']['items'][0]['percentage'], 66.666666667)
        del payload['v']['vvc']
        self.save_official(payload)
        p = self.dashboard(source='official')
        self.assertIsNone(p['candidates']['denominator'])
        self.assertIsNone(p['candidates']['items'][0]['percentage'])
        self.assertEqual(p['summary']['nominal_votes'], 100)
        payload['dv'] = 'n'
        self.save_official(payload)
        self.assertIsNone(self.dashboard(source='official')['summary']['votes'])
        payload['dv'] = 's'
        payload['t'] = '2'
        with self.assertRaises(ValueError):
            self.save_official(payload)
        self.assertFalse(self.dashboard(source='official')['source']['available'])

    def test_official_zone_uses_municipality_context_and_validates_identity(self):
        payload = {'ele': '6257', 't': '1', 'f': 'o', 'tpabr': 'zona', 'cdabr': '0004',
                   'and': 'p', 'dv': 's', 'v': {'tv': '10'}, 'carg': [{'cd': '1'}]}
        self.save_official(payload, area='ac01074-z0004')
        self.save_official({**payload, 'v': {'tv': '30'}}, area='ac01120-z0004')
        for city, votes in [('01074', 10), ('01120', 30)]:
            p = self.dashboard(source='official', uf='ac', municipality=city, zone='0004')
            self.assertEqual(p['summary']['votes'], votes)
            self.assertTrue(p['source']['available'])
            self.assertEqual(p['territories'], {'items': [], 'level': 'zone', 'limited': False})
        zones = self.client.get('/api/options', params={**self.params, 'uf': 'ac', 'municipality': '01074', 'level': 'zone'}).json()
        self.assertEqual(zones['items'], [{'value': '0004', 'label': 'Zona 0004'}])
        with self.assertRaises(ValueError):
            self.save_official({**payload, 'cdabr': '0005'}, area='ac01074-z0004')
        self.assertEqual(self.dashboard(source='official', uf='ac', municipality='01074', zone='0004')['summary']['votes'], 10)

    def test_catalog_office_without_candidates_and_election_geography(self):
        import json
        catalog = {'pl': [{'cd': '3220', 'c': 'ele2026', 'e': [{'cd': '6261', 'nm': 'Conselho Distrital', 't': '1', 'tp': '1', 'abr': [{'cd': 'br', 'cp': [{'cd': '25', 'ds': 'Conselho Distrital'}]}]}]}]}
        area = {'f': 'o', 'abr': [{'cd': 'pe', 'ds': 'Pernambuco', 'mu': [{'cd': '30015', 'nm': 'Fernando de Noronha', 'z': ['0001']}]}]}
        with self.db:
            for url, p in [('http://example/oficial/comum/config/ele-c.json', catalog), ('http://example/oficial/ele2026/6261/config/mun-e006261-cm.json', area)]:
                self.db.execute('insert or ignore into sources(url,name) values(?,?)', (url, 'fixture'))
                save_response(self.db, url, '2026-10-04T20:00:00Z', 'fixture', json.dumps(p))
        m = self.client.get('/api/metadata').json()
        e = next((e for e in m['datasets'][0]['elections'] if e['code'] == '6261'))
        self.assertEqual(e['offices'][0]['scopes'], ['pe30015'])
        p = self.dashboard(election=6261, office=25)
        self.assertIsNone(p['summary']['votes'])
        opts = self.client.get('/api/options', params={**self.params, 'election': 6261, 'office': 25, 'level': 'uf'}).json()
        self.assertEqual(opts['items'], [{'value': 'pe', 'label': 'Pernambuco'}])

    def test_territory_provenance_uses_its_own_official_result(self):
        payload = {'ele': '6257', 't': '1', 'f': 'o', 'tpabr': 'uf', 'cdabr': 'ac', 'and': 'p', 'dv': 's', 'dt': '04/10/2026', 'ht': '17:00:00', 'v': {'tv': '10'}, 's': {'st': '3', 'ts': '4'}, 'carg': [{'cd': '1'}]}
        self.save_official(payload, area='ac', fetched_at='2026-10-04T20:01:00Z')
        child_only = self.dashboard(source='official')
        self.assertFalse(child_only['source']['available'])
        child_source = child_only['territories']['items'][0]['source']
        self.assertEqual(child_source, {'label': 'Resultados oficiais do TSE — EA20', 'updated_at': '2026-10-04T17:00:00-03:00', 'collected_at': '2026-10-04T20:01:00Z', 'url': 'http://example/oficial/ele2026/6257/dados/ac/ac-c0001-e006257-u.json', 'official_progress': 75})
        self.save_official({**payload, 'tpabr': 'br', 'cdabr': 'br', 'ht': '18:00:00', 's': {'st': '1', 'ts': '2'}}, fetched_at='2026-10-04T21:01:00Z')
        parent = self.dashboard(source='official')
        self.assertNotEqual(parent['source']['updated_at'], child_source['updated_at'])
        self.assertEqual(parent['territories']['items'][0]['source'], child_source)

    def test_map_cache_revalidates_changed_consolidated_results(self):
        from unittest.mock import patch
        payload = {'ele': '6257', 't': '1', 'f': 'o', 'tpabr': 'uf', 'cdabr': 'ac',
                   'and': 'p', 'dv': 's', 'v': {'tv': '10'}, 's': {'st': '1', 'ts': '2'}, 'carg': [{'cd': '1'}]}
        self.save_official(payload, area='ac')
        params = {**self.params, 'source': 'official'}
        first = self.client.get('/api/map', params=params)
        self.assertEqual(first.status_code, 200, first.text)
        etag = first.headers['etag']
        headers = {'If-None-Match': etag, 'Cache-Control': 'no-cache'}
        with self.db:
            self.db.execute("update sources set checked_at='2026-10-04T20:05:00Z'")
        with patch('apuracao.api.queries.map_results', side_effect=AssertionError('Resultado sem alteração não deve ser recalculado')):
            self.assertEqual(self.client.get('/api/map', params=params, headers=headers).status_code, 304)
        self.save_official({**payload, 's': {'st': '2', 'ts': '2'}}, area='ac', fetched_at='2026-10-04T20:10:00Z')
        changed = self.client.get('/api/map', params=params, headers=headers)
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed.headers['etag'], etag)
        self.assertEqual(changed.json()['territories']['items'][0]['source']['official_progress'], 100)
