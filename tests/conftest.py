from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(TESTS))

from helpers import make_clip as _make_clip  # noqa: E402


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    """Point HOME/XDG dirs at a temporary tree so tests never touch real data."""
    home = tmp_path / "home"
    (home / "Videos").mkdir(parents=True)
    (home / ".config").mkdir(parents=True)
    (home / ".local" / "state").mkdir(parents=True)
    cfg_dir = home / ".config" / "dji-footage-importer"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text('{"min_free_space_gib": 0}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    return home


@pytest.fixture
def make_clip():
    return _make_clip


@pytest.fixture
def importer(xdg):
    from dji_importer import config, storage
    from dji_importer.database import Database
    from dji_importer.importer import Importer

    store = storage.Storage(config.load_config()["min_free_space_gib"])
    store.ensure_dirs()
    db = Database(store.db_path)
    instance = Importer(store, db)
    yield instance
    db.close()
