import sqlite3
from pathlib import Path


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots'").fetchone():
            raise ValueError('Banco com histórico: execute pdm run migrate --source BANCO --output NOVO_BANCO e configure o banco consolidado.')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
        return db
    except Exception:
        db.close()
        raise
