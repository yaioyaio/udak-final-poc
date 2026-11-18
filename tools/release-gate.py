#!/usr/bin/env python3
"""Check the UDAK release prerequisites locally."""

from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).absolute().parent.parent / "udak-cli"))

from udak_cli import main


if __name__ == "__main__":
    raise SystemExit(main("release-gate"))
