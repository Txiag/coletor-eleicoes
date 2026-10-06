CATALOG_CYCLE = 'ele2026'


def save(db, source_id, url, payload):
    if url.endswith('/comum/config/ele-c.json'):
        _save_catalog(db, source_id, url, payload)
    elif url.endswith('-cm.json'):
        _save_geography(db, source_id, url, payload)


def _save_catalog(db, source_id, url, payload):
    db.execute("UPDATE sources SET kind='catalog' WHERE id=?", (source_id,))
    base = url.removesuffix('/comum/config/ele-c.json')
    for poll in payload.get('pl', []):
        if poll['c'] != CATALOG_CYCLE:
            continue
        datasets = db.execute('SELECT id FROM datasets WHERE base_url=? AND cycle=? AND poll=?',
                              (base, poll['c'], int(poll['cd']))).fetchall()
        for dataset in datasets:
            for election in poll.get('e', []):
                code = int(election['cd'])
                db.execute('''INSERT INTO elections(dataset,code,name,round,type) VALUES(?,?,?,?,?)
                    ON CONFLICT(dataset,code) DO UPDATE SET name=excluded.name,
                        round=excluded.round,type=excluded.type''',
                           (dataset['id'], code, election.get('nm', str(code)),
                            int(election['t']), str(election.get('tp', ''))))
                db.execute('DELETE FROM offices WHERE dataset=? AND election=?', (dataset['id'], code))
                db.executemany('INSERT INTO offices VALUES(?,?,?,?,?)', [
                    (dataset['id'], code, area['cd'], int(office['cd']), office.get('ds', str(office['cd'])))
                    for area in election.get('abr', []) for office in area.get('cp', [])])


def _save_geography(db, source_id, url, payload):
    db.execute("UPDATE sources SET kind='geography',phase=? WHERE id=?", (payload.get('f'), source_id))
    db.execute('DELETE FROM territories WHERE source_url=?', (url,))
    territories = []
    for state in payload.get('abr', []):
        uf = state['cd']
        territories.append((url, uf, '', '', state.get('ds', uf.upper())))
        for city in state.get('mu', []):
            code = str(city['cd']).zfill(5)
            territories.append((url, uf, code, '', city.get('nm', code)))
            territories.extend((url, uf, code, str(zone).zfill(4), str(zone).zfill(4))
                               for zone in city.get('z', []))
    db.executemany('INSERT INTO territories VALUES(?,?,?,?,?)', territories)


def read(db, source_id):
    source = db.execute('SELECT * FROM sources WHERE id=?', (source_id,)).fetchone()
    if source is None:
        return {}
    if source['kind'] == 'catalog':
        return _read_catalog(db, source['url'])
    if source['kind'] == 'geography':
        return _read_geography(db, source)
    return {}


def _read_catalog(db, url):
    polls = []
    datasets = db.execute('SELECT * FROM datasets WHERE base_url=? AND cycle=? ORDER BY poll',
                          (url.removesuffix('/comum/config/ele-c.json'), CATALOG_CYCLE))
    for dataset in datasets:
        elections = []
        for election in db.execute('SELECT * FROM elections WHERE dataset=? ORDER BY code', (dataset['id'],)):
            areas = {}
            for office in db.execute('SELECT * FROM offices WHERE dataset=? AND election=? ORDER BY coverage,code',
                                     (dataset['id'], election['code'])):
                areas.setdefault(office['coverage'], []).append({'cd': str(office['code']), 'ds': office['name']})
            elections.append({'cd': str(election['code']), 'nm': election['name'], 't': str(election['round']),
                              'tp': election['type'], 'abr': [{'cd': area, 'cp': offices} for area, offices in areas.items()]})
        polls.append({'cd': str(dataset['poll']), 'c': dataset['cycle'], 'e': elections})
    return {'pl': polls}


def _read_geography(db, source):
    rows = db.execute('SELECT * FROM territories WHERE source_url=? ORDER BY uf,municipality,zone',
                      (source['url'],)).fetchall()
    states = {}
    cities = {}
    for row in rows:
        uf, municipality, zone = row['uf'], row['municipality'], row['zone']
        if not municipality:
            states[uf] = {'cd': uf, 'ds': row['name'], 'mu': []}
        elif not zone:
            city = {'cd': municipality, 'nm': row['name'], 'z': []}
            cities[uf, municipality] = city
            states[uf]['mu'].append(city)
        else:
            cities[uf, municipality]['z'].append(zone)
    return {'f': source['phase'], 'abr': list(states.values())}
