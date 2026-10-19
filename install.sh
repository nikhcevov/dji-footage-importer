#!/usr/bin/env bash
# DJI Footage Importer - user-local installer for Arch / CachyOS.
set -euo pipefail

APP_NAME="dji-footage-importer"
REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$LOCAL_SHARE/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$LOCAL_SHARE/applications"
LAUNCHER="$BIN_DIR/$APP_NAME"
DESKTOP_ID="import-from-dji.desktop"
SRC_DIR="$REPO_DIR/src/dji_importer"

info() { printf '==> %s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

# 1. System dependencies -----------------------------------------------------
required=()
command -v ffmpeg  >/dev/null 2>&1 || required+=("ffmpeg")
command -v ffprobe >/dev/null 2>&1 || required+=("ffmpeg")
command -v python3 >/dev/null 2>&1 || required+=("python")
if ! python3 -c 'import PySide6' >/dev/null 2>&1; then
  required+=("pyside6")
fi

if ((${#required[@]})); then
  printf 'Missing system packages: %s\n' "${required[*]}"
  printf 'These provide the GUI toolkit (PySide6), FFmpeg/FFprobe, and Python.\n'
  printf 'Install them with:\n\n  sudo pacman -S %s\n\n' "${required[*]}"
  exit 1
fi

[ -d "$SRC_DIR" ] || fail "Python package not found at $SRC_DIR"

# 2. Install the application code -------------------------------------------
info "Installing application to $PREFIX"
mkdir -p "$PREFIX/lib" "$BIN_DIR" "$APPS_DIR"
rm -rf "$PREFIX/lib/dji_importer"
cp -r "$SRC_DIR" "$PREFIX/lib/dji_importer"

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$PREFIX/lib\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m dji_importer "\$@"
EOF
chmod +x "$LAUNCHER"

# 3. Desktop entry -----------------------------------------------------------
info "Registering desktop launcher"
sed "s|@EXEC@|$LAUNCHER|g" "$REPO_DIR/resources/dji-importer.desktop" \
  > "$APPS_DIR/$DESKTOP_ID"
chmod +x "$APPS_DIR/$DESKTOP_ID"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$APPS_DIR/$DESKTOP_ID" || true
fi

# Resolve the desktop directory (KDE may localise it), fall back to ~/Desktop.
DESKTOP_DIR="$HOME/Desktop"
UD="${XDG_CONFIG_HOME:-$HOME/.config}/user-dirs.dirs"
if [ -f "$UD" ]; then
  line="$(grep '^XDG_DESKTOP_DIR=' "$UD" | head -n1 || true)"
  if [ -n "$line" ]; then
    val="${line#*=}"
    val="${val%\"}"
    val="${val#\"}"
    val="${val/\$HOME/$HOME}"
    [ -n "$val" ] && DESKTOP_DIR="$val"
  fi
fi
if [ -n "$DESKTOP_DIR" ] && [ "$DESKTOP_DIR" != "$HOME" ]; then
  info "Creating desktop shortcut in $DESKTOP_DIR"
  mkdir -p "$DESKTOP_DIR"
  cp "$APPS_DIR/$DESKTOP_ID" "$DESKTOP_DIR/$DESKTOP_ID"
  chmod +x "$DESKTOP_DIR/$DESKTOP_ID"
  gio set "$DESKTOP_DIR/$DESKTOP_ID" metadata::trusted true >/dev/null 2>&1 || true
fi

# 4. Destination directories -------------------------------------------------
VIDEOS_DIR="$(PYTHONPATH="$PREFIX/lib" python3 -c 'from dji_importer import config; print(config.videos_dir())')"
info "Preparing destination $VIDEOS_DIR/Library/DJI"
mkdir -p "$VIDEOS_DIR/Library/DJI" "$VIDEOS_DIR/Library/DJI/.original" \
  "$VIDEOS_DIR/Library/DJI/.importer/staging"

info "Installed. Launch 'Import from DJI' from the menu or desktop shortcut."
info "CLI: $LAUNCHER scan|import|verify|repair"
