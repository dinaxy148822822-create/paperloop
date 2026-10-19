"""Finding wallpapers on disk."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".gif"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class Wallpaper:
    path: str
    title: str
    kind: str  # "video" | "image"

    def to_dict(self) -> dict:
        return {"path": self.path, "title": self.title, "kind": self.kind}


def kind_of(path: str | Path) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    return None


def scan(dirs: list[str], limit: int = 5000) -> list[Wallpaper]:
    found: dict[str, Wallpaper] = {}
    for d in dirs:
        root = Path(d).expanduser()
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if len(found) >= limit:
                break
            if not p.is_file():
                continue
            kind = kind_of(p)
            if kind:
                real = str(p.resolve())
                found[real] = Wallpaper(real, p.stem, kind)
    return sorted(found.values(), key=lambda w: w.title.lower())


def is_allowed(path: str, dirs: list[str]) -> bool:
    """A wallpaper must be a media file inside one of the library folders."""
    try:
        target = Path(path).resolve()
    except OSError:
        return False
    if not target.is_file() or kind_of(target) is None:
        return False
    for d in dirs:
        try:
            target.relative_to(Path(d).expanduser().resolve())
            return True
        except (ValueError, OSError):
            continue
    return False
