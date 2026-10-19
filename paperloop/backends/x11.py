"""Linux X11 (KDE Plasma X11, GNOME on Xorg, Xfce, i3, ...): mpv embedded in a desktop-type window."""

from __future__ import annotations

import re
import shutil
import subprocess

from .base import Monitor, MpvBackend
from .. import mpvctl

_MON_RE = re.compile(r"(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)\s+(\S+)\s*$")


def parse_xrandr_monitors(text: str) -> list[Monitor]:
    mons = []
    for line in text.splitlines():
        m = _MON_RE.search(line)
        if m:
            w, h, x, y, name = m.groups()
            mons.append(Monitor(name, int(x), int(y), int(w), int(h)))
    return mons


class X11Backend(MpvBackend):
    name = "x11"

    def __init__(self, cfg):
        super().__init__(cfg)
        self._xd = None
        self._windows: dict[str, int] = {}

    def available(self) -> tuple[bool, str]:
        if not self.mpv_exe():
            return False, "mpv is not installed (Arch/CachyOS: sudo pacman -S mpv)"
        try:
            from .xlib import XDisplay

            XDisplay().close()
        except Exception as exc:  # noqa: BLE001 - report any failure to the user
            return False, f"cannot talk to the X server: {exc}"
        if not shutil.which("xprop"):
            return True, "ok (install xorg-xprop for auto-pause on fullscreen apps)"
        return True, "ok"

    def _xdisplay(self):
        if self._xd is None:
            from .xlib import XDisplay

            self._xd = XDisplay()
        return self._xd

    def monitors(self) -> list[Monitor]:
        if shutil.which("xrandr"):
            try:
                out = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, timeout=3).stdout
                mons = parse_xrandr_monitors(out)
                if mons:
                    return mons
            except (OSError, subprocess.SubprocessError):
                pass
        w, h = self._xdisplay().size()
        return [Monitor("screen", 0, 0, w, h)]

    def spawn(self, monitor: Monitor, path: str) -> mpvctl.MpvProcess:
        xd = self._xdisplay()
        wid = xd.create_desktop_window(monitor.x, monitor.y, monitor.w, monitor.h, f"paperloop-{monitor.name}")
        self._windows[monitor.name] = wid
        argv = self.mpv_argv(monitor, path, [f"--wid={wid}"])
        return mpvctl.MpvProcess(argv, mpvctl.ipc_path(monitor.name))

    def release(self, monitor_name: str) -> None:
        wid = self._windows.pop(monitor_name, None)
        if wid and self._xd:
            self._xd.destroy(wid)

    def stop(self) -> None:
        super().stop()
        if self._xd:
            self._xd.close()
            self._xd = None
