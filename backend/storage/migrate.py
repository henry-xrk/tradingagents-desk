"""Versioned, repeatable dashboard data migrations.

The migration rewrites report paths and drops global price ladders. It does not
assign those old prices to a ticker, and it can run again without further changes.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

MIGRATION_VERSION = 1
_PRICE_KEYS = ("scale_in_prices", "take_profit_prices")


def home_for_database(path: Path) -> Path:
    """The TradingAgents home that contains this dashboard database."""
    if path.parent.name == "dashboard":
        return path.parent.parent
    return path.parent


def relativize_stored_path(path: str | None, home: Path) -> str | None:
    """Return a results-relative path when the file lives under ``home``.

    Absolute Mac paths such as ``/Users/.../.tradingagents/logs/reports/...``
    become ``reports/...`` so the same row opens inside the container home.
    Unknown paths are left unchanged.
    """
    if not path:
        return path
    candidate = Path(path)
    if not candidate.is_absolute():
        return path
    results = (home / "logs").resolve()
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    for base, strip_logs in ((results, False), (home.resolve(), True)):
        try:
            relative = resolved.relative_to(base)
        except ValueError:
            continue
        if strip_logs and relative.parts and relative.parts[0] == "logs":
            relative = Path(*relative.parts[1:])
        target = results / relative
        if target.is_file():
            return relative.as_posix()
    parts = candidate.parts
    if ".tradingagents" not in parts:
        return path
    rest = Path(*parts[parts.index(".tradingagents") + 1 :])
    if rest.parts and rest.parts[0] == "logs":
        rest = Path(*rest.parts[1:])
    target = results / rest
    if target.is_file():
        return rest.as_posix()
    return path


def apply(connection: sqlite3.Connection, home: Path) -> dict[str, int]:
    """Apply pending migrations. A failure leaves the version unset so a retry can finish."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    current = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
    if current >= MIGRATION_VERSION:
        return {"version": current, "paths": 0, "price_keys": 0}
    try:
        paths = _rewrite_paths(connection, home)
        price_keys = _drop_global_prices(connection)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
            (MIGRATION_VERSION,),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"version": MIGRATION_VERSION, "paths": paths, "price_keys": price_keys}


def _rewrite_paths(connection: sqlite3.Connection, home: Path) -> int:
    rows = connection.execute(
        "SELECT id, html_report_path, markdown_report_path FROM analyses"
    ).fetchall()
    changed = 0
    for row in rows:
        html = relativize_stored_path(row["html_report_path"], home)
        markdown = relativize_stored_path(row["markdown_report_path"], home)
        if html == row["html_report_path"] and markdown == row["markdown_report_path"]:
            continue
        connection.execute(
            "UPDATE analyses SET html_report_path = ?, markdown_report_path = ? WHERE id = ?",
            (html, markdown, row["id"]),
        )
        changed += 1
    return changed


def _drop_global_prices(connection: sqlite3.Connection) -> int:
    """Remove price ladders from the global preference blob without copying them."""
    row = connection.execute(
        "SELECT value_json FROM preferences WHERE key = 'capital'"
    ).fetchone()
    if row is None or not row["value_json"]:
        return 0
    try:
        payload = json.loads(row["value_json"])
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    removed = [key for key in _PRICE_KEYS if key in payload]
    if not removed:
        return 0
    for key in removed:
        payload.pop(key, None)
    connection.execute(
        "UPDATE preferences SET value_json = ? WHERE key = 'capital'",
        (json.dumps(payload, ensure_ascii=False),),
    )
    return len(removed)
