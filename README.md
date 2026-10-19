# DJI Footage Importer

A small, native Linux desktop app that imports recordings from a DJI Osmo
Pocket camera over USB-C and prepares editing-ready files for **DaVinci
Resolve Studio**.

- Connect the camera, open **Import from DJI**, press one button.
- Originals are preserved byte-for-byte in `.original/`.
- Video is **never re-encoded**: the compressed HEVC/H.264 stream is stream-copied
  into a MOV container; unsupported AAC audio is converted to 24-bit PCM.
- Imports are idempotent and resumable. No source files are modified or deleted.

## Requirements

- CachyOS / Arch Linux, KDE Plasma (Wayland), Python 3.10+
- `ffmpeg`, `python`, `pyside6` (system packages)
- DaVinci Resolve **Studio** (HEVC 10-bit decode requires Studio on Linux)

## Install options

Choose **one** route; both produce a working launcher.

### A. User-local, no sudo

```bash
./install.sh
```

Installs under `~/.local/share/dji-footage-importer` and
`~/.local/bin/dji-footage-importer`, registers **Import from DJI** in the
application menu, and adds a desktop shortcut (the resolved
`XDG_DESKTOP_DIR`, normally `~/Desktop`). If a dependency is missing the script
prints the exact `pacman` command and stops.

Remove it with:

```bash
./uninstall.sh          # removes the app only
./uninstall.sh --purge  # also deletes footage, after typing DELETE
```

### B. pacman / yay (system package)

```bash
cd packaging
makepkg -si             # or: yay -Bi .
```

The package owns exactly:

- `/usr/bin/dji-footage-importer`
- `/usr/lib/dji-footage-importer/`
- `/usr/share/applications/import-from-dji.desktop`

Remove it with:

```bash
sudo pacman -R dji-footage-importer    # remove the package only
sudo pacman -Rns dji-footage-importer  # also remove unused dependencies
# with yay: yay -Rns dji-footage-importer
```

Footage, originals, the SQLite state and logs live in the user's home
(`<Videos>/DJI`, `~/.local/state/dji-footage-importer`). They are created by the
application at runtime, are **not** owned by the package, and are never touched
by `pacman -R`. Use `-R` rather than `-Rns` if you want to keep dependencies
such as `pyside6` installed.

The pacman route installs the menu entry; the user-local route also creates the
desktop shortcut.

## Destination layout

```
<Videos>/DJI/
├── footage/YYYY-MM-DD/    editing-ready .mov files (import these in Resolve)
├── .original/YYYY-MM-DD/  unmodified camera .mp4 files
└── .importer/             state.sqlite, staging/
```

The Videos directory is resolved through XDG user directories, not assumed to be
`~/Videos`.

## How it works

For each new recording the importer runs the same four stages:

1. **Inspect** — probe streams and capture date.
2. **Preserve** — copy to staging, SHA-256 the source and the copy, verify, then
   atomically publish the original.
3. **Prepare** — remux from the locally stored original with
   `ffmpeg -map 0:v:0 -map 0:a -c:v copy -c:a pcm_s24le -ar 48000`, verify the
   result, then atomically publish the `.mov`.
4. **Commit** — record success in SQLite only when both files are valid.

Failures keep the verified original and can be retried; an import lock prevents
concurrent runs.

## Command line (diagnostics)

```bash
dji-footage-importer scan
dji-footage-importer import [--source /path/to/folder]
dji-footage-importer verify
dji-footage-importer repair
```

Logs are written to `~/.local/state/dji-footage-importer/app.log` (rotated).

## Validation notes

- Prepared MOVs are validated stream-by-stream with FFprobe (video codec
  unchanged, audio present, duration preserved).
- Physical USB detection and DaVinci playback were verified/recorded manually;
  see `idea.md` for the acceptance checklist. FFprobe alone is not treated as
  proof of playback.
