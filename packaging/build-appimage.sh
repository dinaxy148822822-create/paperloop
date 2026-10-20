#!/usr/bin/env bash
# Build Paperloop-<arch>.AppImage from a PyInstaller --onedir build.
# Usage (from the repository root):  packaging/build-appimage.sh [path/to/dist/paperloop]
# The AppImage does not bundle mpv: the host needs mpv installed (see docs/INSTALL-LINUX.md).
set -euo pipefail

ARCH="${ARCH:-x86_64}"
DIST="${1:-dist/paperloop}"
VERSION="$(python3 -c 'import paperloop; print(paperloop.__version__)')"
APPDIR="build/AppDir"
OUT="${OUT:-Paperloop-${ARCH}.AppImage}"
TOOL="build/appimagetool-${ARCH}.AppImage"

[ -x "$DIST/paperloop" ] || { echo "error: $DIST/paperloop not found (build with PyInstaller --onedir first)" >&2; exit 1; }

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "$DIST" "$APPDIR/usr/bin/paperloop"
cp packaging/appimage/paperloop.desktop "$APPDIR/paperloop.desktop"
cp paperloop/web/icon.svg "$APPDIR/paperloop.svg"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/paperloop/paperloop" "$@"
RUN
chmod +x "$APPDIR/AppRun"

if [ ! -x "$TOOL" ]; then
  mkdir -p build
  curl -fsSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  chmod +x "$TOOL"
fi

# runners and containers have no FUSE: let the tool unpack itself instead of mounting
ARCH="$ARCH" VERSION="$VERSION" APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT"
echo "built $OUT"
