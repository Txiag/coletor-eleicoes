from datetime import datetime, timezone
from .. import official
MUNICIPAL = (11, 13, 25)

def dataset_row(db, dataset):
    row = db.execute('SELECT * FROM datasets WHERE id=?', (dataset,)).fetchone()
    if row is None:
        raise ValueError('Dataset não encontrado.')
    return dict(row)

def areas(db, dataset, election):
    prefix = dataset['base_url'].rstrip('/') + '/' + dataset['cycle'] + '/' + str(election) + '/'
    suffix = f'/mun-e{election:06d}-cm.json'
    for r in db.execute('SELECT url FROM sources WHERE substr(url,1,?)=?', (len(prefix), prefix)):
        if r[0].endswith(suffix):
            row = official.latest(db, r[0])
            if row:
                p = row['metadata']
                if p.get('f') in (None, {'official': 'o', 'simulated': 's'}.get(dataset['phase'])):
                    return p.get('abr', [])
    return []

def metadata(db):
    datasets = []
    for d in db.execute('SELECT * FROM datasets ORDER BY id'):
        d = dict(d)
        cat = official.catalog(db, d)
        poll = next((p for p in cat.get('pl', []) if str(p.get('cd')) == str(d['poll']) and p.get('c') == d['cycle']), {})
        elections = []
        for e in db.execute('SELECT * FROM elections WHERE dataset=? ORDER BY round,code', (d['id'],)):
            offices = {}
            for r in db.execute('SELECT DISTINCT office,office_name,scope FROM candidates WHERE dataset=? AND election=?', (d['id'], e['code'])):
                item = offices.setdefault(r['office'], {'code': str(r['office']), 'name': r['office_name'], 'scopes': []})
                if r['scope'] not in item['scopes']:
                    item['scopes'].append(r['scope'])
            entry = next((x for x in poll.get('e', []) if str(x['cd']) == str(e['code'])), {})
            abr = areas(db, d, e['code'])
            for a in entry.get('abr', []):
                for c in a.get('cp', []):
                    code = int(c['cd'])
                    item = offices.setdefault(code, {'code': str(code), 'name': c.get('ds', str(code)), 'scopes': []})
                    if code == 1:
                        scopes = ['br']
                    elif code in MUNICIPAL:
                        scopes = [x['cd'] + m['cd'].zfill(5) for x in abr for m in x.get('mu', []) if x['cd'] != 'br']
                    else:
                        scopes = [x['cd'] for x in abr if x['cd'] not in ('br', 'zz') and (a['cd'] == 'br' or x['cd'] == a['cd']) and (code != 7 or x['cd'] != 'df') and (code != 8 or x['cd'] == 'df')]
                    item['scopes'] = sorted(set(item['scopes']) | set(scopes))
            elections.append({'code': str(e['code']), 'name': e['name'], 'round': e['round'], 'offices': sorted(offices.values(), key=lambda x: int(x['code']))})
        datasets.append({'id': d['id'], 'name': f"{d['cycle']} · {d['phase']} · {d['poll']}", 'phase': d['phase'], 'elections': elections})
    parties = [{'number': r[0], 'name': r[1]} for r in db.execute("SELECT party,MAX(party_name) FROM candidates WHERE party!='' GROUP BY party ORDER BY party")]
    return {'datasets': datasets, 'parties': parties, 'refresh_seconds': 30, 'stale_seconds': 300}

def has_office(db, dataset, election, office):
    registered = db.execute('SELECT 1 FROM candidates WHERE dataset=? AND election=? AND office=? LIMIT 1', (dataset['id'], election, office)).fetchone()
    if registered:
        return True
    catalog = official.catalog(db, dataset)
    return any(
        str(cargo.get('cd')) == str(office)
        for poll in catalog.get('pl', [])
        if str(poll.get('cd')) == str(dataset['poll']) and poll.get('c') == dataset['cycle']
        for entry in poll.get('e', []) if str(entry.get('cd')) == str(election)
        for area in entry.get('abr', []) for cargo in area.get('cp', [])
    )


def scope(f):
    if f['office'] == 1:
        return 'br'
    if f['office'] in MUNICIPAL:
        return f['uf'] + f['municipality'] if f.get('uf') and f.get('municipality') else None
    return f.get('uf')

def leadership(parties, available):
    empty = {'leader': None, 'runner_up': None, 'margin': None}
    if not available:
        return {**empty, 'state': 'pending'}
    if parties is None:
        return {**empty, 'state': 'unavailable'}
    parties = sorted(parties, key=lambda p: (-p['votes'], p['number']))
    total = sum((p['votes'] for p in parties))
    if not total:
        return {**empty, 'state': 'zero'}
    first = parties[0]
    second = parties[1] if len(parties) > 1 else None
    if second and first['votes'] == second['votes']:
        return {**empty, 'state': 'tie', 'margin': 0}
    return {'leader': first, 'runner_up': second, 'margin': 100 * (first['votes'] - (second['votes'] if second else 0)) / total, 'state': 'available'}


def candidate_winner(candidates):
    ranked = sorted((c for c in candidates if c['votes'] is not None), key=lambda c: -c['votes'])
    if ranked and ranked[0]['votes'] > 0 and (len(ranked) == 1 or ranked[0]['votes'] > ranked[1]['votes']):
        return ranked[0]
    return None

