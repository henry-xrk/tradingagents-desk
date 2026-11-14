"""Backup failures and deployment gates. No production Compose project is used."""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from backend.ops.backup import BackupError, create_backup, restore_backup
from backend.ops.gates import GateError, SwitchFacts, evaluate_switch, verified_backup
from backend.ops.paths import read_assignment, resolve_data_dir
from backend.storage.db import DashboardStore


def _facts(**changes) -> SwitchFacts:
    base = {
        "health": "ok",
        "services": "running",
        "dirty": False,
        "conflicts": False,
        "image_api": True,
        "image_web": True,
        "test_stamp": "abc",
        "head": "abc",
        "db_exists": True,
        "db_schema": 2,
        "backup_schema": 2,
        "active": 0,
        "image_schema": 2,
        "tree": "tree-1",
        "stamp_tree": "tree-1",
        "stamp_api_digest": "sha-api",
        "stamp_web_digest": "sha-web",
        "image_api_digest": "sha-api",
        "image_web_digest": "sha-web",
        "image_api_commit": "abc",
        "image_web_commit": "abc",
        "image_api_tree": "tree-1",
        "image_web_tree": "tree-1",
        "image_web_schema": 2,
        "backup_valid": True,
    }
    base.update(changes)
    return SwitchFacts(**base)


def test_env_assignment_is_not_executed(tmp_path):
    env = tmp_path / ".env"
    env.write_text('DESK_DATA_DIR=./custom\nUNSAFE=$(echo injected)\n', encoding="utf-8")
    assert read_assignment(env, "UNSAFE") == "$(echo injected)"
    assert resolve_data_dir(tmp_path, {}) == (tmp_path / "custom").resolve()
    assert resolve_data_dir(tmp_path, {"DESK_DATA_DIR": "/override"}) == Path("/override")


