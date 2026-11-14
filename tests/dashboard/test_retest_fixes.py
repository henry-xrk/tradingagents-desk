"""Regressions from the 2026-11-13 retest. Samples are fictional."""

import threading

from fastapi.testclient import TestClient

from backend.errors import classify_exception, redact
from backend.main import create_app
from backend.services.market_data import load_chart
from backend.services.provider_check import probe_openai
from backend.services.runner import AnalysisRunner
from backend.services.trade_plan import PositionInputs, calculate_position
from backend.storage.db import DashboardStore
from backend.storage.migrate import _snapshot_existing_plans


def test_structured_credentials_are_redacted():
    json_secret = '{"api_key": "demo-secret-12345", "nested": [{"access_token": "demo-token-12345"}]}'
    python_secret = "{'access_token': 'demo-token-12345'}"
    assert "demo-secret-12345" not in redact(json_secret)
    assert "demo-token-12345" not in redact(json_secret)
    assert "demo-token-12345" not in redact(python_secret)
    assert "demo-secret-12345" not in redact({"api_key": "demo-secret-12345"})


def test_quota_beats_generic_429_and_is_not_retried():
    class Response:
        status_code = 429
        headers = {"Retry-After": "9"}

        @staticmethod
        def json():
            return {"error": {"code": "insufficient_quota", "message": "You exceeded your current quota"}}

    class RateResponse:
        status_code = 429
        headers = {"Retry-After": "9"}

        @staticmethod
        def json():
            return {"error": {"code": "rate_limit_exceeded", "message": "Too many requests"}}

    class Error(Exception):
        def __init__(self, text, response):
            super().__init__(text)
            self.response = response
            self.code = response.json()["error"]["code"]

    quota_code, quota_message = classify_exception(
        Error("Error code: 429 - insufficient_quota: You exceeded your current quota", Response())
    )
    rate_code, rate_message = classify_exception(
        Error("Error code: 429 - rate_limit_exceeded", RateResponse())
    )
    assert quota_code == "quota"
    assert "not retried" in quota_message
    assert "Retry after" not in quota_message
    assert rate_code == "rate_limit"
    assert "Retry after 9 seconds" in rate_message


def test_provider_check_uses_the_same_quota_classification(monkeypatch):
    class Response:
        status_code = 429
        headers = {}

        @staticmethod
        def json():
            return {"error": {"code": "insufficient_quota", "message": "You exceeded your current quota"}}

    monkeypatch.setattr(
        "backend.services.provider_check.requests.get",
        lambda *args, **kwargs: Response(),
    )
    result = probe_openai({"OPENAI_API_KEY": "demo-secret-12345"})
    assert result["code"] == "quota"
    assert "demo-secret-12345" not in result["message"]


def test_provider_check_uses_the_configured_openai_host(monkeypatch):
    seen = {}

    class Response:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return {"data": []}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["authorization"] = kwargs["headers"]["Authorization"]
        return Response()

    monkeypatch.setattr("backend.services.provider_check.requests.get", fake_get)
    configured = probe_openai({
        "OPENAI_API_KEY": "demo-secret-12345",
        "TRADINGAGENTS_LLM_BACKEND_URL": "https://us.api.openai.com/v1/",
    })
    assert seen["url"] == "https://us.api.openai.com/v1/models"
    assert configured["ok"] is True
    assert "demo-secret-12345" not in configured["message"]
    assert "demo-secret-12345" not in seen["url"]

    def default_get(url, **kwargs):
        seen["default_url"] = url
        return Response()

    monkeypatch.setattr("backend.services.provider_check.requests.get", default_get)
    probe_openai({"OPENAI_API_KEY": "demo-secret-12345"})
    assert seen["default_url"] == "https://api.openai.com/v1/models"

    refused = probe_openai({
        "OPENAI_API_KEY": "demo-secret-12345",
        "TRADINGAGENTS_LLM_BACKEND_URL": "file:///tmp/models",
    })
    assert refused["ok"] is False
    assert refused["code"] == "error"
    assert "demo-secret-12345" not in refused["message"]


def test_saved_plan_versions_are_append_only(tmp_path):
    store = DashboardStore(tmp_path / "dashboard" / "research.db")
    store.insert_analysis(_record("a", "AAPL"))
    first = store.append_plan_version("a", "AAPL", {"scale_in_prices": [100]}, {"shares": 1})
    second = store.append_plan_version("a", "AAPL", {"scale_in_prices": [110]}, {"shares": 2})
    assert first["version"] == 1
    assert second["version"] == 2
    assert store.get_plan_version("a", 1)["snapshot"]["scale_in_prices"] == [100]
    assert store.get_plan_version("a", 2)["plan"]["shares"] == 2
    assert len(store.list_plan_versions("a")) == 2


