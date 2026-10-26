"""Bounded local feed store shared by one collector and multiple API readers.

The OS advisory lock is held for the collector's lifetime, including RPC waits.
Use a shared PostgreSQL implementation before deploying collectors across hosts.
"""
import os
if os.name == 'nt':
    import msvcrt
else:
    import fcntl
import json
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timezone


def utc(epoch: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, timezone.utc).isoformat()


class FeedStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=2)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS feed_state (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            INSERT OR IGNORE INTO feed_state VALUES (1, '{}');
            CREATE TABLE IF NOT EXISTS feed_blocks (number INTEGER PRIMARY KEY, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS feed_rows (hash TEXT PRIMARY KEY, block INTEGER NOT NULL, data TEXT NOT NULL, sequence INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS feed_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, data TEXT NOT NULL);
        ''')
        self.owner = None

    def acquire(self):
        if self.owner is not None:
            raise RuntimeError('This collector already owns the database')
        self.owner = open(self.path + '.lock', 'a+b')
        try:
            if os.name == 'nt':
                if self.owner.seek(0, os.SEEK_END) == 0:
                    self.owner.write(b'\0')
                    self.owner.flush()
                self.owner.seek(0)
                msvcrt.locking(self.owner.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner.close()
            self.owner = None
            raise RuntimeError('Another feed collector owns this database') from None

    def close(self):
        if self.owner:
            self.owner.close()
            self.owner = None
        self.db.close()

    def state(self):
        return json.loads(self.db.execute('SELECT data FROM feed_state WHERE id=1').fetchone()[0])

    def _update(self, **values):
        state = {**self.state(), **values}
        self.db.execute('UPDATE feed_state SET data=? WHERE id=1', (json.dumps(state),))

    def update(self, **values):
        with self.db:
            self._update(**values)

    def blocks(self):
        return {row['number']: row['hash'] for row in self.db.execute('SELECT * FROM feed_blocks')}

    def accept(self, blocks: list[dict]):
        with self.db:
            for block in blocks:
                self.db.execute('INSERT OR REPLACE INTO feed_blocks VALUES (?,?)', (int(block['number'], 16), block['hash']))
            head = blocks[-1]
            number = int(head['number'], 16)
            self.db.execute('DELETE FROM feed_blocks WHERE number < ?', (number - 31,))
            self._update(head_block=number, head_hash=head['hash'], head_time=utc(int(head['timestamp'], 16)),
                         checked_at=utc(), source_status='live', message=None)

    def _meta(self):
        state = self.state()
        checked = state.get('checked_at')
        head_time = state.get('head_time')
        stale = not checked or time.time() - datetime.fromisoformat(checked).timestamp() > 20
        old_head = head_time and time.time() - datetime.fromisoformat(head_time).timestamp() > 90
        status = state.get('source_status', 'connecting')
        if stale or old_head:
            status = 'stale' if state.get('head_block') is not None else 'connecting'
        quote = state.get('usd_quote')
        if quote and not 0 <= time.time() - datetime.fromisoformat(quote['fetched_at']).timestamp() <= 300:
            quote = None
        return {key: value for key, value in {
            'status': status, 'updated_at': state.get('updated_at'), 'checked_at': checked,
            'head_block': state.get('head_block'), 'head_time': head_time,
            'sequence': state.get('sequence', 0), 'message': state.get('message'),
            'last_gap_at': state.get('last_gap_at'), 'source': 'Ethereum Mainnet RPC',
            'usd_quote': quote,
        }.items()}

    def _snapshot(self, limit=30):
        rows = [json.loads(row[0]) for row in self.db.execute(
            'SELECT data FROM feed_rows ORDER BY sequence DESC LIMIT 100')]
        return {**self._meta(), 'transactions': [row for row in rows if int(row['value_wei']) > 0][:limit]}

    def snapshot(self, limit=30):
        with self.db:
            self.db.execute('BEGIN')
            return self._snapshot(limit)

    def _event(self, kind, data):
        cursor = self.db.execute('INSERT INTO feed_events(kind,data) VALUES (?,?)', (kind, json.dumps(data)))
        seq = cursor.lastrowid
        self._update(sequence=seq)
        self.db.execute('DELETE FROM feed_events WHERE sequence <= ?', (seq - 300,))
        return seq

    def rollback(self, ancestor: int | None, reason: str):
        with self.db:
            threshold = ancestor if ancestor is not None else -1
            self.db.execute('DELETE FROM feed_rows WHERE block > ?', (threshold,))
            self.db.execute('DELETE FROM feed_blocks WHERE number > ?', (threshold,))
            head = self.db.execute('SELECT number,hash FROM feed_blocks ORDER BY number DESC LIMIT 1').fetchone()
            self._update(head_block=head[0] if head else None, head_hash=head[1] if head else None,
                         head_time=None, source_status='recovering', message=reason, last_gap_at=utc())
            seq = self._event('snapshot', {})
            self.db.execute('UPDATE feed_events SET data=? WHERE sequence=?', (json.dumps(self._snapshot()), seq))

    def publish(self, transaction: dict) -> bool:
        if int(transaction['value_wei']) <= 0:
            return False
        with self.db:
            if self.db.execute('SELECT 1 FROM feed_rows WHERE hash=?', (transaction['hash'],)).fetchone():
                return False
            seq = self._event('transaction', {})
            self.db.execute('INSERT INTO feed_rows VALUES (?,?,?,?)',
                            (transaction['hash'], transaction['block_number'], json.dumps(transaction), seq))
            self.db.execute('DELETE FROM feed_rows WHERE hash NOT IN (SELECT hash FROM feed_rows ORDER BY sequence DESC LIMIT 100)')
            self._update(updated_at=utc())
            self.db.execute('UPDATE feed_events SET data=? WHERE sequence=?',
                            (json.dumps({'transaction': transaction, 'meta': self._meta()}), seq))
            return True

    def apply_positive_filter(self):
        """One-time policy transition removes zero-value rows and resets old replay."""
        with self.db:
            if self.state().get('policy') == 'positive-eth-v2':
                return
            for row in self.db.execute('SELECT hash,data FROM feed_rows').fetchall():
                if int(json.loads(row['data'])['value_wei']) <= 0:
                    self.db.execute('DELETE FROM feed_rows WHERE hash=?', (row['hash'],))
            self.db.execute('DELETE FROM feed_events')
            self._update(policy='positive-eth-v2')
            sequence = self._event('snapshot', {})
            self.db.execute('UPDATE feed_events SET data=? WHERE sequence=?',
                            (json.dumps(self._snapshot()), sequence))

    def replay(self, last: int):
        """Atomically return a replay window or a reset snapshot if it has expired."""
        with self.db:
            self.db.execute('BEGIN')
            bounds = self.db.execute('SELECT MIN(sequence),MAX(sequence) FROM feed_events').fetchone()
            current = self.state().get('sequence', 0)
            if last > current or last < 0 or (bounds[0] and last < bounds[0] - 1):
                snapshot = self._snapshot()
                return [(current, 'snapshot', snapshot)]
            return [(row[0], row[1], json.loads(row[2])) for row in self.db.execute(
                'SELECT sequence,kind,data FROM feed_events WHERE sequence>? ORDER BY sequence', (last,))]