def test_shell_backup_of_missing_database_exits_nonzero(tmp_path):
    env = os.environ.copy()
    env["DESK_DATA_DIR"] = str(tmp_path / "empty")
    completed = subprocess.run(
        ["/bin/sh", "scripts/desk.sh", "backup"],
        cwd=Path(".").resolve(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert completed.stdout.strip() == ""
    assert "no dashboard database" in completed.stderr


def test_backup_permission_and_interrupted_copy_fail(tmp_path, monkeypatch):
    data = _sample_data(tmp_path / "data")
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    with pytest.raises(BackupError):
        create_backup(data, blocked / "backups")

    def fail_copy(source, destination):
        raise OSError("copy interrupted")

    monkeypatch.setattr("backend.ops.backup.shutil.copy2", fail_copy)
    with pytest.raises(BackupError):
        create_backup(data, tmp_path / "backups")
    assert list((tmp_path / "backups").glob("*/manifest.json")) == []


def test_successful_backup_restores_reports_and_skips_credentials(tmp_path):
    data = _sample_data(tmp_path / "data")
    secret = data / "chatgpt-auth.json"
    secret.write_text('{"access_token": "demo-token-12345"}', encoding="utf-8")
    (data / ".env").write_text("OPENAI_API_KEY=demo-secret-12345\n", encoding="utf-8")
    backup = create_backup(data, tmp_path / "backups")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["integrity"] == "ok"
    names = {item["path"] for item in manifest["files"]}
    assert "logs/reports/AAPL/complete_report.html" in names
    assert "memory/trading_memory.md" in names
    assert "checkpoints/AAPL.db" in names
    assert not any("chatgpt-auth" in name or name.endswith(".env") for name in names)
    restored = tmp_path / "restored"
    restore_backup(backup, restored)
    assert (restored / "logs/reports/AAPL/complete_report.html").read_text(encoding="utf-8") == "report"
    connection_text = (restored / "dashboard/research.db").read_bytes()
    assert b"demo-secret-12345" not in connection_text


def test_unknown_service_state_blocks_upgrade_even_when_dirty():
    with pytest.raises(GateError, match="not confirmed"):
        evaluate_switch(_facts(health="unknown", dirty=True))


def test_running_but_unhealthy_service_is_not_treated_as_first_start():
    with pytest.raises(GateError, match="not confirmed"):
        evaluate_switch(_facts(health="down", services="running", active=None))


def test_active_research_and_stale_tests_block_switch():
    with pytest.raises(GateError, match="active"):
        evaluate_switch(_facts(active=1))
    with pytest.raises(GateError, match="tests have not passed"):
        evaluate_switch(_facts(test_stamp="old"))


def test_corrupt_restore_does_not_replace_the_current_database(tmp_path):
    source = _sample_data(tmp_path / "source")
    backup = create_backup(source, tmp_path / "backups")
    target = _sample_data(tmp_path / "target")
    database = target / "dashboard" / "research.db"
    report = target / "logs" / "reports" / "AAPL" / "complete_report.html"
    report.write_text("current-valuable", encoding="utf-8")
    before_db = database.read_bytes()
    before_report = report.read_bytes()
    (backup / "logs" / "reports" / "AAPL" / "complete_report.html").write_text("corrupted report", encoding="utf-8")
    with pytest.raises(BackupError, match="does not match"):
        restore_backup(backup, target, idle=True)
    assert database.read_bytes() == before_db
    assert report.read_bytes() == before_report


def test_backup_without_a_database_is_rejected(tmp_path):
    source = _sample_data(tmp_path / "source")
    backup = create_backup(source, tmp_path / "data" / "backups")
    (backup / "dashboard" / "research.db").unlink()
    assert verified_backup(tmp_path, source) is None
    with pytest.raises(GateError, match="verified backup"):
        evaluate_switch(_facts(backup_valid=False, backup_schema=None))


def test_first_install_does_not_skip_conflict_image_or_test_checks():
    with pytest.raises(GateError):
        evaluate_switch(
            _facts(
                health="down",
                services="none",
                conflicts=True,
                image_api=False,
                image_web=False,
                test_stamp=None,
                active=None,
            )
        )


def test_test_stamp_does_not_authorize_a_different_image():
    with pytest.raises(GateError, match="not bound"):
        evaluate_switch(
            _facts(
                test_stamp="head-tested",
                head="head-tested",
                image_api_commit="head-tested",
                image_web_commit="head-tested",
                stamp_api_digest="tested-image",
                image_api_digest="different-untested-image",
            )
        )


def test_restore_rejects_paths_outside_the_backup(tmp_path):
    source = _sample_data(tmp_path / "source")
    backup = create_backup(source, tmp_path / "backups")
    secret = tmp_path / "secret.txt"
    secret.write_text("outside", encoding="utf-8")
    link = backup / "logs" / "escape.md"
    link.symlink_to(secret)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append({"path": "../secret.txt", "sha256": "0" * 64})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target = _sample_data(tmp_path / "target")
    before = (target / "dashboard" / "research.db").read_bytes()
    with pytest.raises(BackupError, match="escapes"):
        restore_backup(backup, target, idle=True)
    manifest["files"][-1] = {"path": "logs/escape.md", "sha256": "0" * 64}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError, match="symlink"):
        restore_backup(backup, target, idle=True)
    assert (target / "dashboard" / "research.db").read_bytes() == before


def test_restore_permission_and_switch_failures_keep_the_original(tmp_path, monkeypatch):
    source = _sample_data(tmp_path / "source")
    backup = create_backup(source, tmp_path / "backups")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "dashboard").mkdir()
    os.chmod(blocked, 0o500)
    try:
        with pytest.raises(BackupError):
            restore_backup(backup, blocked, idle=True)
    finally:
        os.chmod(blocked, 0o700)

    target = _sample_data(tmp_path / "target")
    before = (target / "dashboard" / "research.db").read_bytes()
    real_rename = os.rename
    failed = {"count": 0}

    def fail_switch(src, dst):
        if Path(dst) == target / "dashboard" and failed["count"] == 0:
            failed["count"] += 1
            raise OSError("switch failed")
        real_rename(src, dst)

    monkeypatch.setattr(os, "rename", fail_switch)
    with pytest.raises(BackupError, match="switch"):
        restore_backup(backup, target, idle=True)
    assert (target / "dashboard" / "research.db").read_bytes() == before
    assert (target / "logs" / "reports" / "AAPL" / "complete_report.html").read_text(encoding="utf-8") == "report"


