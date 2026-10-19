"""Launching and controlling mpv processes over its JSON IPC."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000


def find_mpv(configured: str = "") -> str | None:
    if configured and Path(configured).exists():
        return configured
    # a copy bundled next to the Windows executable wins over PATH
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    for cand in (here / "mpv" / "mpv.exe", here / "mpv.exe", here / "mpv" / "mpv"):
        if cand.exists():
            return str(cand)
    return shutil.which("mpv")


def ipc_path(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    if sys.platform == "win32":
        return rf"\\.\pipe\paperloop-mpv-{safe}"
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(base, f"paperloop-mpv-{safe}.sock")


def mpv_options(cfg, ipc: str, title: str) -> list[str]:
    """mpv options (without the executable) shared by every backend."""
    opts = [
        "--no-config",
        "--loop-file=inf",
        "--image-display-duration=inf",
        "--really-quiet",
        "--osd-level=0",
        "--no-osc",
        "--no-input-default-bindings",
        "--input-vo-keyboard=no",
        "--no-border",
        "--force-window=yes",
        f"--title={title}",
        f"--input-ipc-server={ipc}",
        f"--hwdec={cfg['hwdec']}",
    ]
    fit = cfg["fit"]
    if fit == "fill":
        opts += ["--panscan=1.0"]
    elif fit == "stretch":
        opts += ["--keepaspect=no"]
    if cfg["mute"]:
        opts += ["--no-audio"]
    else:
        opts += [f"--volume={int(cfg['volume'])}"]
    if int(cfg["fps_cap"]) > 0:
        opts += [f"--vf=fps={int(cfg['fps_cap'])}"]
    return opts


class MpvProcess:
    def __init__(self, argv: list[str], ipc: str):
        self.ipc = ipc
        self.argv = argv
        kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = CREATE_NO_WINDOW
        self.proc = subprocess.Popen(argv, **kwargs)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def command(self, *args) -> bool:
        data = (json.dumps({"command": list(args)}) + "\n").encode()
        try:
            if sys.platform == "win32":
                with open(self.ipc, "r+b", buffering=0) as pipe:
                    pipe.write(data)
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(1.0)
                    s.connect(self.ipc)
                    s.sendall(data)
            return True
        except OSError:
            return False

    def load(self, path: str) -> bool:
        return self.command("loadfile", path, "replace")

    def set_pause(self, paused: bool) -> bool:
        return self.command("set_property", "pause", bool(paused))

    def terminate(self) -> None:
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if sys.platform != "win32":
            try:
                os.unlink(self.ipc)
            except OSError:
                pass
