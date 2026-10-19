"""FFmpeg conversion: remux video (stream copy) and convert audio to PCM."""
from __future__ import annotations

import subprocess
import tempfile
import threading
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Callable

from . import media


class ConversionError(Exception):
    pass


@dataclass
class ConversionResult:
    output_path: Path
    duration: float | None = None
    video_codec: str = ""
    audio_codec: str = ""
    has_audio: bool = False


def audio_is_pcm(codec: str) -> bool:
    return codec.startswith("pcm_")


def build_ffmpeg_command(src: Path, dst: Path, audio_codec: str | None,
                         has_audio: bool, sample_rate: int) -> list[str]:
    """Build a stream-copy remux command with PCM audio per the conversion profile."""
    cmd = ["ffmpeg", "-hide_banner", "-y", "-i", str(src), "-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", "0:a"]
        if audio_codec and audio_is_pcm(audio_codec):
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "pcm_s24le", "-ar", str(sample_rate)]
    cmd += [
        "-c:v", "copy",
        "-map_metadata", "0",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        "-loglevel", "error",
        "-f", "mov",
        str(dst),
    ]
    return cmd


def _parse_progress_time(line: str) -> float | None:
    """Return seconds elapsed from an FFmpeg -progress line, or None."""
    for key in ("out_time_us=", "out_time_ms="):
        if line.startswith(key):
            try:
                micros = int(line.split("=", 1)[1])
            except ValueError:
                return None
            return micros / (1_000_000 if key == "out_time_us=" else 1_000)
    if line.startswith("out_time="):
        raw = line.split("=", 1)[1]
        if raw == "N/A":
            return None
        try:
            h, m, rest = raw.split(":")
            s = float(rest)
            return int(h) * 3600 + int(m) * 60 + s
        except ValueError:
            return None
    return None


def run_ffmpeg(cmd: list[str], cancel_event: threading.Event | None = None,
               progress_cb: Callable[[int], None] | None = None,
               duration: float | None = None, logger: Logger | None = None) -> None:
    """Run FFmpeg, streaming progress and supporting cancellation. Raises ConversionError."""
    err_f = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err_f)
    except OSError as e:
        raise ConversionError("FFmpeg could not be started.") from e

    last_pct = -1
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        if cancel_event is not None and cancel_event.is_set():
            _terminate(proc)
            raise ConversionError("Cancelled")
        elapsed = _parse_progress_time(line)
        if elapsed is not None and progress_cb is not None:
            if duration and duration > 0:
                pct = min(100, int(elapsed / duration * 100))
                if pct != last_pct:
                    progress_cb(pct)
                    last_pct = pct
            else:
                progress_cb(0)  # indeterminate: report activity, not a percent

    proc.wait()
    err_f.seek(0)
    stderr = err_f.read().decode("utf-8", errors="replace")
    if logger is not None:
        logger.info("ffmpeg cmd: %s", " ".join(cmd))
        if stderr.strip():
            logger.warning("ffmpeg stderr: %s", stderr.strip()[-2000:])
    if proc.returncode != 0:
        raise ConversionError("FFmpeg failed to prepare this recording.")


def _terminate(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def verify_output(dst: Path, src_info: media.MediaInfo) -> None:
    """Validate the prepared file's streams and duration against the source."""
    out = media.probe(dst)
    if not out.video_codec:
        raise ConversionError("Prepared file has no video stream.")
    if out.video_codec != src_info.video_codec:
        raise ConversionError("Prepared video codec does not match the original.")
    if src_info.has_audio and not out.has_audio:
        raise ConversionError("Prepared file is missing its audio stream.")
    if (out.duration is not None and src_info.duration is not None
            and abs(out.duration - src_info.duration) > 1.0):
        raise ConversionError("Prepared file duration does not match the original.")
