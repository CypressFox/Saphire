"""Where Sapphire keeps its own files.

Linux: the XDG base directories (~/.local/share/sapphire, ~/.cache/sapphire).
Windows: %APPDATA%\\Sapphire for data, %LOCALAPPDATA%\\Sapphire\\cache for cache.
Either way, SAPPHIRE_HOME overrides everything (handy for tests and portable use).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sapphire import APP_ID, APP_NAME

WINDOWS = sys.platform == "win32"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "").strip()
    return Path(value) if value else Path.home() / fallback


def _win_dir(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "").strip()
    return (Path(value) if value else Path.home() / fallback) / APP_NAME


def data_dir() -> Path:
    """Library, state and logs. Override with SAPPHIRE_HOME."""
    override = os.environ.get("SAPPHIRE_HOME")
    if override:
        path = Path(override)
    elif WINDOWS:
        path = _win_dir("APPDATA", "AppData/Roaming")
    else:
        path = _xdg("XDG_DATA_HOME", ".local/share") / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    override = os.environ.get("SAPPHIRE_HOME")
    if override:
        path = Path(override) / "cache"
    elif WINDOWS:
        path = _win_dir("LOCALAPPDATA", "AppData/Local") / "cache"
    else:
        path = _xdg("XDG_CACHE_HOME", ".cache") / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def library_dir() -> Path:
    path = data_dir() / "library"
    path.mkdir(parents=True, exist_ok=True)
    return path


def downloads_dir() -> Path:
    path = cache_dir() / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def thumbs_dir() -> Path:
    path = cache_dir() / "thumbs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_file() -> Path:
    return data_dir() / "state.json"


def log_file() -> Path:
    return data_dir() / "sapphire.log"
