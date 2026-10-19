"""Local control server: the web UI and the JSON API the CLI talks to. Bound to 127.0.0.1 only."""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, library
from .config import config_dir

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 1_000_000


def make_server(daemon, token: str, port: int | None = None) -> ThreadingHTTPServer:
    cfg = daemon.cfg
    port = cfg["port"] if port is None else port

    class Handler(BaseHTTPRequestHandler):
        server_version = f"paperloop/{__version__}"

        def log_message(self, *_a):  # keep the console quiet
            pass

        # ---- helpers
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0].lower()
            return host in ("127.0.0.1", "localhost", "[::1]")

        def _token_ok(self, allow_query: bool = False) -> bool:
            supplied = self.headers.get("X-Paperloop-Token", "")
            if not supplied and allow_query:
                supplied = parse_qs(urlparse(self.path).query).get("t", [""])[0]
            return hmac.compare_digest(supplied, token)

        def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj).encode())

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("body too large")
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw or b"{}")
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            return data

        # ---- routes
        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._send(403, b"bad host", "text/plain")
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", token)
                return self._send(200, html.encode(), "text/html; charset=utf-8",
                                  {"Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"})
            if url.path == "/icon.svg":
                icon = WEB_DIR / "icon.svg"
                return self._send(200, icon.read_bytes(), "image/svg+xml") if icon.exists() else self._send(404, b"")
            if url.path == "/api/thumb":
                if not self._token_ok(allow_query=True):
                    return self._send(401, b"unauthorized", "text/plain")
                return self._thumb(parse_qs(url.query).get("path", [""])[0])
            if not self._token_ok():
                return self._send(401, b"unauthorized", "text/plain")
            if url.path == "/api/state":
                return self._json(self._state())
            self._send(404, b"not found", "text/plain")

        def do_POST(self):  # noqa: N802
            if not self._host_ok():
                return self._send(403, b"bad host", "text/plain")
            if not self._token_ok():
                return self._send(401, b"unauthorized", "text/plain")
            try:
                data = self._body()
                route = urlparse(self.path).path
                result = self._route(route, data)
            except (ValueError, KeyError) as exc:
                return self._json({"error": str(exc)}, 400)
            if result is None:
                return self._send(404, b"not found", "text/plain")
            self._json(result)

        def _route(self, route: str, data: dict):
            if route == "/api/apply":
                daemon.set_wallpaper(str(data["path"]), str(data.get("monitor", "*")))
                return {"ok": True}
            if route == "/api/pause":
                daemon.pause(bool(data.get("paused", True)))
                return {"ok": True}
            if route == "/api/next":
                return {"ok": True, "picked": daemon.next_wallpaper()}
            if route == "/api/stop":
                daemon.stop_wallpaper()
                return {"ok": True}
            if route == "/api/library/add":
                folder = Path(str(data["dir"])).expanduser()
                if not folder.is_dir():
                    raise ValueError("not a folder")
                dirs = cfg["library_dirs"]
                if str(folder) not in dirs:
                    dirs.append(str(folder))
                    cfg.save()
                return {"ok": True}
            if route == "/api/library/remove":
                cfg.data["library_dirs"] = [d for d in cfg["library_dirs"] if d != data["dir"]]
                cfg.save()
                return {"ok": True}
            if route == "/api/config":
                allowed = {"mute", "volume", "fit", "fps_cap", "hwdec", "pause", "playlist"}
                patch = {k: v for k, v in data.items() if k in allowed}
                if "fit" in patch and patch["fit"] not in ("fill", "fit", "stretch"):
                    raise ValueError("fit must be fill, fit or stretch")
                cfg.update(patch)
                cfg.save()
                if {"mute", "volume", "fit", "fps_cap", "hwdec"} & patch.keys():
                    daemon.stop_wallpaper()  # restart players so the new mpv options apply
                return {"ok": True}
            return None

        def _state(self) -> dict:
            wallpapers = [w.to_dict() for w in library.scan(cfg["library_dirs"])]
            return {
                "version": __version__,
                "status": daemon.status(),
                "wallpapers": wallpapers,
                "library_dirs": cfg["library_dirs"],
                "config": {k: cfg[k] for k in ("mute", "volume", "fit", "fps_cap", "hwdec", "pause", "playlist")},
            }

        def _thumb(self, path: str):
            if not library.is_allowed(path, cfg["library_dirs"]):
                return self._send(404, b"", "text/plain")
            p = Path(path).resolve()
            if library.kind_of(p) == "image":
                mime = {".png": "image/png", ".webp": "image/webp", ".bmp": "image/bmp"}.get(p.suffix.lower(), "image/jpeg")
                return self._send(200, p.read_bytes(), mime, {"Cache-Control": "max-age=300"})
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return self._send(204, b"", "text/plain")
            cache = config_dir() / "thumbs"
            cache.mkdir(parents=True, exist_ok=True)
            key = hashlib.sha1(f"{p}{p.stat().st_mtime}".encode()).hexdigest()
            out = cache / f"{key}.jpg"
            if not out.exists():
                subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", "1", "-i", str(p), "-frames:v", "1",
                                "-vf", "scale=320:-2", str(out)], capture_output=True, timeout=20)
                if not out.exists():  # clip shorter than one second
                    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(p), "-frames:v", "1",
                                    "-vf", "scale=320:-2", str(out)], capture_output=True, timeout=20)
            if out.exists():
                return self._send(200, out.read_bytes(), "image/jpeg", {"Cache-Control": "max-age=300"})
            self._send(204, b"", "text/plain")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, name="paperloop-web", daemon=True)
    t.start()
    return t
