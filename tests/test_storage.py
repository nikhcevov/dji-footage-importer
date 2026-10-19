from __future__ import annotations

import os

import pytest

from dji_importer import storage
from dji_importer.database import Database, ImportLock
from helpers import sha256


def test_copy_and_hash_matches_source(tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(os.urandom(4096))
    dst = tmp_path / "b.bin"
    digest = storage.copy_and_hash(src, dst)
    assert digest == sha256(src)
    assert sha256(dst) == digest


def test_sha256_file(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello")
    assert storage.sha256_file(p) == sha256(p)


def test_atomic_publish_never_overwrites(tmp_path):
    tmp = tmp_path / "tmp"
    tmp.write_bytes(b"new")
    final = tmp_path / "final"
    final.write_bytes(b"old")
    assert storage.atomic_publish(tmp, final) == final
    assert final.read_bytes() == b"old"
    assert tmp.exists()


def test_unique_dest_path_suffix(tmp_path):
    (tmp_path / "DJI_1.MP4").write_bytes(b"x")
    assert storage.unique_dest_path(tmp_path, "DJI_1.MP4").name == "DJI_1_1.MP4"


def test_check_space_raises(monkeypatch, tmp_path):
    store = storage.Storage(1)
    store.root = tmp_path
    monkeypatch.setattr(store, "free_bytes", lambda: 0)
    with pytest.raises(OSError, match="disk space"):
        store.check_space(1024)


def test_database_roundtrip(tmp_path):
    db = Database(tmp_path / "state.sqlite")
    rec = db.insert_new("a.MP4", "/src/a.MP4", 10, "abc", None, "2026-01-01", 1)
    assert db.find_complete_by_name_size("a.MP4", 10) is None
    db.mark_complete(rec, tmp_path / "o.MP4", tmp_path / "p.mov",
                     "h264", "aac", 320, 240, 1.0, "yuv420p", "30/1")
    found = db.find_complete_by_name_size("a.MP4", 10)
    assert found and found["status"] == "complete"
    assert db.find_by_source("/src/a.MP4", 10)["id"] == rec
    db.close()


def test_import_lock_is_exclusive(tmp_path):
    path = tmp_path / "state.lock"
    first = ImportLock(path)
    second = ImportLock(path)
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_destination_root_is_library_dji(xdg):
    from dji_importer import config
    assert config.dest_root() == xdg / "Videos" / "Library" / "DJI"
    assert config.original_dir() == config.dest_root() / ".original"
    assert config.importer_dir() == config.dest_root() / ".importer"


def test_storage_creates_no_footage_directory(xdg):
    store = storage.Storage(0)
    store.ensure_dirs()
    assert (store.root / ".importer" / "staging").is_dir()
    assert not (store.root / "footage").exists()
