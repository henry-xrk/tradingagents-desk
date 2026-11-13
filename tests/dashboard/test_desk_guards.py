"""Price isolation, path migration, redaction, queue limits, and process stop."""

import time

from fastapi.testclient import TestClient

from backend.errors import classify_exception, redact
from backend.main import create_app
from backend.services.runner import AnalysisRunner
from backend.services.trade_plan import PositionInputs, calculate_position
from backend.storage.db import DashboardStore
from backend.storage.migrate import apply, relativize_stored_path
from tests.dashboard.blocking_worker import block


def test_redaction_removes_keys_urls_and_bearer_tokens():
    raw = (
        "boom Authorization: Bearer sk-secretvalue12345678 "
        "https://user:sk-secretvalue12345678@example.com/v1?api_key=abcd1234"
    )
    cleaned = redact(raw)
    assert "sk-secretvalue12345678" not in cleaned
    assert "abcd1234" not in cleaned
    assert "user:sk-secretvalue" not in cleaned
    code, message = classify_exception(RuntimeError(raw), ref="abc")
    assert code == "error"
    assert "abcd1234" not in message
    assert "ref abc" in message


def test_quota_and_rate_limit_are_distinct():
    quota_code, _quota = classify_exception(RuntimeError("You exceeded your current quota"))
    rate_code, _rate = classify_exception(RuntimeError("429 too many requests"))
    assert quota_code == "quota"
    assert rate_code == "rate_limit"


def test_tighter_of_amount_and_percent_is_used():
    sizing = calculate_position(
        PositionInputs(
            entry_price=100,
            stop_loss=95,
            price_target=110,
            action="Buy",
            available_capital=10000,
            available_cash=10000,
            max_risk_amount=200,
            max_risk_percent=1,
            max_position_percent=50,
            cost_bps=0,
        )
    )
    assert sizing["status"] == "available"
    assert sizing["shares"] == 20
    assert any("tighter budget" in item for item in sizing["assumptions"])
    assert any("not a guaranteed maximum loss" in item for item in sizing["assumptions"])


def test_global_prices_are_not_kept_or_assigned(tmp_path):
    store = DashboardStore(tmp_path / "dashboard" / "research.db")
    store.save_preferences(
        {
            "available_capital": 1000,
            "scale_in_prices": [10, 11],
            "take_profit_prices": [12],
        }
    )
    prefs = store.get_preferences()
    assert prefs["available_capital"] == 1000
    assert "scale_in_prices" not in prefs
    assert "take_profit_prices" not in prefs
    first = store.save_plan_draft("a", "AAPL", 1, {"scale_in_prices": [10], "ticker": "AAPL"})
    second = store.save_plan_draft("b", "MSFT", 1, {"scale_in_prices": [20], "ticker": "MSFT"})
    assert first["inputs"]["scale_in_prices"] == [10]
    assert second["inputs"]["ticker"] == "MSFT"
    assert store.get_plan_draft("a")["inputs"]["scale_in_prices"] == [10]


def test_absolute_report_paths_become_relative(tmp_path):
    home = tmp_path / "home"
    report = home / "logs" / "reports" / "AAPL_1" / "complete_report.html"
    report.parent.mkdir(parents=True)
    report.write_text("<html>kept</html>", encoding="utf-8")
    markdown = report.with_suffix(".md")
    markdown.write_text("kept", encoding="utf-8")
    db_path = home / "dashboard" / "research.db"
    store = DashboardStore(db_path)
    absolute = f"/Users/someone/.tradingagents/logs/reports/AAPL_1/{report.name}"
    assert relativize_stored_path(absolute, home) == "reports/AAPL_1/complete_report.html"
    store.insert_analysis(
        {
            "id": "one",
            "fingerprint": "fp",
            "ticker": "AAPL",
            "analysis_date": "2020-01-02",
            "settings": {},
            "status": "completed",
            "phase": "completed",
            "agent_status": {},
            "reports": {"market_report": "text"},
            "html_report_path": str(report),
            "markdown_report_path": str(markdown),
            "created_at": "2020-01-02T00:00:00+00:00",
        }
    )
    # The first open already recorded version 1, so rerun the path rewrite directly.
    from backend.storage.migrate import _rewrite_paths

    changed = _rewrite_paths(store._conn, home)
    store._conn.commit()
    assert changed == 1
    saved = store.get_analysis("one")
    assert saved["html_report_path"] == "reports/AAPL_1/complete_report.html"
    assert saved["reports"]["market_report"] == "text"
    again = apply(store._conn, home)
    assert again["paths"] == 0


