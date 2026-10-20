"""Start Paperloop at login."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "Paperloop"


def command() -> list[str]:
    appimage = os.environ.get("APPIMAGE")  # inside an AppImage sys.executable is a temporary mount
    if appimage:
        return [appimage, "daemon"]
    if getattr(sys, "frozen", False):
        return [sys.executable, "daemon"]
    return [sys.executable, "-m", "paperloop", "daemon"]


def desktop_entry(cmd: list[str]) -> str:
    return (
        "[Desktop Entry]\nType=Application\nName=Paperloop\n"
        "Comment=Live wallpaper player\n"
        f"Exec={' '.join(shlex.quote(c) for c in cmd)}\n"
        "X-GNOME-Autostart-enabled=true\nTerminal=false\n"
    )


def linux_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / "paperloop.desktop"


def enable() -> str:
    cmd = command()
    if sys.platform == "win32":
        import winreg

        line = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, line)
        return f"registry: HKCU\\{RUN_KEY}\\{VALUE}"
    path = linux_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desktop_entry(cmd), encoding="utf-8")
    return str(path)


def disable() -> None:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE)
        except OSError:
            pass
        return
    try:
        linux_path().unlink()
    except OSError:
        pass
