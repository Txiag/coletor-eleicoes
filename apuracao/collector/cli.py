import argparse
import logging
import sqlite3
from pathlib import Path

from .config import load_config
from .service import run

LOG = logging.getLogger('apuracao')


def parse_arguments():
    parser = argparse.ArgumentParser(description='Coleta resultados oficiais EA20 do TSE em SQLite')
    parser.add_argument('--config', type=Path, default=Path('config.toml'))
    parser.add_argument('--once', action='store_true', help='Executa um ciclo e encerra')
    parser.add_argument('--uf', action='append', help='Limita a coleta a uma UF; pode ser repetido')
    parser.add_argument('--json-only', action='store_true', help='Consulta apenas os endpoints JSON fixos')
    return parser.parse_args()


def main():
    args = parse_arguments()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        config = load_config(args.config.resolve())
        options = config.setdefault('results', {})
        if args.uf:
            options['ufs'] = [uf.lower() for uf in args.uf]
        if args.json_only:
            options['enabled'] = False
        return run(config, args.once)
    except KeyboardInterrupt:
        LOG.info('Coletor encerrado')
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        LOG.error('Não foi possível executar o coletor: %s', error)
        return 1
