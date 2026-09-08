import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

@contextmanager
def connect():
    path = Path(os.environ.get('SMARTATTEND_DB', ROOT / 'data' / 'smartattend.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    try:
        with db:
            yield db
    finally:
        db.close()

def initialize():
    with connect() as db:
        db.executescript((Path(__file__).with_name('schema.sql')).read_text())
        for name in ('AIML', 'CSE', 'Civil', 'ECE', 'MECH'):
            db.execute('INSERT OR IGNORE INTO departments(name) VALUES (?)', (name,))
        for name in ('A', 'B', 'C'):
            db.execute('INSERT OR IGNORE INTO sections(name) VALUES (?)', (name,))
