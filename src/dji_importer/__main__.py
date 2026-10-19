"""Entry point: launch the GUI when no arguments, otherwise the CLI."""
from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1:
        from .cli import main as cli_main
        return cli_main(sys.argv[1:])
    try:
        from .ui import run
    except ImportError as e:
        print(f"GUI dependencies are missing: {e}", file=sys.stderr)
        print("Install PySide6, e.g. 'sudo pacman -S pyside6'.", file=sys.stderr)
        return 1
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
