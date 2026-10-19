"""Configuration: a small JSON file in the per-user config directory."""

from __future__ import annotations

import copy
import json
import os
import secrets
import sys
from pathlib import Path


def config_dir() -> Path:
    override = os.environ.get("PAPERLOOP_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "paperloop"


DEFAULTS: dict = {
    "library_dirs": [],
    # monitor name -> wallpaper path. "*" means "every monitor without its own entry".
    "assignments": {},
    "mute": True,
    "volume": 0,
    "fit": "fill",  # fill | fit | stretch
    "fps_cap": 0,  # 0 = unlimited. Non-zero inserts an mpv fps filter (disables some hwdec paths).
    "hwdec": "auto-safe",
    "port": 8765,
    "poll_seconds": 1.5,
    "mpv_path": "",
    "pause": {
        "on_fullscreen": True,
        "on_maximized": False,
        "on_battery": False,
        # [{"process": "game.exe", "action": "pause" | "ignore"}]
        "app_rules": [],
    },
    "playlist": {
        "enabled": False,
        "mode": "interval",  # interval | schedule
        "interval_minutes": 15,
        "shuffle": False,
        "items": [],
        # [{"at": "08:00", "item": "/path/file.mp4"}] used when mode == "schedule"
        "schedule": [],
    },
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    def __init__(self, data: dict | None = None, path: Path | None = None):
        self.path = path or (config_dir() / "config.json")
        self.data = _merge(DEFAULTS, data or {})

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or (config_dir() / "config.json")
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        return cls(data, path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def update(self, patch: dict) -> None:
        self.data = _merge(self.data, patch)

    def __getitem__(self, key: str):
        return self.data[key]

    def get(self, key: str, default=None):
        return self.data.get(key, default)


def load_or_create_token() -> str:
    """Secret the CLI and web UI send with every request (blocks drive-by browser requests)."""
    path = config_dir() / "token"
    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token