def options(db, f, level, q='', page=1, page_size=20):
    dataset = dataset_row(db, f['dataset'])
    abr = areas(db, dataset, f['election'])
    items = []
    if level == 'uf' and abr:
        items = [{'value': a['cd'], 'label': a.get('ds', a['cd'].upper())} for a in abr if a['cd'] != 'br']
    elif level == 'municipality' and abr:
        items = [{'value': m['cd'].zfill(5), 'label': m['nm']} for a in abr if a['cd'] == f.get('uf') for m in a.get('mu', [])]
    elif level == 'zone' and abr:
        items = [{'value': z.zfill(4), 'label': 'Zona ' + z.zfill(4)} for a in abr if a['cd'] == f.get('uf') for m in a.get('mu', []) if m['cd'].zfill(5) == f.get('municipality') for z in m.get('z', [])]
    if f['office'] != 1 and level == 'uf':
        items = [i for i in items if i['value'] != 'zz' and (f['office'] != 7 or i['value'] != 'df') and (f['office'] != 8 or i['value'] == 'df')]
    items = sorted((i for i in items if q.casefold() in (i['label'] + ' ' + i['value']).casefold()), key=lambda i: i['label'])
    return {'items': items[(page - 1) * page_size:page * page_size], 'total': len(items), 'page': page, 'page_size': page_size}

def result_source(result):
    return {k: result['source'][k] for k in ('label', 'updated_at', 'collected_at', 'url', 'official_progress')}


def territory_item(result, identity, name, level, f):
    candidate_votes = next((c['votes'] for c in result['candidates']
                            if c['number'] == f.get('candidate') and c['scope'] == f.get('candidate_scope')), None)
    return {'id': identity, 'name': name, 'level': level, 'votes': result['votes'],
            'candidate_votes': candidate_votes, 'winner': candidate_winner(result['candidates']),
            'source': result_source(result), **leadership(result['parties'], result['source']['available'])}


def territory_results(db, f, dataset, url_index):
    if f.get('zone'):
        return {'items': [], 'level': 'zone', 'limited': False}, {}
    level = 'zone' if f.get('municipality') else 'municipality' if f.get('uf') else 'uf'
    territory_options = options(db, f, level, page_size=1000)
    territories = []
    regional_sources = {}
    for item in territory_options['items']:
        key = item['value']
        filters = {**f, level: key}
        result = official.result(db, dataset, f['election'], f['office'], url_index=url_index,
                                   **{k: filters.get(k) for k in ('uf', 'municipality', 'zone')})
        if level == 'uf':
            regional_sources[key] = result
        territories.append(territory_item(result, key, item['label'], level, f))
    return {'items': territories, 'level': level, 'limited': territory_options['total'] > len(territories)}, regional_sources


def map_results(db, f, url_index=None):
    dataset = dataset_row(db, f['dataset'])
    if url_index is None:
        url_index = official.result_urls(db, dataset, f['election'])
    result, _ = territory_results(db, f, dataset, url_index)
    return {'territories': result}


def dashboard(db, f):
    dataset = dataset_row(db, f['dataset'])
    url_index = official.result_urls(db, dataset, f['election'])
    result = official.result(db, dataset, f['election'], f['office'], url_index=url_index,
                               **{k: f.get(k) for k in ('uf', 'municipality', 'zone')})
    src = result['source']
    cs = result['candidates']
    if not cs and scope(f):
        cs = [{**dict(row), 'votes': None, 'percentage': None, 'status': None} for row in db.execute(
            'SELECT number,scope,name,party,party_name FROM candidates WHERE dataset=? AND election=? AND office=? AND scope=?',
            (f['dataset'], f['election'], f['office'], scope(f)))]
    denominator = result['denominator']
    map_territory = territory_item(result, f['municipality'], f['municipality'], 'municipality', f) if f.get('municipality') and not f.get('zone') else None
    all_cs = cs
    cs = sorted((c for c in cs if f.get('search', '').casefold() in (c['name'] + ' ' + c['number']).casefold()),
                key=lambda c: (-(c['votes'] or 0), c['name'], c['number']))
    cp, ps = f['candidate_page'], f['page_size']
    remaining = cs[cp * ps:]
    remaining_votes = sum(c['votes'] for c in remaining) if src['available'] and all(c['votes'] is not None for c in remaining) else None
    remainder = {'count': len(remaining), 'votes': remaining_votes,
                 'percentage': 100 * remaining_votes / denominator if remaining_votes is not None and denominator else None}
    territory_result, regional_sources = territory_results(db, f, dataset, url_index)
    parties = {c['party']: c['party_name'] for c in all_cs if c['party']}
    for territory in territory_result['items']:
        for key in ('leader', 'runner_up'):
            if territory[key]:
                parties[territory[key]['number']] = territory[key]['name']
    return {'map_territory': map_territory, 'queried_at': datetime.now(timezone.utc).isoformat(),
            'source': src, 'summary': {k: result[k] for k in ('votes', 'nominal_votes', 'categories')},
            'regions': official.regional_progress(db, dataset, f['election'], f['office'], regional_sources),
            'candidates': {'items': cs[(cp - 1) * ps:cp * ps], 'total': len(cs), 'page': cp, 'page_size': ps,
                           'denominator': denominator, 'denominator_label': 'votos a votáveis concorrentes', 'remaining': remainder},
            'territories': territory_result, 'parties': [{'number': k, 'name': v} for k, v in sorted(parties.items())]}
