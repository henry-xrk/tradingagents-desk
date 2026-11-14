"""Consistent desk backups.

The database is copied with SQLite's backup API and checked before the manifest
is written. Reports, research memory, and checkpoints travel with it. API keys
and ChatGPT sign-in files do not.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from backend.ops.paths import resolve_data_dir

SKIP_NAMES = {"chatgpt-auth.json", "chatgpt-auth.json.lock"}


class BackupError(RuntimeError):
    """A backup or restore that must not be reported as successful."""


def create_backup(data_dir: Path, dest_root: Path) -> Path:
    database = data_dir / "dashboard" / "research.db"
    if not database.is_file():
        raise BackupError(f"no dashboard database at {database}")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    destination = dest_root / stamp
    try:
        dest_root.mkdir(parents=True, exist_ok=True)
        destination.mkdir(mode=0o700)
    except OSError as exc:
        raise BackupError(f"backup directory is not writable: {exc}") from exc
    try:
        _backup_database(database, destination / "dashboard" / "research.db")
        copied = _copy_research_files(data_dir, destination)
        if not _integrity_ok(destination / "dashboard" / "research.db"):
            raise BackupError("backup database failed integrity_check")
        manifest = {
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "data_dir": str(data_dir.resolve()),
            "schema_version": _schema_version(destination / "dashboard" / "research.db"),
            "database": "dashboard/research.db",
            "integrity": "ok",
            "files": copied,
        }
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(destination, 0o700)
    except BackupError:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise BackupError(f"backup did not finish: {exc}") from exc
    return destination


_MANAGED = ("dashboard", "logs", "memory", "checkpoints")
_MANIFEST_KEYS = ("created_at", "data_dir", "schema_version", "database", "integrity", "files")


def validate_backup(backup_dir: Path) -> dict:
    """Check a backup completely before any destination file is changed."""
    root = Path(backup_dir)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise BackupError(f"backup manifest is missing at {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BackupError("backup manifest is not valid json") from exc
    if not isinstance(manifest, dict):
        raise BackupError("backup manifest has the wrong format")
    for key in _MANIFEST_KEYS:
        if key not in manifest:
            raise BackupError(f"backup manifest is missing {key}")
    if manifest["integrity"] != "ok":
        raise BackupError("backup manifest does not record a successful integrity check")
    if manifest["database"] != "dashboard/research.db":
        raise BackupError("backup database path is not dashboard/research.db")
    database = _contained_file(root, manifest["database"])
    if not _integrity_ok(database):
        raise BackupError("backup database failed integrity_check")
    if int(manifest["schema_version"]) != _schema_version(database):
        raise BackupError("backup schema does not match the database")
    files = manifest["files"]
    if not isinstance(files, list):
        raise BackupError("backup manifest file list is invalid")
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
            raise BackupError("backup file entry is invalid")
        path = _contained_file(root, item["path"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise BackupError(f"backup file does not match the manifest: {item['path']}")
    return manifest


def restore_backup(backup_dir: Path, destination: Path, *, idle: bool = False) -> None:
    """Validate the whole backup, stage it aside, and switch only after that succeeds."""
    manifest = validate_backup(backup_dir)
    destination = Path(destination)
    if _has_managed_data(destination) and not idle:
        raise BackupError("refusing to restore while writers to the destination are not confirmed idle")
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".desk-restore-{os.getpid()}"
    previous = parent / f".desk-previous-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(mode=0o700)
    try:
        _materialize(Path(backup_dir), staging, manifest)
        _apply_staging(staging, destination, previous)
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(f"restore did not finish: {exc}") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _contained_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")):
        raise BackupError(f"backup path is not relative: {relative}")
    pure = Path(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise BackupError(f"backup path escapes the backup directory: {relative}")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink():
        raise BackupError(f"backup path is a symlink: {relative}")
    if not candidate.is_file():
        raise BackupError(f"backup file is missing: {relative}")
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise BackupError(f"backup path escapes the backup directory: {relative}")
    return candidate


def _has_managed_data(destination: Path) -> bool:
    return any((destination / name).exists() for name in _MANAGED)


def _materialize(backup_dir: Path, staging: Path, manifest: dict) -> None:
    database = _contained_file(backup_dir, manifest["database"])
    _backup_database(database, staging / "dashboard" / "research.db")
    if not _integrity_ok(staging / "dashboard" / "research.db"):
        raise BackupError("staged database failed integrity_check")
    for item in manifest["files"]:
        source = _contained_file(backup_dir, item["path"])
        target = staging.joinpath(*Path(item["path"]).parts)
        if target.is_symlink() or not target.resolve().is_relative_to(staging.resolve()):
            raise BackupError(f"staged path escapes the restore directory: {item['path']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
            raise BackupError(f"staged file does not match the manifest: {item['path']}")


def _apply_staging(staging: Path, destination: Path, previous: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(previous, ignore_errors=True)
    previous.mkdir(mode=0o700)
    moved: list[str] = []
    applied: list[str] = []
    try:
        for name in _MANAGED:
            current = destination / name
            if not current.exists() and not current.is_symlink():
                continue
            if current.is_symlink():
                raise BackupError(f"destination path is a symlink: {name}")
            os.rename(current, previous / name)
            moved.append(name)
        for name in _MANAGED:
            incoming = staging / name
            if not incoming.exists():
                continue
            os.rename(incoming, destination / name)
            applied.append(name)
    except Exception as exc:
        for name in reversed(applied):
            current = destination / name
            if current.exists() or current.is_symlink():
                os.rename(current, staging / name)
        for name in reversed(moved):
            os.rename(previous / name, destination / name)
        shutil.rmtree(previous, ignore_errors=True)
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f"restore could not switch the destination: {exc}") from exc
    shutil.rmtree(previous, ignore_errors=True)


def _backup_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()


def _integrity_ok(path: Path) -> bool:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    return bool(row and row[0] == "ok")


def _schema_version(path: Path) -> int:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return 0
    finally:
        connection.close()
    return int(row[0] or 0)


def _copy_research_files(data_dir: Path, destination: Path) -> list[dict[str, str]]:
    copied: list[dict[str, str]] = []
    for relative in ("logs", "memory", "checkpoints"):
        source = data_dir / relative
        if not source.exists():
            continue
        for path in source.rglob("*"):
            if not path.is_file() or path.is_symlink() or _skip(path):
                continue
            if relative == "logs" and path.suffix.lower() not in {".html", ".md"}:
                continue
            target_rel = path.relative_to(data_dir).as_posix()
            target = destination / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied.append(
                {
                    "path": target_rel,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "mode": oct(path.stat().st_mode & 0o777),
                }
            )
    return copied


def _skip(path: Path) -> bool:
    return path.name in SKIP_NAMES or path.name.startswith(".env")


def confirm_live_directory_idle(root: Path, destination: Path) -> None:
    """Refuse to restore the live data directory unless no desk container exists."""
    from backend.ops.gates import probe_services

    if destination.resolve() != resolve_data_dir(root).resolve():
        return
    if probe_services(root) != "none":
        raise BackupError(
            "cannot confirm the data directory is idle; stop and remove the desk service before restoring it"
        )


def main() -> None:
    import sys

    root = Path.cwd()
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "restore":
            destination = Path(sys.argv[3])
            if _has_managed_data(destination):
                confirm_live_directory_idle(root, destination)
                restore_backup(Path(sys.argv[2]), destination, idle=True)
            else:
                restore_backup(Path(sys.argv[2]), destination)
            return
        data_dir = resolve_data_dir(root)
        dest_root = root / "data" / "backups"
        print(create_backup(data_dir, dest_root))
    except BackupError as exc:
        print(f"desk: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
