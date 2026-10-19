"""Media inspection via FFprobe and DJI-specific filename handling."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SUPPORTED_EXT = ".mp4"
_FILENAME_TS = re.compile(r"DJI_(\d{14})_")
_FFPROBE_TIMEOUT = 120


@dataclass
class MediaInfo:
    path: Path
    size: int = 0
    duration: float | None = None
    width: int = 0
    height: int = 0
    video_codec: str = ""
    pixel_format: str = ""
    frame_rate: str = ""
    audio_codec: str = ""
    has_audio: bool = False
    rotation: int = 0
    capture_ts: datetime | None = None

    @property
    def capture_date(self) -> str | None:
        return self.capture_ts.strftime("%Y-%m-%d") if self.capture_ts else None


def is_supported(filename: str) -> bool:
    """A supported recording is an MP4 (case-insensitive); LRF proxies are excluded."""
    return filename.lower().endswith(SUPPORTED_EXT)


def filename_timestamp(name: str) -> datetime | None:
    """Extract the camera-local capture timestamp embedded in a DJI filename."""
    m = _FILENAME_TS.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _metadata_timestamp(fmt: dict) -> datetime | None:
    tags = fmt.get("tags", {})
    raw = tags.get("creation_time")
    if not raw:
        return None
    raw = raw.strip().replace("Z", "+00:00")
    for pattern in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    return None


def _extract_rotation(stream: dict, current: int) -> int:
    tags = stream.get("tags", {})
    if "rotate" in tags:
        try:
            return int(float(tags["rotate"])) % 360
        except (ValueError, TypeError):
            pass
    for side in stream.get("side_data_list", []):
        if side.get("rotation") is not None:
            try:
                return int(side["rotation"]) % 360
            except (ValueError, TypeError):
                pass
    return current


def probe(path: Path) -> MediaInfo:
    """Run FFprobe and return a MediaInfo. Never raises on unreadable input."""
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    info = MediaInfo(path=path, size=size)
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            timeout=_FFPROBE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return info
    if out.returncode != 0:
        return info
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return info

    rotation = 0
    for stream in data.get("streams", []):
        ctype = stream.get("codec_type")
        codec = stream.get("codec_name", "")
        # Skip the embedded MJPEG thumbnail/cover when selecting the real video.
        if ctype == "video" and codec != "mjpeg" and not info.video_codec:
            info.video_codec = codec
            info.width = int(stream.get("width", 0) or 0)
            info.height = int(stream.get("height", 0) or 0)
            info.pixel_format = stream.get("pix_fmt", "")
            info.frame_rate = stream.get("r_frame_rate", stream.get("avg_frame_rate", ""))
        elif ctype == "audio" and not info.audio_codec:
            info.audio_codec = codec
            info.has_audio = True
        rotation = _extract_rotation(stream, rotation)

    fmt = data.get("format", {})
    try:
        info.duration = float(fmt["duration"])
    except (TypeError, ValueError, KeyError):
        info.duration = None
    info.rotation = rotation

    # Capture timestamp: the DJI filename is the most reliable, camera-local source.
    info.capture_ts = filename_timestamp(info.path.name)
    if info.capture_ts is None:
        info.capture_ts = _metadata_timestamp(fmt)
    return info


def resolve_capture_date(info: MediaInfo, import_now: datetime) -> str:
    """Return the YYYY-MM-DD grouping key using the spec's fallback order.

    Order: media metadata (filename or creation_time), filesystem mtime when
    meaningful, then import date. Embedded dates are used verbatim (no
    plausibility rewrite).
    """
    if info.capture_ts is not None:
        return info.capture_ts.strftime("%Y-%m-%d")
    try:
        mtime = datetime.fromtimestamp(info.path.stat().st_mtime)
        if mtime.year >= 2000:
            return mtime.strftime("%Y-%m-%d")
    except OSError:
        pass
    return import_now.strftime("%Y-%m-%d")
