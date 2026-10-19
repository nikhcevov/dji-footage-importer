from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("PySide6")


def test_import_worker_runs_off_gui_thread(xdg, make_clip, tmp_path):
    from PySide6.QtCore import QCoreApplication

    from dji_importer import config, storage
    from dji_importer.database import Database
    from dji_importer.importer import Importer
    from dji_importer.workers import ImportWorker

    app = QCoreApplication.instance() or QCoreApplication([])
    store = storage.Storage(config.load_config()["min_free_space_gib"])
    store.ensure_dirs()
    db = Database(store.db_path)
    importer = Importer(store, db)

    clip = make_clip(tmp_path / "src", duration=0.5)
    events = []
    results = []
    worker = ImportWorker(importer, [clip], threading.Event())
    worker.progress.connect(events.append)
    worker.finished.connect(results.append)

    # The worker must not block the calling (GUI) thread.
    worker.start()
    ticks = 0
    deadline = time.time() + 60
    while worker.isRunning() and time.time() < deadline:
        app.processEvents()
        ticks += 1
        time.sleep(0.01)
    worker.wait(5000)
    app.processEvents()

    assert ticks > 1
    assert results and results[0].succeeded == 1
    assert events
    db.close()
