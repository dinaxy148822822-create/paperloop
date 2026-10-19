"""Just enough Xlib (through ctypes) to create desktop-level windows for mpv to draw into."""

from __future__ import annotations

import ctypes
import ctypes.util

XA_ATOM = 4
PROP_MODE_REPLACE = 0


class XlibError(RuntimeError):
    pass


class XDisplay:
    def __init__(self):
        name = ctypes.util.find_library("X11")
        if not name:
            raise XlibError("libX11 not found")
        self.lib = lib = ctypes.CDLL(name)
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XDefaultScreen.argtypes = [ctypes.c_void_p]
        lib.XRootWindow.restype = ctypes.c_ulong
        lib.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XBlackPixel.restype = ctypes.c_ulong
        lib.XBlackPixel.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XCreateSimpleWindow.restype = ctypes.c_ulong
        lib.XCreateSimpleWindow.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong,
        ]
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XChangeProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
        ]
        lib.XStoreName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p]
        lib.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XDestroyWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XGetWindowProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
            ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.XFree.argtypes = [ctypes.c_void_p]

        self.dpy = lib.XOpenDisplay(None)
        if not self.dpy:
            raise XlibError("cannot open the X display (is DISPLAY set?)")
        self.screen = lib.XDefaultScreen(self.dpy)
        self.root = lib.XRootWindow(self.dpy, self.screen)

    def size(self) -> tuple[int, int]:
        return (self.lib.XDisplayWidth(self.dpy, self.screen), self.lib.XDisplayHeight(self.dpy, self.screen))

    def atom(self, name: str) -> int:
        return self.lib.XInternAtom(self.dpy, name.encode(), 0)

    def _set_atoms(self, win: int, prop: str, values: list[str]) -> None:
        arr = (ctypes.c_ulong * len(values))(*[self.atom(v) for v in values])
        self.lib.XChangeProperty(
            self.dpy, win, self.atom(prop), XA_ATOM, 32, PROP_MODE_REPLACE, ctypes.cast(arr, ctypes.c_void_p), len(values)
        )

    def create_desktop_window(self, x: int, y: int, w: int, h: int, title: str) -> int:
        """A black window the window manager treats as part of the desktop (below everything)."""
        win = self.lib.XCreateSimpleWindow(self.dpy, self.root, x, y, w, h, 0, 0, self.lib.XBlackPixel(self.dpy, self.screen))
        self.lib.XStoreName(self.dpy, win, title.encode())
        self._set_atoms(win, "_NET_WM_WINDOW_TYPE", ["_NET_WM_WINDOW_TYPE_DESKTOP"])
        self._set_atoms(
            win,
            "_NET_WM_STATE",
            ["_NET_WM_STATE_BELOW", "_NET_WM_STATE_STICKY", "_NET_WM_STATE_SKIP_TASKBAR", "_NET_WM_STATE_SKIP_PAGER"],
        )
        self.lib.XMapWindow(self.dpy, win)
        self.lib.XFlush(self.dpy)
        return win

    def get_atom_list(self, win: int, prop: str) -> list[str]:
        """Read back an ATOM[] property (used by tests and `doctor`)."""
        actual_type = ctypes.c_ulong()
        fmt = ctypes.c_int()
        nitems = ctypes.c_ulong()
        after = ctypes.c_ulong()
        data = ctypes.c_void_p()
        status = self.lib.XGetWindowProperty(
            self.dpy, win, self.atom(prop), 0, 64, 0, XA_ATOM,
            ctypes.byref(actual_type), ctypes.byref(fmt), ctypes.byref(nitems), ctypes.byref(after), ctypes.byref(data),
        )
        names: list[str] = []
        if status == 0 and data.value and nitems.value:
            values = ctypes.cast(data.value, ctypes.POINTER(ctypes.c_ulong))
            wanted = [
                "_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_STATE_BELOW", "_NET_WM_STATE_STICKY",
                "_NET_WM_STATE_SKIP_TASKBAR", "_NET_WM_STATE_SKIP_PAGER",
            ]
            lookup = {self.atom(n): n for n in wanted}
            for i in range(nitems.value):
                names.append(lookup.get(values[i], str(values[i])))
        if data.value:
            self.lib.XFree(data)
        return names

    def destroy(self, win: int) -> None:
        self.lib.XDestroyWindow(self.dpy, win)
        self.lib.XFlush(self.dpy)

    def close(self) -> None:
        if self.dpy:
            self.lib.XCloseDisplay(self.dpy)
            self.dpy = None
