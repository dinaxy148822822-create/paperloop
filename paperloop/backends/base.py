"""Backend interface plus the shared mpv-process bookkeeping."""

from __future__ import annotations

import abc
from dataclasses import dataclass

from .. import mpvctl


@dataclass(frozen=True)
class Monitor:
    name: str
    x: int = 0
    y: int = 0
    w: int = 1920
    h: int = 1080


def resolve_targets(assignments: dict[str, str], monitors: list[Monitor]) -> list[tuple[Monitor, str]]:
    """Pair every monitor with its wallpaper: its own entry first, then the "*" default."""
    out = []
    default = assignments.get("*")
    for mon in monitors:
        path = assignments.get(mon.name) or default
        if path:
            out.append((mon, path))
    return out


class Backend(abc.ABC):
    name = "base"

    def __init__(self, cfg):
        self.cfg = cfg
        self.paused = False

    @abc.abstractmethod
    def available(self) -> tuple[bool, str]:
        """(usable, human readable detail or what is missing)."""

    @abc.abstractmethod
    def apply(self, assignments: dict[str, str]) -> None:
        """Make the screens show these wallpapers (monitor name or "*" -> path)."""

    @abc.abstractmethod
    def set_paused(self, paused: bool) -> None: ...

    @abc.abstractmethod
    def stop(self) -> None: ...


class MpvBackend(Backend):
    """Backends that run one mpv process per monitor."""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.players: dict[str, mpvctl.MpvProcess] = {}
        self.current: dict[str, str] = {}

    # subclasses -------------------------------------------------------
    @abc.abstractmethod
    def monitors(self) -> list[Monitor]: ...

    @abc.abstractmethod
    def spawn(self, monitor: Monitor, path: str) -> mpvctl.MpvProcess: ...

    def release(self, monitor_name: str) -> None:
        """Hook for backends that own extra resources per monitor."""

    # shared -----------------------------------------------------------
    def mpv_exe(self) -> str | None:
        return mpvctl.find_mpv(self.cfg["mpv_path"])

    def mpv_argv(self, monitor: Monitor, path: str, extra: list[str]) -> list[str]:
        exe = self.mpv_exe()
        if not exe:
            raise RuntimeError("mpv was not found. Install mpv or set mpv_path in the config.")
        ipc = mpvctl.ipc_path(monitor.name)
        opts = mpvctl.mpv_options(self.cfg, ipc, f"paperloop-{monitor.name}")
        if self.paused:
            opts.append("--pause")
        return [exe, *opts, *extra, "--", path]

    def apply(self, assignments: dict[str, str]) -> None:
        targets = resolve_targets(assignments, self.monitors())
        wanted = {m.name for m, _ in targets}
        for name in list(self.players):
            if name not in wanted:
                self._drop(name)
        for mon, path in targets:
            player = self.players.get(mon.name)
            if player and player.alive():
                if self.current.get(mon.name) != path:
                    if not player.load(path):
                        self._drop(mon.name)
                        player = None
                    else:
                        self.current[mon.name] = path
                        continue
                else:
                    continue
            elif player:
                self._drop(mon.name)
            self.players[mon.name] = self.spawn(mon, path)
            self.current[mon.name] = path

    def _drop(self, name: str) -> None:
        player = self.players.pop(name, None)
        self.current.pop(name, None)
        if player:
            player.terminate()
        self.release(name)

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        for player in self.players.values():
            player.set_pause(paused)

    def stop(self) -> None:
        for name in list(self.players):
            self._drop(name)