def test_restart_marks_leftover_work_interrupted_and_keeps_reports(tmp_path):
    store = DashboardStore(tmp_path / "dashboard" / "research.db")
    store.insert_analysis(
        {
            "id": "run",
            "fingerprint": "fp",
            "ticker": "AAPL",
            "analysis_date": "2020-01-02",
            "settings": {"ticker": "AAPL"},
            "status": "running",
            "phase": "analysts",
            "agent_status": {"Market Analyst": "in_progress"},
            "reports": {"market_report": "partial"},
            "created_at": "2020-01-02T00:00:00+00:00",
        }
    )
    runner = AnalysisRunner(store, worker=lambda job, handle: None, isolate=False)
    app = create_app(store, runner)
    with TestClient(app) as client:
        body = client.get("/api/analyses/run").json()
    assert body["status"] == "interrupted"
    assert body["error_code"] == "interrupted"
    assert "not cancelled" in body["error"]
    assert body["reports"]["market_report"] == "partial"
    assert body["agent_status"]["Market Analyst"] == "in_progress"


def test_queue_full_and_invalid_market_date(tmp_path):
    started = []

    def worker(job, handle):
        started.append(job.id)
        handle.update(status="running", phase="analysts", message="working")
        time.sleep(0.4)
        handle.update(status="completed", phase="completed", message="done")

    store = DashboardStore(tmp_path / "dashboard" / "research.db")
    runner = AnalysisRunner(store, worker=worker, isolate=False, max_running=1, max_queued=2)
    app = create_app(store, runner)
    with TestClient(app) as client:
        for ticker in ("AAPL", "MSFT", "NVDA"):
            response = client.post("/api/analyses", json=_payload(ticker))
            assert response.status_code == 200
        rejected = client.post("/api/analyses", json=_payload("IBM"))
        assert rejected.status_code == 429
        assert rejected.json()["detail"]["code"] == "queue_full"
        bad_date = client.get("/api/market/AAPL", params={"as_of": "13-11-2026"})
        assert bad_date.status_code == 422
        time.sleep(1.2)


def test_cancel_stops_the_child_process(tmp_path):
    store = DashboardStore(tmp_path / "dashboard" / "research.db")
    runner = AnalysisRunner(store, worker=block, isolate=True, timeout_seconds=30)
    app = create_app(store, runner)
    with TestClient(app) as client:
        started = client.post("/api/analyses", json=_payload("AAPL"))
        assert started.status_code == 200
        analysis_id = started.json()["id"]
        deadline = time.time() + 30
        seen_report = False
        while time.time() < deadline:
            body = client.get(f"/api/analyses/{analysis_id}").json()
            if body.get("reports", {}).get("market_report"):
                seen_report = True
                break
            time.sleep(0.1)
        assert seen_report
        cancelled = client.post(f"/api/analyses/{analysis_id}/cancel")
        assert cancelled.status_code == 200
        final = None
        while time.time() < deadline:
            final = client.get(f"/api/analyses/{analysis_id}").json()
            if final["status"] in {"stopped", "failed", "timed_out"}:
                break
            time.sleep(0.1)
        assert final is not None
        assert final["status"] == "stopped"
        assert final["error_code"] == "stopped"
        assert final["reports"]["market_report"] == "partial note"
        assert "cancelled" not in (final["error"] or "").lower() or "not cancelled" in (final["error"] or "").lower()


def _payload(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "analysis_date": "2020-01-02",
        "analysts": ["market"],
        "research_depth": 1,
        "output_language": "English",
        "llm_provider": "ollama",
        "quick_think_llm": "test-model",
        "deep_think_llm": "test-model",
    }
