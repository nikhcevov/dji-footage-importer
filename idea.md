# Technical Specification: DJI Footage Importer

## 1. Project overview

Build a lightweight native Linux desktop application called **DJI Footage Importer**.

The application imports video recordings from a DJI Osmo Pocket camera connected directly via USB-C, preserves the original recordings, and prepares editing-compatible media for DaVinci Resolve Studio on Linux.

The primary user is a non-technical video creator. She should not need to understand filesystems, video codecs, containers, FFmpeg, or terminal commands.

**Primary goal:** connect the camera, click a desktop shortcut, press one Import button, wait for completion, and start editing in DaVinci Resolve.

### Design principles

- Simple, friendly, single-window graphical interface.
- Safe, non-destructive handling of camera files.
- No unnecessary configuration during regular use.
- Idempotent imports.
- Resumable after interruptions.
- No duplicate footage.
- No video quality loss during preparation.
- Predictable output paths for DaVinci Resolve.
- Minimal installation and maintenance overhead.
- No background services or network dependencies.

## 2. Target environment

| Component        | Specification                                   |
| ---------------- | ----------------------------------------------- |
| Operating system | CachyOS (Arch Linux)                            |
| Desktop          | KDE Plasma / Wayland                            |
| GUI              | Python + PySide6 (Qt 6)                         |
| CPU              | AMD Ryzen 7 7700                                |
| GPU              | AMD Radeon RX 6900 XT                           |
| System storage   | ADATA Legend 900, 1 TB NVMe                     |
| Camera           | DJI Osmo Pocket 4                               |
| Connection       | Direct USB-C                                    |
| Editor           | DaVinci Resolve Studio for Linux                |
| Media tools      | FFmpeg / FFprobe                                |
| Local state      | SQLite                                          |
| Installation     | User-local installation and `.desktop` shortcut |

Use Python's standard library wherever possible. Prefer system-provided FFmpeg and Qt packages.

Do not introduce Electron, web servers, Docker, cloud services, or unnecessary dependencies.

## 3. User workflow

### 3.1 Launch

The user connects the camera to the PC with a USB-C cable, enables the appropriate file-transfer mode if prompted on the camera, and double-clicks the desktop shortcut:

**Import from DJI**

The application opens a compact window and immediately attempts to discover the connected camera.

### 3.2 Device detected

Display:

```text
┌────────────────────────────────────┐
│  DJI Footage Importer              │
│                                    │
│  ✓ DJI camera connected            │
│                                    │
│  38 recordings found               │
│  12 new recordings                 │
│  26 already imported               │
│                                    │
│  New footage: 8.4 GB               │
│                                    │
│  [     Import 12 videos      ]     │
│                                    │
│  Refresh                           │
└────────────────────────────────────┘
```

The main button should be disabled if there is nothing new to import.

If all files are already imported, display:

"All recordings are already imported."

### 3.3 Import in progress

After clicking Import:

```text
┌────────────────────────────────────┐
│  DJI Footage Importer              │
│                                    │
│  Importing recordings...           │
│                                    │
│  ███████████░░░░░░░░  58%          │
│                                    │
│  7 of 12 recordings                │
│                                    │
│  Preparing video for DaVinci       │
│  DJI_0042.MP4                      │
│                                    │
│  [          Cancel          ]      │
└────────────────────────────────────┘
```

Requirements:

- Show overall progress.
- Show processed files / total files.
- Show current filename.
- Display current operation: copying, verifying, preparing or saving.
- Keep UI responsive throughout.
- Handle safe cancellation.
- Do not invent percentages when actual progress cannot be determined; use indeterminate progress instead.

### 3.4 Completion

On full success:

- Display a brief success state.
- Send a KDE desktop notification.
- Automatically close the window after approximately 3 seconds.

Example:

"Import completed. 12 new videos are ready for editing."

Do not automatically open Dolphin or DaVinci.

If any file failed, leave the window open with a short summary and an option to retry failed operations.

### 3.5 Device not connected

Display:

```text
No DJI camera detected

Connect your camera using USB-C
and enable file transfer.

[ Try Again ]

Choose folder manually
```

Manual directory selection is a fallback, not the primary workflow.

