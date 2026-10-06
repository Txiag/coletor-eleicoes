import math
import tomllib
from urllib.parse import urlsplit

from ..metadata_store import CATALOG_CYCLE
from .result_schedule import result_levels


def load_config(path):
    with path.open('rb') as file:
        config = tomllib.load(file)
    for key, default in (('interval_seconds', 30), ('timeout_seconds', 20)):
        value = float(config.get(key, default))
        if not math.isfinite(value) or value < 1:
            raise ValueError(f'{key} deve ser um número de pelo menos 1')
        config[key] = value

    options = config.get('results', {})
    endpoints = config.get('endpoints', [])
    if not endpoints and not options.get('enabled'):
        raise ValueError('Configure endpoints ou habilite results.enabled')
    _validate_endpoints(endpoints)
    if options.get('enabled'):
        _normalize_results(options, config['timeout_seconds'])
    config['database'] = path.parent / config.get('database', 'data/apuracao-2026.sqlite3')
    return config


def _normalize_results(options, timeout):
    if options.get('cycle', CATALOG_CYCLE) != CATALOG_CYCLE:
        raise ValueError(f'results.cycle deve ser {CATALOG_CYCLE}')
    options['cycle'] = CATALOG_CYCLE
    if options.get('phase') not in {'official', 'simulated'}:
        raise ValueError('results.phase deve ser official ou simulated')
    options['levels'] = result_levels(options)
    for key, default, upper in (
        ('requests_per_second', 20, 80),
        ('max_local_results_per_cycle', 1000, 10000),
    ):
        value = int(options.get(key, default))
        if not 1 <= value <= upper:
            raise ValueError(f'results.{key} deve estar entre 1 e {upper}')
        options[key] = value
    options['timeout_seconds'] = timeout
    options['ufs'] = [uf.lower() for uf in options.get('ufs', [])]


def _validate_endpoints(endpoints):
    urls = set()
    for endpoint in endpoints:
        parsed = urlsplit(endpoint['url'])
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            raise ValueError('Endpoint deve ser uma URL HTTP(S)')
        if not endpoint['name'] or endpoint['url'] in urls:
            raise ValueError('Endpoints precisam de nome e URLs únicas')
        urls.add(endpoint['url'])
