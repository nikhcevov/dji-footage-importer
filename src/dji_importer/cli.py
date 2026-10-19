"""Command-line interface for diagnostics and maintenance."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config, discovery, storage
from .database import Database, ImportLock
from .importer import Importer


def _fmt_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def _make_importer(cfg: dict) -> tuple[storage.Storage, Database, Importer]:
    store = storage.Storage(cfg["min_free_space_gib"])
    store.ensure_dirs()
    db = Database(store.db_path)
    return store, db, Importer(store, db, cfg["audio_sample_rate"])


def cmd_scan(args, logger) -> int:
    sources = discovery.find_sources()
    if not sources:
        print("No DJI camera detected.")
        return 1
    store, db, imp = _make_importer(config.load_config())
    try:
        for src in sources:
            files = discovery.iter_supported_files(src.dcim_dir)
            summary = imp.scan(files)
            print(f"{src.display_name} ({src.mount_point})")
            print(f"  {summary.total} recordings found")
            print(f"  {summary.new} new, {summary.already_imported} already imported")
            print(f"  New footage: {_fmt_bytes(summary.new_bytes)}")
    finally:
        db.close()
    return 0


def cmd_import(args, logger) -> int:
    store, db, imp = _make_importer(config.load_config())
    lock = ImportLock(config.lock_path())
    if not lock.acquire():
        print("Another import is already running.", file=sys.stderr)
        db.close()
        return 1
    try:
        if args.source:
            root = Path(args.source).expanduser()
            if not root.is_dir():
                print(f"Source not found: {root}", file=sys.stderr)
                return 2
            files = discovery.iter_manual_files(root)
        else:
            sources = discovery.find_sources()
            if not sources:
                print("No DJI camera detected. Use --source to choose a folder.",
                      file=sys.stderr)
                return 1
            files = discovery.iter_supported_files(sources[0].dcim_dir)
        summary = imp.scan(files)
        result = imp.run(summary.new_files, logger=logger)
        print(f"Imported {result.succeeded}, skipped {result.skipped}, "
              f"failed {result.failed}")
        for err in result.errors:
            print(f"  error: {err}", file=sys.stderr)
        return 0 if result.ok else 1
    finally:
        lock.release()
        db.close()


def cmd_verify(args, logger) -> int:
    store, db, imp = _make_importer(config.load_config())
    try:
        problems = imp.verify(logger)
        if not problems:
            print("No problems found.")
            return 0
        for problem in problems:
            print(problem)
        return 1
    finally:
        db.close()


def cmd_repair(args, logger) -> int:
    store, db, imp = _make_importer(config.load_config())
    lock = ImportLock(config.lock_path())
    if not lock.acquire():
        print("Another import is already running.", file=sys.stderr)
        db.close()
        return 1
    try:
        result = imp.repair_missing_movs(logger=logger)
        print(f"Rebuilt {result.succeeded}, failed {result.failed}")
        for err in result.errors:
            print(f"  error: {err}", file=sys.stderr)
        return 0 if result.failed == 0 else 1
    finally:
        lock.release()
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dji-footage-importer",
        description="Import DJI camera recordings for DaVinci Resolve.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("scan", help="list detected camera and recordings").set_defaults(
        func=cmd_scan)
    p_import = sub.add_parser("import", help="import recordings")
    p_import.add_argument("--source", help="import from a specific directory")
    p_import.set_defaults(func=cmd_import)
    sub.add_parser("verify", help="check imported files against the database").set_defaults(
        func=cmd_verify)
    sub.add_parser("repair", help="rebuild missing prepared MOVs").set_defaults(
        func=cmd_repair)
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args, config.setup_logging())
