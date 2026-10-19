"""Application configuration and XDG path resolution."""
from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "dji-footage-importer"
APP_VERSION = "0.1.0"
DISPLAY_NAME = "Import from DJI"

DEFAULT_MIN_FREE_SPACE_GIB = 50
DEFAULT_AUDIO_SAMPLE_RATE = 48000
CONVERSION_PROFILE_VERSION = 1


def _home() -> Path:
    return Path.home()


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", _home() / ".config"))


def xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", _home() / ".local" / "state"))


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", _home() / ".local" / "share"))


def _user_dirs_file() -> Path:
    return xdg_config_home() / "user-dirs.dirs"


def videos_dir() -> Path:
    """Resolve the user's Videos directory via XDG user dirs, falling back to ~/Videos."""
    try:
        for line in _user_dirs_file().read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("XDG_VIDEOS_DIR="):
                raw = line.split("=", 1)[1].strip().strip('"')
                path = Path(os.path.expandvars(raw)).expanduser()
                if path.is_absolute():
                    return path
    except (OSError, ValueError):
        pass
    return _home() / "Videos"


def dest_root() -> Path:
    return videos_dir() / "DJI"


def footage_dir() -> Path:
    return dest_root() / "footage"


def original_dir() -> Path:
    return dest_root() / ".original"


def importer_dir() -> Path:
    return dest_root() / ".importer"


def staging_dir() -> Path:
    return importer_dir() / "staging"


def state_db_path() -> Path:
    return importer_dir() / "state.sqlite"


def lock_path() -> Path:
    return importer_dir() / "state.lock"


def log_dir() -> Path:
    return xdg_state_home() / APP_NAME


def config_file() -> Path:
    return xdg_config_home() / APP_NAME / "config.json"


def load_config() -> dict:
    """Return user configuration merged over defaults."""
    cfg = {
        "min_free_space_gib": DEFAULT_MIN_FREE_SPACE_GIB,
        "audio_sample_rate": DEFAULT_AUDIO_SAMPLE_RATE,
    }
    path = config_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in data.items() if k in cfg})
    except (OSError, ValueError, TypeError):
        pass
    return cfg


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure and return the application logger (XDG state dir, rotated)."""
    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(APP_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler = RotatingFileHandler(
        d / "app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.info("starting %s %s", APP_NAME, APP_VERSION)
    return logger