def test_concurrent_plan_versions_do_not_share_a_number(tmp_path):
    path = tmp_path / "dashboard" / "research.db"
    DashboardStore(path).insert_analysis(_record("a", "AAPL"))
    versions = []

    def save(price):
        store = DashboardStore(path)
        saved = store.append_plan_version("a", "AAPL", {"scale_in_prices": [price]}, {"shares": price})
        versions.append(saved["version"])

    threads = [threading.Thread(target=save, args=(price,)) for price in (100, 110, 120)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(versions) == [1, 2, 3]


def test_migration_does_not_invent_missing_plan_versions(tmp_path):
    store = DashboardStore(tmp_path / "dashboard" / "research.db")
    record = _record("a", "MSFT")
    record["trade_plan"] = {"plan_version": 2, "input_snapshot": {"scale_in_prices": [50]}, "shares": 3}
    store.insert_analysis(record)
    assert _snapshot_existing_plans(store._conn) == 1
    store._conn.commit()
    assert [row["version"] for row in store.list_plan_versions("a")] == [2]
    assert _snapshot_existing_plans(store._conn) == 0


def test_manual_prices_are_not_labeled_as_hypotheses():
    sizing = calculate_position(
        PositionInputs(
            entry_price=100,
            stop_loss=95,
            price_target=110,
            action="Buy",
            available_capital=10000,
            available_cash=10000,
            max_risk_amount=500,
            max_position_percent=25,
            level_source="manual",
        )
    )
    assert sizing["limit_entries"][0]["source"] == "manual"
    assert sizing["exits"][0]["source"] == "manual"


def test_position_endpoint_marks_typed_prices_manual(tmp_path):
    client = TestClient(create_app(DashboardStore(tmp_path / "dashboard" / "research.db"), AnalysisRunner(DashboardStore(tmp_path / "other.db"), worker=lambda job, handle: None, isolate=False)))
    response = client.post(
        "/api/position-size",
        json={
            "entry_price": 100,
            "stop_loss": 95,
            "price_target": 110,
            "action": "Buy",
            "available_capital": 10000,
            "available_cash": 10000,
            "max_risk_amount": 500,
            "max_position_percent": 25,
        },
    )
    assert response.status_code == 200
    assert response.json()["limit_entries"][0]["source"] == "manual"


def test_cache_hit_does_not_claim_a_new_download():
    import pandas as pd

    frame = pd.DataFrame({"Date": pd.to_datetime(["2020-01-02"]), "Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]})
    frame.attrs["desk_market"] = {"cache_hit": True, "downloaded_at": None, "cache_written_at": "2020-01-02T00:00:00+00:00"}
    chart = load_chart("AAPL", "2020-01-02", loader=lambda ticker, as_of: frame)
    assert chart["cache_status"] == "hit"
    assert chart["downloaded_at"] is None
    assert chart["read_at"]


def test_selected_analyst_absence_is_not_partial(tmp_path):
    store = DashboardStore(tmp_path / "dashboard" / "research.db")
    record = _record("a", "AAPL")
    record["settings"] = {"analysts": ["market"]}
    record["reports"] = {
        "market_report": "prices",
        "investment_plan": "plan",
        "trader_investment_plan": "trade",
        "final_trade_decision": "decision",
    }
    record["status"] = "completed"
    store.insert_analysis(record)
    summary = store.list_analyses()[0]
    assert summary["has_partial_report"] is False


def test_research_calendar_covers_the_utc_boundary_dst_and_weekends():
    from datetime import UTC, datetime

    from tradingagents.dataflows.date_window import research_calendar_date

    assert research_calendar_date(datetime(2026, 11, 14, 3, 30, tzinfo=UTC)) == "2026-11-13"
    assert research_calendar_date(datetime(2026, 11, 13, 21, 0, tzinfo=UTC)) == "2026-11-13"
    assert research_calendar_date(datetime(2026, 7, 1, 3, 30, tzinfo=UTC)) == "2026-06-30"
    assert research_calendar_date(datetime(2026, 11, 14, 16, 0, tzinfo=UTC)) == "2026-11-14"


def test_connection_check_does_not_survive_an_endpoint_change(tmp_path, monkeypatch):
    from backend.routers.api import _current_validation
    from backend.services.provider_check import credential_fingerprint

    monkeypatch.setenv("OPENAI_API_KEY", "demo-secret-12345")
    monkeypatch.setenv("TRADINGAGENTS_LLM_BACKEND_URL", "https://us.api.openai.com/v1")
    host, digest = credential_fingerprint()
    store = DashboardStore(tmp_path / "dashboard" / "research.db")
    store.save_provider_check(
        {"ok": True, "code": "ok", "message": "accepted", "endpoint": host, "credential_id": digest}
    )
    current = _current_validation(store.latest_provider_check())
    assert current["matches_current"] is True
    assert "demo-secret-12345" not in current["message"]
    monkeypatch.setenv("TRADINGAGENTS_LLM_BACKEND_URL", "https://api.openai.com/v1")
    stale = _current_validation(store.latest_provider_check())
    assert stale["code"] == "stale"
    assert stale["matches_current"] is False


def test_public_terminal_status_hides_in_progress_without_rewriting_storage(tmp_path):
    from backend.routers.api import _public

    store = DashboardStore(tmp_path / "dashboard" / "research.db")
    record = _record("failed-run", "NVDA")
    record["status"] = "failed"
    record["agent_status"] = {"Market Analyst": "in_progress", "Trader": "completed"}
    store.insert_analysis(record)
    shown = _public(store.get_analysis("failed-run"))
    assert shown["agent_status"]["Market Analyst"] == "not_completed"
    assert shown["agent_status"]["Trader"] == "completed"
    stored = store.get_analysis("failed-run")["agent_status"]["Market Analyst"]
    assert stored == "in_progress"


def test_terminal_run_does_not_leave_agents_in_progress():
    from backend.services.runner import _settle_open_agents

    record = {"agent_status": {"Market Analyst": "completed", "News Analyst": "in_progress"}}
    _settle_open_agents(record)
    assert record["agent_status"]["Market Analyst"] == "completed"
    assert record["agent_status"]["News Analyst"] == "not_completed"


def _record(analysis_id: str, ticker: str) -> dict:
    return {
        "id": analysis_id,
        "fingerprint": analysis_id,
        "ticker": ticker,
        "analysis_date": "2020-01-02",
        "settings": {"analysts": ["market"]},
        "status": "completed",
        "phase": "completed",
        "agent_status": {},
        "reports": {"market_report": "text"},
        "created_at": "2020-01-02T00:00:00+00:00",
    }
