"""Pagination, plan-save atomicity, and research snapshot immutability."""

import threading

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.services.runner import AnalysisRunner
from backend.services.trade_plan import assemble_trade_plan, interpret_decision
from backend.storage.db import DashboardStore, PlanConflict
from tests.dashboard.test_trade_plan import NVDA_DECISION, NVDA_TRADER


def _record(analysis_id: str, ticker: str = "NVDA", created_at: str = "2020-01-02T00:00:00+00:00") -> dict:
    return {
        "id": analysis_id,
        "fingerprint": analysis_id,
        "ticker": ticker,
        "analysis_date": "2026-11-13",
        "settings": {
            "ticker": ticker,
            "analysis_date": "2026-11-13",
            "analysts": ["market"],
            "research_depth": 1,
            "output_language": "English",
            "llm_provider": "openai",
            "quick_think_llm": "quick",
            "deep_think_llm": "deep",
        },
        "status": "completed",
        "phase": "completed",
        "agent_status": {},
        "reports": {
            "trader_investment_plan": NVDA_TRADER,
            "final_trade_decision": NVDA_DECISION,
        },
        "rating": "Underweight",
        "trade_plan": {
            "verified_market": {
                "status": "available",
                "source": "yfinance",
                "price": 10,
                "bar_date": "2026-11-13",
                "currency": "USD",
                "role": "research_snapshot",
            }
        },
        "data_sources": {
            "market": {"status": "available", "source": "yfinance", "price": 10, "bar_date": "2026-11-13", "currency": "USD"},
            "research_market": {
                "status": "available",
                "source": "yfinance",
                "price": 10,
                "bar_date": "2026-11-13",
                "currency": "USD",
                "role": "research_snapshot",
            },
        },
        "created_at": created_at,
    }


def _capital(**overrides):
    body = {
        "available_capital": 10000,
        "available_cash": 8000,
        "max_risk_amount": 200,
        "max_risk_percent": 2,
        "max_position_percent": 25,
        "cost_bps": 1,
        "scale_in_prices": [],
        "take_profit_prices": [],
        "expected_plan_version": None,
        "save_as_default": False,
    }
    body.update(overrides)
    return body


def test_not_provided_prices_do_not_fail_the_research():
    decision = interpret_decision(NVDA_TRADER, NVDA_DECISION)
    assert decision["result_status"] == "readable"
    assert decision["final_status"] == "parsed"
    assert decision["rating"] == "Underweight"
    assert decision["action"] is None
    assert decision["plan_status"] == "not_applicable"
    assert decision["price_fields"]["entry_price"] == "stated_absent"
    plan = assemble_trade_plan(
        ticker="NVDA",
        analysis_date="2026-11-13",
        reports={"trader_investment_plan": NVDA_TRADER, "final_trade_decision": NVDA_DECISION},
        reference={"status": "available", "source": "yfinance", "price": 162.85, "bar_date": "2026-11-13"},
        preferences={},
    )
    assert plan["sizing"]["shares"] is None
    assert plan["hypotheses"]["entry_price"] is None


def test_history_cursor_returns_every_tied_row(tmp_path):
    store = DashboardStore(tmp_path / "research.db")
    for index in range(105):
        store.insert_analysis(_record(f"id-{index:03d}"))
    client = TestClient(create_app(store, AnalysisRunner(store, worker=lambda job, handle: None)))
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 20}
        if cursor:
            params["cursor"] = cursor
        response = client.get("/api/history", params=params)
        assert response.status_code == 200
        body = response.json()
        assert "reports" not in body["items"][0] if body["items"] else True
        seen.extend(row["id"] for row in body["items"])
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            break
        assert pages < 20
    assert len(seen) == 105
    assert len(set(seen)) == 105
    assert seen == sorted(seen, reverse=True)
    assert client.get("/api/history", params={"cursor": "not-a-cursor"}).status_code == 422


