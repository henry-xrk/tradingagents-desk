"""Serve saved HTML reports only from the engine's results directory."""

from __future__ import annotations

from pathlib import Path

from backend.errors import DashboardError
from tradingagents.default_config import DEFAULT_CONFIG


def results_root() -> Path:
    return Path(DEFAULT_CONFIG["results_dir"]).resolve()


def relativize_report_path(path: str | None, root: Path | None = None) -> str | None:
    """Store a report path relative to the results directory when it belongs there."""
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        return path
    base = (root or results_root()).resolve()
    try:
        return candidate.resolve().relative_to(base).as_posix()
    except (OSError, ValueError):
        return path


def resolve_html_report(path: str, root: Path | None = None) -> Path:
    """Return a report file that stays inside ``root`` after symlink resolution."""
    base = (root or results_root()).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise DashboardError("HTML report not found.", status=404, code="not_found") from exc
    if not resolved.is_relative_to(base):
        raise DashboardError(
            "That report is outside the results directory.",
            status=403,
            code="forbidden",
        )
    if resolved.suffix.lower() != ".html" or not resolved.is_file():
        raise DashboardError("HTML report not found.", status=404, code="not_found")
    return resolved
