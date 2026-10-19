from __future__ import annotations

import pytest

from dji_importer import conversion, media
from helpers import audio_streams, ffprobe_json, video_packet_hashes, video_stream


def _convert(src, dst):
    info = media.probe(src)
    cmd = conversion.build_ffmpeg_command(
        src, dst, info.audio_codec, info.has_audio, 48000)
    conversion.run_ffmpeg(cmd, None, None, info.duration)
    conversion.verify_output(dst, info)
    return info


def test_command_uses_stream_copy_and_pcm():
    cmd = conversion.build_ffmpeg_command(
        __import__("pathlib").Path("in.mp4"), __import__("pathlib").Path("out.mov"),
        "aac", True, 48000)
    joined = " ".join(cmd)
    assert "-c:v copy" in joined
    assert "-map 0:v:0" in joined
    assert "pcm_s24le" in joined
    assert "-ar 48000" in joined
    assert "-map 0:a" in joined


def test_command_preserves_pcm_without_reencoding():
    from pathlib import Path
    cmd = conversion.build_ffmpeg_command(Path("in.mp4"), Path("out.mov"),
                                          "pcm_s16le", True, 48000)
    assert "-c:a copy" in " ".join(cmd)
    assert "pcm_s24le" not in " ".join(cmd)


def test_command_without_audio():
    from pathlib import Path
    cmd = conversion.build_ffmpeg_command(Path("in.mp4"), Path("out.mov"),
                                          "", False, 48000)
    joined = " ".join(cmd)
    assert "-map 0:a" not in joined
    assert "-c:v copy" in joined


def test_aac_converted_to_pcm(make_clip, tmp_path):
    src = make_clip(tmp_path / "src", duration=0.7)
    dst = tmp_path / "out.mov"
    _convert(src, dst)
    streams = audio_streams(dst)
    assert streams
    assert streams[0]["codec_name"] == "pcm_s24le"
    assert int(streams[0]["sample_rate"]) == 48000
    assert int(streams[0]["channels"]) == 2


def test_video_payload_preserved_h264(make_clip, tmp_path):
    src = make_clip(tmp_path / "src", duration=0.7)
    dst = tmp_path / "out.mov"
    _convert(src, dst)
    assert video_stream(dst)["codec_name"] == "h264"
    assert video_packet_hashes(src) == video_packet_hashes(dst)


def test_video_payload_preserved_h265(make_clip, tmp_path):
    pytest.importorskip("shutil")
    try:
        src = make_clip(tmp_path / "src", video="libx265",
                        pix_fmt="yuv420p10le", duration=0.5)
    except Exception:
        pytest.skip("libx265 not available")
    dst = tmp_path / "out.mov"
    _convert(src, dst)
    assert video_stream(dst)["codec_name"] == "hevc"
    assert video_stream(dst)["pix_fmt"] == "yuv420p10le"
    assert video_packet_hashes(src) == video_packet_hashes(dst)


def test_file_without_audio(make_clip, tmp_path):
    src = make_clip(tmp_path / "src", audio_streams=0, duration=0.5)
    dst = tmp_path / "out.mov"
    _convert(src, dst)
    assert audio_streams(dst) == []


def test_multiple_audio_streams(make_clip, tmp_path):
    src = make_clip(tmp_path / "src", audio_streams=2, duration=0.5)
    dst = tmp_path / "out.mov"
    _convert(src, dst)
    streams = audio_streams(dst)
    assert len(streams) == 2
    assert all(s["codec_name"] == "pcm_s24le" for s in streams)


def test_verify_rejects_missing_audio(make_clip, tmp_path):
    src = make_clip(tmp_path / "src", duration=0.5)
    dst = tmp_path / "out.mov"
    # Produce a video-only file, then verify against the audio-bearing source.
    info = media.probe(src)
    cmd = conversion.build_ffmpeg_command(src, dst, "", False, 48000)
    conversion.run_ffmpeg(cmd, None, None, info.duration)
    with pytest.raises(conversion.ConversionError):
        conversion.verify_output(dst, info)
