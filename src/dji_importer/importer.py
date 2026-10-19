"""Safe import pipeline: inspect -> preserve original -> prepare -> commit."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from logging import Logger
from pathlib import Path
from typing import Callable

from . import config, conversion, media, storage
from .database import Database


class SourceDisconnected(Exception):
    """Raised when the camera source vanishes mid-import."""


@dataclass
class ScanSummary:
    total: int = 0
    new: int = 0
    already_imported: int = 0
    new_bytes: int = 0
    new_files: list[Path] = field(default_factory=list)


@dataclass
class ImportResult:
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.failed == 0 and not self.cancelled


@dataclass
class ProgressEvent:
    index: int
    total: int
    filename: str
    operation: str  # copying | verifying | preparing | saving
    percent: int | None = None


ProgressCb = Callable[[ProgressEvent], None]


def _emit(cb: ProgressCb | None, index: int, total: int, filename: str,
          operation: str, percent: int | None) -> None:
    if cb is not None:
        cb(ProgressEvent(index, total, filename, operation, percent))


class Importer:
    def __init__(self, store: storage.Storage, db: Database,
                 audio_sample_rate: int = config.DEFAULT_AUDIO_SAMPLE_RATE):
        self.store = store
        self.db = db
        self.audio_sample_rate = audio_sample_rate
        self.profile_version = config.CONVERSION_PROFILE_VERSION

    # -- scanning ---------------------------------------------------------
    def scan(self, files: list[Path], import_now: datetime | None = None) -> ScanSummary:
        summary = ScanSummary(total=len(files))
        for f in files:
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if self.db.find_complete_by_name_size(f.name, size):
                summary.already_imported += 1
            else:
                summary.new += 1
                summary.new_bytes += size
                summary.new_files.append(f)
        return summary

    # -- importing --------------------------------------------------------
    def run(self, files: list[Path],
            cancel_event: threading.Event | None = None,
            progress_cb: ProgressCb | None = None,
            logger: Logger | None = None) -> ImportResult:
        result = ImportResult()
        if not files:
            return result
        self.store.ensure_dirs()

        total_bytes = 0
        for f in files:
            try:
                total_bytes += f.stat().st_size
            except OSError:
                pass
        try:
            self.store.check_space(total_bytes)
        except OSError as e:
            result.errors.append(str(e))
            return result

        total = len(files)
        for i, src in enumerate(files, start=1):
            if cancel_event is not None and cancel_event.is_set():
                result.cancelled = True
                break
            try:
                self._import_one(src, cancel_event, progress_cb, i, total, logger, result)
            except SourceDisconnected:
                result.errors.append("Camera disconnected. Connect it again to continue.")
                break
            except conversion.ConversionError as e:
                if cancel_event is not None and cancel_event.is_set():
                    result.cancelled = True
                    break
                result.failed += 1
                result.errors.append(f"{src.name}: {e}")
            except OSError as e:
                result.failed += 1
                result.errors.append(f"{src.name}: {e}")
        return result

    def _mark_complete_from(self, rec_id: int, rec: dict) -> None:
        self.db.mark_complete(
            rec_id, rec["original_path"], rec["prepared_path"],
            rec.get("video_codec") or "", rec.get("audio_codec") or "",
            rec.get("width") or 0, rec.get("height") or 0, rec.get("duration"),
            rec.get("pixel_format") or "", rec.get("frame_rate") or "")

    def _import_one(self, src: Path, cancel_event, progress_cb, idx: int, total: int,
                    logger: Logger | None, result: ImportResult) -> None:
        # Stage A - inspect
        info = media.probe(src)
        if not info.video_codec:
            raise conversion.ConversionError("Not a supported video recording.")
        date = media.resolve_capture_date(info, datetime.now())
        capture_ts = info.capture_ts.isoformat() if info.capture_ts else None

        # Retry path: reuse an already-preserved original for this source file.
        reusable = self.db.find_by_source(str(src), info.size)
        final_orig: Path
        rec_id: int
        if reusable is not None and Path(reusable["original_path"]).exists():
            final_orig = Path(reusable["original_path"])
            prepared = reusable.get("prepared_path")
            if reusable["status"] == "complete" and prepared and Path(prepared).exists():
                rec_id = self.db.insert_new(src.name, str(src), info.size,
                                            reusable["sha256"], capture_ts, date,
                                            self.profile_version)
                self._mark_complete_from(rec_id, reusable)
                result.skipped += 1
                return
            rec_id = self.db.insert_new(src.name, str(src), info.size,
                                        reusable["sha256"], capture_ts, date,
                                        self.profile_version)
        else:
            # Stage B - preserve original (copy + verify)
            stage_copy = self.store.staging / f"{src.name}.{os.getpid()}.copy.part"
            _emit(progress_cb, idx, total, src.name, "copying", None)
            try:
                src_sha = storage.copy_and_hash(src, stage_copy)
            except FileNotFoundError as e:
                stage_copy.unlink(missing_ok=True)
                raise SourceDisconnected() from e
            except OSError:
                stage_copy.unlink(missing_ok=True)
                raise

            if cancel_event is not None and cancel_event.is_set():
                stage_copy.unlink(missing_ok=True)
                raise conversion.ConversionError("Cancelled")
            _emit(progress_cb, idx, total, src.name, "verifying", None)
            if storage.sha256_file(stage_copy) != src_sha:
                stage_copy.unlink(missing_ok=True)
                raise conversion.ConversionError("Checksum mismatch during copy.")

            # Content-level duplicate: map this filename to the imported files.
            existing = self.db.find_complete_by_sha(src_sha)
            if (existing is not None and existing.get("prepared_path")
                    and Path(existing["prepared_path"]).exists()):
                stage_copy.unlink(missing_ok=True)
                rec_id = self.db.insert_new(src.name, str(src), info.size, src_sha,
                                            capture_ts, date, self.profile_version)
                self._mark_complete_from(rec_id, existing)
                result.skipped += 1
                return

            rec_id = self.db.insert_new(src.name, str(src), info.size, src_sha,
                                        capture_ts, date, self.profile_version)
            orig_dir, _ = self.store.date_dirs(date)
            orig_dir.mkdir(parents=True, exist_ok=True)
            final_orig = storage.unique_dest_path(orig_dir, src.name)
            storage.atomic_publish(stage_copy, final_orig)
            self.db.set_original_path(rec_id, final_orig)

        # Stage C - prepare working copy from the locally stored original
        stage_mov: Path | None = None
        try:
            _emit(progress_cb, idx, total, src.name, "preparing", 0)
            mov_name = Path(src.name).stem + ".mov"
            stage_mov = self.store.staging / f"{mov_name}.{os.getpid()}.part"
            cmd = conversion.build_ffmpeg_command(
                final_orig, stage_mov, info.audio_codec, info.has_audio,
                self.audio_sample_rate)

            def on_pct(p: int, _idx=idx, _name=src.name) -> None:
                _emit(progress_cb, _idx, total, _name, "preparing", p)

            conversion.run_ffmpeg(cmd, cancel_event, on_pct, info.duration, logger)
            conversion.verify_output(stage_mov, info)

            _emit(progress_cb, idx, total, src.name, "saving", None)
            _, prepared_dir = self.store.date_dirs(date)
            prepared_dir.mkdir(parents=True, exist_ok=True)
            final_mov = storage.unique_dest_path(prepared_dir, mov_name)
            storage.atomic_publish(stage_mov, final_mov)

            # Stage D - commit
            self.db.mark_complete(rec_id, final_orig, final_mov, info.video_codec,
                                  info.audio_codec, info.width, info.height,
                                  info.duration, info.pixel_format, info.frame_rate)
            result.succeeded += 1
        except Exception as e:
            if stage_mov is not None:
                stage_mov.unlink(missing_ok=True)
            self.db.mark_failed(rec_id, str(e))
            raise

    # -- maintenance ------------------------------------------------------
    def verify(self, logger: Logger | None = None) -> list[str]:
        problems: list[str] = []
        for rec in self.db.complete_records():
            orig = Path(rec["original_path"]) if rec["original_path"] else None
            prep = Path(rec["prepared_path"]) if rec["prepared_path"] else None
            if orig is None or not orig.exists():
                problems.append(f"{rec['source_filename']}: original missing")
                continue
            try:
                if storage.sha256_file(orig) != rec["sha256"]:
                    problems.append(f"{rec['source_filename']}: original checksum mismatch")
            except OSError:
                problems.append(f"{rec['source_filename']}: original unreadable")
            if prep is None or not prep.exists():
                problems.append(f"{rec['source_filename']}: prepared MOV missing")
        return problems

    def repair_missing_movs(self, cancel_event: threading.Event | None = None,
                            progress_cb: ProgressCb | None = None,
                            logger: Logger | None = None) -> ImportResult:
        result = ImportResult()
        records = [r for r in self.db.complete_records()
                   if not r["prepared_path"] or not Path(r["prepared_path"]).exists()]
        total = len(records)
        for i, rec in enumerate(records, start=1):
            if cancel_event is not None and cancel_event.is_set():
                result.cancelled = True
                break
            stage_mov: Path | None = None
            orig = Path(rec["original_path"]) if rec["original_path"] else None
            if orig is None or not orig.exists():
                result.failed += 1
                result.errors.append(f"{rec['source_filename']}: original missing, cannot rebuild")
                continue
            try:
                info = media.probe(orig)
                date = rec["capture_date"] or media.resolve_capture_date(info, datetime.now())
                _, prepared_dir = self.store.date_dirs(date)
                prepared_dir.mkdir(parents=True, exist_ok=True)
                mov_name = Path(rec["source_filename"]).stem + ".mov"
                stage_mov = self.store.staging / f"{mov_name}.{os.getpid()}.repair.part"
                cmd = conversion.build_ffmpeg_command(
                    orig, stage_mov, info.audio_codec, info.has_audio,
                    self.audio_sample_rate)

                def on_pct(p: int, _i=i, _n=rec["source_filename"]) -> None:
                    _emit(progress_cb, _i, total, _n, "preparing", p)

                conversion.run_ffmpeg(cmd, cancel_event, on_pct, info.duration, logger)
                conversion.verify_output(stage_mov, info)
                final_mov = storage.unique_dest_path(prepared_dir, mov_name)
                storage.atomic_publish(stage_mov, final_mov)
                self.db.set_prepared_path(rec["id"], final_mov)
                result.succeeded += 1
            except (conversion.ConversionError, OSError) as e:
                if stage_mov is not None:
                    stage_mov.unlink(missing_ok=True)
                result.failed += 1
                result.errors.append(f"{rec['source_filename']}: {e}")
        return result
