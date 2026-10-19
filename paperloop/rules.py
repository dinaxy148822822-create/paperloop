"""Decide whether the wallpaper should be paused. Pure logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Foreground:
    process: str = ""  # lowercase executable name, e.g. "game.exe" or "steam"
    fullscreen: bool = False
    maximized: bool = False


def _norm(name: str) -> str:
    name = name.strip().lower()
    return name[:-4] if name.endswith(".exe") else name


def should_pause(pause_cfg: dict, fg: Foreground | None, on_battery: bool) -> tuple[bool, str]:
    """Returns (paused, reason). Per-app rules win over the generic switches."""
    if pause_cfg.get("on_battery") and on_battery:
        return True, "on battery"
    if fg is None:
        return False, ""
    proc = _norm(fg.process)
    for rule in pause_cfg.get("app_rules", []):
        if _norm(str(rule.get("process", ""))) == proc and proc:
            if rule.get("action") == "ignore":
                return False, ""
            return True, f"app rule: {fg.process}"
    if pause_cfg.get("on_fullscreen") and fg.fullscreen:
        return True, "fullscreen app"
    if pause_cfg.get("on_maximized") and fg.maximized:
        return True, "maximized app"
    return False, ""
