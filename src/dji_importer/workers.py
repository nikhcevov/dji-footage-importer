"""Qt worker threads: discovery/scanning and importing off the GUI thread."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from logging import Logger
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import discovery
from .importer import Importer, ImportResult, ProgressEvent, ScanSummary


@dataclass
class DiscoveryResult:
    sources: list[discovery.Source]
    source: discovery.Source | None
    files: list[Path]
    summary: ScanSummary | None
    error: str | None = None


class DiscoveryWorker(QThread):
    finished = Signal(object)  # DiscoveryResult

    def __init__(self, importer: Importer, manual_path: Path | None = None,
                 mount_point: Path | None = None, parent=None):
        super().__init__(parent)
        self._importer = importer
        self._manual = manual_path
        self._mount = mount_point

    def run(self) -> None:
        try:
            if self._manual is not None:
                source = discovery.Source(
                    mount_point=self._manual, label=self._manual.name, dcim_dir=self._manual)
                sources = [source]
                files = discovery.iter_manual_files(self._manual)
            else:
                sources = discovery.find_sources()
                chosen = None
                if self._mount is not None:
                    chosen = next(
                        (s for s in sources if s.mount_point == self._mount), None)
                if chosen is None and sources:
                    chosen = sources[0]
                source = chosen
                files = discovery.iter_supported_files(chosen.dcim_dir) if chosen else []
            summary = self._importer.scan(files) if files else ScanSummary()
            self.finished.emit(DiscoveryResult(sources, source, files, summary, None))
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            self.finished.emit(DiscoveryResult([], None, [], None, str(e)))


class ImportWorker(QThread):
    progress = Signal(object)  # ProgressEvent
    finished = Signal(object)  # ImportResult
    failed = Signal(str)

    def __init__(self, importer: Importer, files: list[Path],
                 cancel_event: threading.Event, logger: Logger | None = None, parent=None):
        super().__init__(parent)
        self._importer = importer
        self._files = files
        self._cancel = cancel_event
        self._logger = logger

    def run(self) -> None:
        try:
            result = self._importer.run(self._files, self._cancel,
                                        self.progress.emit, self._logger)
            self.finished.emit(result)
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            self.failed.emit(str(e))
