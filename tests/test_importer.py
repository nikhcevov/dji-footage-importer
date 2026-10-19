from __future__ import annotations

import threading
from pathlib import Path

import pytest

from dji_importer import conversion
from dji_importer import storage as storage_mod
from helpers import audio_streams, sha256, video_stream


def test_first_import_multiple_files(importer, make_clip, tmp_path):
    src = tmp_path / "src"
    files = [
        make_clip(src, name=f"DJI_2026092517000{i}_000{i}_D.MP4",
                  duration=0.4 + 0.1 * i)
        for i in range(3)
    ]
    summary = importer.scan(files)
    assert summary.new == 3 and summary.already_imported == 0

    result = importer.run(files)
    assert result.succeeded == 3 and result.failed == 0

    records = importer.db.complete_records()
    assert len(records) == 3
    for src_file in files:
        rec = next(r for r in records if r["source_filename"] == src_file.name)
        assert sha256(Path(rec["original_path"])) == sha256(src_file)
        assert Path(rec["prepared_path"]).exists()


def test_repeat_import_creates_no_duplicates(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", duration=0.4)
    importer.run([f])
    summary = importer.scan([f])
    assert summary.new == 0 and summary.already_imported == 1
    importer.run(summary.new_files)

    assert len(importer.db.complete_records()) == 1
    assert len(list(importer.store.original.rglob("*.MP4"))) == 1
    assert len(list(importer.store.root.rglob("*.mov"))) == 1


def test_only_new_files_are_imported(importer, make_clip, tmp_path):
    src = tmp_path / "src"
    first = make_clip(src, name="DJI_20260925170001_0001_D.MP4", duration=0.4)
    second = make_clip(src, name="DJI_20260925170002_0002_D.MP4", duration=0.6)
    importer.run([first, second])

    third = make_clip(src, name="DJI_20260925170003_0003_D.MP4", duration=0.8)
    summary = importer.scan([first, second, third])
    assert summary.new == 1 and summary.already_imported == 2
    importer.run(summary.new_files)

    assert len(importer.db.complete_records()) == 3


def test_lrf_is_ignored(make_clip, tmp_path):
    from dji_importer import discovery
    make_clip(tmp_path / "src", name="DJI_20260925170001_0001_D.MP4", duration=0.3)
    (tmp_path / "src" / "DJI_20260925170001_0001_D.LRF").write_bytes(b"proxy")
    files = discovery.iter_manual_files(tmp_path / "src")
    assert [p.name for p in files] == ["DJI_20260925170001_0001_D.MP4"]


def test_original_checksum_preserved(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", duration=0.4)
    importer.run([f])
    rec = importer.db.complete_records()[0]
    assert rec["sha256"] == sha256(f)
    assert sha256(Path(rec["original_path"])) == sha256(f)


def test_aac_converted_to_pcm(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", duration=0.4)
    importer.run([f])
    rec = importer.db.complete_records()[0]
    streams = audio_streams(Path(rec["prepared_path"]))
    assert streams and streams[0]["codec_name"] == "pcm_s24le"
    assert video_stream(Path(rec["prepared_path"]))["codec_name"] == "h264"


def test_recording_without_audio(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", audio_streams=0, duration=0.4)
    result = importer.run([f])
    assert result.succeeded == 1
    rec = importer.db.complete_records()[0]
    assert audio_streams(Path(rec["prepared_path"])) == []


def test_multiple_audio_streams(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", audio_streams=2, duration=0.4)
    result = importer.run([f])
    assert result.succeeded == 1
    rec = importer.db.complete_records()[0]
    streams = audio_streams(Path(rec["prepared_path"]))
    assert len(streams) == 2
    assert all(s["codec_name"] == "pcm_s24le" for s in streams)


def test_identical_filenames_remain_distinct(importer, make_clip, tmp_path):
    name = "DJI_20260925170036_0438_D.MP4"
    a = make_clip(tmp_path / "a", name=name, duration=0.4)
    b = make_clip(tmp_path / "b", name=name, duration=0.9)
    result = importer.run([a, b])
    assert result.succeeded == 2

    originals = list((importer.store.original / "2026-09-25").iterdir())
    prepared = list((importer.store.root / "2026-09-25").iterdir())
    assert len(originals) == 2 and len(prepared) == 2
    assert len({p.name for p in originals}) == 2
    assert len(importer.db.complete_records()) == 2


def test_unicode_and_space_paths(importer, make_clip, tmp_path):
    src = tmp_path / "clips ünïcode with spaces"
    f = make_clip(src, duration=0.4)
    result = importer.run([f])
    assert result.succeeded == 1
    rec = importer.db.complete_records()[0]
    assert Path(rec["original_path"]).exists()
    assert Path(rec["prepared_path"]).exists()


def test_rejects_corrupt_media(importer, tmp_path):
    bad = tmp_path / "src" / "DJI_20260925170036_0438_D.MP4"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"garbage" * 1000)
    result = importer.run([bad])
    assert result.failed == 1
    assert importer.db.complete_records() == []
    assert not list(importer.store.original.rglob("*.MP4"))


def test_progress_events(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", duration=0.5)
    events = []
    importer.run([f], progress_cb=events.append)
    operations = {e.operation for e in events}
    assert {"copying", "verifying", "preparing", "saving"} <= operations
    assert events[-1].index == 1 and events[-1].total == 1


def test_insufficient_disk_space(importer, make_clip, tmp_path, monkeypatch):
    f = make_clip(tmp_path / "src", duration=0.4)
    monkeypatch.setattr(importer.store, "free_bytes", lambda: 0)
    result = importer.run([f])
    assert result.errors and "disk space" in result.errors[0].lower()
    assert importer.db.complete_records() == []


def test_disconnected_source(importer, make_clip, tmp_path, monkeypatch):
    f = make_clip(tmp_path / "src", duration=0.4)

    def gone(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(storage_mod, "copy_and_hash", gone)
    result = importer.run([f])
    assert any("disconnected" in e.lower() for e in result.errors)
    assert importer.db.complete_records() == []


def test_cancellation_before_start(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", duration=0.4)
    event = threading.Event()
    event.set()
    result = importer.run([f], cancel_event=event)
    assert result.cancelled
    assert result.succeeded == 0
    assert importer.db.complete_records() == []


def test_recovers_from_leftover_staging(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", duration=0.4)
    (importer.store.staging / "leftover.copy.part").write_bytes(b"partial")
    result = importer.run([f])
    assert result.succeeded == 1
    assert len(list(importer.store.original.rglob("*.MP4"))) == 1


def test_recovers_from_failed_conversion(importer, make_clip, tmp_path, monkeypatch):
    f = make_clip(tmp_path / "src", duration=0.4)
    real = conversion.run_ffmpeg

    def boom(*args, **kwargs):
        raise conversion.ConversionError("boom")

    monkeypatch.setattr(conversion, "run_ffmpeg", boom)
    first = importer.run([f])
    assert first.failed == 1
    assert len(list(importer.store.original.rglob("*.MP4"))) == 1
    assert not list(importer.store.root.rglob("*.mov"))

    monkeypatch.setattr(conversion, "run_ffmpeg", real)
    second = importer.run([f])
    assert second.succeeded == 1
    # The preserved original is reused rather than duplicated.
    assert len(list(importer.store.original.rglob("*.MP4"))) == 1
    assert importer.db.complete_records()


def test_rebuild_missing_mov(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", duration=0.4)
    importer.run([f])
    rec = importer.db.complete_records()[0]
    mov = Path(rec["prepared_path"])
    mov.unlink()

    result = importer.repair_missing_movs()
    assert result.succeeded == 1
    assert Path(rec["prepared_path"]).exists()


def test_verify_detects_missing_mov(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", duration=0.4)
    importer.run([f])
    assert importer.verify() == []
    rec = importer.db.complete_records()[0]
    Path(rec["prepared_path"]).unlink()
    problems = importer.verify()
    assert any("prepared MOV missing" in p for p in problems)


def test_capture_date_directory(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", name="DJI_20260925170036_0438_D.MP4",
                  duration=0.4)
    importer.run([f])
    assert (importer.store.root / "2026-09-25").is_dir()
    assert (importer.store.original / "2026-09-25").is_dir()


def test_layout_has_no_footage_directory(importer, make_clip, tmp_path):
    f = make_clip(tmp_path / "src", name="DJI_20260925170036_0438_D.MP4",
                  duration=0.4)
    importer.run([f])
    assert (importer.store.root / "2026-09-25"
            / "DJI_20260925170036_0438_D.mov").is_file()
    assert (importer.store.original / "2026-09-25"
            / "DJI_20260925170036_0438_D.MP4").is_file()
    assert (importer.store.importer / "state.sqlite").is_file()
    assert not (importer.store.root / "footage").exists()
