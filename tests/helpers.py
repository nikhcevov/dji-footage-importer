"""Shared test helpers: generate small recordings and inspect streams."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

DEFAULT_NAME = "DJI_20260925170036_0438_D.MP4"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def make_clip(dest, name: str = DEFAULT_NAME, video: str = "libx264",
              audio: str = "aac", duration: float = 1.0, size: str = "320x240",
              pix_fmt: str | None = None, audio_streams: int = 1) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / name
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={duration}",
    ]
    use_audio = bool(audio_streams and audio)
    if use_audio:
        for k in range(audio_streams):
            cmd += ["-f", "lavfi", "-i",
                    f"sine=frequency={440 + 110 * k}:duration={duration}"]
    cmd += ["-map", "0:v:0", "-c:v", video]
    if pix_fmt:
        cmd += ["-pix_fmt", pix_fmt]
    if use_audio:
        for k in range(audio_streams):
            cmd += ["-map", f"{k + 1}:a:0"]
        cmd += ["-c:a", audio, "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd += [str(out)]
    run(cmd)
    return out


def sha256(path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ffprobe_json(path) -> dict:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def audio_streams(path) -> list[dict]:
    return [s for s in ffprobe_json(path).get("streams", [])
            if s.get("codec_type") == "audio"]


def video_stream(path) -> dict | None:
    for s in ffprobe_json(path).get("streams", []):
        if s.get("codec_type") == "video":
            return s
    return None


def video_packet_hashes(path) -> list[str]:
    """Hash of every compressed video packet (container-independent payload check)."""
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_packets",
         "-show_data_hash", "sha256", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    return [p.get("data_hash") for p in data.get("packets", [])]
