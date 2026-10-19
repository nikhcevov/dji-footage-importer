"""PySide6 single-window graphical interface."""
from __future__ import annotations

import subprocess
import sys
import threading
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import config, discovery, storage
from .database import Database
from .importer import Importer, ImportResult, ProgressEvent
from .workers import DiscoveryResult, DiscoveryWorker, ImportWorker

_OPERATION_TEXT = {
    "copying": "Copying recording…",
    "verifying": "Verifying copy…",
    "preparing": "Preparing video for DaVinci…",
    "saving": "Saving…",
}


class AppState(Enum):
    SCANNING = auto()
    NO_DEVICE = auto()
    READY = auto()
    UP_TO_DATE = auto()
    IMPORTING = auto()
    SUCCESS = auto()
    PARTIAL_FAILURE = auto()
    ERROR = auto()
    CANCELLING = auto()


def _fmt_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


class MainWindow(QWidget):
    def __init__(self, logger):
        super().__init__()
        self.logger = logger
        cfg = config.load_config()
        self.store = storage.Storage(cfg["min_free_space_gib"])
        self.store.ensure_dirs()
        self.db = Database(self.store.db_path)
        self.importer = Importer(self.store, self.db, cfg["audio_sample_rate"])

        self.state = AppState.SCANNING
        self.cancel_event = threading.Event()
        self.sources: list[discovery.Source] = []
        self.source: discovery.Source | None = None
        self.files: list[Path] = []
        self.summary = None
        self.manual_path: Path | None = None
        self.worker: ImportWorker | None = None
        self._discovery: DiscoveryWorker | None = None
        self._auto_import = False
        self._close_when_done = False
        self._tray: QSystemTrayIcon | None = None

        self._build_ui()
        self.set_state(AppState.SCANNING)
        self._start_discovery()

    # -- construction -----------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle(config.DISPLAY_NAME)
        self.setWindowIcon(QIcon.fromTheme("camera-video"))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel("DJI Footage Importer")
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.combo = QComboBox()
        self.combo.setVisible(False)
        self.combo.currentIndexChanged.connect(self._on_source_changed)
        layout.addWidget(self.combo)

        self.counts = QLabel()
        self.counts.setWordWrap(True)
        layout.addWidget(self.counts)

        self.size = QLabel()
        self.size.setWordWrap(True)
        layout.addWidget(self.size)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.op_label = QLabel()
        self.op_label.setVisible(False)
        layout.addWidget(self.op_label)

        self.file_label = QLabel()
        self.file_label.setVisible(False)
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self.error_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.error_label)

        self.import_btn = QPushButton("Import")
        self.import_btn.clicked.connect(self._start_import)
        layout.addWidget(self.import_btn)

        row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh)
        self.try_again_btn = QPushButton("Try Again")
        self.try_again_btn.clicked.connect(self._try_again)
        self.manual_btn = QPushButton("Choose folder manually")
        self.manual_btn.clicked.connect(self._choose_folder)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        self.retry_btn = QPushButton("Retry failed")
        self.retry_btn.clicked.connect(self._retry_failed)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.try_again_btn)
        row.addWidget(self.manual_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.retry_btn)
        layout.addLayout(row)

    # -- state ------------------------------------------------------------
    def set_state(self, state: AppState) -> None:
        self.state = state
        busy = state in (AppState.SCANNING, AppState.IMPORTING, AppState.CANCELLING)
        self.refresh_btn.setEnabled(not busy)
        self.manual_btn.setEnabled(not busy and state is not AppState.SUCCESS)
        self.cancel_btn.setVisible(state is AppState.IMPORTING)
        self.retry_btn.setVisible(state is AppState.PARTIAL_FAILURE)
        self.progress.setVisible(state in (AppState.IMPORTING, AppState.CANCELLING))
        self.size.setVisible(state not in (AppState.IMPORTING, AppState.CANCELLING))
        self.op_label.setVisible(state in (AppState.IMPORTING, AppState.CANCELLING))
        self.file_label.setVisible(state in (AppState.IMPORTING, AppState.CANCELLING))
        self.import_btn.setVisible(state in (AppState.READY, AppState.UP_TO_DATE))
        self.import_btn.setEnabled(
            state is AppState.READY and bool(self.summary and self.summary.new))
        self.try_again_btn.setVisible(state is AppState.NO_DEVICE)
        self.combo.setVisible(
            len(self.sources) > 1 and state in (AppState.READY, AppState.UP_TO_DATE))

    # -- discovery --------------------------------------------------------
    def _start_discovery(self, mount_point: Path | None = None) -> None:
        self.status.setText("Looking for a DJI camera…")
        self.counts.setText("")
        self.size.setText("")
        self.error_label.setVisible(False)
        self.set_state(AppState.SCANNING)
        self._discovery = DiscoveryWorker(
            self.importer, self.manual_path, mount_point, self)
        self._discovery.finished.connect(self._on_discovery_finished)
        self._discovery.start()

    def _on_discovery_finished(self, result: DiscoveryResult) -> None:
        self._discovery = None
        if result.error:
            self.status.setText("Could not read the camera.")
            self.error_label.setText(result.error)
            self.error_label.setVisible(True)
            self.set_state(AppState.ERROR)
            return

        self.sources = result.sources
        self._populate_combo()
        if result.source is None:
            self._show_no_device()
            return

        self.source = result.source
        self.files = result.files
        self.summary = result.summary
        self._show_ready()

        if self._auto_import and self.summary and self.summary.new > 0:
            self._auto_import = False
            self._start_import()
        else:
            self._auto_import = False

    def _populate_combo(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        selected = self.source.mount_point if self.source else None
        for src in self.sources:
            self.combo.addItem(src.display_name, str(src.mount_point))
        if selected is not None:
            idx = self.combo.findData(str(selected))
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)

    def _on_source_changed(self, index: int) -> None:
        if index < 0:
            return
        data = self.combo.itemData(index)
        if data:
            self._start_discovery(Path(data))

    def _show_no_device(self) -> None:
        self.status.setText(
            "No DJI camera detected\n\n"
            "Connect your camera using USB-C and enable file transfer.")
        self.counts.setText("")
        self.size.setText("")
        self.error_label.setVisible(False)
        self.set_state(AppState.NO_DEVICE)

    def _show_ready(self) -> None:
        s = self.summary
        connected = "✓ DJI camera connected" if self.manual_path is None else "✓ Source selected"
        self.status.setText(connected)
        self.error_label.setVisible(False)
        if s.new > 0:
            self.counts.setText(
                f"{s.total} recordings found\n"
                f"{s.new} new recordings\n"
                f"{s.already_imported} already imported")
            self.size.setText(f"New footage: {_fmt_bytes(s.new_bytes)}")
            noun = "video" if s.new == 1 else "videos"
            self.import_btn.setText(f"Import {s.new} {noun}")
            self.set_state(AppState.READY)
        else:
            self.counts.setText(
                f"{s.total} recordings found\nAll recordings are already imported.")
            self.size.setText("")
            self.set_state(AppState.UP_TO_DATE)

    # -- actions ----------------------------------------------------------
    def _refresh(self) -> None:
        self._start_discovery()

    def _try_again(self) -> None:
        self.manual_path = None
        self._start_discovery()

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose DJI footage folder", str(Path.home()))
        if not path:
            return
        chosen = Path(path)
        if not discovery.iter_manual_files(chosen):
            QMessageBox.warning(
                self, config.DISPLAY_NAME,
                "No MP4 recordings were found in that folder.")
            return
        self.manual_path = chosen
        self._start_discovery()

    def _start_import(self) -> None:
        if not self.summary or not self.summary.new_files:
            return
        self.cancel_event = threading.Event()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.op_label.setText("Starting…")
        self.file_label.setText("")
        self.status.setText("Importing recordings…")
        self.set_state(AppState.IMPORTING)
        self.worker = ImportWorker(
            self.importer, self.summary.new_files, self.cancel_event, self.logger, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_import_finished)
        self.worker.failed.connect(self._on_worker_error)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _on_progress(self, ev: ProgressEvent) -> None:
        fraction = 0.0
        if ev.operation == "preparing" and ev.percent is not None:
            fraction = ev.percent / 100.0
        total = max(ev.total, 1)
        overall = int((ev.index - 1 + fraction) / total * 100)
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, overall)))
        self.op_label.setText(_OPERATION_TEXT.get(ev.operation, "Working…"))
        self.file_label.setText(ev.filename)
        self.counts.setText(f"{ev.index} of {ev.total} recordings")

    def _on_import_finished(self, result: ImportResult) -> None:
        self.worker = None
        if self._close_when_done:
            self.close()
            return
        if result.cancelled:
            self.status.setText("Import cancelled.")
            self._start_discovery()
            return
        if result.failed:
            self._show_partial_failure(result)
            return
        if result.succeeded == 0:
            self.status.setText("All recordings are already imported.")
            self.counts.setText("")
            self.size.setText("")
            self.set_state(AppState.UP_TO_DATE)
            return
        noun = "video" if result.succeeded == 1 else "videos"
        self.status.setText(
            f"Import completed. {result.succeeded} new {noun} ready for editing.")
        self.counts.setText("")
        self.size.setText("")
        self.set_state(AppState.SUCCESS)
        self._notify("Import complete",
                     f"{result.succeeded} new {noun} are ready for editing.")
        QTimer.singleShot(3000, self.close)

    def _show_partial_failure(self, result: ImportResult) -> None:
        self.status.setText("Some recordings could not be imported.")
        self.counts.setText(
            f"Imported {result.succeeded}, failed {result.failed}.")
        visible = result.errors[:8]
        if len(result.errors) > len(visible):
            visible.append(f"…and {len(result.errors) - len(visible)} more.")
        self.error_label.setText("\n".join(visible))
        self.error_label.setVisible(True)
        self.set_state(AppState.PARTIAL_FAILURE)

    def _on_worker_error(self, message: str) -> None:
        self.worker = None
        self.status.setText("The import could not be completed.")
        self.error_label.setText(message)
        self.error_label.setVisible(True)
        self.set_state(AppState.ERROR)

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.status.setText("Cancelling…")
        self.cancel_btn.setEnabled(False)
        self.set_state(AppState.CANCELLING)

    def _retry_failed(self) -> None:
        self._auto_import = True
        self._start_discovery()

    # -- notifications ----------------------------------------------------
    def _notify(self, title: str, message: str) -> None:
        try:
            if self._tray is None:
                self._tray = QSystemTrayIcon(QIcon.fromTheme("camera-video"), self)
                self._tray.show()
            self._tray.showMessage(title, message, QSystemTrayIcon.Information, 5000)
            return
        except Exception:  # noqa: BLE001 - fall through to notify-send
            pass
        try:
            subprocess.Popen(
                ["notify-send", "-a", config.DISPLAY_NAME, title, message])
        except OSError:
            pass

    # -- lifecycle --------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.worker is not None and self.worker.isRunning():
            self.cancel_event.set()
            self._close_when_done = True
            self.status.setText("Cancelling…")
            self.set_state(AppState.CANCELLING)
            event.ignore()
            return
        try:
            self.db.close()
        finally:
            event.accept()


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(config.DISPLAY_NAME)
    app.setDesktopFileName(config.APP_NAME)
    app.setWindowIcon(QIcon.fromTheme("camera-video"))
    logger = config.setup_logging()
    window = MainWindow(logger)
    window.show()
    return app.exec()
