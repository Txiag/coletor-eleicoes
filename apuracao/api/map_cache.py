import hashlib
import json

from .. import official
from . import queries


def revision(db, f):
    dataset = queries.dataset_row(db, f['dataset'])
    index = official.result_urls(db, dataset, f['election'])
    digest = hashlib.sha256(json.dumps({k: f.get(k) for k in ('dataset', 'election', 'office', 'source', 'uf')}, sort_keys=True).encode())

    def include(rows):
        for row in rows:
            digest.update(json.dumps(tuple(row), ensure_ascii=False, separators=(',', ':')).encode())

    include([tuple(dataset.values())])
    include(db.execute('SELECT * FROM elections WHERE dataset=? AND code=?', (f['dataset'], f['election'])))
    # Metadados podem alterar abrangências e nomes mesmo sem uma nova votação.
    metadata_urls = [dataset['base_url'].rstrip('/') + '/comum/config/ele-c.json']
    metadata_urls.extend(url for name, urls in index.items() if name.endswith('-cm.json') for url in urls)
    for url in sorted(metadata_urls):
        include(db.execute('SELECT content_hash FROM sources WHERE url=?', (url,)))
    suffix = f"-c{f['office']:04d}-e{f['election']:06d}-u.json"
    for name, urls in sorted(index.items()):
        if not name.endswith(suffix) or '-z' in name or (f.get('uf') and not name.startswith(f['uf'])):
            continue
        area = name[:-len(suffix)]
        if (f.get('uf') and len(area) != 7) or (not f.get('uf') and len(area) != 2):
            continue
        for url in sorted(urls):
            digest.update(url.encode())
            include(db.execute('SELECT content_hash FROM sources WHERE url=?', (url,)))
    return '"' + digest.hexdigest() + '"', index
