import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from apuracao.database import connect
from apuracao.collector.http import fetch
from apuracao.collector.config import load_config
from apuracao.collector.service import run


class CollectorTest(unittest.TestCase):
    def setUp(self):
        geography = patch('apuracao.collector.service.ensure_prepared')
        geography.start()
        self.addCleanup(geography.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "results.sqlite3"
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        self.responses = []
        self.headers = []
        self.paths = []
        self.routes = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.headers.append(self.headers)
                owner.paths.append(self.path)
                status, payload, etag = owner.routes.get(self.path, (404, "", None)) if owner.routes else owner.responses.pop(0)
                self.send_response(status)
                if etag:
                    self.send_header("ETag", etag)
                self.end_headers()
                self.wfile.write(payload.encode("utf-8"))

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.endpoint = {"name": "teste", "url": f"http://127.0.0.1:{self.server.server_port}/resultado.json"}

    def test_current_response_survives_restart_and_updates_on_return_to_previous_value(self):
        a = '{"candidato":"João", "votos":10}'
        b = '{"candidato":"João", "votos":20}'
        self.responses = [(200, a, '"a"'), (304, "", None), (200, b, '"b"'), (200, a, '"a2"')]
        self.assertEqual(fetch(self.db, self.endpoint, 2), 200)
        original = dict(self.db.execute("SELECT * FROM sources").fetchone())
        self.db.close()
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        self.assertEqual(fetch(self.db, self.endpoint, 2), 304)
        self.assertEqual(self.headers[1]["If-None-Match"], '"a"')
        self.assertEqual(fetch(self.db, self.endpoint, 2), 200)
        self.assertNotEqual(self.db.execute("SELECT content_hash FROM sources").fetchone()[0], original['content_hash'])
        self.assertEqual(fetch(self.db, self.endpoint, 2), 200)
        current = self.db.execute("SELECT * FROM sources").fetchall()
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]['id'], original['id'])
        self.assertEqual(current[0]['content_hash'], original['content_hash'])

    def test_catalog_consolidates_2026_offices_and_survives_304_after_restart(self):
        from apuracao.metadata_store import read

        base = self.endpoint['url'].removesuffix('/resultado.json') + '/oficial'
        endpoint = {'name': 'EA11', 'url': base + '/comum/config/ele-c.json'}
        with self.db:
            self.db.execute("INSERT INTO datasets VALUES('test',?,'ele2026',3220,'official')", (base,))
        polls = [{'cd': code, 'c': cycle, 'e': [
            {'cd': election, 'nm': name, 't': '1', 'tp': '2',
             'abr': [{'cd': 'br', 'cp': [{'cd': '1', 'ds': 'Presidente'}]}]}]}
            for code, cycle, election, name in [
                ('452', 'ele2024', '619', 'Eleição anterior'),
                ('3220', 'ele2026', '6257', 'Eleição de 2026')]]
        revised = json.loads(json.dumps(polls))
        revised[1]['e'][0]['abr'][0]['cp'][0]['ds'] = 'Presidência'
        self.responses = [(200, json.dumps({'pl': polls}), '"first"'),
                          (200, json.dumps({'pl': revised}), '"revised"'), (304, '', None)]
        self.assertEqual(fetch(self.db, endpoint, 2), 200)
        self.assertEqual(fetch(self.db, endpoint, 2), 200)
        source_id = self.db.execute('SELECT id FROM sources').fetchone()[0]
        self.db.close()
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        self.assertEqual(fetch(self.db, endpoint, 2), 304)
        self.assertEqual(read(self.db, source_id)['pl'], [revised[1]])
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT code,name FROM offices')],
                         [(1, 'Presidência')])

    def test_invalid_json_and_http_failure_preserve_last_valid_data(self):
        self.responses = [(200, '{"votos":10}', '"good"'), (200, '<html>indisponível</html>', '"bad"'), (503, '', None)]
        self.assertEqual(fetch(self.db, self.endpoint, 2), 200)
        for expected in (0, 503):
            with self.assertLogs("apuracao", level="ERROR"):
                self.assertEqual(fetch(self.db, self.endpoint, 2), expected)
            row = self.db.execute("SELECT * FROM sources").fetchone()
            self.assertEqual(row["etag"], '"good"')
            self.assertTrue(row["error"])
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)

    def test_rate_limit_stops_cycle_without_requesting_next_endpoint(self):
        self.responses = [(429, "", None)]
        config = {"database": self.path, "endpoints": [self.endpoint, {"name": "outro", "url": self.endpoint["url"] + "?outro"}], "timeout_seconds": 2, "interval_seconds": 30}
        with patch("apuracao.collector.service.time.sleep") as sleep, self.assertLogs("apuracao"):
            self.assertEqual(run(config, once=True), 1)
        self.assertEqual(len(self.headers), 1)
        sleep.assert_not_called()

    def test_results_require_election_context_and_replace_current_totals(self):
        from apuracao.official_store import save_response
        from apuracao.official import result
        base = 'http://example/oficial'
        url = base + '/ele2026/6257/dados/br/br-c0001-e006257-u.json'
        payload = {'ele': '6257', 't': '1', 'f': 'o', 'tpabr': 'br', 'cdabr': 'br',
                   'and': 'p', 'dv': 's', 'carg': [{'cd': '1'}]}
        with self.assertRaises(ValueError), self.db:
            save_response(self.db, url, '2026-10-04T20:00:00Z', 'unknown', json.dumps(payload))
        with self.db:
            self.db.execute("INSERT INTO datasets VALUES('test',?,'ele2026',3220,'official')", (base,))
            self.db.execute("INSERT INTO elections(dataset,code,name,round) VALUES('test',6257,'Eleição',1)")
            for minute, votes in ((0, 10), (10, 20), (20, 10)):
                save_response(self.db, url, f'2026-10-04T20:{minute:02d}:00Z', str(votes),
                              json.dumps({**payload, 'v': {'tv': str(votes)}}))
        dataset = dict(self.db.execute('SELECT * FROM datasets').fetchone())
        self.assertEqual(result(self.db, dataset, 6257, 1)['votes'], 10)
        self.assertEqual(self.db.execute('SELECT count(*) FROM results').fetchone()[0], 1)
        with self.assertRaises(ValueError), self.db:
            save_response(self.db, url, '2026-10-04T20:30:00Z', 'wrong-phase',
                          json.dumps({**payload, 'f': 's', 'v': {'tv': '999'}}))
        current = self.db.execute('SELECT available,votes FROM results').fetchone()
        self.assertEqual(tuple(current), (1, 10))
        self.assertTrue(result(self.db, dataset, 6257, 1)['source']['available'])

    def test_results_discovery_preserves_office_scopes_and_existing_results(self):
        base = self.endpoint["url"].removesuffix("/resultado.json") + "/oficial"
        templates = {"cm": "<base>/<ambiente>/<ciclo>/<cd_eleicao>/config",
                     "u": "<base>/<ambiente>/<ciclo>/<cd_eleicao>/dados/<uf>"}
        catalog = {"arq": [{"tp": k, "dir": v} for k, v in templates.items()], "pl": [
            {"cd": "3220", "c": "ele2026", "e": [
                {"cd": "6257", "nm": "Federal", "t": "1", "abr": [{"cd": "br", "cp": [{"cd": "1"}]}]},
                {"cd": "6259", "nm": "Estadual", "t": "1", "abr": [{"cd": "br", "cp": [{"cd": str(c)} for c in (3, 7, 8)]}]},
                {"cd": "6261", "nm": "Conselho", "t": "1", "tp": "3", "abr": [{"cd": "br", "cp": [{"cd": "25"}]}]},
            ]}]}

        def route(path, payload):
            self.routes["/oficial/" + path] = (200, json.dumps(payload, ensure_ascii=False), None)

        route("comum/config/ele-c.json", catalog)
        for election, territories in ((6257, [("ac", "01074"), ("df", "97012"), ("zz", "00001")]),
                                      (6259, [("ac", "01074"), ("df", "97012")]),
                                      (6261, [("pe", "30015")])):
            route(f"ele2026/{election}/config/mun-e{election:06d}-cm.json", {"f": "o", "abr": [
                {"cd": uf, "mu": [{"cd": city, "nm": "Município", "z": ["0004"]}]} for uf, city in territories]})
        targets = [(6257, 1, "br", "br", "br")]
        for election, office, uf, city in [(6257, 1, "ac", "01074"), (6257, 1, "df", "97012"),
                                          (6257, 1, "zz", "00001"), (6259, 3, "ac", "01074"),
                                          (6259, 3, "df", "97012"), (6259, 7, "ac", "01074"),
                                          (6259, 8, "df", "97012"), (6261, 25, "pe", "30015")]:
            if office != 25:
                targets.append((election, office, uf, "uf", uf))
            targets.extend([(election, office, uf + city, "mu", city),
                            (election, office, uf + city + "-z0004", "zona", "0004")])
        priority = set()
        local = set()
        for election, office, territory, kind, code in targets:
            path = f"ele2026/{election}/dados/{territory[:2]}/{territory}-c{office:04d}-e{election:06d}-u.json"
            route(path, {"f": "o", "ele": str(election), "t": "1", "tpabr": kind, "cdabr": code,
                         "and": "p", "dv": "s", "v": {"tv": "10"}, "carg": [{"cd": str(office), "nmn": "Cargo",
                         "agr": [{"par": [{"n": "90", "sg": "TESTE", "cand": [{"n": "90", "nmu": "Candidata de teste"}]}]}]}]})
            (priority if kind in ("br", "uf") else local).add("/oficial/" + path)
        config = {"database": self.path, "timeout_seconds": 2, "interval_seconds": 30,
                  "results": {"enabled": True, "base_url": base,
                  "cycle": "ele2026", "poll": 3220, "phase": "official", "requests_per_second": 80,
                  "max_local_results_per_cycle": 2}}
        fixed_path = Path(self.folder.name) / 'fixed.sqlite3'
        fixed = {**config, 'database': fixed_path, 'results': {**config['results'], 'enabled': False},
                 'endpoints': [{'name': 'EA11', 'url': base + '/comum/config/ele-c.json'},
                               {'name': 'EA20', 'url': base + '/ele2026/6257/dados/br/br-c0001-e006257-u.json'}]}
        self.assertEqual(run(fixed, once=True), 0)
        national = '/oficial/ele2026/6257/dados/br/br-c0001-e006257-u.json'
        response = self.routes[national]
        self.routes[national] = (304, '', None)
        self.assertEqual(run({**config, 'database': fixed_path}, once=True), 0)
        check = connect(fixed_path)
        try:
            self.assertEqual(check.execute("SELECT name,party_name FROM candidates WHERE office=1 AND scope='br'").fetchone()[:],
                             ('Candidata de teste', 'TESTE'))
        finally:
            check.close()
        self.routes[national] = response
        self.paths.clear()
        self.assertEqual(run(config, once=True), 0)
        self.assertEqual(len(local.intersection(self.paths)), 2)
        self.assertTrue(priority.issubset(self.paths))
        self.assertLess(max(self.paths.index(p) for p in priority), min(self.paths.index(p) for p in local.intersection(self.paths)))
        before = set(self.paths)
        self.assertEqual(run(config, once=True), 0)
        self.assertGreater(len(local.intersection(set(self.paths) - before)), 0)
        for _ in range(40):
            if local.issubset(self.paths):
                break
            self.assertEqual(run(config, once=True), 0)
        self.assertTrue(local.issubset(self.paths))
    def result_scenario(self, limit=2, levels=None):
        base = self.endpoint['url'].removesuffix('/resultado.json') + '/oficial'
        elections = [(6257, [1]), (6259, [3, 6])]
        catalog = {'arq': [
            {'tp': 'cm', 'dir': '<base>/<ambiente>/<ciclo>/<cd_eleicao>/config'},
            {'tp': 'u', 'dir': '<base>/<ambiente>/<ciclo>/<cd_eleicao>/dados/<uf>'}],
            'pl': [{'cd': '3220', 'c': 'ele2026', 'e': [
                {'cd': str(e), 'nm': 'Eleição', 't': '1',
                 'abr': [{'cd': 'br', 'cp': [{'cd': str(c)} for c in offices]}]}
                for e, offices in elections]}]}
        self.routes['/oficial/comum/config/ele-c.json'] = (200, json.dumps(catalog), None)
        cities = [('ac', '10001'), ('ac', '10002'), ('pe', '20001')]
        totals = {(1, '10001'): 10, (1, '10002'): 50, (1, '20001'): 100,
                  (3, '10001'): 90, (3, '10002'): None, (3, '20001'): 5,
                  (6, '10001'): 1, (6, '10002'): 70, (6, '20001'): 0}
        paths = {}

        def result(election, office, uf, city='', zone=''):
            kind = 'zona' if zone else 'mu' if city else 'br' if uf == 'br' else 'uf'
            territory = uf + city + ('-z' + zone if zone else '')
            path = f'/oficial/ele2026/{election}/dados/{uf}/{territory}-c{office:04d}-e{election:06d}-u.json'
            payload = {'ele': str(election), 't': '1', 'f': 'o', 'tpabr': kind,
                       'cdabr': zone or city or uf, 'and': 'p', 'dv': 's',
                       'v': {'tv': totals.get((office, city))},
                       'carg': [{'cd': str(office), 'nmn': 'Cargo'}]}
            self.routes[path] = (200, json.dumps(payload), '"version"')
            paths[kind, office, uf, city] = path

        for election, offices in elections:
            geography = {'f': 'o', 'abr': [
                {'cd': uf, 'mu': [{'cd': city, 'nm': city, 'z': ['0001']}
                                 for state, city in cities if state == uf]}
                for uf in ('ac', 'pe')]}
            self.routes[f'/oficial/ele2026/{election}/config/mun-e{election:06d}-cm.json'] = (200, json.dumps(geography), None)
            for office in offices:
                if office == 1:
                    result(election, office, 'br')
                for uf in ('ac', 'pe'):
                    result(election, office, uf)
                for uf, city in cities:
                    result(election, office, uf, city)
                    result(election, office, uf, city, '0001')
        config = {'database': self.path, 'timeout_seconds': 2, 'interval_seconds': 30,
                  'results': {'enabled': True, 'base_url': base, 'cycle': 'ele2026',
                              'poll': 3220, 'phase': 'official', 'requests_per_second': 80,
                              'max_local_results_per_cycle': limit, 'levels': levels or {}}}
        return config, paths

    def test_result_pass_orders_levels_and_resumes_before_refreshing(self):
        config, paths = self.result_scenario()
        expected = [paths['br', 1, 'br', '']]
        expected += [paths['uf', office, uf, ''] for uf in ('ac', 'pe') for office in (1, 3, 6)]
        expected += [paths['mu', office, uf, city]
                     for uf, city in [('pe', '20001'), ('ac', '10001'), ('ac', '10002')]
                     for office in (1, 3, 6)]
        expected += [paths['zona', office, uf, city] for office, uf, city in [
            (1, 'pe', '20001'), (3, 'ac', '10001'), (6, 'ac', '10002'),
            (1, 'ac', '10002'), (1, 'ac', '10001'), (3, 'pe', '20001'),
            (6, 'ac', '10001'), (6, 'pe', '20001'), (3, 'ac', '10002')]]
        for _ in range(9):
            self.assertEqual(run(config, once=True), 0)
        requests = [p for p in self.paths if p.endswith('-u.json')]
        self.assertEqual(requests, expected)
        self.paths.clear()
        self.assertEqual(run(config, once=True), 0)
        self.assertEqual([p for p in self.paths if p.endswith('-u.json')], expected[:9])

    def test_result_level_toggles_control_fixed_endpoints_and_zone_only(self):
        config, paths = self.result_scenario(limit=100, levels={
            'brasil': False, 'ufs': False, 'municipios': False, 'zonas': True})
        national = paths['br', 1, 'br', '']
        config['endpoints'] = [{'name': 'Nacional fixo', 'url':
                               self.endpoint['url'].removesuffix('/resultado.json') + national}]
        self.assertEqual(run(config, once=True), 0)
        self.assertEqual(set(p for p in self.paths if p.endswith('-u.json')),
                         {p for key, p in paths.items() if key[0] == 'zona'})
        self.paths.clear()
        config['results']['levels']['zonas'] = False
        self.assertEqual(run(config, once=True), 0)
        self.assertFalse(any(p.endswith('-u.json') for p in self.paths))
        config['results']['levels'] = {'brasil': True, 'ufs': True, 'municipios': True, 'zonas': False}
        self.paths.clear()
        self.assertEqual(run(config, once=True), 0)
        self.assertEqual(set(p for p in self.paths if p.endswith('-u.json')),
                         {p for key, p in paths.items() if key[0] != 'zona'})

    def test_failed_result_remains_pending_without_repeating_completed_targets(self):
        config, paths = self.result_scenario(limit=100)
        failed = paths['mu', 1, 'pe', '20001']
        response = self.routes[failed]
        self.routes[failed] = (503, '', None)
        with self.assertLogs('apuracao'):
            self.assertEqual(run(config, once=True), 1)
        self.assertFalse(any('-z0001' in p for p in self.paths))
        self.paths.clear()
        self.routes[failed] = response
        self.assertEqual(run(config, once=True), 0)
        requests = [p for p in self.paths if p.endswith('-u.json')]
        self.assertEqual(requests[0], failed)
        self.assertEqual(set(requests[1:]), {p for key, p in paths.items() if key[0] == 'zona'})

    def test_result_cooldown_resumes_at_blocked_target_and_accepts_304(self):
        config, paths = self.result_scenario(limit=100)
        blocked = paths['mu', 3, 'pe', '20001']
        response = self.routes[blocked]
        self.routes[blocked] = (429, '', None)
        with self.assertLogs('apuracao'):
            self.assertEqual(run(config, once=True), 1)
        before = [p for p in self.paths if p.endswith('-u.json')]
        self.paths.clear()
        with self.assertLogs('apuracao'):
            self.assertEqual(run(config, once=True), 1)
        self.assertEqual(self.paths, [])
        with self.db:
            self.db.execute("UPDATE collection_state SET value=0 WHERE key LIKE '%/cooldown'")
        self.routes[blocked] = response
        self.assertEqual(run(config, once=True), 0)
        after = [p for p in self.paths if p.endswith('-u.json')]
        self.assertEqual(after[0], blocked)
        self.assertEqual(set(before[:-1]) & set(after), set())
        self.assertEqual(set(before + after), set(paths.values()))
        versions = self.db.execute('SELECT count(*) FROM results').fetchone()[0]
        for path in paths.values():
            self.routes[path] = (304, '', None)
        self.paths.clear()
        self.assertEqual(run(config, once=True), 0)
        self.assertEqual(set(p for p in self.paths if p.endswith('-u.json')), set(paths.values()))
        self.assertEqual(self.db.execute('SELECT count(*) FROM results').fetchone()[0], versions)

    def test_304_does_not_complete_a_result_with_invalid_cached_identity(self):
        config, paths = self.result_scenario(limit=100)
        national = paths['br', 1, 'br', '']
        status, body, etag = self.routes[national]
        invalid = {**json.loads(body), 'f': 's'}
        self.routes[national] = (status, json.dumps(invalid), etag)
        with self.assertLogs('apuracao'):
            self.assertEqual(run(config, once=True), 1)
        self.paths.clear()
        self.routes[national] = (304, '', None)
        with self.assertLogs('apuracao'):
            self.assertEqual(run(config, once=True), 1)
        self.assertEqual([p for p in self.paths if p.endswith('-u.json')], [national])
        self.routes[national] = (status, body, '"corrected"')
        self.assertEqual(run(config, once=True), 0)

    def test_completed_targets_stay_skipped_after_restart_without_completing_children(self):
        config, paths = self.result_scenario(limit=100)
        finished = {paths['br', 1, 'br', ''], paths['uf', 1, 'ac', ''],
                    paths['mu', 1, 'ac', '10001']}
        for path in finished:
            status, body, etag = self.routes[path]
            self.routes[path] = (status, json.dumps({**json.loads(body), 's': {'st': '10', 'ts': '10'}, 'v': {'tv': '100'}}), etag)
        self.assertEqual(run(config, once=True), 0)
        self.assertEqual(set(p for p in self.paths if p.endswith('-u.json')), set(paths.values()))
        self.paths.clear()
        self.assertEqual(run(config, once=True), 0)
        pending = set(paths.values()) - finished
        self.assertEqual(set(p for p in self.paths if p.endswith('-u.json')), pending)
        self.assertIn(paths['mu', 1, 'ac', '10002'], pending)
        self.assertIn(paths['zona', 1, 'ac', '10001'], pending)
        self.paths.clear()
        self.assertEqual(run(config, once=True), 0)
        self.assertEqual(set(p for p in self.paths if p.endswith('-u.json')), pending)

        self.paths.clear()
        catalog_path = '/oficial/comum/config/ele-c.json'
        fixed_paths = [catalog_path, *paths.values()]
        base = self.endpoint['url'].removesuffix('/resultado.json')
        fixed = {**config, 'results': {**config['results'], 'enabled': False},
                 'endpoints': [{'name': path, 'url': base + path} for path in fixed_paths]}
        self.assertEqual(run(fixed, once=True), 0)
        self.assertEqual(set(self.paths), {catalog_path, *pending})

    def test_invalid_level_configuration_is_rejected(self):
        path = Path(self.folder.name) / 'config.toml'
        for levels in ('brasil = "false"', 'municipos = false'):
            with self.subTest(levels=levels):
                path.write_text('[results]\nenabled = true\nphase = "official"\n[results.levels]\n' + levels,
                                encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_config(path)
