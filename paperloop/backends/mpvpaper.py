"""Wayland compositors with wlr-layer-shell (Hyprland, Sway, river, Wayfire): mpvpaper does the drawing."""

from __future__ import annotations

import shutil

from .base import Monitor, MpvBackend
from .. import mpvctl


def option_string(opts: list[str]) -> str:
    """mpvpaper wants mpv options as one string without leading dashes."""
    out = []
    for o in opts:
        o = o[2:] if o.startswith("--") else o
        # window options mean nothing to a layer-shell surface
        if o.startswith(("title=", "force-window", "border", "no-border")):
            continue
        out.append(o)
    return " ".join(out)


class MpvpaperBackend(MpvBackend):
    name = "mpvpaper"

    def available(self) -> tuple[bool, str]:
        if not self.mpv_exe():
            return False, "mpv is not installed (sudo pacman -S mpv)"
        if not shutil.which("mpvpaper"):
            return False, "mpvpaper is not installed (CachyOS/Arch: paru -S mpvpaper)"
        return True, "ok"

    def monitors(self) -> list[Monitor]:
        # mpvpaper addresses outputs by name; "*" means all of them
        names = list(self.cfg_assignments) or ["*"]
        return [Monitor(n) for n in names]

    cfg_assignments: dict = {}

    def apply(self, assignments: dict[str, str]) -> None:
        self.cfg_assignments = assignments
        super().apply(assignments)

    def spawn(self, monitor: Monitor, path: str) -> mpvctl.MpvProcess:
        exe = shutil.which("mpvpaper")
        ipc = mpvctl.ipc_path(monitor.name)
        opts = mpvctl.mpv_options(self.cfg, ipc, f"paperloop-{monitor.name}")
        if self.paused:
            opts.append("--pause")
        argv = [exe, "-o", option_string(opts), monitor.name, path]
        return mpvctl.MpvProcess(argv, ipc)
