"""The long-running process: applies wallpapers, runs playlists and pause rules, serves the UI."""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime

from . import library, playlist, rules, sensors, session
from .backends.base import Backend
from .config import Config


class Daemon:
    def __init__(self, cfg: Config, backend: Backend, session_kind: str | None = None, clock=time.time,
                 fg_reader=None, battery_reader=None):
        self.cfg = cfg
        self.backend = backend
        self.session_kind = session_kind or session.detect()
        self.clock = clock
        self._fg = fg_reader or (lambda: sensors.foreground(self.session_kind))
        self._battery = battery_reader or sensors.on_battery
        self.state = playlist.PlaylistState()
        self.user_paused = False
        self.auto_paused = False
        self.pause_reason = ""
        self.last_error = ""
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._applied: dict[str, str] | None = None

    # ------------------------------------------------------------ actions
    def apply_assignments(self) -> None:
        assignments = {k: v for k, v in self.cfg["assignments"].items() if v}
        try:
            self.backend.apply(assignments)
            self.last_error = ""
        except Exception as exc:  # noqa: BLE001 - surface to UI instead of crashing the loop
            self.last_error = str(exc)
        self._applied = dict(assignments)
        self._push_pause()

    def set_wallpaper(self, path: str, monitor: str = "*") -> None:
        with self.lock:
            if not library.is_allowed(path, self.cfg["library_dirs"]):
                raise ValueError("wallpaper must be a media file inside a library folder")
            self.cfg.data["assignments"][monitor] = path
            self.cfg.save()
            self.apply_assignments()

    def next_wallpaper(self) -> str | None:
        with self.lock:
            now = datetime.now()
            current = self.cfg["assignments"].get("*")
            pick = playlist.next_wallpaper(self.cfg["playlist"], current, self.state, self.clock(), now, force=True)
            if pick and library.is_allowed(pick, self.cfg["library_dirs"]):
                self.cfg.data["assignments"]["*"] = pick
                self.cfg.save()
                self.apply_assignments()
            return pick

    def pause(self, paused: bool) -> None:
        with self.lock:
            self.user_paused = paused
            self._push_pause()

    def stop_wallpaper(self) -> None:
        with self.lock:
            self.backend.stop()
            self._applied = None

    def effective_paused(self) -> bool:
        return self.user_paused or self.auto_paused

    def _push_pause(self) -> None:
        try:
            self.backend.set_paused(self.effective_paused())
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)

    # --------------------------------------------------------------- loop
    def tick(self) -> None:
        with self.lock:
            # 1. playlist
            if self.cfg["playlist"].get("enabled"):
                current = self.cfg["assignments"].get("*")
                pick = playlist.next_wallpaper(self.cfg["playlist"], current, self.state, self.clock(), datetime.now())
                if pick and pick != current and library.is_allowed(pick, self.cfg["library_dirs"]):
                    self.cfg.data["assignments"]["*"] = pick
                    self.cfg.save()
            # 2. (re)apply if config changed or a player died
            assignments = {k: v for k, v in self.cfg["assignments"].items() if v}
            if assignments != self._applied and assignments:
                self.apply_assignments()
            elif assignments:
                self._revive()
            # 3. pause rules
            paused, reason = rules.should_pause(self.cfg["pause"], self._fg(), self._battery())
            if paused != self.auto_paused or reason != self.pause_reason:
                self.auto_paused, self.pause_reason = paused, reason
                self._push_pause()

    def _revive(self) -> None:
        players = getattr(self.backend, "players", None)
        if players and any(not p.alive() for p in players.values()):
            self.apply_assignments()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
            self._stop.wait(float(self.cfg["poll_seconds"]))

    def shutdown(self) -> None:
        self._stop.set()
        with self.lock:
            self.backend.stop()

    def status(self) -> dict:
        return {
            "backend": self.backend.name,
            "session": self.session_kind,
            "paused": self.effective_paused(),
            "user_paused": self.user_paused,
            "pause_reason": "paused by you" if self.user_paused else self.pause_reason,
            "error": self.last_error,
            "assignments": self.cfg["assignments"],
        }
