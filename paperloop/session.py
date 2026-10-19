"""Work out which desktop environment we are running on."""

from __future__ import annotations

import os
import sys


def detect() -> str:
    """One of: windows, x11, wlroots (Hyprland/Sway/...), kde-wayland, gnome-wayland, wayland-other, unknown."""
    if sys.platform == "win32":
        return "windows"
    if not sys.platform.startswith("linux"):
        return "unknown"
    env = os.environ
    desktop = (env.get("XDG_CURRENT_DESKTOP") or "").lower()
    session = (env.get("XDG_SESSION_TYPE") or "").lower()
    wayland = session == "wayland" or bool(env.get("WAYLAND_DISPLAY"))
    if wayland:
        if env.get("HYPRLAND_INSTANCE_SIGNATURE") or env.get("SWAYSOCK") or "sway" in desktop or "hypr" in desktop or "river" in desktop or "wayfire" in desktop:
            return "wlroots"
        if "kde" in desktop:
            return "kde-wayland"
        if "gnome" in desktop:
            return "gnome-wayland"
        return "wayland-other"
    if env.get("DISPLAY") or session == "x11":
        return "x11"
    return "unknown"
