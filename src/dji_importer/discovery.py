"""Discover a connected DJI camera via mounted filesystems (UDisks/GIO mounts)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import media


@dataclass
class Source:
    mount_point: Path
    label: str = ""
    dcim_dir: Path | None = None

    @property
    def display_name(self) -> str:
        return self.label or self.mount_point.name


_MOUNT_ROOTS = (
    Path("/run/media"),  # UDisks: /run/media/<user>/<label>
    Path("/media"),
    Path("/mnt"),
)


def _mount_candidates() -> list[Path]:
    candidates: list[Path] = []
    for root in _MOUNT_ROOTS:
        if not root.is_dir():
            continue
        for sub in root.iterdir():
            if sub.is_dir() and sub.name not in (".", ".."):
                candidates.append(sub)
                # UDisks mounts live at /run/media/<user>/<label>, so descend
                # one level to catch per-user mount directories as well.
                try:
                    for inner in sub.iterdir():
                        if inner.is_dir():
                            candidates.append(inner)
                except OSError:
                    continue
    return _dedupe(candidates)


def _dedupe(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def _find_dcim(mount: Path) -> Path | None:
    dcim = mount / "DCIM"
    return dcim if dcim.is_dir() else None


def _has_dji_recordings(dcim: Path) -> bool:
    """True if the DCIM tree contains DJI-named MP4 recordings."""
    for entry in dcim.rglob("*"):
        try:
            if entry.is_file() and entry.name.upper().startswith("DJI_") and media.is_supported(entry.name):
                return True
        except OSError:
            continue
    return False


def find_sources() -> list[Source]:
    """Return recognized DJI sources (mounted filesystems containing DJI recordings)."""
    sources: list[Source] = []
    for mount in _mount_candidates():
        try:
            if not mount.is_dir():
                continue
        except OSError:
            continue
        dcim = _find_dcim(mount)
        if dcim is not None and _has_dji_recordings(dcim):
            sources.append(Source(mount_point=mount, label=mount.name, dcim_dir=dcim))
    return sources


def iter_supported_files(dcim_dir: Path) -> list[Path]:
    """Recursively collect supported MP4 recordings from a DCIM directory."""
    files = [
        entry for entry in dcim_dir.rglob("*")
        if entry.is_file() and media.is_supported(entry.name)
    ]
    files.sort()
    return files


def iter_manual_files(path: Path) -> list[Path]:
    """Recursively collect supported MP4 recordings from a manually chosen directory."""
    files = [
        entry for entry in path.rglob("*")
        if entry.is_file() and media.is_supported(entry.name)
    ]
    files.sort()
    return files
