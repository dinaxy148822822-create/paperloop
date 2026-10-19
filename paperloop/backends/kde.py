"""KDE Plasma on Wayland (and X11 as a fallback): a bundled Plasma wallpaper plugin plays the video.

EXPERIMENTAL. Plasma has no layer-shell background, so we drive plasmashell itself through its
scripting interface. Images use the stock `plasma-apply-wallpaperimage` tool.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .base import Backend
from ..library import kind_of

PLUGIN_ID = "org.paperloop.video"


def plugin_source_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "kde" / PLUGIN_ID


def plugin_target_dir() -> Path:
    return Path.home() / ".local" / "share" / "plasma" / "wallpapers" / PLUGIN_ID


def evaluate_script_js(path: str | None, paused: bool) -> str:
    """JavaScript for plasmashell's evaluateScript that points every desktop at the video plugin."""
    url = Path(path).resolve().as_uri() if path else ""
    return (
        "var all = desktops();"
        "for (var i = 0; i < all.length; i++) {"
        " var d = all[i];"
        f" d.wallpaperPlugin = {json.dumps(PLUGIN_ID)};"
        f" d.currentConfigGroup = ['Wallpaper', {json.dumps(PLUGIN_ID)}, 'General'];"
        f" d.writeConfig('VideoUrl', {json.dumps(url)});"
        f" d.writeConfig('Paused', {'true' if paused else 'false'});"
        " d.reloadConfig();"
        "}"
    )


def _qdbus() -> str | None:
    return shutil.which("qdbus6") or shutil.which("qdbus") or shutil.which("qdbus-qt6")


class KdeBackend(Backend):
    name = "kde"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.path: str | None = None

    def available(self) -> tuple[bool, str]:
        if not _qdbus():
            return False, "qdbus6 not found (sudo pacman -S qt6-tools)"
        if not (plugin_target_dir() / "metadata.json").exists():
            return False, "Plasma plugin not installed: run `paperloop kde-install`"
        return True, "ok (experimental)"

    def install_plugin(self) -> Path:
        src, dst = plugin_source_dir(), plugin_target_dir()
        if not src.is_dir():
            raise RuntimeError(f"plugin sources not found at {src}")
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
        return dst

    def _script(self, js: str) -> None:
        exe = _qdbus()
        if not exe:
            raise RuntimeError("qdbus6 not found")
        subprocess.run([exe, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", js],
                       capture_output=True, timeout=10, check=False)

    def apply(self, assignments: dict[str, str]) -> None:
        # Plasma desktops are not addressable by monitor name here: use "*" or the first entry
        path = assignments.get("*") or next(iter(assignments.values()), None)
        if not path or path == self.path:
            return
        self.path = path
        if kind_of(path) == "image" and shutil.which("plasma-apply-wallpaperimage"):
            subprocess.run(["plasma-apply-wallpaperimage", path], capture_output=True, timeout=10, check=False)
            return
        self._script(evaluate_script_js(path, self.paused))

    def set_paused(self, paused: bool) -> None:
        if paused == self.paused:
            return
        self.paused = paused
        if self.path and kind_of(self.path) == "video":
            self._script(evaluate_script_js(self.path, paused))

    def stop(self) -> None:
        self.path = None
