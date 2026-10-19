import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from paperloop import library, playlist, rules
from paperloop.config import Config
from paperloop.rules import Foreground


class PlaylistTests(unittest.TestCase):
    def pl(self, **kw):
        base = {"enabled": True, "mode": "interval", "interval_minutes": 10, "shuffle": False, "items": ["a", "b", "c"], "schedule": []}
        base.update(kw)
        return base

    def test_disabled_returns_none(self):
        st = playlist.PlaylistState()
        self.assertIsNone(playlist.next_wallpaper(self.pl(enabled=False), None, st, 0, datetime.now()))

    def test_first_pick_is_immediate_then_waits_interval(self):
        st = playlist.PlaylistState()
        now = datetime(2026, 1, 1, 12, 0)
        self.assertEqual(playlist.next_wallpaper(self.pl(), None, st, 1000, now), "a")
        self.assertIsNone(playlist.next_wallpaper(self.pl(), "a", st, 1000 + 599, now))
        self.assertEqual(playlist.next_wallpaper(self.pl(), "a", st, 1000 + 600, now), "b")

    def test_wraps_around(self):
        st = playlist.PlaylistState(index=2, last_switch=0)
        self.assertEqual(playlist.next_wallpaper(self.pl(), "c", st, 10_000, datetime.now()), "a")

    def test_shuffle_never_repeats_current(self):
        rng = random.Random(1)
        for _ in range(50):
            st = playlist.PlaylistState(index=0, last_switch=0)
            self.assertNotEqual(playlist.next_wallpaper(self.pl(shuffle=True), "a", st, 10_000, datetime.now(), rng), "a")

    def test_force_ignores_interval_and_enabled(self):
        st = playlist.PlaylistState(index=0, last_switch=999)
        self.assertEqual(playlist.next_wallpaper(self.pl(enabled=False), "a", st, 1000, datetime.now(), force=True), "b")

    def test_schedule_picks_latest_past_slot_and_wraps_midnight(self):
        sched = [{"at": "08:00", "item": "day"}, {"at": "20:00", "item": "night"}]
        self.assertEqual(playlist.scheduled_item(sched, datetime(2026, 1, 1, 9, 0)), "day")
        self.assertEqual(playlist.scheduled_item(sched, datetime(2026, 1, 1, 21, 0)), "night")
        self.assertEqual(playlist.scheduled_item(sched, datetime(2026, 1, 1, 3, 0)), "night")

    def test_schedule_mode_only_switches_on_change(self):
        st = playlist.PlaylistState()
        pl = self.pl(mode="schedule", schedule=[{"at": "08:00", "item": "day"}])
        now = datetime(2026, 1, 1, 9, 0)
        self.assertEqual(playlist.next_wallpaper(pl, None, st, 1, now), "day")
        self.assertIsNone(playlist.next_wallpaper(pl, "day", st, 2, now))

    def test_bad_schedule_entries_ignored(self):
        self.assertIsNone(playlist.scheduled_item([{"at": "25:99", "item": "x"}, {"at": "zz", "item": "y"}], datetime.now()))


class RuleTests(unittest.TestCase):
    cfg = {"on_fullscreen": True, "on_maximized": False, "on_battery": False, "app_rules": []}

    def test_fullscreen_pauses(self):
        self.assertEqual(rules.should_pause(self.cfg, Foreground("game", True, False), False), (True, "fullscreen app"))

    def test_normal_window_does_not_pause(self):
        self.assertFalse(rules.should_pause(self.cfg, Foreground("firefox", False, True), False)[0])

    def test_maximized_only_when_enabled(self):
        on = dict(self.cfg, on_maximized=True)
        self.assertTrue(rules.should_pause(on, Foreground("x", False, True), False)[0])

    def test_battery(self):
        on = dict(self.cfg, on_battery=True)
        self.assertEqual(rules.should_pause(on, None, True), (True, "on battery"))
        self.assertFalse(rules.should_pause(on, None, False)[0])

    def test_app_rule_pause_and_exe_suffix(self):
        c = dict(self.cfg, app_rules=[{"process": "Game.EXE", "action": "pause"}])
        self.assertTrue(rules.should_pause(c, Foreground("game.exe"), False)[0])
        self.assertTrue(rules.should_pause(c, Foreground("game"), False)[0])

    def test_ignore_rule_beats_fullscreen(self):
        c = dict(self.cfg, app_rules=[{"process": "vlc", "action": "ignore"}])
        self.assertFalse(rules.should_pause(c, Foreground("vlc", True, False), False)[0])

    def test_no_foreground_info_is_not_paused(self):
        self.assertFalse(rules.should_pause(self.cfg, None, False)[0])


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "sub").mkdir()
        for name in ("a.mp4", "sub/b.PNG", "c.txt", "sub/d.webm"):
            (self.root / name).write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_finds_media_recursively(self):
        found = library.scan([str(self.root)])
        self.assertEqual([w.title for w in found], ["a", "b", "d"])
        self.assertEqual({w.kind for w in found}, {"video", "image"})

    def test_missing_dir_is_ignored(self):
        self.assertEqual(library.scan([str(self.root / "nope")]), [])

    def test_is_allowed(self):
        self.assertTrue(library.is_allowed(str(self.root / "a.mp4"), [str(self.root)]))
        self.assertFalse(library.is_allowed(str(self.root / "c.txt"), [str(self.root)]))
        self.assertFalse(library.is_allowed(str(self.root / "a.mp4"), []))

    def test_path_traversal_blocked(self):
        sneaky = str(self.root / "sub" / ".." / ".." / "etc" / "passwd")
        self.assertFalse(library.is_allowed(sneaky, [str(self.root)]))


class ConfigTests(unittest.TestCase):
    def test_defaults_and_deep_merge(self):
        c = Config({"pause": {"on_battery": True}})
        self.assertTrue(c["pause"]["on_battery"])
        self.assertTrue(c["pause"]["on_fullscreen"])  # default survives the partial override

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            c = Config(path=path)
            c.update({"fit": "stretch", "playlist": {"enabled": True}})
            c.save()
            back = Config.load(path)
            self.assertEqual(back["fit"], "stretch")
            self.assertTrue(back["playlist"]["enabled"])
            self.assertEqual(back["playlist"]["interval_minutes"], 15)

    def test_corrupt_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text("{not json")
            self.assertEqual(Config.load(path)["fit"], "fill")


if __name__ == "__main__":
    unittest.main()
