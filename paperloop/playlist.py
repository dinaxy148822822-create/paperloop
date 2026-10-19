"""Playlist scheduling. Pure logic, no I/O, so it is easy to test."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlaylistState:
    index: int = -1
    last_switch: float = 0.0  # epoch seconds


def _minutes(hhmm: str) -> int | None:
    try:
        h, m = hhmm.split(":")
        h, m = int(h), int(m)
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h * 60 + m


def scheduled_item(schedule: list[dict], now: datetime) -> str | None:
    """The entry whose start time most recently passed (wraps past midnight)."""
    entries = []
    for e in schedule:
        mins = _minutes(str(e.get("at", "")))
        if mins is not None and e.get("item"):
            entries.append((mins, e["item"]))
    if not entries:
        return None
    entries.sort()
    current = now.hour * 60 + now.minute
    chosen = entries[-1][1]  # before the first slot of the day: yesterday's last entry
    for mins, item in entries:
        if mins <= current:
            chosen = item
    return chosen


def next_wallpaper(
    playlist: dict,
    current: str | None,
    state: PlaylistState,
    now_ts: float,
    now: datetime,
    rng: random.Random | None = None,
    force: bool = False,
) -> str | None:
    """Return the wallpaper to switch to, or None to keep what is playing."""
    if not playlist.get("enabled") and not force:
        return None
    rng = rng or random
    mode = playlist.get("mode", "interval")

    if mode == "schedule" and not force:
        item = scheduled_item(playlist.get("schedule", []), now)
        if item and item != current:
            state.last_switch = now_ts
            return item
        return None

    items = [i for i in playlist.get("items", []) if i]
    if not items:
        return None
    due = force or state.index < 0 or (
        now_ts - state.last_switch >= max(1, int(playlist.get("interval_minutes", 15))) * 60
    )
    if not due:
        return None
    if playlist.get("shuffle") and len(items) > 1:
        choices = [i for i in items if i != current]
        pick = rng.choice(choices)
        state.index = items.index(pick)
    else:
        state.index = (state.index + 1) % len(items)
        pick = items[state.index]
    state.last_switch = now_ts
    return pick
