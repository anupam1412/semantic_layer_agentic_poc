"""Minimal .env loader (no dependency required).

Loads environment variables from a .env file (key=value pairs) into os.environ.
Existing environment variables are preserved.

This is intentionally very small and dependency-free so the project can run without
requiring python-dotenv.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path | None = None) -> None:
    """Load variables from a .env file into the process environment.

    - Lines starting with # are ignored.
    - Blank lines are ignored.
    - Supports key=value and key="value" / key='value'.
    - Existing environment values are not overwritten.
    """

    if path is None:
        path = Path(__file__).resolve().parent / ".env"
    else:
        path = Path(path)

    if not path.exists():
        return

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if not key:
            continue
        os.environ.setdefault(key, val)
