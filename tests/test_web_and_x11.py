import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from urllib.parse import quote
from pathlib import Path

from paperloop import autostart, mpvctl
from paperloop.backends import base
from paperloop.config import Config
from paperloop.daemon import Daemon
from paperloop.webserver import make_server, serve_in_thread

from .helpers import FAKE_MPV, read_log, wait_for

TOKEN = "secret-token"


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "lib").mkdir()
        (root / "lib" / "a.mp4").write_bytes(b"x")
        (root / "lib" / "p.png").write_bytes(b"\x89PNG fake")
        (root / "secret.mp4").write_bytes(b"x")
        self.root = root
        self.cfg = Config({"library_dirs": [str(root / "lib")]}, path=root / "config.json")
        self.applied = []

        class Rec(base.Backend):
            name = "rec"

            def available(s):
                return True, "ok"

            def apply(s, a):
                self.applied.append(dict(a))

            def set_paused(s, p):
                pass

            def stop(s):
                pass

        self.daemon = Daemon(self.cfg, Rec(self.cfg), "x11", fg_reader=lambda: None, battery_reader=lambda: False)
        self.server = make_server(self.daemon, TOKEN, port=0)
        self.port = self.server.server_address[1]
        serve_in_thread(self.server)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def req(self, path, body=None, token=TOKEN, host=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if token:
            r.add_header("X-Paperloop-Token", token)
        if host:
            r.add_header("Host", host)
        if body is not None:
            r.data = json.dumps(body).encode()
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_index_embeds_token_and_icon_served(self):
        code, body = self.req("/", token=None)
        self.assertEqual(code, 200)
        self.assertIn(TOKEN, body.decode())
        self.assertNotIn("__TOKEN__", body.decode())
        self.assertEqual(self.req("/icon.svg", token=None)[0], 200)

    def test_api_requires_token(self):
        self.assertEqual(self.req("/api/state", token=None)[0], 401)
        self.assertEqual(self.req("/api/state", token="wrong")[0], 401)
        self.assertEqual(self.req("/api/apply", {"path": "x"}, token=None)[0], 401)

    def test_dns_rebinding_host_blocked(self):
        self.assertEqual(self.req("/api/state", host="evil.example.com")[0], 403)
        self.assertEqual(self.req("/", token=None, host="evil.example.com:8765")[0], 403)

    def test_state_lists_library(self):
        code, body = self.req("/api/state")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual({w["title"] for w in data["wallpapers"]}, {"a", "p"})
        self.assertEqual(data["status"]["backend"], "rec")

    def test_apply_inside_library_ok_outside_rejected(self):
        ok = self.req("/api/apply", {"path": str(self.root / "lib" / "a.mp4")})
        self.assertEqual(ok[0], 200)
        self.assertEqual(self.applied[-1]["*"], str(self.root / "lib" / "a.mp4"))
        bad = self.req("/api/apply", {"path": str(self.root / "secret.mp4")})
        self.assertEqual(bad[0], 400)
        self.assertEqual(self.req("/api/apply", {"path": "/etc/passwd"})[0], 400)

    def test_thumb_only_for_library_files_and_accepts_query_token(self):
        good = quote(str(self.root / "lib" / "p.png"), safe="")
        self.assertEqual(self.req(f"/api/thumb?t={TOKEN}&path={good}", token=None)[0], 200)
        self.assertEqual(self.req(f"/api/thumb?t={TOKEN}&path={quote(str(self.root / 'secret.mp4'), safe='')}", token=None)[0], 404)
        self.assertEqual(self.req(f"/api/thumb?path={good}", token=None)[0], 401)

    def test_config_patch_validates_and_persists(self):
        self.assertEqual(self.req("/api/config", {"fit": "bogus"})[0], 400)
        self.assertEqual(self.req("/api/config", {"pause": {"on_battery": True}, "evil": 1})[0], 200)
        self.assertTrue(Config.load(self.cfg.path)["pause"]["on_battery"])
        self.assertNotIn("evil", Config.load(self.cfg.path).data)

    def test_library_add_remove(self):
        extra = self.root / "more"
        extra.mkdir()
        self.assertEqual(self.req("/api/library/add", {"dir": str(extra)})[0], 200)
        self.assertIn(str(extra), self.cfg["library_dirs"])
        self.assertEqual(self.req("/api/library/add", {"dir": str(self.root / "nope")})[0], 400)
        self.req("/api/library/remove", {"dir": str(extra)})
        self.assertNotIn(str(extra), self.cfg["library_dirs"])

    def test_pause_endpoint(self):
        self.req("/api/pause", {"paused": True})
        self.assertTrue(self.daemon.user_paused)

    def test_oversized_and_malformed_bodies(self):
        self.assertEqual(self.req("/api/apply", [1, 2])[0], 400)
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/apply", data=b"{nope", headers={"X-Paperloop-Token": TOKEN})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(r)
        self.assertEqual(ctx.exception.code, 400)


class AutostartTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "linux autostart")
    def test_desktop_entry_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["XDG_CONFIG_HOME"] = d
            try:
                where = autostart.enable()
                text = Path(where).read_text()
                self.assertIn("Exec=", text)
                self.assertIn("paperloop", text)
                autostart.disable()
                self.assertFalse(Path(where).exists())
            finally:
                os.environ.pop("XDG_CONFIG_HOME", None)


@unittest.skipUnless(shutil.which("Xvfb"), "Xvfb not installed")
class X11IntegrationTests(unittest.TestCase):
    """Real X server (Xvfb) + real Xlib calls + fake mpv: checks the window the wallpaper is drawn into."""

    def setUp(self):
        from paperloop.backends.x11 import X11Backend

        self.tmp = tempfile.TemporaryDirectory()
        self.display = ":97"
        self.xvfb = subprocess.Popen(["Xvfb", self.display, "-screen", "0", "1280x720x24"], stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        self.old = {k: os.environ.get(k) for k in ("DISPLAY", "FAKE_MPV_LOG", "XDG_RUNTIME_DIR")}
        os.environ.update({"DISPLAY": self.display, "FAKE_MPV_LOG": os.path.join(self.tmp.name, "log"), "XDG_RUNTIME_DIR": self.tmp.name})
        self.backend = X11Backend(Config({"mpv_path": FAKE_MPV}))

    def tearDown(self):
        self.backend.stop()
        self.xvfb.terminate()
        self.xvfb.wait(5)
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def test_available_and_window_is_desktop_type(self):
        ok, detail = self.backend.available()
        self.assertTrue(ok, detail)
        self.backend.apply({"*": "/w/a.mp4"})
        log = os.environ["FAKE_MPV_LOG"]
        self.assertTrue(wait_for(lambda: any("argv" in e for e in read_log(log))))
        argv = [e for e in read_log(log) if "argv" in e][0]["argv"]
        wid_args = [a for a in argv if a.startswith("--wid=")]
        self.assertEqual(len(wid_args), 1)
        wid = int(wid_args[0].split("=")[1])
        xd = self.backend._xdisplay()
        self.assertEqual(xd.get_atom_list(wid, "_NET_WM_WINDOW_TYPE"), ["_NET_WM_WINDOW_TYPE_DESKTOP"])
        state = xd.get_atom_list(wid, "_NET_WM_STATE")
        self.assertIn("_NET_WM_STATE_BELOW", state)
        self.assertIn("_NET_WM_STATE_SKIP_TASKBAR", state)
        # pause goes over IPC to the player
        self.backend.set_paused(True)
        self.assertTrue(wait_for(lambda: any(e.get("command") == ["set_property", "pause", True] for e in read_log(log))))

    def test_window_destroyed_when_stopped(self):
        self.backend.apply({"*": "/w/a.mp4"})
        self.assertEqual(len(self.backend._windows), 1)
        self.backend.stop()
        self.assertEqual(self.backend._windows, {})


if __name__ == "__main__":
    unittest.main()
