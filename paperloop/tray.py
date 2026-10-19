"""Optional system tray icon (needs `pip install paperloop[tray]`: pystray + Pillow)."""

from __future__ import annotations

import threading
import webbrowser


def available() -> bool:
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
    except Exception:  # noqa: BLE001 - tray backends can fail in many ways
        return False
    return True


def _image():
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (18, 20, 26, 255))
    d = ImageDraw.Draw(img)
    d.arc((8, 12, 56, 52), 200, 340, fill=(110, 168, 255, 255), width=6)
    d.arc((8, 26, 56, 66), 200, 340, fill=(139, 92, 246, 255), width=6)
    return img


def run(daemon, url: str, on_quit) -> threading.Thread | None:
    """Starts the tray icon in a background thread. Returns None if it cannot run here."""
    if not available():
        return None
    import pystray

    def toggle_pause(icon, item):
        daemon.pause(not daemon.user_paused)

    menu = pystray.Menu(
        pystray.MenuItem("Open Paperloop", lambda icon, item: webbrowser.open(url), default=True),
        pystray.MenuItem("Pause", toggle_pause, checked=lambda item: daemon.user_paused),
        pystray.MenuItem("Next wallpaper", lambda icon, item: daemon.next_wallpaper()),
        pystray.MenuItem("Quit", lambda icon, item: (icon.stop(), on_quit())),
    )
    icon = pystray.Icon("paperloop", _image(), "Paperloop", menu)
    thread = threading.Thread(target=icon.run, name="paperloop-tray", daemon=True)
    thread.start()
    return thread