Never show Python tracebacks or raw FFmpeg output to the user.

## 4. USB-C camera detection

The application must support importing directly from the DJI camera connected using USB-C.

### Discovery requirements

First inspect the actual device behavior on the target system.

Determine whether the camera exposes its files through:

- USB Mass Storage / mounted filesystem.
- MTP or another GVfs-accessible file-transfer mechanism.

Do not assume the device always appears under `/run/media/$USER`.

For regular mounted filesystems, use UDisks2/GIO-compatible discovery mechanisms.

For MTP, evaluate GIO/GVfs access or another well-maintained compatible mechanism. Do not assume MTP supports ordinary filesystem operations, seeking or random-access reads.

If an MTP source cannot be processed reliably, implement staging through a supported transfer mechanism rather than pretending it is a local disk.

### Detection behavior

- Prefer a recognizable connected DJI camera.
- Inspect expected media directories such as `DCIM`.
- Validate that the discovered source actually contains supported recordings.
- If multiple possible sources are detected, offer a simple device selection.
- Avoid treating unrelated USB drives as a DJI camera solely because they contain MP4 files.
- Allow a manually selected directory.
- Provide a Refresh button.
- Never require root privileges during regular imports.
- Never reformat, eject or modify the source device.

If no physical camera is available during development, create a mock source and clearly document the untested USB-discovery path.

## 5. Source file handling

The camera may contain files such as:

```text
DJI_0001.MP4
DJI_0001.LRF
DJI_0002.MP4
DJI_0002.LRF
```

### Import rules

- Import `.mp4` files, case-insensitively.
- Ignore `.LRF` proxy/preview files.
- Ignore unrelated thumbnails, temporary files and metadata sidecars in MVP.
- Scan supported directories recursively.
- Do not modify camera contents.
- Do not delete LRF or MP4 files on the camera.
- Do not automatically synchronize deletions from source to destination.

An LRF file is not a RAW master recording and must never replace the original MP4 as the editing source.

## 6. Destination storage layout

Resolve the actual Videos directory via XDG user directories rather than assuming the folder is always named `Videos`.

Default root:

`~/Videos/DJI/`

Required structure:

```text
Videos/
└── DJI/
    ├── footage/
    │   ├── 2026-10-19/
    │   │   ├── DJI_0001.mov
    │   │   └── DJI_0002.mov
    │   └── 2026-10-20/
    │       └── DJI_0003.mov
    │
    ├── .original/
    │   ├── 2026-10-19/
    │   │   ├── DJI_0001.MP4
    │   │   └── DJI_0002.MP4
    │   └── 2026-10-20/
    │       └── DJI_0003.MP4
    │
    └── .importer/
        ├── state.sqlite
        └── staging/
```

### Directory responsibilities

