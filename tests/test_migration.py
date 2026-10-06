import sqlite3
import tempfile
import unittest
from pathlib import Path

from apuracao.migrate import migrate
from apuracao.official_store import read_result


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.source = Path(self.folder.name) / 'legacy.sqlite3'
        self.output = Path(self.folder.name) / 'current.sqlite3'
        self.result_url = 'http://example/oficial/ele2026/6257/dados/br/br-c0001-e006257-u.json'
        db = sqlite3.connect(self.source)
        self.addCleanup(db.close)
        self.legacy = db
        db.executescript('''
            CREATE TABLE datasets(id,base_url,cycle,poll,phase);
            CREATE TABLE sources(url,name,etag,last_modified,content_hash,checked_at,status,error);
            CREATE TABLE snapshots(id INTEGER PRIMARY KEY,url,fetched_at,content_hash);
            CREATE TABLE elections(dataset,code,name,round);
            CREATE TABLE candidates(dataset,election,office,scope,number,tse_id,name,party,party_name,office_name);
            CREATE TABLE collection_state(key,value);
            CREATE TABLE result_collection_progress(dataset,url,pass_number);
            CREATE TABLE metadata_versions(snapshot_id,kind,phase);
            CREATE TABLE catalog_polls(snapshot_id,code,cycle);
            CREATE TABLE catalog_elections(snapshot_id,poll,code,name,round,type);
            CREATE TABLE catalog_offices(snapshot_id,poll,election,coverage,office,name);
            CREATE TABLE geographic_states(snapshot_id,uf,name);
            CREATE TABLE geographic_municipalities(snapshot_id,uf,code,name);
            CREATE TABLE geographic_zones(snapshot_id,uf,municipality,zone);
            CREATE TABLE official_results(
                snapshot_id,dataset,election,office,scope,uf,municipality,zone,
                reported_election,reported_round,phase,kind,area,updated_at,available,
                votes,nominal_votes,denominator,totalized_sections,total_sections,parties_complete);
            CREATE TABLE official_candidates(id,number);
            CREATE TABLE official_parties(id,number,name);
            CREATE TABLE official_candidate_votes(snapshot_id,dataset,office,ordinal,candidate_id,votes,percentage,status);
            CREATE TABLE official_party_votes(snapshot_id,dataset,office,party_id,votes);
            CREATE TABLE official_vote_categories(snapshot_id,dataset,office,type,votes);
            INSERT INTO datasets VALUES('test','http://example/oficial','ele2026',3220,'official');
            INSERT INTO elections VALUES('test',6257,'Eleição anterior',1);
            INSERT INTO candidates VALUES('test',6257,1,'br','90','900','José','90','Partido A','Presidente');
            INSERT INTO collection_state VALUES('cooldown_until',1800000000);
            INSERT INTO catalog_polls VALUES(1,'3220','ele2026');
            INSERT INTO catalog_elections VALUES(1,'3220','6257','Eleição 2026','1','1');
            INSERT INTO catalog_offices VALUES(1,'3220','6257','br','1','Presidente');
            INSERT INTO metadata_versions VALUES(1,'catalog',NULL),(2,'geography','o');
            INSERT INTO geographic_states VALUES(2,'ac','Acre');
            INSERT INTO geographic_municipalities VALUES(2,'ac','01074','Município');
            INSERT INTO geographic_zones VALUES(2,'ac','01074','0004');
            INSERT INTO official_candidates VALUES(1,'90');
            INSERT INTO official_parties VALUES(1,'90','Partido A');
        ''')
        urls = ['http://example/oficial/comum/config/ele-c.json',
                'http://example/oficial/ele2026/6257/config/ac-cm.json',
                self.result_url, self.result_url, self.result_url]
        for sid, url in enumerate(urls, 1):
            db.execute('INSERT INTO snapshots VALUES(?,?,?,?)',
                       (sid, url, f'2026-10-05T00:0{sid}:00Z', f'hash-{sid}'))
        for url in dict.fromkeys(urls):
            db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',
                       (url, 'TSE', 'etag-invalid', None, 'hash-5', '2026-10-05T00:05:00Z', 200, None))
        for sid, total, round_, sections in [(3, 10, '1', 1), (4, 20, '1', 2), (5, 999, '2', 2)]:
            db.execute('INSERT INTO official_results VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (sid, 'test', 6257, 1, 'br', 'br', '', '', '6257', round_, 'o', 'br', 'br',
                        f'2026-10-05T00:0{sid}:00Z', 1, total, total, total, sections, 2, 1))
            db.execute('INSERT INTO official_candidate_votes VALUES(?,?,?,?,?,?,?,?)',
                       (sid, 'test', 1, 0, 1, total, 100, 'Eleito'))
            db.execute('INSERT INTO official_party_votes VALUES(?,?,?,?,?)', (sid, 'test', 1, 1, total))
            db.execute('INSERT INTO official_vote_categories VALUES(?,?,?,?,?)',
                       (sid, 'test', 1, 'nominal', total))
        db.execute('INSERT INTO result_collection_progress VALUES(?,?,?)', ('test', self.result_url, 7))
        db.commit()

    def test_preserves_last_valid_result_metadata_and_collection_state(self):
        before = self.source.read_bytes()
        self.assertEqual(migrate(self.source, self.output), 1)
        self.assertEqual(self.source.read_bytes(), before)
        db = sqlite3.connect(self.output)
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        source = db.execute('SELECT * FROM sources WHERE url=?', (self.result_url,)).fetchone()
        self.assertEqual((source['content_hash'], source['fetched_at'], source['etag']),
                         ('hash-4', '2026-10-05T00:04:00Z', None))
        result = read_result(db, source['id'], 'test', 1)
        self.assertEqual((result['votes'], result['completed']), (20, 1))
        self.assertEqual(result['candidates'], [{'number': '90', 'scope': 'br', 'name': 'José',
            'party': '90', 'party_name': 'Partido A', 'votes': 20, 'percentage': 100, 'status': 'Eleito'}])
        self.assertEqual(result['parties'], [{'number': '90', 'name': 'Partido A', 'votes': 20}])
        self.assertEqual(result['categories'], [{'type': 'nominal', 'votes': 20}])
        self.assertEqual(tuple(db.execute('SELECT name,type FROM elections').fetchone()), ('Eleição 2026', '1'))
        self.assertEqual(tuple(db.execute('SELECT coverage,code,name FROM offices').fetchone()), ('br', 1, 'Presidente'))
        self.assertEqual([tuple(row) for row in db.execute('SELECT uf,municipality,zone,name FROM territories')],
                         [('ac', '', '', 'Acre'), ('ac', '01074', '', 'Município'), ('ac', '01074', '0004', '0004')])
        self.assertEqual(dict(db.execute('SELECT key,value FROM collection_state')),
                         {'cooldown_until': 1800000000, 'test/results/completed/' + self.result_url: 7})

    def test_failure_removes_partial_destination_and_preserves_source(self):
        self.legacy.execute('DELETE FROM candidates')
        self.legacy.commit()
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'voto sem candidatura'):
            migrate(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(Path(self.folder.name).glob('current.sqlite3*')), [])

    def test_existing_destination_is_preserved(self):
        self.output.write_bytes(b'arquivo existente')
        with self.assertRaisesRegex(ValueError, 'destino já existe'):
            migrate(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'arquivo existente')
