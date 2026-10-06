import argparse
import sqlite3
import tomllib
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from . import queries

@contextmanager
def read_database(path):
    db = None
    try:
        db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    except sqlite3.Error as exc:
        raise HTTPException(503, 'Banco indisponível ou incompleto. Configure o banco já criado pelo coletor.') from exc
    finally:
        if db:
            db.close()

def context(request: Request, dataset: str, election: int=Query(gt=0), office: int=Query(gt=0), source: Literal['official']='official', uf: str | None=Query(None, pattern='^[a-z]{2}$'), municipality: str | None=Query(None, pattern='^\\d{5}$'), zone: str | None=Query(None, pattern='^\\d{4}$'), search: str=Query('', max_length=100), candidate: str | None=Query(None, pattern='^\\d{1,6}$'), candidate_scope: str | None=Query(None, pattern='^[a-z]{2}(\\d{5})?$'), page: int=Query(1, ge=1), candidate_page: int=Query(1, ge=1), page_size: int=Query(20, ge=1, le=100)):
    if municipality and (not uf) or (zone and (not municipality)):
        raise HTTPException(422, 'Selecione os territórios superiores antes de detalhar o recorte.')
    if bool(candidate) != bool(candidate_scope):
        raise HTTPException(422, 'Candidato requer seu número e sua circunscrição.')
    if 'at' in request.query_params:
        raise HTTPException(422, 'Consultas por instante não são suportadas; a API fornece os resultados consolidados atuais.')
    values = locals()
    values.pop('request')
    return values

def validate_context(db, f):
    if not db.execute('SELECT 1 FROM elections WHERE dataset=? AND code=?', (f['dataset'], f['election'])).fetchone():
        raise HTTPException(404, 'Dataset ou eleição não encontrado.')
    dataset = queries.dataset_row(db, f['dataset'])
    if not queries.has_office(db, dataset, f['election'], f['office']):
        raise HTTPException(404, 'Cargo não cadastrado nesta eleição.')
    f['_areas'] = queries.areas(db, dataset, f['election'])

def create_app(database=Path('data/apuracao-2026.sqlite3'), dist=None):
    app = FastAPI(title='Apuração 2026 — API de leitura')
    root = Path(dist or Path(__file__).resolve().parents[2] / 'frontend' / 'dist').resolve()
    map_cache = OrderedDict()
    cache_lock = threading.Lock()

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse(status_code=422, content={'detail': 'Parâmetros inválidos: ' + '; '.join(('.'.join(map(str, e['loc'][1:])) + ' — ' + e['msg'] for e in exc.errors()))})

    @app.get('/api/metadata')
    def metadata():
        with read_database(database) as db:
            return queries.metadata(db)

    @app.get('/api/options')
    def options(level: Literal['uf', 'municipality', 'zone'], q: str=Query('', max_length=100), f: dict=Depends(context)):
        required = {'municipality': 'uf', 'zone': 'municipality'}.get(level)
        if required and (not f.get(required)):
            raise HTTPException(422, 'Selecione o território superior.')
        with read_database(database) as db:
            validate_context(db, f)
            return queries.options(db, f, level, q, f['page'], f['page_size'])

    @app.get('/api/dashboard')
    def dashboard(f: dict=Depends(context)):
        with read_database(database) as db:
            validate_context(db, f)
            return queries.dashboard(db, f)

    @app.get('/api/map')
    def map_results(request: Request, f: dict=Depends(context)):
        if any(f.get(key) for key in ('municipality', 'zone', 'candidate', 'search')):
            raise HTTPException(422, 'O mapa consulta municípios por UF ou o resumo nacional, sem filtros do painel.')
        key = tuple(f.get(k) for k in ('dataset', 'election', 'office', 'source', 'uf'))
        now = time.monotonic()
        with cache_lock:
            cached = map_cache.get(key)
        if cached and cached[2] > now and 'no-cache' not in request.headers.get('cache-control', ''):
            etag, body, _ = cached
        else:
            from .map_cache import revision
            with read_database(database) as db:
                validate_context(db, f)
                etag, index = revision(db, f)
                body = cached[1] if cached and cached[0] == etag else JSONResponse(queries.map_results(db, f, index)).body
            with cache_lock:
                map_cache[key] = (etag, body, now + 5)
                map_cache.move_to_end(key)
                while len(map_cache) > 84:
                    map_cache.popitem(last=False)
        headers = {'ETag': etag, 'Cache-Control': 'private, max-age=15, must-revalidate'}
        if etag in request.headers.get('if-none-match', '').split(', '):
            return Response(status_code=304, headers=headers)
        return Response(body, media_type='application/json', headers=headers)

    @app.get('/api/geography')
    def geography(request: Request, uf: str | None=Query(None, pattern='^[a-z]{2}$')):
        from .geography import get_geography, ASSET_DIR, UFS
        key = uf or 'br'
        asset = ASSET_DIR / f'{key}.geojson'
        if (key == 'br' or key in UFS) and asset.is_file():
            stat = asset.stat()
            etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
            headers = {'ETag': etag, 'Cache-Control': 'public, max-age=86400'}
            if request.headers.get('if-none-match') == etag:
                return Response(status_code=304, headers=headers)
            return FileResponse(asset, media_type='application/geo+json', headers=headers)
        try:
            return get_geography(uf)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get('/{path:path}')
    def frontend(path: str):
        if path == 'api' or path.startswith('api/'):
            raise HTTPException(404, 'Rota não encontrada.')
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(404, 'Arquivo não encontrado.')
        if target.is_file():
            return FileResponse(target)
        if Path(path).suffix:
            raise HTTPException(404, 'Arquivo não encontrado.')
        index = root / 'index.html'
        if not index.exists():
            raise HTTPException(503, 'Frontend não compilado. Execute o build em frontend/.')
        return FileResponse(index)
    return app

def main():
    parser = argparse.ArgumentParser(description='API de leitura e dashboard da apuração')
    parser.add_argument('--config', type=Path, default=Path('config.toml'))
    parser.add_argument('--database', type=Path)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.database:
        database = args.database
    else:
        with args.config.open('rb') as file:
            config = tomllib.load(file)
        database = args.config.parent / config.get('database', 'data/apuracao-2026.sqlite3')
    import uvicorn
    uvicorn.run(create_app(database), host=args.host, port=args.port)
if __name__ == '__main__':
    main()
