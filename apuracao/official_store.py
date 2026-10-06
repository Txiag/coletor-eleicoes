import json
import re
from dataclasses import dataclass


def save_response(db, url, fetched_at, content_hash, payload):
    from .metadata_store import save

    parsed = json.loads(payload)
    # O savepoint permite desfazer esta resposta sem desfazer a transação HTTP do chamador.
    db.execute('SAVEPOINT save_response')
    try:
        source_id = _save_source(db, url, fetched_at, content_hash)
        save(db, source_id, url, parsed)
        normalize(db, source_id, url, parsed)
    except Exception:
        db.execute('ROLLBACK TO save_response')
        db.execute('RELEASE save_response')
        raise
    db.execute('RELEASE save_response')
    return source_id


def _save_source(db, url, fetched_at, content_hash):
    db.execute("""
        INSERT INTO sources (url, fetched_at, content_hash, kind)
        VALUES (?, ?, ?, 'other')
        ON CONFLICT(url) DO UPDATE SET
            fetched_at=excluded.fetched_at, content_hash=excluded.content_hash
    """, (url, fetched_at, content_hash))
    return db.execute('SELECT id FROM sources WHERE url=?', (url,)).fetchone()[0]


@dataclass(frozen=True)
class ResultIdentity:
    uf: str
    municipality: str
    zone: str
    office: int
    election: int

    @property
    def scope(self):
        if self.office == 1:
            return 'br'
        if self.office in (11, 13, 25):
            return self.uf + self.municipality
        return self.uf

    @property
    def kind(self):
        if self.zone:
            return 'zona'
        if self.municipality:
            return 'mu'
        return 'br' if self.uf == 'br' else 'uf'

    @property
    def area(self):
        return self.zone or self.municipality or self.uf


def _identity_from_url(url):
    # A URL descreve o recorte solicitado, independentemente da identidade declarada no JSON.
    match = re.search(
        r'/([a-z]{2})(\d{5})?(?:-z(\d{4}))?-c(\d{4})-e(\d{6})-u\.json$', url
    )
    if match is None:
        return None
    uf, municipality, zone, office, election = match.groups()
    return ResultIdentity(uf, municipality or '', zone or '', int(office), int(election))


def _datasets_for_result(db, url, election):
    rows = db.execute('''
        SELECT d.*, e.round expected_round
        FROM datasets d JOIN elections e ON e.dataset=d.id
        WHERE e.code=?
    ''', (election,)).fetchall()
    datasets = [
        row for row in rows
        if url.startswith(f"{row['base_url'].rstrip('/')}/{row['cycle']}/{election}/")
    ]
    if not datasets:
        raise ValueError(
            'Cadastre o dataset e a eleição antes de coletar resultados oficiais; '
            'o payload não será retido.'
        )
    return datasets


def _payload_matches_identity(payload, identity, dataset):
    return (
        str(payload.get('ele')) == str(identity.election)
        and str(payload.get('t')) == str(dataset['expected_round'])
        and payload.get('f') == {'official': 'o', 'simulated': 's'}.get(dataset['phase'])
        and payload.get('tpabr') == identity.kind
        and str(payload.get('cdabr', '')).lower() == identity.area
    )


def _update_candidates(db, dataset, identity, office_payload, candidate_pairs):
    rows = [
        {
            'dataset': dataset,
            'election': identity.election,
            'office': identity.office,
            'scope': identity.scope,
            'number': candidate['number'],
            'tse_id': raw.get('sqcand'),
            'name': candidate['name'],
            'party': candidate['party'],
            'party_name': candidate['party_name'],
            'office_name': office_payload.get('nmn', str(identity.office)),
        }
        for candidate, raw in candidate_pairs
    ]
    db.executemany('''
        INSERT INTO candidates (
            dataset, election, office, scope, number, tse_id,
            name, party, party_name, office_name
        ) VALUES (
            :dataset, :election, :office, :scope, :number, :tse_id,
            :name, :party, :party_name, :office_name
        )
        ON CONFLICT(dataset,election,office,scope,number) DO UPDATE SET
            tse_id=excluded.tse_id, name=excluded.name, party=excluded.party,
            party_name=excluded.party_name, office_name=excluded.office_name
    ''', rows)


def _result_values(url, dataset, identity, payload, result):
    source = result['source']
    sections = source['total_sections']
    # Contagens exatas evitam encerrar a coleta por um percentual arredondado para 100%.
    completed = bool(
        source['available'] and sections and sections > 0
        and source['totalized_sections'] == sections
    )
    return {
        'source_url': url,
        'dataset': dataset,
        'election': identity.election,
        'office': identity.office,
        'scope': identity.scope,
        'uf': identity.uf,
        'municipality': identity.municipality,
        'zone': identity.zone,
        'reported_election': str(payload.get('ele')),
        'reported_round': str(payload.get('t')),
        'phase': payload.get('f'),
        'kind': payload.get('tpabr'),
        'area': str(payload.get('cdabr', '')).lower(),
        'updated_at': source['updated_at'],
        'available': source['available'],
        'votes': result['votes'],
        'nominal_votes': result['nominal_votes'],
        'denominator': result['denominator'],
        'totalized_sections': source['totalized_sections'],
        'total_sections': sections,
        'parties_complete': result['parties'] is not None,
        'completed': completed,
    }


