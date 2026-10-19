"""Destination storage layout, atomic publishing, copying and hashing."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from . import config

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def copy_and_hash(src: Path, dst: Path) -> str:
    """Copy src -> dst while hashing the source; returns the source SHA-256."""
    h = hashlib.sha256()
    with src.open("rb") as fin, dst.open("wb") as fout:
        while True:
            block = fin.read(_CHUNK)
            if not block:
                break
            h.update(block)
            fout.write(block)
        fout.flush()
        os.fsync(fout.fileno())
    return h.hexdigest()


def atomic_publish(tmp: Path, final: Path) -> Path:
    """Atomically move tmp -> final (same filesystem), never overwriting."""
    if final.exists():
        return final
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, final)
    return final


def unique_dest_path(directory: Path, filename: str) -> Path:
    """Return a collision-resistant path, appending a stable suffix when needed."""
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = directory / filename
    n = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{n}{suffix}"
        n += 1
    return candidate


class Storage:
    def __init__(self, min_free_space_gib: int = config.DEFAULT_MIN_FREE_SPACE_GIB):
        self.min_free_space_gib = min_free_space_gib
        self.root = config.dest_root()
        self.footage = config.footage_dir()
        self.original = config.original_dir()
        self.importer = config.importer_dir()
        self.staging = config.staging_dir()
        self.db_path = config.state_db_path()

    def ensure_dirs(self) -> None:
        for d in (self.footage, self.original, self.importer, self.staging):
            d.mkdir(parents=True, exist_ok=True)

    def date_dirs(self, date: str) -> tuple[Path, Path]:
        return self.original / date, self.footage / date

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.root).free

    def reserve_bytes(self) -> int:
        return self.min_free_space_gib * 1024 ** 3

    def check_space(self, source_bytes: int) -> None:
        """Raise OSError when free space cannot hold originals + prepared + reserve."""
        required = source_bytes * 2 + self.reserve_bytes()
        if self.free_bytes() < required:
            raise OSError("Not enough disk space to import these recordings.")
