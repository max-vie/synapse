#!/usr/bin/env python3
"""Executable entrypoint for Synapse Ask."""

from __future__ import annotations

from pathlib import Path
import sys

ASK_DIR = Path(__file__).resolve().parent
if str(ASK_DIR) not in sys.path:
    sys.path.insert(0, str(ASK_DIR))

from synapse_ask.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
