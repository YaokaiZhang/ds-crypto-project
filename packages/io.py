"""Strict JSON/JSONL storage and optional normalized Parquet tables."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable


def atomic_bytes(path: str | Path, value: bytes, *, immutable=False) -> bool:
    """Publish complete bytes; immutable caches use first-writer-wins semantics."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".publish-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
            if immutable:
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    return False
            else:
                os.replace(temporary, path)
            return True
        finally:
            temporary.unlink(missing_ok=True)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gzip_content_sha256(path: str | Path) -> str:
    """Hash the original bytes, also validating the gzip stream and its CRC."""
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compress_file(source: str | Path, destination: str | Path) -> None:
    """Atomically gzip exact source bytes; never remove the source."""
    import shutil
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".compress-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            with Path(source).open("rb") as original, gzip.GzipFile(
                    filename="", mode="wb", fileobj=handle, mtime=0, compresslevel=6) as compressed:
                shutil.copyfileobj(original, compressed, length=1024 * 1024)
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


def load_json(path: str | Path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: str | Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_jsonl(path: str | Path) -> list[dict]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    rows = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{number}: record must be an object")
            rows.append(row)
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as raw:
        # Fixed headers make the same records produce the same physical digest.
        if path.suffix == ".gz":
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as handle:
                for row in rows:
                    handle.write((json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
        else:
            for row in rows:
                raw.write((json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(tmp, path)


def read_records(path: str | Path) -> list[dict]:
    if Path(path).suffix == ".parquet":
        import pyarrow.parquet as pq
        table = pq.read_table(path)
        if (table.schema.metadata or {}).get(b"chainrisk_storage") == b"strict-json-records-v1":
            return [json.loads(value) for value in table["_record_json"].to_pylist()]
        return table.to_pylist()
    return read_jsonl(path)


def write_records(path: str | Path, rows: Iterable[dict]) -> None:
    path = Path(path)
    if path.suffix == ".parquet":
        import pyarrow as pa
        import pyarrow.parquet as pq
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = list(rows)
        if any("_record_json" in row for row in rows):
            raise ValueError("_record_json is reserved for lossless Parquet storage")
        # Arrow otherwise infers columns from the first record and can discard
        # token-only fields appearing later. Keep wide analytical columns and
        # an exact JSON copy for variable nested evidence/lineage structures.
        keys = sorted({key for row in rows for key in row})
        wide = [{**{key: row.get(key) for key in keys},
                 "_record_json": json.dumps(row, ensure_ascii=False, allow_nan=False)} for row in rows]
        table = pa.Table.from_pylist(wide)
        if not rows:
            table = pa.table({"_record_json": pa.array([], type=pa.string())})
        table = table.replace_schema_metadata({**(table.schema.metadata or {}), b"chainrisk_storage": b"strict-json-records-v1"})
        pq.write_table(table, path)
    else:
        write_jsonl(path, rows)
