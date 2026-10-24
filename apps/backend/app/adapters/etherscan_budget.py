"""Process-shared Etherscan pacing and UTC-calendar-day request accounting.

Shares the legacy collector's buckets/pacing schema, so the same account can
keep a single ledger. All cooperating processes must point to the same file.
Reservations count before network dispatch, including failures and retries.
No imports, constructors or RPC calls open this database.
"""
import asyncio
from dataclasses import dataclass
import math
from pathlib import Path
import sqlite3
import time

from ..errors import QuotaExhausted, ServiceError


@dataclass(frozen=True)
class QuotaState:
    used: int
    limit: int
    resets_at: float
    next_request_at: float

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class EtherscanBudget:
    def __init__(self, path: str | Path, *, rate: float = 3.0, limit: int = 99000,
                 clock=time.time, sleep=asyncio.sleep):
        if isinstance(rate, bool) or not math.isfinite(rate) or not 0 < rate <= 3:
            raise ValueError('Etherscan rate must be greater than 0 and at most 3')
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 99000:
            raise ValueError('Etherscan daily limit must be between 1 and 99000')
        self.path, self.rate, self.limit = Path(path).expanduser(), rate, limit
        self.clock, self.sleep = clock, sleep

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute('CREATE TABLE IF NOT EXISTS buckets (minute INTEGER PRIMARY KEY, calls INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS pacing (id INTEGER PRIMARY KEY CHECK(id=1), next_at REAL NOT NULL)')
            db.execute('INSERT OR IGNORE INTO pacing VALUES (1, 0)')
            db.commit()
            return db
        except BaseException:
            db.close()
            raise

    def _state(self, db, now: float) -> QuotaState:
        start = int(now // 86400) * 86400
        used = db.execute('SELECT COALESCE(SUM(calls), 0) FROM buckets WHERE minute >= ? AND minute < ?',
                          (start, start + 86400)).fetchone()[0]
        next_at = db.execute('SELECT next_at FROM pacing WHERE id=1').fetchone()[0]
        return QuotaState(used, self.limit, start + 86400, next_at)

    def snapshot(self) -> QuotaState:
        """Read admission state; never spend a slot simply to submit a job."""
        db = None
        try:
            db = self._connect()
            db.execute('BEGIN IMMEDIATE')
            state = self._state(db, self.clock())
            db.commit()
            return state
        except (sqlite3.Error, OSError):
            raise ServiceError('quota_store_unavailable') from None
        finally:
            if db is not None:
                db.close()

    def check_admission(self) -> QuotaState:
        state = self.snapshot()
        if state.remaining == 0:
            raise QuotaExhausted(state.resets_at)
        return state

    def reserve(self) -> float:
        """Return pacing wait seconds, or atomically spend one ready slot.

        Daily exhaustion raises immediately. A worker must persist its paused
        state instead of holding a thread or request open until the next day.
        """
        db = None
        try:
            db = self._connect()
            db.execute('BEGIN IMMEDIATE')
            now = self.clock()
            state = self._state(db, now)
            if state.remaining == 0:
                raise QuotaExhausted(state.resets_at)
            delay = max(0.0, state.next_request_at - now)
            if delay > 0:
                return delay
            minute = int(now // 60) * 60
            db.execute('INSERT INTO buckets VALUES (?, 1) ON CONFLICT(minute) DO UPDATE SET calls=calls+1', (minute,))
            db.execute('UPDATE pacing SET next_at=? WHERE id=1', (now + 1 / self.rate,))
            # Preserve the last 24h for the local trainer's rolling-window policy.
            db.execute('DELETE FROM buckets WHERE minute + 60 <= ?', (now - 86400,))
            db.commit()
            return 0.0
        except (sqlite3.Error, OSError):
            raise ServiceError('quota_store_unavailable') from None
        finally:
            if db is not None:
                db.close()

    async def acquire(self) -> None:
        while True:
            delay = await asyncio.to_thread(self.reserve)
            if delay == 0:
                return
            await self.sleep(min(delay, 1.0))
