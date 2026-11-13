"""API behavior that does not call a model or a market-data vendor."""

import threading
import time

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.services.options import clear_model_cache
from backend.services.runner import AnalysisRunner
from backend.storage.db import DashboardStore


def _payload(**overrides):
    body = {
        "ticker": "AAPL",
        "analysis_date": "2020-01-02",
        "analysts": ["market"],
        "research_depth": 1,
        "output_language": "English",
        "llm_provider": "ollama",
        "quick_think_llm": "test-model",
        "deep_think_llm": "test-model",
    }
    body.update(overrides)
    return body


def _client(tmp_path, worker=None, timeout_seconds=45 * 60):
    store = DashboardStore(tmp_path / "research.db")
    runner = AnalysisRunner(store, worker=worker, timeout_seconds=timeout_seconds)
    app = create_app(store, runner, timeout_seconds=timeout_seconds)
    return TestClient(app), runner


def test_health_reports_the_installed_engine():
    client, _runner = _client_from_factory()
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.7.1"
    assert body["today"]


def _client_from_factory():
    # Health does not need a private database beyond the app factory's temp store.
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    return _client(folder)


def test_auth_status_does_not_expose_tokens():
    client, _runner = _client_from_factory()
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"provider", "signed_in", "email", "message"}
    raw = response.text.lower()
    assert "access_token" not in raw
    assert "refresh_token" not in raw
    assert "chatgpt-auth" not in raw


def test_options_use_the_catalog_without_calling_the_plan(monkeypatch):
    clear_model_cache()
    monkeypatch.setattr("backend.services.options.signed_in_as", lambda: None)
    monkeypatch.setattr(
        "backend.services.options.chatgpt_models",
        lambda: (_ for _ in ()).throw(AssertionError("live model list should not be called")),
    )
    client, _runner = _client_from_factory()
    response = client.get("/api/config/options")
    assert response.status_code == 200
    body = response.json()
    assert body["default_provider"] == "openai"
    ids = {provider["id"] for provider in body["providers"]}
    assert "chatgpt" not in ids
    assert "ollama" in ids
    assert "API key" not in response.text or "OPENAI_API_KEY" in response.text


def test_position_size_endpoint_matches_the_engine():
    client, _runner = _client_from_factory()
    response = client.post(
        "/api/position-size",
        json={
            "entry_price": 100,
            "stop_loss": 95,
            "price_target": 110,
            "action": "Buy",
            "available_capital": 10000,
            "available_cash": 10000,
            "max_risk_amount": 200,
            "max_position_percent": 50,
            "cost_bps": 0,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["orders_sent"] is False
    assert body["sizing"]["shares"] == 40
    assert body["entry_zone"]["status"] == "unavailable"


def test_duplicate_analysis_reuses_the_active_run(tmp_path):
    started = threading.Event()
    release = threading.Event()

    def worker(job, handle):
        handle.update(status="running", phase="analysts", message="working")
        started.set()
        release.wait(5)
        handle.update(status="completed", phase="completed", message="done")

    client, _runner = _client(tmp_path, worker=worker)
    with client:
        first = client.post("/api/analyses", json=_payload())
        assert first.status_code == 200
        assert started.wait(2)
        second = client.post("/api/analyses", json=_payload())
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["reused"] is True
        release.set()


def test_future_date_and_crypto_fundamentals_are_rejected(tmp_path):
    client, _runner = _client(tmp_path, worker=lambda job, handle: None)
    with client:
        future = client.post("/api/analyses", json=_payload(analysis_date="2999-01-01"))
        assert future.status_code == 422
        crypto = client.post(
            "/api/analyses",
            json=_payload(ticker="BTC-USD", analysts=["market", "fundamentals"]),
        )
        assert crypto.status_code == 422
        assert "fundamentals" in crypto.json()["detail"]["message"]


def test_timeout_is_not_replaced_by_a_late_completion(tmp_path):
    def worker(job, handle):
        time.sleep(0.3)
        handle.update(status="completed", phase="completed", message="late")

    client, _runner = _client(tmp_path, worker=worker, timeout_seconds=0.05)
    with client:
        started = client.post("/api/analyses", json=_payload())
        analysis_id = started.json()["id"]
        deadline = time.time() + 2
        status = None
        while time.time() < deadline:
            status = client.get(f"/api/analyses/{analysis_id}").json()
            if status["status"] == "timed_out":
                break
            time.sleep(0.05)
        assert status is not None
        assert status["status"] == "timed_out"
        assert status["error_code"] == "timeout"
        time.sleep(0.4)
        again = client.get(f"/api/analyses/{analysis_id}").json()
        assert again["status"] == "timed_out"


def test_report_route_rejects_paths_outside_the_results_directory(tmp_path, monkeypatch):
    root = tmp_path / "results"
    root.mkdir()
    report = root / "complete_report.html"
    report.write_text("<html>report</html>", encoding="utf-8")
    outside = tmp_path / "complete_report.html"
    outside.write_text("<html>no</html>", encoding="utf-8")
    monkeypatch.setattr("backend.services.reports.results_root", lambda: root.resolve())
    client, _runner = _client(tmp_path)
    with client:
        allowed = client.get("/api/reports/html", params={"path": str(report)})
        assert allowed.status_code == 200
        assert "report" in allowed.text
        rejected = client.get("/api/reports/html", params={"path": str(outside)})
        assert rejected.status_code == 403


def test_event_stream_replays_a_finished_run(tmp_path):
    def worker(job, handle):
        handle.update(status="completed", phase="completed", message="done", rating="Buy")

    client, _runner = _client(tmp_path, worker=worker)
    with client:
        started = client.post("/api/analyses", json=_payload())
        analysis_id = started.json()["id"]
        deadline = time.time() + 2
        while time.time() < deadline:
            if client.get(f"/api/analyses/{analysis_id}").json()["status"] == "completed":
                break
            time.sleep(0.02)
        with client.stream("GET", f"/api/analyses/{analysis_id}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())
        assert "event: completed" in body
        assert "done" in body
