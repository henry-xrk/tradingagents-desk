"""Local SQLite history for research runs, the watchlist, and capital inputs.

The database lives under the user's TradingAgents home, separate from the
ChatGPT sign-in file. Tokens are never written here.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_PREFERENCES: dict[str, Any] = {
    "available_capital": None,
    "available_cash": None,
    "max_risk_amount": None,
    "max_risk_percent": None,
    "max_position_percent": None,
    "cost_bps": 0,
}

ACTIVE_STATUSES = ("queued", "running", "cancel_requested", "cancelling")


def default_db_path() -> Path:
    override = os.environ.get("TRADINGAGENTS_DASHBOARD_DB")
    if override:
        return Path(override)
    return Path.home() / ".tradingagents" / "dashboard" / "research.db"


def utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


class DashboardStore:
    """Thread-safe access to the dashboard database."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                ticker TEXT NOT NULL,
                analysis_date TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                status TEXT NOT NULL,
                phase TEXT NOT NULL,
                agent_status_json TEXT NOT NULL,
                reports_json TEXT NOT NULL,
                rating TEXT,
                trade_plan_json TEXT,
                error TEXT,
                error_code TEXT,
                data_sources_json TEXT NOT NULL,
                activity_json TEXT NOT NULL,
                html_report_path TEXT,
                markdown_report_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_analyses_fingerprint
                ON analyses(fingerprint, status);
            CREATE INDEX IF NOT EXISTS idx_analyses_created
                ON analyses(created_at DESC);
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plan_drafts (
                analysis_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                plan_version INTEGER NOT NULL,
                inputs_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_checks (
                id INTEGER PRIMARY KEY,
                checked_at TEXT NOT NULL,
                ok INTEGER NOT NULL,
                code TEXT NOT NULL,
                message TEXT NOT NULL
            );
            """
        )
        self._conn.commit()
        from backend.storage.migrate import apply as apply_migrations, home_for_database

        apply_migrations(self._conn, home_for_database(self.path))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def fail_unfinished(self, message: str) -> int:
        """Mark runs that were still open when the process stopped."""
        now = utcnow()
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE analyses
                SET status = 'interrupted',
                    phase = 'interrupted',
                    error = ?,
                    error_code = 'interrupted',
                    finished_at = COALESCE(finished_at, ?),
                    updated_at = ?
                WHERE status IN ('queued', 'running', 'cancel_requested', 'cancelling')
                """,
                (message, now, now),
            )
            self._conn.commit()
            return cursor.rowcount

    def insert_analysis(self, record: dict[str, Any]) -> None:
        now = record.get("created_at") or utcnow()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO analyses (
                    id, fingerprint, ticker, analysis_date, settings_json, status, phase,
                    agent_status_json, reports_json, rating, trade_plan_json, error, error_code,
                    data_sources_json, activity_json, html_report_path, markdown_report_path,
                    created_at, updated_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["fingerprint"],
                    record["ticker"],
                    record["analysis_date"],
                    _dump(record.get("settings") or {}),
                    record.get("status") or "queued",
                    record.get("phase") or "queued",
                    _dump(record.get("agent_status") or {}),
                    _dump(record.get("reports") or {}),
                    record.get("rating"),
                    _dump(record["trade_plan"]) if record.get("trade_plan") is not None else None,
                    record.get("error"),
                    record.get("error_code"),
                    _dump(record.get("data_sources") or {}),
                    _dump(record.get("activity") or []),
                    record.get("html_report_path"),
                    record.get("markdown_report_path"),
                    now,
                    record.get("updated_at") or now,
                    record.get("started_at"),
                    record.get("finished_at"),
                ),
            )
            self._conn.commit()

    def save_analysis(self, record: dict[str, Any]) -> None:
        now = utcnow()
        record["updated_at"] = now
        with self._lock:
            self._conn.execute(
                """
                UPDATE analyses SET
                    status = ?, phase = ?, agent_status_json = ?, reports_json = ?,
                    rating = ?, trade_plan_json = ?, error = ?, error_code = ?,
                    data_sources_json = ?, activity_json = ?, html_report_path = ?,
                    markdown_report_path = ?, updated_at = ?, started_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    record["status"],
                    record["phase"],
                    _dump(record.get("agent_status") or {}),
                    _dump(record.get("reports") or {}),
                    record.get("rating"),
                    _dump(record["trade_plan"]) if record.get("trade_plan") is not None else None,
                    record.get("error"),
                    record.get("error_code"),
                    _dump(record.get("data_sources") or {}),
                    _dump(record.get("activity") or []),
                    record.get("html_report_path"),
                    record.get("markdown_report_path"),
                    now,
                    record.get("started_at"),
                    record.get("finished_at"),
                    record["id"],
                ),
            )
            self._conn.commit()

    def get_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
            ).fetchone()
        return _analysis_from_row(row) if row is not None else None

    def find_active_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM analyses
                WHERE fingerprint = ? AND status IN ('queued', 'running', 'cancel_requested', 'cancelling')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (fingerprint,),
            ).fetchone()
        return _analysis_from_row(row) if row is not None else None

    def list_analyses(
        self,
        *,
        limit: int = 50,
        statuses: tuple[str, ...] | None = None,
        ticker: str | None = None,
        analysis_date: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM analyses"
        clauses: list[str] = []
        params: list[Any] = []
        if statuses:
            marks = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({marks})")
            params.extend(statuses)
        if ticker:
            clauses.append("ticker = ?")
            params.append(ticker)
        if analysis_date:
            clauses.append("analysis_date = ?")
            params.append(analysis_date)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_analysis_summary(row) for row in rows]

    def list_watchlist(self) -> list[dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ticker, created_at FROM watchlist ORDER BY created_at"
            ).fetchall()
        return [{"ticker": row["ticker"], "created_at": row["created_at"]} for row in rows]

    def add_watch(self, ticker: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO watchlist (ticker, created_at) VALUES (?, ?)",
                (ticker, utcnow()),
            )
            self._conn.commit()

    def remove_watch(self, ticker: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))
            self._conn.commit()

    def get_preferences(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT value_json FROM preferences WHERE key = 'capital'"
            ).fetchone()
        stored = _load(row["value_json"], {}) if row is not None else {}
        return _capital_only(stored)

    def save_preferences(self, preferences: dict[str, Any]) -> dict[str, Any]:
        merged = _capital_only(preferences)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO preferences (key, value_json, updated_at)
                VALUES ('capital', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (_dump(merged), utcnow()),
            )
            self._conn.commit()
        return merged

    def get_plan_draft(self, analysis_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM plan_drafts WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "analysis_id": row["analysis_id"],
            "ticker": row["ticker"],
            "plan_version": row["plan_version"],
            "inputs": _load(row["inputs_json"], {}),
            "updated_at": row["updated_at"],
        }

    def save_plan_draft(
        self,
        analysis_id: str,
        ticker: str,
        plan_version: int,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        now = utcnow()
        payload = {
            "analysis_id": analysis_id,
            "ticker": ticker,
            "plan_version": plan_version,
            "inputs": inputs,
            "updated_at": now,
        }
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO plan_drafts (analysis_id, ticker, plan_version, inputs_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(analysis_id) DO UPDATE SET
                    ticker = excluded.ticker,
                    plan_version = excluded.plan_version,
                    inputs_json = excluded.inputs_json,
                    updated_at = excluded.updated_at
                """,
                (analysis_id, ticker, plan_version, _dump(inputs), now),
            )
            self._conn.commit()
        return payload

    def latest_provider_check(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT checked_at, ok, code, message FROM provider_checks ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {
            "checked_at": row["checked_at"],
            "ok": bool(row["ok"]),
            "code": row["code"],
            "message": row["message"],
        }

    def save_provider_check(self, result: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        saved = {
            "checked_at": now,
            "ok": bool(result.get("ok")),
            "code": str(result.get("code") or "error"),
            "message": str(result.get("message") or ""),
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO provider_checks (checked_at, ok, code, message) VALUES (?, ?, ?, ?)",
                (saved["checked_at"], int(saved["ok"]), saved["code"], saved["message"]),
            )
            self._conn.commit()
        return saved


def _capital_only(preferences: dict[str, Any]) -> dict[str, Any]:
    """Global preferences never keep per-symbol prices."""
    merged = dict(DEFAULT_PREFERENCES)
    for key in DEFAULT_PREFERENCES:
        if key in preferences:
            merged[key] = preferences[key]
    return merged


def _analysis_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "fingerprint": row["fingerprint"],
        "ticker": row["ticker"],
        "analysis_date": row["analysis_date"],
        "settings": _load(row["settings_json"], {}),
        "status": row["status"],
        "phase": row["phase"],
        "agent_status": _load(row["agent_status_json"], {}),
        "reports": _load(row["reports_json"], {}),
        "rating": row["rating"],
        "trade_plan": _load(row["trade_plan_json"], None),
        "error": row["error"],
        "error_code": row["error_code"],
        "data_sources": _load(row["data_sources_json"], {}),
        "activity": _load(row["activity_json"], []),
        "html_report_path": row["html_report_path"],
        "markdown_report_path": row["markdown_report_path"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "reused": False,
    }


def _analysis_summary(row: sqlite3.Row) -> dict[str, Any]:
    full = _analysis_from_row(row)
    reports = full.pop("reports", None) or {}
    plan = full.pop("trade_plan", None)
    sections = [
        key for key, value in reports.items() if isinstance(value, str) and value.strip()
    ]
    full["report_sections"] = sorted(sections)
    full["has_partial_report"] = bool(sections)
    full["has_report"] = bool(full.get("html_report_path") or full.get("markdown_report_path") or sections)
    full["has_trade_plan"] = plan is not None
    full["plan_version"] = plan.get("plan_version") if isinstance(plan, dict) else None
    return full