def test_failed_plan_save_leaves_no_partial_update(tmp_path, monkeypatch):
    store = DashboardStore(tmp_path / "research.db")
    store.insert_analysis(_record("nvda"))
    store.save_preferences({"available_capital": 50, "available_cash": 40, "cost_bps": 0})
    import backend.storage.db as database

    original = database._dump
    calls = {"n": 0}

    def dump(value):
        calls["n"] += 1
        if calls["n"] == 5:
            raise RuntimeError("forced failure")
        return original(value)

    monkeypatch.setattr(database, "_dump", dump)
    try:
        store.commit_rebuilt_plan(
            analysis_id="nvda",
            ticker="NVDA",
            snapshot={"capital": {"available_capital": 10000}},
            plan={"verified_market": {"price": 10}},
            expected_plan_version=None,
            preferences={"available_capital": 10000, "available_cash": 10000, "cost_bps": 0},
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("the forced failure should abort the save")
    saved = store.get_analysis("nvda")
    assert saved["trade_plan"]["verified_market"]["price"] == 10
    assert saved["trade_plan"].get("plan_version") is None
    assert store.list_plan_versions("nvda") == []
    assert store.get_preferences()["available_capital"] == 50


def test_concurrent_plan_saves_do_not_move_the_current_version_backward(tmp_path):
    store = DashboardStore(tmp_path / "research.db")
    store.insert_analysis(_record("nvda"))
    barrier = threading.Barrier(2)
    results = []
    conflicts = []

    def save(price: int):
        barrier.wait(5)
        try:
            saved = store.commit_rebuilt_plan(
                analysis_id="nvda",
                ticker="NVDA",
                snapshot={"capital": {"available_capital": price}},
                plan={"marker": price},
                expected_plan_version=None,
                preferences=None,
            )
            results.append(saved["version"])
        except PlanConflict as exc:
            conflicts.append(exc.current)

    threads = [threading.Thread(target=save, args=(price,)) for price in (100, 200)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [1]
    assert conflicts == [1]
    current = store.get_analysis("nvda")["trade_plan"]["plan_version"]
    assert current == max(row["version"] for row in store.list_plan_versions("nvda"))
    newer = store.commit_rebuilt_plan(
        analysis_id="nvda",
        ticker="NVDA",
        snapshot={},
        plan={"marker": 2},
        expected_plan_version=1,
        preferences=None,
    )
    assert newer["version"] == 2
    try:
        store.commit_rebuilt_plan(
            analysis_id="nvda",
            ticker="NVDA",
            snapshot={},
            plan={"marker": 1},
            expected_plan_version=1,
            preferences=None,
        )
    except PlanConflict as exc:
        assert exc.current == 2
    else:
        raise AssertionError("an older plan version should be rejected")
    assert store.get_analysis("nvda")["trade_plan"]["plan_version"] == 2


def test_recalculate_keeps_the_research_snapshot_and_optional_default(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.api.reference_quote",
        lambda ticker, day: {
            "status": "available",
            "source": "yfinance",
            "price": 999,
            "bar_date": "2024-02-02",
            "fetched_at": "2024-02-03T00:00:00+00:00",
            "currency": "USD",
            "error": None,
        },
    )
    store = DashboardStore(tmp_path / "research.db")
    store.insert_analysis(_record("nvda"))
    client = TestClient(create_app(store, AnalysisRunner(store, worker=lambda job, handle: None)))
    first = client.post("/api/analyses/nvda/trade-plan", json=_capital())
    assert first.status_code == 200
    body = first.json()
    assert body["verified_market"]["price"] == 10
    assert body["verified_market"]["role"] == "research_snapshot"
    assert body["calculation_market"]["price"] == 999
    assert body["calculation_market"]["role"] == "calculation_snapshot"
    saved = store.get_analysis("nvda")
    assert saved["data_sources"]["research_market"]["price"] == 10
    assert saved["data_sources"]["market"]["price"] == 10
    assert store.get_preferences()["available_capital"] is None
    second = client.post("/api/analyses/nvda/trade-plan", json=_capital(expected_plan_version=1, save_as_default=True, available_capital=2222))
    assert second.status_code == 200
    assert store.get_preferences()["available_capital"] == 2222
    assert store.get_analysis("nvda")["data_sources"]["research_market"]["price"] == 10
    conflict = client.post("/api/analyses/nvda/trade-plan", json=_capital(expected_plan_version=1))
    assert conflict.status_code == 409
    assert store.get_analysis("nvda")["trade_plan"]["plan_version"] == 2
