import re
from datetime import datetime

def integer(value):
    return int(value) if isinstance(value, (str, int)) and re.fullmatch('\\d+', str(value)) else None

def source(kind, **values):
    return {'kind': kind, 'label': 'Resultados oficiais do TSE — EA20', 'available': False, 'reason': None, 'updated_at': None, 'collected_at': None, 'checked_at': None, 'url': None, 'error': None, 'official_progress': None, 'totalized_sections': None, 'total_sections': None, **values}

def stamp(day, hour):
    if not day or not hour:
        return None
    try:
        return datetime.strptime(day + ' ' + hour, '%d/%m/%Y %H:%M:%S').isoformat() + '-03:00'
    except ValueError:
        return None

def latest_source(db, url):
    row = db.execute('SELECT * FROM sources WHERE url=? AND fetched_at IS NOT NULL', (url,)).fetchone()
    return dict(row) if row else None

def latest(db, url):
    from .metadata_store import read
    row = latest_source(db, url)
    if row:
        row['metadata'] = read(db, row['id'])
    return row


def catalog(db, dataset):
    row = latest(db, dataset['base_url'].rstrip('/') + '/comum/config/ele-c.json')
    return row['metadata'] if row else {}

def result_urls(db, dataset, election):
    prefix = dataset['base_url'].rstrip('/') + '/' + dataset['cycle'] + '/' + str(election) + '/'
    index = {}
    for row in db.execute('SELECT url FROM sources WHERE substr(url,1,?)=?', (len(prefix), prefix)):
        index.setdefault(row[0].rsplit('/', 1)[-1], []).append(row[0])
    return index


def result(db, dataset, election, office, uf=None, municipality=None, zone=None, url_index=None):
    missing = {'source': source('official', reason='Resultado oficial indisponível para este recorte.'), 'candidates': [], 'categories': [], 'votes': None, 'nominal_votes': None, 'denominator': None, 'parties': None}
    if office != 1 and (not uf):
        missing['source']['reason'] = 'Selecione a circunscrição do cargo.'
        return missing
    territory = (uf or 'br') + (municipality or '')
    zone_suffix = f'-z{zone}' if zone else ''
    filename = f'{territory}{zone_suffix}-c{office:04d}-e{election:06d}-u.json'
    urls = (url_index if url_index is not None else result_urls(db, dataset, election)).get(filename, [])
    if len(urls) != 1:
        return missing
    from .official_store import read_result
    row = latest_source(db, urls[0])
    if not row:
        missing['source']['url'] = urls[0]
        state = db.execute('SELECT checked_at,error FROM sources WHERE url=?', (urls[0],)).fetchone()
        if state:
            missing['source'].update(checked_at=state['checked_at'], error=state['error'])
        return missing
    result = read_result(db, row['id'], dataset['id'], office)
    if result is None:
        return missing
    el = db.execute('SELECT round FROM elections WHERE dataset=? AND code=?', (dataset['id'], election)).fetchone()
    expected_type = 'zona' if zone else 'mu' if municipality else 'uf' if uf else 'br'
    expected_area = zone or municipality or uf or 'br'
    if (not el or result['reported_election'] != str(election) or result['reported_round'] != str(el[0])
            or result['phase'] != {'official': 'o', 'simulated': 's'}.get(dataset['phase'])
            or result['kind'] != expected_type or result['area'] != expected_area):
        missing['source']['reason'] = 'Identidade ou formato do resultado oficial incompatível.'
        return missing
    src = source('official', url=row['url'], updated_at=result['updated_at'], collected_at=row['fetched_at'],
                 checked_at=row['checked_at'], error=row['error'], available=bool(result['available']),
                 reason=None if result['available'] else 'Aguardando totalização ou liberação da votação pelo TSE.')
    st, ts = result['totalized_sections'], result['total_sections']
    if st is not None and ts:
        src.update(totalized_sections=st, total_sections=ts, official_progress=100 * st / ts)
    return {'source': src, **{key: result[key] for key in
            ('candidates', 'categories', 'votes', 'nominal_votes', 'denominator', 'parties')}}


