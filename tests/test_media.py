from __future__ import annotations

from datetime import datetime

from dji_importer import media


def test_filename_timestamp():
    assert media.filename_timestamp("DJI_20260925170036_0438_D.MP4") == \
        datetime(2026, 9, 25, 17, 0, 36)


def test_filename_timestamp_absent():
    assert media.filename_timestamp("random.mp4") is None


def test_supported_extension_is_case_insensitive():
    assert media.is_supported("clip.MP4")
    assert media.is_supported("clip.mp4")
    assert not media.is_supported("clip.LRF")
    assert not media.is_supported("clip.mov")


def test_probe_reads_streams(make_clip, tmp_path):
    clip = make_clip(tmp_path / "src", duration=0.5)
    info = media.probe(clip)
    assert info.video_codec == "h264"
    assert info.width == 320 and info.height == 240
    assert info.has_audio
    assert info.audio_codec == "aac"
    assert info.duration and info.duration > 0
    assert info.capture_ts == datetime(2026, 9, 25, 17, 0, 36)


def test_probe_rejects_non_media(tmp_path):
    bad = tmp_path / "DJI_20260925170036_0438_D.MP4"
    bad.write_bytes(b"not a video" * 50)
    info = media.probe(bad)
    assert info.video_codec == ""
    assert not info.has_audio


def test_capture_date_uses_embedded_date_verbatim(make_clip, tmp_path):
    """A clock-reset (year 2000) filename date is used as-is, per spec decision."""
    clip = make_clip(tmp_path / "src", name="DJI_20000531192426_0005_D.MP4",
                     duration=0.4)
    info = media.probe(clip)
    assert media.resolve_capture_date(info, datetime(2026, 10, 19)) == "2000-05-31"
