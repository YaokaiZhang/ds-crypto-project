"""Single-writer stage execution with durable, credential-free status reports."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from pathlib import Path
import sys
import uuid

from packages.io import save_json


@contextmanager
def snapshot_lock(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / ".pipeline.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("snapshot_is_running_in_another_process") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_stage(out, stage, operation, *, dry_run=False):
    if dry_run:
        return operation()
    with snapshot_lock(out):
        now = datetime.now(timezone.utc)
        record = {"stage": stage, "started_at": now.isoformat(), "status": "running"}
        path = Path(out) / "runs" / f"{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}.json"

        def persist():
            save_json(path, record)
            save_json(Path(out) / "status.json", record)

        persist()
        print(f"[{stage}] started; report: {path}", file=sys.stderr)
        try:
            result = operation()
            record["status"] = result.get("status", "complete")
            record["result"] = result
            return result
        except BaseException as error:
            record["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "error"
            # Exceptions from providers can contain credentials. The CLI owns
            # the user-facing error; durable logs store only the exception type.
            record["error_type"] = type(error).__name__
            raise
        finally:
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            persist()
            print(f"[{stage}] {record['status']}", file=sys.stderr)
