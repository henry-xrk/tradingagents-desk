"""Decide whether a desk service switch is allowed.

Image replacement is not a database rollback. A newer schema than the target
image understands must be restored from a backup instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from backend.ops.backup import BackupError, _schema_version, validate_backup
from backend.ops.paths import resolve_data_dir
from backend.storage.migrate import MIGRATION_VERSION


class GateError(RuntimeError):
    """The switch must stop before Compose changes the service."""


@dataclass
class SwitchFacts:
    health: str
    services: str
    dirty: bool
    conflicts: bool
    image_api: bool
    image_web: bool
    test_stamp: str | None
    head: str
    db_exists: bool
    db_schema: int
    backup_schema: int | None
    active: int | None
    image_schema: int | None = None
    tree: str = ""
    stamp_tree: str = ""
    stamp_api_digest: str = ""
    stamp_web_digest: str = ""
    image_api_digest: str = ""
    image_web_digest: str = ""
    image_api_commit: str = ""
    image_web_commit: str = ""
    image_api_tree: str = ""
    image_web_tree: str = ""
    image_web_schema: int | None = None
    backup_valid: bool = True


def evaluate_switch(facts: SwitchFacts, *, rollback: bool = False) -> None:
    first_install = facts.services == "none" and facts.health == "down"
    if facts.health == "unknown" or facts.services == "unknown":
        raise GateError("service state is not confirmed; refusing to replace it")
    if facts.services == "running" and facts.health != "ok":
        raise GateError("service state is not confirmed; refusing to replace it")
    if facts.health == "ok" or facts.services == "stopped":
        if facts.active is None:
            raise GateError("could not confirm whether research is active")
        if facts.active > 0:
            raise GateError(f"{facts.active} analysis run(s) are still active")
    elif not first_install:
        raise GateError("service state is not confirmed; refusing to replace it")

    if rollback:
        if not facts.image_api or not facts.image_web:
            raise GateError("target image is missing")
        if facts.image_schema is None or facts.image_web_schema is None:
            raise GateError("target image has no schema label; refusing to claim it can read this database")
        if facts.image_web_schema != facts.image_schema:
            raise GateError("api and web images do not advertise the same schema")
        if facts.db_exists and (not facts.backup_valid or facts.backup_schema != facts.db_schema):
            raise GateError("no verified backup matches the current database")
        if facts.db_exists and facts.db_schema > facts.image_schema:
            raise GateError(
                "database schema is newer than the target image; "
                "restore a backup instead of only swapping the image"
            )
        return

    if facts.conflicts:
        raise GateError("merge conflicts are unresolved")
    if not facts.image_api or not facts.image_web:
        raise GateError("target image is missing")
    if not facts.test_stamp or facts.test_stamp != facts.head:
        raise GateError("tests have not passed for the target commit")
    if not facts.tree or facts.tree != facts.stamp_tree:
        raise GateError("tests did not cover the current source tree")
    if (
        not facts.stamp_api_digest
        or not facts.stamp_web_digest
        or facts.stamp_api_digest != facts.image_api_digest
        or facts.stamp_web_digest != facts.image_web_digest
    ):
        raise GateError("target image is not bound to the tested build")
    if facts.image_api_commit != facts.head or facts.image_web_commit != facts.head:
        raise GateError("target images were not built from the tested commit")
    if facts.image_api_tree != facts.tree or facts.image_web_tree != facts.tree:
        raise GateError("target images were not built from the tested source tree")
    if facts.image_schema is None or facts.image_web_schema is None:
        raise GateError("target image has no schema label; refusing to claim it can read this database")
    if facts.image_web_schema != facts.image_schema:
        raise GateError("api and web images do not advertise the same schema")
    if facts.db_exists and (not facts.backup_valid or facts.backup_schema != facts.db_schema):
        raise GateError("no verified backup matches the current database")


def latest_backup_schema(root: Path, data_dir: Path | None = None) -> int | None:
    verified = verified_backup(root, data_dir)
    if verified is None:
        return None
    return int(verified["schema_version"])


def verified_backup(root: Path, data_dir: Path | None = None) -> dict | None:
    """Return the newest backup that still has its database, hashes, and source directory."""
    backups = root / "data" / "backups"
    if not backups.is_dir():
        return None
    manifests = sorted(backups.glob("*/manifest.json"))
    if not manifests:
        return None
    try:
        manifest = validate_backup(manifests[-1].parent)
    except (BackupError, OSError, json.JSONDecodeError, ValueError):
        return None
    if data_dir is not None and Path(str(manifest["data_dir"])).resolve() != Path(data_dir).resolve():
        return None
    return manifest


def source_identity(root: Path) -> tuple[str, str]:
    """Full HEAD and a digest of the tracked diff plus untracked source files."""
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "-uall", "--", ".", ":!.desk", ":!data"],
        cwd=root,
        text=True,
    )
    diff = subprocess.check_output(["git", "diff", "HEAD", "--", ".", ":!.desk", ":!data"], cwd=root)
    digest = hashlib.sha256()
    digest.update(commit.encode())
    digest.update(b"\0")
    digest.update(status.encode())
    digest.update(b"\0")
    digest.update(diff)
    for line in status.splitlines():
        if not line.startswith("?? "):
            continue
        relative = line[3:]
        path = root / relative
        if path.is_file() and not path.is_symlink():
            digest.update(relative.encode())
            digest.update(path.read_bytes())
    return commit, digest.hexdigest()


def write_test_stamp(root: Path, commit: str, tree: str, *, api_digest: str = "", web_digest: str = "") -> None:
    folder = root / ".desk"
    folder.mkdir(mode=0o700, exist_ok=True)
    payload = {
        "commit": commit.strip(),
        "tree": tree.strip(),
        "api_digest": api_digest.strip(),
        "web_digest": web_digest.strip(),
    }
    (folder / "test-ok").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def read_stamp(root: Path) -> dict | None:
    path = root / ".desk" / "test-ok"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    if text.startswith("{"):
        payload = json.loads(text)
        if isinstance(payload, dict) and payload.get("commit") and payload.get("tree"):
            return payload
        return None
    return {"commit": text, "tree": "", "api_digest": "", "web_digest": ""}


def read_test_stamp(root: Path) -> str | None:
    payload = read_stamp(root)
    if payload is None:
        return None
    return str(payload.get("commit") or "") or None


def probe_health(url: str) -> str:
    completed = subprocess.run(
        ["curl", "-fsS", "--max-time", "5", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return "ok"
    if completed.returncode == 7:
        return "down"
    return "unknown"


def probe_services(root: Path) -> str:
    completed = subprocess.run(
        ["docker", "compose", "-f", str(root / "compose.desk.yml"), "ps", "-a", "--format", "json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"
    text = completed.stdout.strip()
    if not text:
        return "none"
    running = False
    seen = False
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return "unknown"
        seen = True
        state = str(item.get("State") or item.get("Status") or "").lower()
        if state.startswith("running") or state.startswith("restarting"):
            running = True
    if not seen:
        return "unknown"
    return "running" if running else "stopped"


def image_present(name: str) -> bool:
    completed = subprocess.run(
        ["docker", "image", "inspect", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def image_schema(name: str) -> int | None:
    text = image_label(name, "desk.schema")
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def image_label(name: str, label: str) -> str | None:
    completed = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{index .Config.Labels \"" + label + "\"}}", name],
        capture_output=True,
        text=True,
        check=False,
    )
    text = completed.stdout.strip()
    if completed.returncode != 0 or not text or text == "<no value>":
        return None
    return text


def image_digest(name: str) -> str:
    completed = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", name],
        capture_output=True,
        text=True,
        check=False,
    )
    text = completed.stdout.strip()
    if completed.returncode != 0 or not text:
        return ""
    return text


def active_count(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            rows = json.load(response)
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    return len(rows)


def wait_for_commit(url: str, commit: str, tree: str = "", timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body = json.load(response)
            if body.get("status") == "ok" and body.get("commit") == commit and (not tree or body.get("tree") == tree):
                return
        except Exception:
            pass
        time.sleep(1)
    raise GateError(f"service did not become healthy at commit {commit}")


def database_active_count(database: Path) -> int | None:
    if not database.is_file():
        return 0
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM analyses WHERE status IN ('queued', 'running', 'cancel_requested', 'cancelling')"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    return int(row[0] if row else 0)


def collect_facts(root: Path, tag: str, *, health_url: str, active_url: str) -> SwitchFacts:
    health = probe_health(health_url)
    services = probe_services(root)
    data_dir = resolve_data_dir(root)
    database = data_dir / "dashboard" / "research.db"
    commit, tree = source_identity(root)
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
    conflicts = bool(
        subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=root,
            text=True,
        ).strip()
    )
    stamp = read_stamp(root) or {}
    api_name = f"tradingagents-desk-api:{tag}"
    web_name = f"tradingagents-desk-web:{tag}"
    backup = verified_backup(root, data_dir)
    if health == "ok":
        active = active_count(active_url)
    elif services == "stopped":
        active = database_active_count(database)
    else:
        active = None
    return SwitchFacts(
        health=health,
        services=services,
        dirty=dirty,
        conflicts=conflicts,
        image_api=image_present(api_name),
        image_web=image_present(web_name),
        test_stamp=str(stamp.get("commit") or "") or None,
        head=commit,
        tree=tree,
        stamp_tree=str(stamp.get("tree") or ""),
        stamp_api_digest=str(stamp.get("api_digest") or ""),
        stamp_web_digest=str(stamp.get("web_digest") or ""),
        image_api_digest=image_digest(api_name),
        image_web_digest=image_digest(web_name),
        image_api_commit=image_label(api_name, "desk.commit") or "",
        image_web_commit=image_label(web_name, "desk.commit") or "",
        image_api_tree=image_label(api_name, "desk.tree") or "",
        image_web_tree=image_label(web_name, "desk.tree") or "",
        db_exists=database.is_file(),
        db_schema=_schema_version(database) if database.is_file() else 0,
        backup_schema=int(backup["schema_version"]) if backup else None,
        backup_valid=backup is not None,
        active=active,
        image_schema=image_schema(api_name),
        image_web_schema=image_schema(web_name),
    )


def compose(root: Path, *args: str) -> None:
    data_dir = resolve_data_dir(root)
    env = os.environ.copy()
    env["DESK_DATA_DIR"] = str(data_dir)
    completed = subprocess.run(
        ["docker", "compose", "-f", str(root / "compose.desk.yml"), *args],
        cwd=root,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise GateError(f"docker compose exited {completed.returncode}")


def switch(root: Path, tag: str, *, rollback: bool, health_url: str) -> None:
    facts = collect_facts(
        root,
        tag,
        health_url=health_url,
        active_url=health_url.rsplit("/", 1)[0] + "/analyses/active",
    )
    evaluate_switch(facts, rollback=rollback)
    os.environ["DESK_IMAGE_TAG"] = tag
    compose(root, "up", "-d", "--no-build")
    expected_commit = facts.image_api_commit if rollback else facts.head
    expected_tree = facts.image_api_tree if rollback else facts.tree
    try:
        wait_for_commit(health_url, expected_commit, expected_tree)
        _web_matches(health_url, expected_commit, expected_tree)
    except GateError as exc:
        state = probe_services(root)
        health = probe_health(health_url)
        raise GateError(
            f"{exc} Service is {state} and health is {health}. "
            "This attempt did not succeed. Image rollback does not restore the database; "
            "use scripts/desk.sh restore only after the service is stopped."
        ) from exc
    if rollback:
        print(
            f"service rolled back to {tag}. This does not restore the database. "
            "Use scripts/desk.sh restore when the data itself must return to a backup."
        )
    else:
        print(f"service is healthy at commit {facts.head}")


def _web_matches(health_url: str, commit: str, tree: str) -> None:
    url = health_url.rsplit("/", 2)[0] + "/desk-build.json"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = json.load(response)
    except Exception as exc:
        raise GateError("web version file is not available") from exc
    if body.get("commit") != commit or body.get("tree") != tree:
        raise GateError("web image does not match the tested api commit")


def record_built_images(root: Path, tag: str) -> None:
    commit, tree = source_identity(root)
    stamp = read_stamp(root)
    if not stamp or stamp.get("commit") != commit or stamp.get("tree") != tree:
        raise GateError("tests have not passed for the current source tree")
    api_name = f"tradingagents-desk-api:{tag}"
    web_name = f"tradingagents-desk-web:{tag}"
    if image_label(api_name, "desk.commit") != commit or image_label(web_name, "desk.commit") != commit:
        raise GateError("built images do not contain the tested commit")
    if image_label(api_name, "desk.tree") != tree or image_label(web_name, "desk.tree") != tree:
        raise GateError("built images do not contain the tested source tree")
    if image_schema(api_name) != image_schema(web_name):
        raise GateError("api and web images do not advertise the same schema")
    write_test_stamp(
        root,
        commit,
        tree,
        api_digest=image_digest(api_name),
        web_digest=image_digest(web_name),
    )


def main() -> None:
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else ""
    root = Path.cwd()
    health_url = os.environ.get("DESK_HEALTH_URL", "http://127.0.0.1:5173/api/health")
    try:
        if command == "prepare-build":
            commit, tree = source_identity(root)
            stamp = read_stamp(root)
            if not stamp or stamp.get("commit") != commit or stamp.get("tree") != tree:
                raise GateError("tests have not passed for the current source tree")
            print(commit)
            print(tree)
            return
        if command == "stamp":
            commit, tree = source_identity(root)
            write_test_stamp(root, commit, tree)
            return
        if command == "bind":
            tag = sys.argv[2]
            record_built_images(root, tag)
            return
        if command == "up":
            tag = os.environ.get("DESK_IMAGE_TAG") or subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True
            ).strip()
            switch(root, tag, rollback=False, health_url=health_url)
            return
        if command == "rollback":
            tag = sys.argv[2]
            switch(root, tag, rollback=True, health_url=health_url)
            return
    except GateError as exc:
        print(f"desk: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("usage: python -m backend.ops.gates stamp|bind <tag>|up|rollback <tag>", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()


# The supported schema this source tree can write. Images label the same value.
SUPPORTED_SCHEMA = MIGRATION_VERSION