def _save_result(db, url, dataset, identity, payload, result):
    values = _result_values(url, dataset, identity, payload, result)
    columns = ', '.join(values)
    parameters = ', '.join(':' + field for field in values)
    updates = ', '.join(f'{field}=excluded.{field}' for field in values)
    return db.execute(f"""
        INSERT INTO results ({columns}) VALUES ({parameters})
        ON CONFLICT(dataset,election,office,uf,municipality,zone)
        DO UPDATE SET {updates} RETURNING id
    """, values).fetchone()[0]


def _replace_votes(db, result_id, result):
    # A resposta é um consolidado completo.
    for table in ('candidate_votes', 'party_votes', 'vote_categories'):
        db.execute(f'DELETE FROM {table} WHERE result_id=?', (result_id,))
    db.executemany("""
        INSERT INTO candidate_votes
            (result_id,candidate_number,ordinal,votes,percentage,status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [
        (result_id, candidate['number'], ordinal, candidate['votes'],
         candidate['percentage'], candidate['status'])
        for ordinal, candidate in enumerate(result['candidates'])
    ])
    db.executemany("""
        INSERT INTO party_votes (result_id,number,name,votes) VALUES (?, ?, ?, ?)
    """, [
        (result_id, party['number'], party['name'], party['votes'])
        for party in result['parties'] or []
    ])
    db.executemany("""
        INSERT INTO vote_categories (result_id,type,votes) VALUES (?, ?, ?)
    """, [(result_id, category['type'], category['votes']) for category in result['categories']])


def _office_payload(payload, office_code):
    if not isinstance(payload, dict):
        raise ValueError('Resultado oficial deve ser um objeto.')
    matches = [
        office for office in payload.get('carg', [])
        if str(office.get('cd')) == str(office_code)
    ]
    if len(matches) != 1:
        raise ValueError('Cargo do resultado oficial não corresponde ao recorte solicitado.')
    return matches[0]


def _raw_candidates(office_payload):
    for group in office_payload.get('agr', []):
        for party in group.get('par', []):
            yield from party.get('cand', [])


def normalize(db, source_id, url, payload):
    from .official import decode_result

    identity = _identity_from_url(url)
    if identity is None:
        return
    office_payload = _office_payload(payload, identity.office)
    datasets = _datasets_for_result(db, url, identity.election)
    if any(not _payload_matches_identity(payload, identity, dataset) for dataset in datasets):
        raise ValueError('Identidade do resultado oficial não corresponde ao recorte solicitado.')
    raw_candidates = list(_raw_candidates(office_payload))
    db.execute("UPDATE sources SET kind='result' WHERE id=?", (source_id,))
    for dataset in datasets:
        result = decode_result(payload, identity.office, identity.scope)
        # decode_result preserva a ordem grupo → partido → candidato do EA20.
        candidate_pairs = list(zip(result['candidates'], raw_candidates))
        _update_candidates(db, dataset['id'], identity, office_payload, candidate_pairs)
        result_id = _save_result(db, url, dataset['id'], identity, payload, result)
        _replace_votes(db, result_id, result)


def read_result(db, source_id, dataset, office):
    row = db.execute("""
        SELECT r.* FROM results r JOIN sources s ON s.url=r.source_url
        WHERE s.id=? AND r.dataset=? AND r.office=?
    """, (source_id, dataset, office)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result['candidates'] = [dict(candidate) for candidate in db.execute("""
        SELECT c.number,c.scope,c.name,c.party,c.party_name,v.votes,v.percentage,v.status
        FROM candidate_votes v JOIN results r ON r.id=v.result_id
        JOIN candidates c ON c.dataset=r.dataset AND c.election=r.election
            AND c.office=r.office AND c.scope=r.scope AND c.number=v.candidate_number
        WHERE v.result_id=? ORDER BY v.ordinal
    """, (row['id'],))]
    result['categories'] = [dict(category) for category in db.execute("""
        SELECT type,votes FROM vote_categories WHERE result_id=? ORDER BY rowid
    """, (row['id'],))]
    # None significa total partidário desconhecido; uma lista vazia significa total conhecido sem partidos.
    result['parties'] = None
    if row['parties_complete']:
        result['parties'] = [dict(party) for party in db.execute("""
            SELECT number,name,votes FROM party_votes WHERE result_id=? ORDER BY rowid
        """, (row['id'],))]
    return result
