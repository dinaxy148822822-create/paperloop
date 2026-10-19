"""Backend selection."""

from __future__ import annotations

from .. import session
from .base import Backend


def create(cfg, kind: str | None = None) -> Backend:
    kind = kind or session.detect()
    if kind == "windows":
        from .windows import WindowsBackend

        return WindowsBackend(cfg)
    if kind == "x11":
        from .x11 import X11Backend

        return X11Backend(cfg)
    if kind == "wlroots":
        from .mpvpaper import MpvpaperBackend

        return MpvpaperBackend(cfg)
    if kind == "kde-wayland":
        from .kde import KdeBackend

        return KdeBackend(cfg)
    raise RuntimeError(
        f"Unsupported session: {kind}. GNOME on Wayland has no desktop-background API for video; "
        "log in with 'GNOME on Xorg' or use KDE Plasma / Hyprland / Sway."
    )
