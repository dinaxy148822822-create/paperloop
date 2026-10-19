"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__, autostart, backends, library, mpvctl, session, tray, webserver
from .config import Config, load_or_create_token


def _url(cfg: Config) -> str:
    return f"http://127.0.0.1:{cfg['port']}/"


def _call(cfg: Config, path: str, body: dict | None = None) -> dict:
    token = load_or_create_token()
    req = urllib.request.Request(_url(cfg).rstrip("/") + path, headers={"X-Paperloop-Token": token})
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("error", exc.reason)
        except Exception:  # noqa: BLE001
            detail = exc.reason
        raise SystemExit(f"paperloop: {detail}")
    except (urllib.error.URLError, OSError):
        raise SystemExit("paperloop: the daemon is not running. Start it with: paperloop daemon")


def _daemon_running(cfg: Config) -> bool:
    try:
        urllib.request.urlopen(_url(cfg) + "icon.svg", timeout=1).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def cmd_daemon(args, cfg: Config) -> int:
    from .daemon import Daemon

    if _daemon_running(cfg):
        print("paperloop is already running.")
        if not args.no_browser:
            webbrowser.open(_url(cfg))
        return 0
    try:
        backend = backends.create(cfg)
    except RuntimeError as exc:
        print(f"paperloop: {exc}", file=sys.stderr)
        return 2
    ok, detail = backend.available()
    if not ok:
        print(f"paperloop: backend '{backend.name}' is not ready: {detail}", file=sys.stderr)
        return 2

    daemon = Daemon(cfg, backend)
    token = load_or_create_token()
    server = webserver.make_server(daemon, token)
    webserver.serve_in_thread(server)
    stop = threading.Event()

    def quit_now(*_a):
        stop.set()
        daemon.shutdown()

    signal.signal(signal.SIGINT, quit_now)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, quit_now)

    tray.run(daemon, _url(cfg), quit_now)
    print(f"paperloop {__version__}: {backend.name} backend, UI at {_url(cfg)}")
    if not args.no_browser:
        webbrowser.open(_url(cfg))
    runner = threading.Thread(target=daemon.run, name="paperloop-loop", daemon=True)
    runner.start()
    try:
        while not stop.is_set():
            stop.wait(0.5)
    finally:
        server.shutdown()
        daemon.shutdown()
    return 0


def cmd_doctor(args, cfg: Config) -> int:
    kind = session.detect()
    print(f"paperloop {__version__}")
    print(f"session   : {kind}")
    print(f"mpv       : {mpvctl.find_mpv(cfg['mpv_path']) or 'NOT FOUND'}")
    for tool in ("mpvpaper", "xprop", "xrandr", "ffmpeg", "qdbus6", "hyprctl", "swaymsg"):
        print(f"{tool:<10}: {shutil.which(tool) or '-'}")
    print(f"tray      : {'available' if tray.available() else 'not installed (pip install paperloop[tray])'}")
    try:
        backend = backends.create(cfg)
        ok, detail = backend.available()
        print(f"backend   : {backend.name} -> {'READY' if ok else 'NOT READY'} ({detail})")
        return 0 if ok else 1
    except RuntimeError as exc:
        print(f"backend   : {exc}")
        return 1


def cmd_add(args, cfg: Config) -> int:
    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"paperloop: {folder} is not a folder", file=sys.stderr)
        return 1
    if _daemon_running(cfg):
        _call(cfg, "/api/library/add", {"dir": str(folder)})  # the daemon owns the live config
    elif str(folder) not in cfg["library_dirs"]:
        cfg["library_dirs"].append(str(folder))
        cfg.save()
    print(f"{len(library.scan([str(folder)]))} wallpapers found in {folder}")
    return 0


def cmd_list(args, cfg: Config) -> int:
    for w in library.scan(cfg["library_dirs"]):
        print(f"{w.kind:<6} {w.path}")
    return 0


def cmd_set(args, cfg: Config) -> int:
    _call(cfg, "/api/apply", {"path": str(Path(args.file).expanduser().resolve()), "monitor": args.monitor})
    print("ok")
    return 0


def cmd_simple(path: str, body: dict | None = None):
    def run(args, cfg: Config) -> int:
        print(json.dumps(_call(cfg, path, body if body is not None else {})))
        return 0

    return run


def cmd_ui(args, cfg: Config) -> int:
    webbrowser.open(_url(cfg))
    return 0


def cmd_autostart(args, cfg: Config) -> int:
    if args.action == "enable":
        print("enabled:", autostart.enable())
    else:
        autostart.disable()
        print("disabled")
    return 0


def cmd_kde_install(args, cfg: Config) -> int:
    from .backends.kde import KdeBackend

    dst = KdeBackend(cfg).install_plugin()
    print(f"installed the Plasma wallpaper plugin to {dst}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paperloop", description="Free live wallpapers for Windows 10/11 and Linux.")
    p.add_argument("--version", action="version", version=f"paperloop {__version__}")
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("daemon", help="run Paperloop (wallpaper + web UI)")
    d.add_argument("--no-browser", action="store_true", help="do not open the UI in a browser")
    d.set_defaults(fn=cmd_daemon)

    sub.add_parser("doctor", help="check that everything needed is installed").set_defaults(fn=cmd_doctor)
    sub.add_parser("ui", help="open the web UI").set_defaults(fn=cmd_ui)

    a = sub.add_parser("add", help="add a folder of wallpapers to the library")
    a.add_argument("folder")
    a.set_defaults(fn=cmd_add)

    sub.add_parser("list", help="list wallpapers in the library").set_defaults(fn=cmd_list)

    s = sub.add_parser("set", help="set a wallpaper")
    s.add_argument("file")
    s.add_argument("--monitor", default="*", help='monitor name, default "*" (all)')
    s.set_defaults(fn=cmd_set)

    sub.add_parser("pause", help="pause playback").set_defaults(fn=cmd_simple("/api/pause", {"paused": True}))
    sub.add_parser("resume", help="resume playback").set_defaults(fn=cmd_simple("/api/pause", {"paused": False}))
    sub.add_parser("next", help="next wallpaper in the playlist").set_defaults(fn=cmd_simple("/api/next"))
    sub.add_parser("stop", help="stop the wallpaper").set_defaults(fn=cmd_simple("/api/stop"))

    au = sub.add_parser("autostart", help="start Paperloop at login")
    au.add_argument("action", choices=["enable", "disable"])
    au.set_defaults(fn=cmd_autostart)

    sub.add_parser("kde-install", help="install the KDE Plasma wallpaper plugin (Wayland)").set_defaults(fn=cmd_kde_install)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = Config.load()
    if not args.cmd:  # double-clicking the Windows executable lands here
        args = parser.parse_args(["daemon"])
    return args.fn(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
