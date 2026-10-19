# Paperloop

Free, open-source **live wallpapers** for **Windows 10/11** and **Linux** (X11, Hyprland, Sway, KDE Plasma).
Play a video or image behind your desktop icons, pause automatically while you game, rotate wallpapers on a schedule, and manage everything from a small web UI.

Paperloop is an independent project. It is not affiliated with or endorsed by any commercial live-wallpaper product, and it does not use their code, assets, names or content.

> **Status: v0.1.0, early.** The core is covered by automated tests (see [Testing](#testing)), but the Windows and Wayland/KDE parts have only been written against the platform APIs, not yet run on real machines. Please open an issue with `paperloop doctor` output if something does not work.

## What works

| Feature | Windows 10/11 | Linux X11 | Hyprland / Sway | KDE Plasma (Wayland) |
| --- | --- | --- | --- | --- |
| Video wallpaper (mp4, webm, mkv, mov, gif) | yes | yes | yes (mpvpaper) | experimental (plugin) |
| Image wallpaper | yes | yes | yes | yes |
| Multi-monitor, per-monitor wallpaper | yes | yes | yes | one wallpaper for all |
| Auto-pause: fullscreen app | yes | yes (needs `xprop`) | yes | not yet |
| Auto-pause: maximized app | yes | yes | no | not yet |
| Auto-pause: on battery | yes | yes | yes | yes |
| Per-app pause / ignore rules | yes | yes | yes | not yet |
| Playlists (interval, shuffle, time-of-day) | yes | yes | yes | yes |
| Web UI, CLI, autostart | yes | yes | yes | yes |
| Tray icon (optional) | yes | yes | depends on your bar | depends |

**Not included** (and not planned for 0.x): HTML/web wallpapers, interactive "scene" wallpapers and an editor, a community wallpaper catalogue, RGB lighting sync, a phone companion app. Bring your own videos and images.

GNOME on Wayland has no desktop-background API for video; log in with "GNOME on Xorg" or use another desktop.

## Install

You need [mpv](https://mpv.io). Paperloop uses it to decode and draw.

### CachyOS / Arch

```bash
sudo pacman -S mpv python-pipx xorg-xprop      # xprop is for fullscreen detection on X11
pipx install git+https://github.com/dinaxy148822822-create/paperloop
paperloop doctor                                # tells you what is missing
```

- **X11 session** (KDE Plasma X11, Xfce, i3, GNOME on Xorg): nothing else needed.
- **Hyprland / Sway**: `paru -S mpvpaper` (AUR).
- **KDE Plasma on Wayland** (the CachyOS default): `sudo pacman -S qt6-tools`, then `paperloop kde-install` once, and log out and in.

There is also a `PKGBUILD` in `packaging/` for `makepkg -si`.

### Windows 10/11

Download `paperloop-windows.zip` from the [Releases](../../releases) page, unzip it anywhere and run `paperloop.exe`. The zip bundles mpv when the release build could fetch it; otherwise install mpv (`winget install mpv`) or put `mpv.exe` next to `paperloop.exe`.

From source: `pip install .[tray]` then `python -m paperloop`.

## Use

```bash
paperloop                       # start (opens the web UI at http://127.0.0.1:8765)
paperloop add ~/Videos/walls    # add a folder to the library
paperloop set ~/Videos/walls/rain.mp4
paperloop set --monitor HDMI-1 ~/Videos/walls/city.mp4
paperloop pause | resume | next | stop
paperloop autostart enable      # start at login
paperloop doctor
```

Everything is also available in the web UI: pick wallpapers from a thumbnail grid, tick "+ playlist", set pause rules, fit mode (fill/fit/stretch), mute and FPS cap.

Config lives in `%APPDATA%\paperloop\config.json` on Windows and `~/.config/paperloop/config.json` on Linux. Per-app rules go there, for example:

```json
"pause": { "app_rules": [
  { "process": "eldenring.exe", "action": "pause" },
  { "process": "vlc", "action": "ignore" }
] }
```

## How it works

```
paperloop daemon
 ├─ playlist.py   which wallpaper should play now (pure logic)
 ├─ rules.py      should it be paused? (pure logic)
 ├─ sensors.py    foreground window, fullscreen, battery (per OS)
 ├─ backends/     put mpv *behind* the desktop
 │    windows.py  re-parents an mpv window under the WorkerW behind the icons
 │    x11.py      creates a desktop-type X window through libX11 and runs mpv with --wid
 │    mpvpaper.py wlr-layer-shell compositors via mpvpaper
 │    kde.py      Plasma wallpaper plugin (kde/org.paperloop.video) driven through plasmashell
 └─ webserver.py  local UI + JSON API on 127.0.0.1
```

Pausing sends `pause` to mpv over its IPC socket, so a paused wallpaper uses no decoding.

### Security

The web UI listens on `127.0.0.1` only. Every API call needs a random token (stored in your config folder, mode 0600), the `Host` header is checked against DNS-rebinding, and wallpapers can only be files inside your library folders.

## Testing

```bash
python -m unittest discover -s tests -t .
```

The suite covers playlists, pause rules, config, the library, mpv argument building, the per-monitor process handling (against a fake mpv), the daemon loop, the web API and its auth, and a real X server (Xvfb) check that the wallpaper window is created as a desktop-type window. CI runs it on Linux and Windows.

## Contributing

Issues and PRs are welcome, especially reports and fixes from real Windows 10/11, KDE Wayland, Hyprland and Sway machines. Run `paperloop doctor` and include its output.

## License

MIT. mpv is a separate program under its own license (GPL/LGPL); Paperloop only launches it.
