"""Reading system state: what is in the foreground, and is the machine on battery."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .rules import Foreground


def _run(argv: list[str], timeout: float = 2.0) -> str:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- battery

def on_battery() -> bool:
    if sys.platform == "win32":
        return _win_on_battery()
    base = Path("/sys/class/power_supply")
    try:
        for dev in base.iterdir():
            if not dev.name.startswith("BAT"):
                continue
            status = (dev / "status").read_text().strip().lower()
            if status == "discharging":
                return True
    except OSError:
        pass
    return False


def _win_on_battery() -> bool:
    import ctypes
    from ctypes import wintypes

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", wintypes.BYTE),
            ("BatteryFlag", wintypes.BYTE),
            ("BatteryLifePercent", wintypes.BYTE),
            ("SystemStatusFlag", wintypes.BYTE),
            ("BatteryLifeTime", wintypes.DWORD),
            ("BatteryFullLifeTime", wintypes.DWORD),
        ]

    st = SYSTEM_POWER_STATUS()
    if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return st.ACLineStatus == 0
    return False


# ------------------------------------------------------------- foreground

def foreground(session: str) -> Foreground | None:
    try:
        if session == "windows":
            return _win_foreground()
        if session == "x11":
            return _x11_foreground()
        if session == "wlroots":
            return _wlroots_foreground()
    except Exception:  # sensors must never take the daemon down
        return None
    return None


def _proc_name(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip().lower()
    except OSError:
        return ""


def parse_xprop_state(text: str) -> tuple[bool, bool]:
    """(fullscreen, maximized) from `xprop _NET_WM_STATE` output."""
    fullscreen = "_NET_WM_STATE_FULLSCREEN" in text
    maximized = "_NET_WM_STATE_MAXIMIZED_VERT" in text and "_NET_WM_STATE_MAXIMIZED_HORZ" in text
    return fullscreen, maximized


def _x11_foreground() -> Foreground | None:
    if not shutil.which("xprop"):
        return None
    root = _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    m = re.search(r"(0x[0-9a-fA-F]+)", root)
    if not m or int(m.group(1), 16) == 0:
        return Foreground()
    wid = m.group(1)
    info = _run(["xprop", "-id", wid, "_NET_WM_STATE", "_NET_WM_PID", "_NET_WM_WINDOW_TYPE"])
    if "_NET_WM_WINDOW_TYPE_DESKTOP" in info:
        return Foreground()
    fullscreen, maximized = parse_xprop_state(info)
    pid_m = re.search(r"_NET_WM_PID\(CARDINAL\)\s*=\s*(\d+)", info)
    name = _proc_name(int(pid_m.group(1))) if pid_m else ""
    return Foreground(name, fullscreen, maximized)


def _wlroots_foreground() -> Foreground | None:
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        raw = _run(["hyprctl", "activewindow", "-j"])
        if not raw.strip():
            return Foreground()
        data = json.loads(raw)
        if not data:
            return Foreground()
        return Foreground(_proc_name(int(data.get("pid", 0) or 0)), bool(data.get("fullscreen")), False)
    if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
        tree = json.loads(_run(["swaymsg", "-t", "get_tree"]) or "{}")
        node = _sway_focused(tree)
        if node:
            return Foreground(_proc_name(int(node.get("pid", 0) or 0)), bool(node.get("fullscreen_mode")), False)
        return Foreground()
    return None


def _sway_focused(node: dict) -> dict | None:
    if node.get("focused"):
        return node
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        found = _sway_focused(child)
        if found:
            return found
    return None


def _win_foreground() -> Foreground | None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return Foreground()

    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "SHELLDLL_DefView"):
        return Foreground()

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    mon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    fullscreen = False
    if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        r = mi.rcMonitor
        fullscreen = rect.left <= r.left and rect.top <= r.top and rect.right >= r.right and rect.bottom >= r.bottom
    maximized = bool(user32.IsZoomed(hwnd))

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ""
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            name = os.path.basename(buf.value).lower()
        kernel32.CloseHandle(handle)
    return Foreground(name, fullscreen, maximized)
