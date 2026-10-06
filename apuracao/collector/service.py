import logging
import math
import time
from urllib.parse import urlsplit

from scripts.prepare_geography import ensure_prepared

from ..database import connect
from .http import RateLimiter, fetch
from .results import ResultCollector

LOG = logging.getLogger('apuracao')
BLOCKED_STATUSES = {403, 404, 429}
COOLDOWN_SECONDS = 610


def _register_dataset(db, options):
    if not all(key in options for key in ('base_url', 'cycle', 'poll', 'phase')):
        return
    base = options['base_url'].rstrip('/')
    dataset = f"{base}/{options['cycle']}/{options['poll']}"
    with db:
        db.execute('INSERT OR IGNORE INTO datasets VALUES(?,?,?,?,?)',
                   (dataset, base, options['cycle'], options['poll'], options['phase']))


def _collect_fixed_endpoints(db, config, limiter, collector):
    ok = True
    options = config.get('results', {})
    dataset = None
    if all(key in options for key in ('base_url', 'cycle', 'poll')):
        dataset = f"{options['base_url'].rstrip('/')}/{options['cycle']}/{options['poll']}"
    for endpoint in config.get('endpoints', []):
        if collector and urlsplit(endpoint['url']).path.endswith('-u.json'):
            continue
        completed = db.execute(
            'SELECT 1 FROM results WHERE source_url=? AND completed=1 AND (? IS NULL OR dataset=?)',
            (endpoint['url'], dataset, dataset),
        ).fetchone()
        if completed:
            continue
        limiter.wait()
        status = fetch(db, endpoint, config['timeout_seconds'])
        ok = status in (200, 304) and ok
        if status in BLOCKED_STATUSES:
            limiter.blocked.set()
            if collector:
                collector.pause(COOLDOWN_SECONDS)
            LOG.warning('Ciclo interrompido; aguardar ao menos 10 minutos antes de tentar novamente')
            return ok, True
    return ok, False


def _collect_cycle(db, config, limiter, collector):
    limiter.blocked.clear()
    ok = collector.cycle() if collector else True
    if collector and collector.remaining_pause():
        return False, True
    endpoints_ok, blocked = _collect_fixed_endpoints(db, config, limiter, collector)
    return ok and endpoints_ok, blocked


def run(config, once=False):
    ensure_prepared()
    db = connect(config['database'])
    try:
        options = config.get('results', {})
        _register_dataset(db, options)
        limiter = RateLimiter(options.get('requests_per_second', 20))
        # Generator
        collector = ResultCollector(db, options, fetch, limiter) if options.get('enabled') else None
        while True:
            remaining = collector.remaining_pause() if collector else 0
            if remaining:
                LOG.warning('Coleta em pausa por mais %.0f segundos', remaining)
                if once:
                    return 1
                time.sleep(min(30, remaining))
                continue
            ok, blocked = _collect_cycle(db, config, limiter, collector)
            if once:
                return 0 if ok else 1
            delay = max(config['interval_seconds'], COOLDOWN_SECONDS if blocked else 0)
            remaining = collector.remaining_pause() if collector else 0
            LOG.info('Próxima requisição em %d segundos', math.ceil(max(delay, remaining)))
            time.sleep(delay)
    finally:
        db.close()
