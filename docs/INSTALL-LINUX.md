# Installing Paperloop on Linux

Paperloop needs three things: **Python 3.9+**, **[mpv](https://mpv.io)**, and a desktop it knows how to draw behind.
Run `paperloop doctor` at any point; it prints what is missing for your session.

## 1. Which session are you on?

```bash
echo $XDG_SESSION_TYPE; echo $XDG_CURRENT_DESKTOP
```

| You see | Meaning | What to do |
| --- | --- | --- |
| `x11` | Xorg session (Xfce, Cinnamon, MATE, i3, KDE X11, GNOME on Xorg, ...) | Works fully. Install the X11 tools below. |
| `wayland` + Hyprland / Sway / river / Wayfire | wlroots compositor | Install `mpvpaper` (section 4). |
| `wayland` + KDE | Plasma on Wayland | Plasma 6 only, experimental (section 5). |
| `wayland` + GNOME | GNOME on Wayland | Not supported for video. Log out and pick the **Xorg** session from the gear icon on the login screen, or use another desktop. Newer GNOME/Ubuntu releases have removed the Xorg session; then use KDE, Xfce, Cinnamon or MATE. |

Python older than 3.9 (for example Ubuntu 20.04, which ships 3.8) is not supported.

## 2. Install the dependencies

Pick your distribution. `xprop` is used to detect fullscreen apps for auto-pause, `xrandr` to find your monitors, `ffmpeg` is optional and makes video thumbnails in the web UI.

### Ubuntu 22.04+, Debian 12+, Linux Mint, Pop!_OS, Zorin, elementary OS

```bash
sudo apt update
sudo apt install mpv x11-utils x11-xserver-utils ffmpeg git pipx
pipx ensurepath          # then open a new terminal
```

### Fedora

```bash
sudo dnf install mpv xorg-x11-utils xrandr ffmpeg git pipx
```

If `dnf` cannot find `mpv` or `ffmpeg`, enable [RPM Fusion](https://rpmfusion.org/Configuration) first.

### openSUSE (Tumbleweed / Leap)

```bash
sudo zypper install mpv xprop xrandr ffmpeg git python3-pipx
```

Codec support is better with the [Packman](https://en.opensuse.org/Additional_package_repositories#Packman) repository.

### Arch, Manjaro, EndeavourOS, CachyOS

```bash
sudo pacman -S mpv xorg-xprop xorg-xrandr ffmpeg git python-pipx
```

### Void, Alpine, Gentoo, NixOS, others

Install the same four things with your package manager: `mpv`, `xprop`, `xrandr`, and `python` 3.9+ with `pipx` (or `venv`). On NixOS, for a quick try: `nix-shell -p mpv xorg.xprop xorg.xrandr python3 pipx git`.

> **Use your distribution's own mpv**, not the Flatpak or Snap one. A sandboxed mpv cannot reliably embed into the desktop window or reach Paperloop's control socket.

## 3. Install Paperloop

```bash
pipx install git+https://github.com/dinaxy148822822-create/paperloop
paperloop doctor
```

If `paperloop` is "command not found", run `pipx ensurepath` and open a new terminal (the program lives in `~/.local/bin`).

Without pipx:

```bash
git clone https://github.com/dinaxy148822822-create/paperloop
cd paperloop
python3 -m venv .venv && . .venv/bin/activate
pip install .            # add ".[tray]" for the tray icon
paperloop doctor
```

Optional tray icon: `pipx inject paperloop pystray pillow` (needs a system tray; many Wayland setups and some GNOME versions do not show one).

Update later with `pipx upgrade paperloop`; remove with `pipx uninstall paperloop`.

## 4. Hyprland, Sway and other wlroots compositors

Paperloop uses [mpvpaper](https://github.com/GhostNaN/mpvpaper). It is not in the default Debian/Ubuntu/Fedora repositories.

- **Arch / CachyOS:** `paru -S mpvpaper` (AUR)
- **Others:** build it from source following its README (it needs a C compiler, meson, ninja, `libmpv`, Wayland and EGL development packages).

Then run `paperloop doctor`. Fullscreen auto-pause works through `hyprctl` or `swaymsg`.

## 5. KDE Plasma on Wayland (experimental)

This needs **Plasma 6** (for example Fedora KDE, Kubuntu 25.04+, CachyOS/Arch, openSUSE Tumbleweed). Plasma 5, as in Kubuntu 24.04, is not supported. Use an X11 session there instead.

1. Install the Qt 6 D-Bus tool that provides `qdbus6`. The package name varies: `qt6-tools` on Arch, `qt6-qttools` on Fedora, `qt6-tools-dev-tools` on Debian/Ubuntu. Check with `which qdbus6`.
2. Run `paperloop kde-install` once, then log out and in.
3. Run `paperloop`. Images use Plasma's own wallpaper tool; videos use the Paperloop wallpaper plugin.

Known limits: one wallpaper on all screens, and no auto-pause on fullscreen apps yet (pausing from the UI, the tray or on battery works).

## 5b. Plasma on X11

Nothing special: the normal X11 backend is used. This is the most complete setup on KDE today.

## 6. First run

```bash
paperloop add ~/Videos/wallpapers     # any folder with mp4/webm/mkv/gif/jpg/png files
paperloop                             # opens the web UI at http://127.0.0.1:8765
paperloop autostart enable            # start at login
```

## Troubleshooting

| Problem | Try |
| --- | --- |
| `mpv ... NOT FOUND` in `paperloop doctor` | Install mpv with your package manager, or set `"mpv_path"` in `~/.config/paperloop/config.json`. |
| `cannot talk to the X server` | You are not in an X11 session, or `DISPLAY` is not set. Check section 1. |
| Wallpaper does not pause for fullscreen apps | Install `xprop` (X11) or check `hyprctl`/`swaymsg` is on your `PATH`. |
| Wallpaper draws over your windows | Your window manager ignores the "desktop" window type. Open an issue with your WM name; tiling WMs such as i3 and bspwm may need a rule. |
| Wallpaper stays black | Try `"hwdec": "no"` in the config; hardware decoding drivers are a common cause. |
| Web UI says the daemon is unreachable | Another program uses port 8765; change `"port"` in the config and restart. |
| Nothing at all after login with autostart | Run `paperloop daemon` in a terminal to see the error message. |

If you still cannot get it working, open an issue and paste the output of `paperloop doctor`, plus your distribution and desktop.