**footage/**

Only editing-ready media should appear here.

These files are intended to be imported directly into DaVinci Resolve.

**.original/**

Contains unmodified original MP4 recordings.

Originals must be byte-for-byte identical to the camera files.

Never overwrite or automatically delete original footage.

**.importer/**

Contains application state and temporary files.

The user must not need to interact with this directory.

### Naming and grouping

Group recordings by their capture date when reliably available.

Fallback order:

1. Reliable capture timestamp from media metadata.
2. Filesystem modification timestamp, when meaningful.
3. Import date.

Handle timezone differences consistently.

Preserve original filenames whenever possible.

If two distinct recordings have the same filename and date, generate a stable collision-resistant suffix.

Ensure that a corresponding original and working file can be matched reliably through the database.

Once a working MOV is published, its path must remain stable.

Do not rename or move files already referenced by DaVinci projects.

## 7. Media conversion

The main compatibility requirement is to produce files that DaVinci Resolve Studio can read and play correctly on Linux.

In the current setup:

- Some original recordings contain AAC audio.
- DaVinci may display video correctly but fail to decode their AAC audio.
- Standalone PCM WAV playback works.
- Video must retain original image quality.

### Primary conversion strategy

Use FFmpeg to remux the original video while converting unsupported audio to PCM.

Example:

```bash
ffmpeg -i input.mp4 \
  -map 0:v:0 \
  -map 0:a? \
  -c:v copy \
  -c:a pcm_s24le \
  -ar 48000 \
  output.mov
```

The command is illustrative, not a universal implementation.

### Video requirements

- Use stream copy (`-c:v copy`) whenever possible.
- Never re-encode video silently.
- Preserve resolution, frame rate, pixel format, color metadata and video stream data to the extent supported by the container.
- Preserve rotation/orientation metadata or flag any unsupported case.
- Do not automatically apply color conversions or LUTs.
- Do not convert 10-bit video to 8-bit.
- Do not change H.264 into H.265 or vice versa.
- Do not apply scaling or frame interpolation.
- If the video cannot be safely remuxed or played in Resolve, report an error instead of generating a misleading result.

### Audio requirements

- Convert AAC audio to uncompressed PCM.
- Default format: PCM signed 24-bit, 48 kHz.
- Preserve original channel count/layout when supported.
- Preserve multiple relevant audio tracks when possible.
- Support files without an audio stream.
- For already compatible PCM audio, avoid unnecessary transformation.
- Detect and report incompatible or unsupported audio layouts.

24-bit PCM does not restore quality already lost during AAC compression, but avoids introducing another lossy encoding step.

### Quality guarantee

When FFmpeg uses `-c:v copy`, the compressed video stream is copied without video re-encoding.

Verify the prepared file using FFprobe and, where feasible, compare packet payloads or equivalent stream-level information. Do not rely on whole-file hashes to compare MP4 and MOV containers.

### First-run compatibility validation

Before considering the implementation production-ready, test at least one genuine camera clip:

1. Original MP4 plays with the expected picture.
2. Prepared MOV plays correctly in DaVinci.
3. Audio is audible.
4. Fairlight audio meters move.
5. Audio and video remain synchronized.
6. Orientation and colors look correct.
7. Clip duration and frame count are consistent.

Do not claim successful DaVinci compatibility based on FFprobe alone.

## 8. Safe import pipeline

The importer must prioritize data safety over speed.

For each new recording:

**Stage A — Inspect**

- Read source metadata.
- Determine file size and available streams.
- Check previous import state.
- Estimate disk-space requirements.

**Stage B — Preserve original**

- Copy MP4 to local staging.
- Calculate SHA-256 hashes for the source and copy.
- Verify that the hashes match.
- Publish the verified original in `.original/` using a safe rename.
- Never overwrite an existing original.

**Stage C — Prepare working copy**

- Read from the locally stored original, not the camera.
- Run FFmpeg to produce a temporary MOV.
- Monitor progress and process exit code.
- Validate resulting streams, duration, timestamps and expected audio.
- Publish the completed MOV atomically where supported.

**Stage D — Commit**

- Update SQLite import state.
- Mark the recording as successfully imported only when its original and working copy are valid.
- Continue to the next recording.

### Failure handling

If the camera disconnects:

- Stop new reads.
- Keep previously verified originals.
- Keep successfully completed MOV files.
- Do not publish incomplete files.
- Allow a later import to resume.

If FFmpeg fails:

- Retain the verified original.
- Record the error.
- Allow retrying conversion without reconnecting the camera.

If storage becomes full:

- Stop safely.
- Do not corrupt completed data.
- Explain the problem in plain language.

Cancellation must terminate active FFmpeg child processes cleanly and finish or roll back the current operation safely.

### Disk-space checks

Estimate peak temporary space, accounting for:

- Original MP4.
- Prepared MOV.
- Temporary copies.
- Existing files on the same SSD.

Keep a configurable minimum free-space reserve, defaulting to 50 GiB.

Never start a batch that is clearly too large without informing the user.

Process files sequentially in MVP to limit memory, CPU, disk usage and complexity.

## 9. Duplicate detection and persistence

Use SQLite as the importer state store.

Track:

- Original filename and source path.
- Source file size.
- SHA-256 checksum.
- Capture timestamp.
- Destination original path.
- Destination prepared path.
- Audio/video codec information.
- Import timestamps.
- Conversion profile version.
- Import status and last error.

### Required behavior

- Repeated imports must not create duplicate footage.
- Different recordings with identical filenames must remain distinct.
- A partially imported recording must not be classified as complete.
- If the original exists but the MOV is missing, regenerate the MOV locally.
- If the database becomes inconsistent, provide a repair/verification procedure.
- Never delete files solely because a database record is missing.
- Never assume a file is unchanged based only on its name.

Database writes must be transactional.

Prevent simultaneous import processes from writing to the same destination.

Use a single-writer model or appropriate locking.

The importer should be able to recover after a power loss or forced termination without losing successfully preserved originals.

## 10. GUI implementation

Use PySide6 (Qt 6).

Create one compact, polished window styled consistently with KDE Plasma.

### GUI states

Define explicit application states:

- `SCANNING`
- `NO_DEVICE`
- `READY`
- `UP_TO_DATE`
- `IMPORTING`
- `SUCCESS`
- `PARTIAL_FAILURE`
- `ERROR`
- `CANCELLING`

Avoid complex navigation, tabs or settings pages.

### Threading and processes

- Run scanning, hashing, copying and conversion outside the GUI thread.
- Use Qt signals to report progress and state changes.
- Run FFmpeg through an appropriately managed subprocess.
- Do not update Qt widgets from background worker threads.
- Handle window closure while an import is running.
- Do not leave orphaned FFmpeg processes.

### User-facing language

Use clear human-readable wording.

Good:

"Preparing video 4 of 12"

"Camera disconnected. Connect it again to continue."

"Not enough disk space to import these recordings."

Avoid:

"FFmpeg exited with AVERROR_INVALIDDATA"

Technical details belong in logs.

### GUI behavior

- One primary action: Import.
- Secondary Refresh action.
- Manual folder selection as fallback.
- Cancel during import.
- Retry failed items.
- Automatically close only after full success.
- Keep errors visible until acknowledged.

Use Qt/KDE notifications for completion when available.

The application should respect desktop light/dark themes.

## 11. Desktop integration

Create a desktop launcher named:

**Import from DJI**

Icon: camera/video-related icon from the installed desktop theme.

Install the launcher into the application's menu and create a desktop shortcut for the current user.

Example desktop entry:

```ini
[Desktop Entry]
Type=Application
Name=Import from DJI
Comment=Import recordings for DaVinci Resolve
Exec=/home/USER/.local/bin/dji-footage-importer
Icon=camera-video
Terminal=false
Categories=AudioVideo;
```

Replace the example executable path with the actual installation path during setup.

Support desktop trust/execute requirements on KDE Plasma.

Ensure the launcher works on Wayland without terminal interaction.

## 12. Architecture

Separate GUI from import logic.

Suggested structure:

```text
dji-footage-importer/
├── pyproject.toml
├── README.md
├── install.sh
├── uninstall.sh
├── src/
│   └── dji_importer/
│       ├── __main__.py
│       ├── config.py
│       ├── discovery.py
│       ├── media.py
│       ├── storage.py
│       ├── database.py
│       ├── importer.py
│       ├── conversion.py
│       ├── workers.py
│       ├── ui.py
│       └── cli.py
├── resources/
│   └── dji-importer.desktop
└── tests/
```

Avoid unnecessary abstractions, plugins, frameworks and dependency injection.

Keep the implementation maintainable and appropriately sized for a small desktop utility.

### CLI

Expose limited commands for debugging and maintenance:

```bash
dji-footage-importer scan
dji-footage-importer import --source /path/to/source
dji-footage-importer verify
dji-footage-importer repair
```

Normal users only interact with the GUI.

## 13. Logging

Store application logs in an XDG-compliant location:

`~/.local/state/dji-footage-importer/`

Log:

- Application startup and version.
- Discovered devices.
- Selected source.
- Source metadata.
- File copying and checksum verification.
- FFmpeg commands and relevant output.
- Conversion results.
- Import database updates.
- Errors and cancellation.
- Import summary.

Use log rotation or retention limits.

Never dump complete personal directory listings unrelated to the selected media source.

Provide a way to retrieve diagnostic logs when troubleshooting.

## 14. Installation

Provide an `install.sh` script.

Requirements:

- Detect required system dependencies.
- Install the Python package into an isolated environment where appropriate.
- Use Arch/CachyOS-compatible packaging practices.
- Avoid modifying system Python packages with global pip installations.
- Register the `.desktop` launcher.
- Create the destination directory if missing.
- Do not require sudo during normal application use.
- Do not modify DaVinci Resolve or system codec libraries.
- Do not modify existing video files.

If installation requires system packages, show the required `pacman` command and explain what will be installed.

Provide an uninstall script that removes application files but **never deletes footage or import records without explicit confirmation**.

## 15. Automated testing

Use pytest.

Generate small test recordings using FFmpeg.

Required tests:

1. First import of multiple MP4 files.
2. Repeat import: no duplicates.
3. Add new files and import only those.
4. Ignore LRF files.
5. Preserve original MP4 checksum.
6. Convert AAC to PCM.
7. Preserve H.264/H.265 compressed video payload.
8. Handle recordings without audio.
9. Handle multiple audio streams.
10. Handle identical filenames from different recordings.
11. Recover from interrupted copying.
12. Recover from interrupted conversion.
13. Rebuild missing MOV from an existing original.
14. Handle insufficient disk space.
15. Handle disconnected source.
16. Handle cancellation.
17. Prevent concurrent imports.
18. Reject invalid or corrupted media.
19. Keep the GUI responsive.
20. Handle filesystem paths containing spaces and Unicode characters.

Do not run integration tests against actual camera media without explicit permission.

Use temporary directories and fixtures.

Provide a test report after implementation.

## 16. Acceptance criteria

The MVP is considered ready when:

- The desktop shortcut launches a functional GUI.
- A connected DJI camera can be detected over USB-C on the target machine.
- The interface clearly identifies new recordings.
- Import starts using one button.
- UI remains responsive and shows meaningful progress.
- All originals are preserved in `.original/`.
- Editing-ready MOV files appear in `footage/`.
- The original compressed video streams are not re-encoded.
- Unsupported AAC audio is converted to PCM.
- A real prepared recording plays with picture and sound inside DaVinci.
- Repeat imports do not create duplicates.
- Recovery works after a failed or interrupted import.
- No source files are modified or deleted.
- Logs are sufficient for troubleshooting.
- The application works without terminal interaction.

## 17. Explicitly out of scope

Do not implement the following in MVP:

- iPhone importing.
- Automatic NAS synchronization.
- Cloud uploads.
- AI tagging or video analysis.
- Project creation in DaVinci.
- DaVinci scripting API integration.
- Automatic creation of proxy video.
- Automatic video transcoding to another codec.
- Color correction.
- Automatic deletion or formatting of camera storage.
- Background camera monitoring.
- Auto-import on USB connection.
- Automatic removal of imported originals.
- A complex settings interface.

These may be considered separately once the basic importer works reliably.

## 18. Instructions for the coding agent

Work in the following order:

**Phase 1 — Environment inspection**

Inspect the system, available dependencies, camera connection mode and a small representative recording.

Do not assume details that can be verified.

**Phase 2 — Media compatibility proof**

Implement a minimal FFmpeg conversion prototype using one real recording.

Verify that the converted MOV plays correctly, with audio, inside DaVinci Resolve.

This is a mandatory prerequisite for relying on the selected conversion profile.

**Phase 3 — Core importer**

Implement file discovery, original preservation, verification, conversion, persistence and recovery.

Write automated tests.

**Phase 4 — GUI**

Implement the PySide6 interface and connect it to the tested import logic.

**Phase 5 — Desktop integration**

Implement installation, launcher creation, logging and documentation.

**Phase 6 — Acceptance testing**

Test the entire workflow from connecting the camera to importing footage into DaVinci.

If the camera is unavailable, complete mock-based tests and explicitly report the outstanding physical-device validation.

### Development constraints

- Do not delete or alter existing user footage.
- Do not perform destructive operations on connected devices.
- Do not silently re-encode video.
- Do not claim compatibility without testing.
- Do not install additional DaVinci plugins.
- Do not overengineer the application.
- Keep the implementation focused on reliability and user experience.

**Final deliverable:** a working, installed GUI application accessible through a desktop shortcut, with tested import behavior, automated tests and concise documentation.
