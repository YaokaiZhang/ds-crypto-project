"""Project-local credentials and a selectable persistent collector quota.

One shared instance coordinates in-process worker threads. This is not an
account-wide or cross-process rate limiter. Other programs and
machines using the same Etherscan account must be budgeted separately.
"""
from contextlib import contextmanager
import ast
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
import threading

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_FILE = PROJECT_ROOT / "local_secrets.py"
QUOTA_FILE = PROJECT_ROOT / ".runtime/etherscan/quota.sqlite3"
REQUESTS_PER_SECOND = 2.5
REQUESTS_PER_24H = 95000


def local_credential(name, *, path=None):
    # An explicitly empty environment value disables fallback as well.
    if name in os.environ:
        return os.environ[name].strip()
    path = Path(path) if path is not None else SECRETS_FILE
    if not path.exists():
        return ""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                value = ast.literal_eval(node.value)
                if not isinstance(value, str):
                    raise ValueError
                return value.strip()
    except (SyntaxError, ValueError, TypeError):
        # Do not include source lines (which could contain the credential).
        raise ValueError(f"local_secrets.py requires a literal {name} string") from None
    return ""


def etherscan_key(env_name="ETHERSCAN_API_KEY", *, path=None):
    if env_name != "ETHERSCAN_API_KEY":
        return os.environ.get(env_name, "").strip()
    return local_credential(env_name, path=path)


def ethereum_rpc_url(*, path=None):
    return local_credential("ETHEREUM_RPC_URL", path=path)


class SerialRequestBudget:
    """Reserve thread-shared HTTP attempts; cached responses do not consume quota.

    Minute buckets conservatively retain up to an extra minute of history. State
    survives restarts, and a slot is committed before issuing a network request.
    The serial request context waits at most 60 seconds per sleep and reports
    quota waits, allowing the unattended process to continue on the next window.
    """
    def __init__(self, path=None, *, rate=REQUESTS_PER_SECOND, limit=REQUESTS_PER_24H,
                 clock=None, sleep=None, notify=None):
        if not math.isfinite(rate) or not 0 < rate <= REQUESTS_PER_SECOND or not 1 <= limit <= 100000:
            raise ValueError("invalid_etherscan_request_budget")
        # Resolve at construction time: a child collector can use a different
        # account ledger without changing existing workers or local secrets.
        if path is None:
            path = os.environ.get("ETHERSCAN_QUOTA_FILE", "").strip() or QUOTA_FILE
        self.path, self.rate, self.limit = Path(path).expanduser(), rate, limit
        self.clock, self.sleep = clock or time.time, sleep or time.sleep
        self.notify = notify or (lambda message: print(message, file=sys.stderr, flush=True))
        self.wait_seconds = 0.0
        self._lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.custom_sleep = sleep is not None

    def cancel(self):
        self.cancel_event.set()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("CREATE TABLE IF NOT EXISTS buckets (minute INTEGER PRIMARY KEY, calls INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS pacing (id INTEGER PRIMARY KEY CHECK(id=1), next_at REAL NOT NULL)")
        db.execute("INSERT OR IGNORE INTO pacing VALUES (1, 0)")
        db.commit()
        return db

    @contextmanager
    def request_slot(self):
        """One shared instance reserves slots across in-process HTTP workers.

        The lock covers only the quota transaction, never the HTTP response.
        This permits concurrent in-flight requests while pacing all starts.
        """
        last_notice = None
        while True:
            if self.cancel_event.is_set():
                raise InterruptedError("provider_request_cancelled")
            with self._lock:
                db = self._connect()
                try:
                    now = self.clock()
                    db.execute("DELETE FROM buckets WHERE minute + 60 <= ?", (now - 86400,))
                    count, oldest = db.execute("SELECT COALESCE(SUM(calls), 0), MIN(minute) FROM buckets").fetchone()
                    next_at = db.execute("SELECT next_at FROM pacing WHERE id=1").fetchone()[0]
                    quota_ready = oldest + 60 + 86400 if count >= self.limit else now
                    delay = max(0, next_at - now, quota_ready - now)
                    if delay <= 0:
                        minute = int(now // 60) * 60
                        db.execute("INSERT INTO buckets VALUES (?, 1) ON CONFLICT(minute) DO UPDATE SET calls=calls+1", (minute,))
                        db.execute("UPDATE pacing SET next_at=? WHERE id=1", (now + 1 / self.rate,))
                    db.commit()
                    started = self.clock()
                finally:
                    db.close()
            if delay <= 0:
                break
            if count >= self.limit and (last_notice is None or now - last_notice >= 300):
                self.notify(f"[etherscan] rolling-24h quota {count}/{self.limit}; waiting {math.ceil(quota_ready - now)}s; resume automatically")
                last_notice = now
            before = self.clock()
            if self.custom_sleep:
                self.sleep(min(60, delay))
            else:
                self.cancel_event.wait(min(60, delay))
            with self._lock:
                self.wait_seconds += max(0, self.clock() - before)
        try:
            if self.cancel_event.is_set():
                raise InterruptedError("provider_request_cancelled")
            yield
        finally:
            with self._lock:
                db = self._connect()
                try:
                    ended = max(now, self.clock())
                    end_minute = int(ended // 60) * 60
                    if end_minute != minute:
                        db.execute("UPDATE buckets SET calls=calls-1 WHERE minute=?", (minute,))
                        db.execute("INSERT INTO buckets VALUES (?, 1) ON CONFLICT(minute) DO UPDATE SET calls=calls+1", (end_minute,))
                        db.execute("DELETE FROM buckets WHERE calls=0")
                    # Slow/out-of-order HTTP responses must never move a later
                    # worker's reservation backwards or add response latency.
                    db.execute("UPDATE pacing SET next_at=MAX(next_at, ?) WHERE id=1", (started + 1 / self.rate,))
                    db.commit()
                finally:
                    db.close()
