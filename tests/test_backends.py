import os
import shutil
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

from paperloop import mpvctl, session
from paperloop.backends import base, kde, mpvpaper, x11
from paperloop.config import Config
from paperloop.daemon import Daemon

from .helpers import FAKE_MPV, read_log, wait_for

XRANDR = """Monitors: 2
 0: +*DP-1 2560/597x1440/336+0+0  DP-1
 1: +HDMI-1 1920/527x1080/296+2560+0  HDMI-1
"""


class PureTests(unittest.TestCase):
    def test_xrandr_parse(self):
        mons = x11.parse_xrandr_monitors(XRANDR)
        self.assertEqual([(m.name, m.x, m.y, m.w, m.h) for m in mons], [("DP-1", 0, 0, 2560, 1440), ("HDMI-1", 2560, 0, 1920, 1080)])

    def test_resolve_targets_specific_beats_default(self):
        mons = x11.parse_xrandr_monitors(XRANDR)
        t = base.resolve_targets({"*": "/d.mp4", "HDMI-1": "/h.mp4"}, mons)
        self.assertEqual([(m.name, p) for m, p in t], [("DP-1", "/d.mp4"), ("HDMI-1", "/h.mp4")])

    def test_resolve_targets_skips_unassigned(self):
        mons = x11.parse_xrandr_monitors(XRANDR)
        self.assertEqual(len(base.resolve_targets({"DP-1": "/a.mp4"}, mons)), 1)

    def test_mpv_options_reflect_config(self):
        opts = mpvctl.mpv_options(Config({"mute": False, "volume": 30, "fit": "stretch", "fps_cap": 30}), "/tmp/s", "t")
        self.assertIn("--volume=30", opts)
        self.assertIn("--keepaspect=no", opts)
        self.assertIn("--vf=fps=30", opts)
        self.assertNotIn("--no-audio", opts)
        fill = mpvctl.mpv_options(Config(), "/tmp/s", "t")
        self.assertIn("--panscan=1.0", fill)
        self.assertIn("--no-audio", fill)
        self.assertIn("--no-config", fill)  # the user's own mpv.conf must not interfere

    def test_mpvpaper_option_string(self):
        s = mpvpaper.option_string(["--no-audio", "--title=x", "--force-window=yes", "--loop-file=inf", "--no-border"])
        self.assertEqual(s, "no-audio loop-file=inf")

    def test_kde_script_escapes_and_targets_plugin(self):
        js = kde.evaluate_script_js('/tmp/a "b".mp4', True)
        self.assertIn("org.paperloop.video", js)
        self.assertIn("Paused', true", js)
        self.assertIn(r"%22b%22", js)  # URL-encoded, so no quote can break out of the string
        self.assertIn("VideoUrl", js)

    @unittest.skipIf(sys.platform == "win32", "linux session detection")
    def test_session_detection(self):
        keep = dict(os.environ)
        try:
            for k in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "SWAYSOCK"):
                os.environ.pop(k, None)
            os.environ.update({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"})
            self.assertEqual(session.detect(), "kde-wayland")
            os.environ["XDG_CURRENT_DESKTOP"] = "GNOME"
            self.assertEqual(session.detect(), "gnome-wayland")
            os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "x"
            self.assertEqual(session.detect(), "wlroots")
            os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE")
            os.environ.update({"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "KDE"})
            os.environ.pop("WAYLAND_DISPLAY", None)
            self.assertEqual(session.detect(), "x11")
        finally:
            os.environ.clear()
            os.environ.update(keep)


class FakeBackend(base.MpvBackend):
    """MpvBackend running the fake mpv, no window system needed."""
    name = "fake"

    def available(self):
        return True, "ok"

    def monitors(self):
        return [base.Monitor("A", 0, 0, 100, 100), base.Monitor("B", 100, 0, 100, 100)]

    def spawn(self, monitor, path):
        return mpvctl.MpvProcess(self.mpv_argv(monitor, path, []), mpvctl.ipc_path(monitor.name))


@unittest.skipIf(sys.platform == "win32", "fake mpv speaks unix sockets")
class MpvBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "log")
        os.environ["FAKE_MPV_LOG"] = self.log
        os.environ["XDG_RUNTIME_DIR"] = self.tmp.name
        self.cfg = Config({"mpv_path": FAKE_MPV})
        self.backend = FakeBackend(self.cfg)

    def tearDown(self):
        self.backend.stop()
        self.tmp.cleanup()

    def spawned(self):
        return [e for e in read_log(self.log) if "argv" in e]

    def commands(self):
        return [e["command"] for e in read_log(self.log) if "command" in e]

    def test_spawns_one_player_per_monitor_with_the_file(self):
        self.backend.apply({"*": "/w/a.mp4"})
        self.assertTrue(wait_for(lambda: len(self.spawned()) == 2))
        for e in self.spawned():
            self.assertEqual(e["argv"][-2:], ["--", "/w/a.mp4"])

    def test_same_assignment_does_not_respawn(self):
        self.backend.apply({"*": "/w/a.mp4"})
        wait_for(lambda: len(self.spawned()) == 2)
        self.backend.apply({"*": "/w/a.mp4"})
        self.assertEqual(len(self.spawned()), 2)

    def test_changing_wallpaper_uses_ipc_loadfile(self):
        self.backend.apply({"*": "/w/a.mp4"})
        wait_for(lambda: len(self.spawned()) == 2)
        self.backend.apply({"*": "/w/b.mp4"})
        self.assertTrue(wait_for(lambda: len([c for c in self.commands() if c[0] == "loadfile"]) == 2))
        self.assertEqual(len(self.spawned()), 2)
        self.assertEqual(self.commands()[-1], ["loadfile", "/w/b.mp4", "replace"])

    def test_pause_sends_ipc_and_new_players_start_paused(self):
        self.backend.apply({"A": "/w/a.mp4"})
        wait_for(lambda: len(self.spawned()) == 1)
        self.backend.set_paused(True)
        self.assertTrue(wait_for(lambda: ["set_property", "pause", True] in self.commands()))
        self.backend.apply({"A": "/w/a.mp4", "B": "/w/b.mp4"})
        wait_for(lambda: len(self.spawned()) == 2)
        self.assertIn("--pause", self.spawned()[-1]["argv"])

    def test_removed_monitor_player_is_stopped(self):
        self.backend.apply({"A": "/w/a.mp4", "B": "/w/b.mp4"})
        wait_for(lambda: len(self.backend.players) == 2)
        proc = self.backend.players["B"].proc
        self.backend.apply({"A": "/w/a.mp4"})
        self.assertEqual(list(self.backend.players), ["A"])
        self.assertTrue(wait_for(lambda: proc.poll() is not None))

    def test_missing_mpv_gives_clear_error(self):
        b = FakeBackend(Config({"mpv_path": "/nonexistent/mpv"}))
        keep = shutil.which
        shutil.which = lambda *_a, **_k: None
        try:
            with self.assertRaisesRegex(RuntimeError, "mpv was not found"):
                b.apply({"A": "/w/a.mp4"})
        finally:
            shutil.which = keep


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        for n in ("a.mp4", "b.mp4"):
            (root / n).write_bytes(b"x")
        self.root = root
        self.cfg = Config({"library_dirs": [str(root)]}, path=root / "config.json")
        self.calls = []

        class Rec(base.Backend):
            name = "rec"

            def available(s):
                return True, "ok"

            def apply(s, a):
                self.calls.append(("apply", dict(a)))

            def set_paused(s, p):
                self.calls.append(("pause", p))

            def stop(s):
                self.calls.append(("stop",))

        self.fg = None
        self.battery = False
        self.d = Daemon(self.cfg, Rec(self.cfg), "x11", fg_reader=lambda: self.fg, battery_reader=lambda: self.battery)

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_wallpaper_applies_and_persists(self):
        self.d.set_wallpaper(str(self.root / "a.mp4"))
        self.assertEqual(self.calls[0], ("apply", {"*": str((self.root / "a.mp4"))}))
        self.assertEqual(Config.load(self.cfg.path)["assignments"]["*"], str(self.root / "a.mp4"))

    def test_rejects_files_outside_library(self):
        with self.assertRaises(ValueError):
            self.d.set_wallpaper("/etc/passwd")

    def test_fullscreen_app_pauses_then_resumes(self):
        from paperloop.rules import Foreground
        self.d.set_wallpaper(str(self.root / "a.mp4"))
        self.calls.clear()
        self.fg = Foreground("game", True, False)
        self.d.tick()
        self.assertIn(("pause", True), self.calls)
        self.assertTrue(self.d.status()["paused"])
        self.fg = Foreground("firefox", False, False)
        self.d.tick()
        self.assertIn(("pause", False), self.calls)
        self.assertFalse(self.d.status()["paused"])

    def test_user_pause_survives_auto_resume(self):
        self.d.pause(True)
        self.d.tick()
        self.assertTrue(self.d.status()["paused"])
        self.assertEqual(self.d.status()["pause_reason"], "paused by you")

    def test_playlist_tick_switches_wallpaper(self):
        a, b = str(self.root / "a.mp4"), str(self.root / "b.mp4")
        self.cfg.update({"playlist": {"enabled": True, "items": [a, b], "interval_minutes": 1}})
        now = [1000.0]
        self.d.clock = lambda: now[0]
        self.d.tick()
        self.assertEqual(self.cfg["assignments"]["*"], a)
        now[0] += 61
        self.d.tick()
        self.assertEqual(self.cfg["assignments"]["*"], b)
        self.assertEqual(self.calls.count(("apply", {"*": b})), 1)

    def test_backend_error_is_reported_not_raised(self):
        def boom(a):
            raise RuntimeError("mpv was not found")
        self.d.backend.apply = boom
        self.d.set_wallpaper(str(self.root / "a.mp4"))
        self.assertIn("mpv was not found", self.d.status()["error"])


if __name__ == "__main__":
    unittest.main()
