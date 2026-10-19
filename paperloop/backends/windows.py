"""Windows 10/11: mpv windows re-parented behind the desktop icons (the WorkerW technique)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from .base import Monitor, MpvBackend
from .. import mpvctl

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
SMTO_NORMAL = 0x0000

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _user32():
    u = ctypes.windll.user32
    u.FindWindowW.restype = wintypes.HWND
    u.FindWindowExW.restype = wintypes.HWND
    u.SetParent.restype = wintypes.HWND
    return u


def find_workerw() -> int | None:
    """Ask Progman to spawn the WorkerW that sits behind the icons, then return its handle."""
    user32 = _user32()
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return None
    result = wintypes.DWORD()
    user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, SMTO_NORMAL, 1000, ctypes.byref(result))

    found: list[int] = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        if user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            worker = user32.FindWindowExW(None, hwnd, "WorkerW", None)
            if worker:
                found.append(worker)
        return True

    user32.EnumWindows(callback, 0)
    if found:
        return found[0]
    # Windows 11 24H2 and newer keep the WorkerW as a child of Progman
    child = user32.FindWindowExW(progman, None, "WorkerW", None)
    return child or progman


def list_monitors() -> list[Monitor]:
    user32 = ctypes.windll.user32

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

    MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    mons: list[Monitor] = []

    @MonitorEnumProc
    def cb(hmon, _hdc, _rect, _lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            name = info.szDevice.lstrip("\\.").replace("\\", "") or f"mon{len(mons)}"
            mons.append(Monitor(name, r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    user32.EnumDisplayMonitors(None, None, cb, 0)
    return mons


class WindowsBackend(MpvBackend):
    name = "windows"

    def available(self) -> tuple[bool, str]:
        if not self.mpv_exe():
            return False, "mpv.exe not found (winget install mpv, or put mpv.exe next to paperloop.exe)"
        if not find_workerw():
            return False, "could not find the desktop window (Progman)"
        return True, "ok"

    def monitors(self) -> list[Monitor]:
        return list_monitors() or [Monitor("primary", 0, 0, ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1))]

    def spawn(self, monitor: Monitor, path: str) -> mpvctl.MpvProcess:
        argv = self.mpv_argv(monitor, path, [f"--geometry={monitor.w}x{monitor.h}+{monitor.x}+{monitor.y}"])
        proc = mpvctl.MpvProcess(argv, mpvctl.ipc_path(monitor.name))
        self._attach(f"paperloop-{monitor.name}", monitor)
        return proc

    def _attach(self, title: str, monitor: Monitor) -> None:
        user32 = _user32()
        deadline = time.time() + 6
        hwnd = None
        while time.time() < deadline:
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            return
        workerw = find_workerw()
        if not workerw:
            return
        # the WorkerW spans the whole virtual desktop; child coordinates are relative to its origin
        origin = wintypes.RECT()
        user32.GetWindowRect(workerw, ctypes.byref(origin))
        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        style = get_long(hwnd, GWL_STYLE)
        style = (style & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)) | WS_CHILD
        set_long(hwnd, GWL_STYLE, style)
        user32.SetParent(hwnd, workerw)
        user32.SetWindowPos(hwnd, None, monitor.x - origin.left, monitor.y - origin.top, monitor.w, monitor.h, SWP_NOZORDER | SWP_SHOWWINDOW)
