#!/usr/bin/env bash
# DJI Footage Importer - uninstaller. Never deletes footage without explicit
# confirmation.
set -euo pipefail

APP_NAME="dji-footage-importer"
LOCAL_SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$LOCAL_SHARE/$APP_NAME"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$LOCAL_SHARE/applications"
DESKTOP_ID="import-from-dji.desktop"

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

# Resolve the Videos directory before removing the package.
VIDEOS_DIR="$HOME/Videos"
UD="${XDG_CONFIG_HOME:-$HOME/.config}/user-dirs.dirs"
if [ -f "$UD" ]; then
  line="$(grep '^XDG_VIDEOS_DIR=' "$UD" | head -n1 || true)"
  if [ -n "$line" ]; then
    val="${line#*=}"
    val="${val%\"}"
    val="${val#\"}"
    val="${val/\$HOME/$HOME}"
    VIDEOS_DIR="$val"
  fi
fi

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

rm -rf "$PREFIX"
rm -f "$BIN_DIR/$APP_NAME"
rm -f "$APPS_DIR/$DESKTOP_ID"
rm -f "$DESKTOP_DIR/$DESKTOP_ID"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi
echo "Removed the DJI Footage Importer application files."

echo
echo "Your footage and import records were NOT deleted."
echo "Location: $VIDEOS_DIR/Library/DJI"

if [ "$PURGE" -eq 1 ]; then
  echo
  echo "WARNING: --purge permanently deletes ALL imported originals and prepared files."
  read -r -p "Type DELETE to continue: " answer
  if [ "$answer" = "DELETE" ]; then
    rm -rf "$VIDEOS_DIR/Library/DJI"
    echo "Deleted $VIDEOS_DIR/Library/DJI"
  else
    echo "Purge cancelled; nothing else was deleted."
  fi
fi
