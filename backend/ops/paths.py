"""Resolve the desk data directory the same way Compose does.

Process environment wins. Otherwise the value is read from a ``KEY=value``
line in ``.env``. The file is not executed and ``$`` references are not expanded.
"""

from __future__ import annotations

import os
from pathlib import Path


def read_assignment(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return None


def resolve_data_dir(root: Path, environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get("DESK_DATA_DIR")
    if not configured:
        configured = read_assignment(root / ".env", "DESK_DATA_DIR")
    if not configured:
        return (root / "data" / "desk").resolve()
    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def main() -> None:
    import sys

    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    print(resolve_data_dir(root))