def test_interrupted_restore_copy_keeps_the_original(tmp_path, monkeypatch):
    source = _sample_data(tmp_path / "source")
    backup = create_backup(source, tmp_path / "backups")
    target = _sample_data(tmp_path / "target")
    before = (target / "dashboard" / "research.db").read_bytes()

    def fail_copy(source_path, destination_path, *args, **kwargs):
        raise OSError("copy interrupted")

    monkeypatch.setattr("backend.ops.backup.shutil.copy2", fail_copy)
    with pytest.raises(BackupError, match="did not finish"):
        restore_backup(backup, target, idle=True)
    assert (target / "dashboard" / "research.db").read_bytes() == before


def test_successful_restore_replaces_reports_from_the_same_snapshot(tmp_path):
    source = _sample_data(tmp_path / "source")
    (source / "logs" / "reports" / "AAPL" / "complete_report.html").write_text("backup report", encoding="utf-8")
    backup = create_backup(source, tmp_path / "backups")
    target = _sample_data(tmp_path / "target")
    (target / "logs" / "reports" / "AAPL" / "complete_report.html").write_text("current-valuable", encoding="utf-8")
    restore_backup(backup, target, idle=True)
    assert (target / "logs" / "reports" / "AAPL" / "complete_report.html").read_text(encoding="utf-8") == "backup report"
    assert (target / "memory" / "trading_memory.md").read_text(encoding="utf-8") == "memory"
    assert (target / "checkpoints" / "AAPL.db").read_bytes() == b"checkpoint"


def test_rollback_refuses_a_newer_database_schema():
    with pytest.raises(GateError, match="restore a backup"):
        evaluate_switch(_facts(db_schema=3, backup_schema=3, image_schema=2), rollback=True)
    with pytest.raises(GateError, match="no schema label"):
        evaluate_switch(_facts(image_schema=None), rollback=True)


def test_first_start_does_not_call_compose_when_health_is_ambiguous(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "desk@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Desk"], cwd=repo, check=True)
    (repo / "README").write_text("desk\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "dirty").write_text("local\n", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "commands"
    (bindir / "curl").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (bindir / "docker").write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$DESK_FAKE_LOG\"\n"
        "if [ \"$1\" = compose ] && [ \"$4\" = ps ]; then exit 0; fi\n"
        "if [ \"$1\" = image ]; then echo 2; exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    os.chmod(bindir / "curl", 0o755)
    os.chmod(bindir / "docker", 0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["DESK_ROOT"] = str(repo)
    env["DESK_FAKE_LOG"] = str(log)
    env["DESK_DATA_DIR"] = str(tmp_path / "nodata")
    completed = subprocess.run(
        ["/bin/sh", "scripts/desk.sh", "up"],
        cwd=Path(".").resolve(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    recorded = log.read_text(encoding="utf-8") if log.exists() else ""
    assert "up -d" not in recorded
    assert "not confirmed" in completed.stderr or "tests have not passed" in completed.stderr


def _sample_data(root: Path) -> Path:
    store = DashboardStore(root / "dashboard" / "research.db")
    store.insert_analysis(
        {
            "id": "one",
            "fingerprint": "fp",
            "ticker": "AAPL",
            "analysis_date": "2020-01-02",
            "settings": {"analysts": ["market"]},
            "status": "completed",
            "phase": "completed",
            "agent_status": {},
            "reports": {"market_report": "text"},
            "html_report_path": "reports/AAPL/complete_report.html",
            "created_at": "2020-01-02T00:00:00+00:00",
        }
    )
    report = root / "logs" / "reports" / "AAPL" / "complete_report.html"
    report.parent.mkdir(parents=True)
    report.write_text("report", encoding="utf-8")
    (report.with_suffix(".md")).write_text("markdown", encoding="utf-8")
    memory = root / "memory" / "trading_memory.md"
    memory.parent.mkdir()
    memory.write_text("memory", encoding="utf-8")
    checkpoint = root / "checkpoints" / "AAPL.db"
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"checkpoint")
    return root
