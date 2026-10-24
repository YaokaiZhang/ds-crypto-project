"""Single-host durable jobs, fenced leases, artifacts and replayable events."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from ..errors import ServiceError


TERMINAL = {'completed', 'partial', 'failed'}


def utc(stamp=None):
    return datetime.fromtimestamp(time.time() if stamp is None else stamp, timezone.utc).isoformat().replace('+00:00', 'Z')


class LeaseLost(RuntimeError):
    pass


class AnalysisStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, command TEXT NOT NULL, fingerprint TEXT NOT NULL,
                  idem TEXT UNIQUE, result TEXT NOT NULL, owner TEXT, token TEXT,
                  lease_until REAL NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
                  failures INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS event_job ON events(job,seq);
                CREATE TABLE IF NOT EXISTS artifacts (
                  job TEXT NOT NULL, kind TEXT NOT NULL, task TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL,
                  PRIMARY KEY(job,kind,task));
                CREATE TABLE IF NOT EXISTS ledger (
                  job TEXT NOT NULL, category TEXT NOT NULL, identity TEXT NOT NULL,
                  block INTEGER NOT NULL, position TEXT NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(job,category,identity));
                CREATE INDEX IF NOT EXISTS ledger_order ON ledger(job,category,block DESC,position DESC,identity);
                CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, heartbeat REAL NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _event(self, db, identity, result):
        event = {k: deepcopy(result.get(k)) for k in ('stage', 'status', 'message', 'progress')}
        event.update(analysis_id=identity, timestamp=result['updated_at'])
        cursor = db.execute('INSERT INTO events(job,payload) VALUES (?,?)', (identity, json.dumps(event)))
        return cursor.lastrowid

    def existing(self, command, idem):
        if not idem:
            return None
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE idem=?', (idem,)).fetchone()
        if row is None:
            return None
        if row['fingerprint'] != self.fingerprint(command):
            raise ServiceError('idempotency_conflict')
        return json.loads(row['result'])

    @staticmethod
    def fingerprint(command):
        return hashlib.sha256(json.dumps(command, sort_keys=True).encode()).hexdigest()

    def create(self, command, idem):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if idem:
                row = db.execute('SELECT * FROM jobs WHERE idem=?', (idem,)).fetchone()
                if row:
                    if row['fingerprint'] != self.fingerprint(command):
                        raise ServiceError('idempotency_conflict')
                    return json.loads(row['result'])
            identity, stamp = str(uuid4()), utc()
            result = dict(analysis_id=identity, status='queued', stage='queued', target=command['target'],
                family=command['family'], result_origin='chain_data_simulated_scores', created_at=stamp, updated_at=stamp,
                message='Queued for real Ethereum collection. Model scores will be simulated.',
                tasks=[{'task_id': task, 'status': 'pending', 'score': None} for task in command['tasks']],
                graphs={}, progress={'state': 'queued', 'unit': 'requests', 'completed': 0})
            db.execute('INSERT INTO jobs(id,command,fingerprint,idem,result,created) VALUES (?,?,?,?,?,?)',
                (identity, json.dumps(command), self.fingerprint(command), idem, json.dumps(result), time.time()))
            self._event(db, identity, result)
        return result

    def get(self, identity):
        with self.db() as db:
            row = db.execute('SELECT result FROM jobs WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise ServiceError('analysis_not_found')
        return json.loads(row['result'])

    def claim(self, owner, lease_seconds=60, concurrency=2):
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute('SELECT COUNT(*) FROM jobs WHERE lease_until>?', (now,)).fetchone()[0]
            if active >= concurrency:
                return None
            for row in db.execute('SELECT * FROM jobs WHERE lease_until<=? AND retry_at<=? ORDER BY created', (now, now)):
                if json.loads(row['result'])['status'] in TERMINAL:
                    continue
                token = str(uuid4())
                db.execute('UPDATE jobs SET owner=?,token=?,lease_until=? WHERE id=?',
                           (owner, token, now + lease_seconds, row['id']))
                return {'id': row['id'], 'token': token, 'command': json.loads(row['command']), 'failures': row['failures']}
        return None

    def _fence(self, db, lease):
        row = db.execute('SELECT * FROM jobs WHERE id=? AND token=? AND lease_until>?',
                         (lease['id'], lease['token'], time.time())).fetchone()
        if row is None:
            raise LeaseLost('Analysis lease expired or was reclaimed')
        return row

    def save(self, lease, patch, *, artifacts=None, ledger=None, ledger_append=None, finish=False, retry_at=0, failures=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._fence(db, lease)
            result = json.loads(row['result'])
            result.update(patch, updated_at=utc())
            for (kind, task), payload in (artifacts or {}).items():
                db.execute('INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?)',
                           (lease['id'], kind, task, json.dumps(payload, allow_nan=False)))
            if ledger is not None:
                db.execute('DELETE FROM ledger WHERE job=?', (lease['id'],))
            if ledger is not None or ledger_append is not None:
                db.executemany('INSERT OR REPLACE INTO ledger VALUES (?,?,?,?,?,?)', [
                    (lease['id'], r['category'], r['id'], r['block_number'],
                     f"{r.get('transaction_index') or 0:08d}:{r.get('log_index') or 0:08d}:{r.get('trace_id') or ''}", json.dumps(r)) for r in [*(ledger or []), *(ledger_append or [])]])
            db.execute('UPDATE jobs SET result=?,retry_at=?,failures=?,lease_until=?,token=? WHERE id=?',
                (json.dumps(result, allow_nan=False), retry_at,
                 row['failures'] if failures is None else failures,
                 0 if finish else row['lease_until'], None if finish else row['token'], lease['id']))
            self._event(db, lease['id'], result)
        return result

    def heartbeat(self, lease, seconds):
        with self.db() as db:
            cursor = db.execute('UPDATE jobs SET lease_until=? WHERE id=? AND token=? AND lease_until>?',
                (time.time() + seconds, lease['id'], lease['token'], time.time()))
        if not cursor.rowcount:
            raise LeaseLost('Analysis lease was lost')

    def artifact(self, identity, kind, task=''):
        with self.db() as db:
            row = db.execute('SELECT payload FROM artifacts WHERE job=? AND kind=? AND task=?', (identity, kind, task)).fetchone()
        return json.loads(row['payload']) if row else None

    def transactions(self, identity, category, limit, offset):
        with self.db() as db:
            count = db.execute('SELECT COUNT(*) FROM ledger WHERE job=? AND category=?', (identity, category)).fetchone()[0]
            rows = db.execute('SELECT payload FROM ledger WHERE job=? AND category=? ORDER BY block DESC,position DESC,identity LIMIT ? OFFSET ?',
                              (identity, category, limit, offset)).fetchall()
        return [json.loads(r['payload']) for r in rows], count

    def replay(self, identity, after):
        with self.db() as db:
            if after and not db.execute('SELECT 1 FROM events WHERE job=? AND seq=?', (identity, after)).fetchone():
                raise ServiceError('invalid_cursor')
            rows = db.execute('SELECT * FROM events WHERE job=? AND seq>? ORDER BY seq LIMIT 200', (identity, after)).fetchall()
        return [(r['seq'], json.loads(r['payload'])) for r in rows]

    def worker_tick(self, owner):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO workers VALUES (?,?)', (owner, time.time()))

    def worker_alive(self):
        with self.db() as db:
            return bool(db.execute('SELECT 1 FROM workers WHERE heartbeat>? LIMIT 1', (time.time() - 20,)).fetchone())

    def worker_remove(self, owner):
        with self.db() as db:
            db.execute('DELETE FROM workers WHERE id=?', (owner,))