def decode_result(p, office, scope):
    c = next(c for c in p.get('carg', []) if str(c.get('cd')) == str(office))
    src = source('official', updated_at=stamp(p.get('dt'), p.get('ht')))
    valid = p.get('and') in ('p', 'f') and (not (office == 1 and p.get('dv') != 's'))
    totals = p.get('v', {})
    valid = valid and integer(totals.get('tv')) is not None
    src['available'] = valid
    src['reason'] = None if valid else 'Aguardando totalização ou liberação da votação pelo TSE.'
    s = p.get('s', {})
    st = integer(s.get('st'))
    ts = integer(s.get('ts'))
    if st is not None and ts and st <= ts:
        src.update(totalized_sections=st, total_sections=ts, official_progress=100 * st / ts)
    denominator = integer(totals.get('vvc')) if valid else None
    candidates = []
    party_votes = {}
    complete = True
    for group in c.get('agr', []):
        for party in group.get('par', []):
            number = str(party.get('n', ''))
            name = party.get('sg', number)
            nominal = integer(party.get('tvtn'))
            legend = integer(party.get('tvtl')) if office in (6, 7, 8, 13, 25) else 0
            if not number or nominal is None or legend is None:
                complete = False
            else:
                party_votes[number] = {'number': number, 'name': name, 'votes': nominal + legend}
            for cand in party.get('cand', []):
                value = integer(cand.get('vap')) if valid else None
                raw = str(cand['pvapn']).replace(',', '.') if cand.get('pvapn') is not None else None
                percentage = float(raw) if valid and denominator and raw is not None and re.fullmatch('\\d+(\\.\\d+)?', str(raw)) else None
                candidates.append({'number': str(cand['n']), 'scope': scope, 'name': cand.get('nmu', cand.get('nm', '')), 'party': number, 'party_name': name, 'votes': value, 'percentage': percentage, 'status': cand.get('st') or None})
    mapping = {'vnom': 'nominal', 'vl': 'legenda', 'vb': 'branco', 'tvn': 'nulo', 'van': 'anulado', 'vansj': 'anulado_sub_judice', 'vscv': 'cargo_sem_candidato'}
    categories = [{'type': name, 'votes': integer(totals[key])} for key, name in mapping.items() if valid and integer(totals.get(key)) is not None]
    return {'source': src, 'candidates': candidates, 'categories': categories, 'votes': integer(totals.get('tv')) if valid else None, 'nominal_votes': integer(totals.get('vnom')) if valid else None, 'denominator': denominator, 'parties': list(party_votes.values()) if valid and complete else None}


REGIONS = {
    'norte': ('Norte', ('ac', 'am', 'ap', 'pa', 'ro', 'rr', 'to')),
    'nordeste': ('Nordeste', ('al', 'ba', 'ce', 'ma', 'pb', 'pe', 'pi', 'rn', 'se')),
    'centro-oeste': ('Centro-Oeste', ('df', 'go', 'ms', 'mt')),
    'sudeste': ('Sudeste', ('es', 'mg', 'rj', 'sp')),
    'sul': ('Sul', ('pr', 'rs', 'sc')),
}


def regional_progress(db, dataset, election, office, sources):
    if office in (11, 13, 25):
        return []
    scopes = {
        area['cd']
        for poll in catalog(db, dataset).get('pl', [])
        if str(poll.get('cd')) == str(dataset['poll']) and poll.get('c') == dataset['cycle']
        for entry in poll.get('e', []) if str(entry.get('cd')) == str(election)
        for area in entry.get('abr', [])
        if any(str(c.get('cd')) == str(office) for c in area.get('cp', []))
    }
    if not scopes:
        return []
    regions = []
    groups = {**REGIONS, **({'exterior': ('Exterior', ('zz',))} if 'br' in scopes else {})}
    url_index = result_urls(db, dataset, election)
    for key, (name, members) in groups.items():
        expected = [uf for uf in members if ('br' in scopes or uf in scopes)
                    and (office != 7 or uf != 'df') and (office != 8 or uf == 'df')]
        results = {uf: sources[uf] if uf in sources else result(db, dataset, election, office, uf=uf, url_index=url_index) for uf in expected}
        states = {uf: result['source'] for uf, result in results.items()}
        ranking = regional_ranking(results) if office == 1 and expected else {'status': 'not_applicable', 'items': []}
        missing = [uf for uf, src in states.items() if src['official_progress'] is None]
        complete = bool(expected) and not missing
        total = sum(src['total_sections'] for src in states.values()) if complete else None
        totalized = sum(src['totalized_sections'] for src in states.values()) if complete else None
        times = {}
        for field in ('updated_at', 'collected_at'):
            values = [src[field] for src in states.values()]
            times[field] = min(values) if complete and all(values) else None
        regions.append({
            'id': key, 'name': name, 'total': total, 'totalized': totalized,
            'percentage': 100 * totalized / total if complete else None,
            'status': 'not_applicable' if not expected else 'available' if complete else 'pending' if len(missing) == len(expected) else 'incomplete',
            'ranking': ranking,
            'expected_ufs': expected, 'missing_ufs': missing,
            'error_ufs': [uf for uf, src in states.items() if src['error']],
            **times,
        })
    return regions


def regional_ranking(results):
    missing = [uf for uf, result in results.items() if not result['source']['available']
               or not result['denominator'] or not result['candidates']
               or any(candidate['votes'] is None for candidate in result['candidates'])]
    if missing:
        return {'status': 'pending' if len(missing) == len(results) else 'incomplete', 'items': [], 'missing_ufs': missing}
    denominator = sum(result['denominator'] for result in results.values())
    candidates = {}
    for result in results.values():
        for candidate in result['candidates']:
            identity = (candidate['scope'], candidate['number'])
            aggregate = candidates.setdefault(identity, {**candidate, 'votes': 0, 'status': None})
            aggregate['votes'] += candidate['votes']
    ranked = sorted(candidates.values(), key=lambda candidate: (-candidate['votes'], candidate['name'], candidate['number']))
    return {'status': 'available', 'denominator': denominator, 'items': [
        {**candidate, 'percentage': 100 * candidate['votes'] / denominator} for candidate in ranked[:2]]}
