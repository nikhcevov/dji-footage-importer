"""SQLite persistence for import state, with single-writer file locking."""
from __future__ import annotations

import fcntl
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_filename TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    capture_ts TEXT,
    capture_date TEXT NOT NULL,
    original_path TEXT,
    prepared_path TEXT,
    video_codec TEXT,
    audio_codec TEXT,
    width INTEGER,
    height INTEGER,
    duration REAL,
    pixel_format TEXT,
    frame_rate TEXT,
    profile_version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    last_error TEXT,
    first_seen_at TEXT NOT NULL,
    imported_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_name_size ON recordings(source_filename, source_size);
CREATE INDEX IF NOT EXISTS idx_sha256 ON recordings(sha256);
CREATE INDEX IF NOT EXISTS idx_status ON recordings(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thread-safe connection used by worker threads one operation at a time."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _one(self, sql: str, params: tuple) -> dict | None:
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def find_complete_by_name_size(self, filename: str, size: int) -> dict | None:
        return self._one(
            "SELECT * FROM recordings WHERE source_filename=? AND source_size=? "
            "AND status='complete'", (filename, size))

    def find_by_source(self, path: str, size: int) -> dict | None:
        """Latest record for a source path/size that has a preserved original."""
        return self._one(
            "SELECT * FROM recordings WHERE source_path=? AND source_size=? "
            "AND original_path IS NOT NULL ORDER BY id DESC LIMIT 1", (path, size))

    def find_complete_by_sha(self, sha256: str) -> dict | None:
        return self._one(
            "SELECT * FROM recordings WHERE sha256=? AND status='complete'", (sha256,))

    def insert_new(self, filename: str, path: str, size: int, sha256: str,
                   capture_ts: str | None, capture_date: str, profile_version: int) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO recordings(source_filename, source_path, source_size, sha256, "
                "capture_ts, capture_date, profile_version, status, first_seen_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (filename, path, size, sha256, capture_ts, capture_date,
                 profile_version, "new", _now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def mark_complete(self, rec_id: int, original_path, prepared_path,
                      video_codec: str, audio_codec: str, width: int, height: int,
                      duration: float | None, pixel_format: str, frame_rate: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE recordings SET status='complete', original_path=?, prepared_path=?, "
                "video_codec=?, audio_codec=?, width=?, height=?, duration=?, pixel_format=?, "
                "frame_rate=?, imported_at=?, last_error=NULL WHERE id=?",
                (str(original_path), str(prepared_path), video_codec, audio_codec,
                 width, height, duration, pixel_format, frame_rate, _now(), rec_id),
            )
            self.conn.commit()

    def mark_failed(self, rec_id: int, error: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE recordings SET status='failed', last_error=? WHERE id=?",
                (error, rec_id))
            self.conn.commit()

    def set_original_path(self, rec_id: int, original_path: Path) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE recordings SET original_path=? WHERE id=?",
                (str(original_path), rec_id))
            self.conn.commit()

    def set_prepared_path(self, rec_id: int, prepared_path: Path) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE recordings SET prepared_path=? WHERE id=?",
                (str(prepared_path), rec_id))
            self.conn.commit()

    def all_records(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM recordings ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def complete_records(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM recordings WHERE status='complete' ORDER BY id").fetchall()
        return [dict(r) for r in rows]


class ImportLock:
    """Non-blocking exclusive lock to prevent concurrent import processes."""

    def __init__(self, path: Path):
        self.path = path
        self.fd = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = self.path.open("w")
        try:
            fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def release(self) -> None:
        if self.fd is not None:
            try:
                fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            self.fd.close()
            self.fd = None

    def __enter__(self) -> "ImportLock":
        if not self.acquire():
            raise RuntimeError("Another import is already running.")
        return self

    def __exit__(self, *exc) -> None:
        self.release()
