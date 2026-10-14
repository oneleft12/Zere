"""Точка входа CLI: `python -m zere.core.conspect …` (см. `zere/core/conspect/cli.py`)."""

from __future__ import annotations

import sys

from zere.core.conspect.cli import main

if __name__ == "__main__":
    sys.exit(main())
