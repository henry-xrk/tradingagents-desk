"""Dashboard HTTP API."""

from __future__ import annotations

import asyncio
import json
import os
import queue
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

import tradingagents
from backend.errors import DashboardError
from backend.schemas.models import (
    AnalysisCreate,
    CapitalPreferences,
    PositionSizeRequest,
    TradePlanUpdate,
    ValidateRequest,
    WatchlistAdd,
)
from backend.services.market_data import MarketDataError, load_chart, quote_summary, reference_quote
from backend.services.options import config_options
from backend.services.provider_check import credential_fingerprint, probe_openai
from backend.services.reports import resolve_html_report
from backend.services.runner import TERMINAL
from backend.services.settings import canonical_ticker, parse_calendar_date, prepare_settings
from backend.services.trade_plan import (
    DISCLAIMER,
    LIMITATIONS,
    PositionInputs,
    assemble_trade_plan,
    calculate_position,
    interpret_decision,
)
from backend.storage.db import ACTIVE_STATUSES, PlanConflict, decode_cursor, encode_cursor, utcnow
from backend.storage.migrate import MIGRATION_VERSION
from tradingagents.dataflows.date_window import research_calendar_date
from tradingagents.llm_clients.chatgpt_auth import LOGIN_HINT, signed_in_as

router = APIRouter()

_HIDDEN = {"fingerprint"}
_SIZING_WRAP = {"entry_zone", "limit_entries", "exits", "invalidation", "assumptions", "inputs"}


def _current_validation(check: dict | None) -> dict:
    host, fingerprint = credential_fingerprint()
    if not check or not check.get("credential_id"):
        return {
            "checked_at": None if not check else check.get("checked_at"),
            "ok": None,
            "code": "not_checked" if not check else "stale",
            "message": "No connection test has been run."
            if not check
            else "The saved connection check does not match the current endpoint or credential configuration.",
            "endpoint": host,
            "matches_current": False,
        }
    matches = check.get("credential_id") == fingerprint and (check.get("endpoint") or "") == host
    if not matches:
        return {
            "checked_at": check.get("checked_at"),
            "ok": None,
            "code": "stale",
            "message": "The saved connection check does not match the current endpoint or credential configuration.",
            "endpoint": host,
            "matches_current": False,
        }
    return {
        "checked_at": check.get("checked_at"),
        "ok": check.get("ok"),
        "code": check.get("code"),
        "message": check.get("message"),
        "endpoint": host,
        "matches_current": True,
    }


def _public(record: dict) -> dict:
    body = {key: value for key, value in record.items() if key not in _HIDDEN}
    if body.get("status") in {"completed", "failed", "timed_out", "stopped", "interrupted"}:
        agents = dict(body.get("agent_status") or {})
        body["agent_status"] = {
            name: "not_completed" if value == "in_progress" else value
            for name, value in agents.items()
        }
    reports = body.get("reports") or {}
    body["decision"] = interpret_decision(
        reports.get("trader_investment_plan"),
        reports.get("final_trade_decision"),
        reports.get("investment_plan"),
    )
    return body


def _http(exc: DashboardError) -> HTTPException:
    detail = {"code": exc.code, "message": exc.message}
    if exc.ref:
        detail["ref"] = exc.ref
    return HTTPException(status_code=exc.status, detail=detail)


def _market_http(exc: MarketDataError) -> HTTPException:
    status = 404 if exc.code == "no_market_data" else 502
    return HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": exc.message, "source": "yfinance"},
    )


def _baked_build() -> dict[str, str]:
    """Identity written into the image. A runtime environment value cannot replace it."""
    path = Path(os.environ.get("DESK_BUILD_FILE", "/app/desk-build.json"))
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            return {
                "commit": str(payload.get("commit") or "unknown"),
                "tree": str(payload.get("tree") or "unknown"),
            }
    return {"commit": "unknown", "tree": "unknown"}


@router.get("/api/health")
def health():
    build = _baked_build()
    return {
        "status": "ok",
        "service": "tradingagents-dashboard",
        "version": tradingagents.__version__,
        "commit": build["commit"],
        "tree": build["tree"],
        "schema": MIGRATION_VERSION,
        "today": research_calendar_date(),
        "research_calendar": "America/New_York",
    }


@router.get("/api/system")
def system_status(request: Request):
    check = _current_validation(request.app.state.store.latest_provider_check())
    return {
        "service": "tradingagents-dashboard",
        "version": tradingagents.__version__,
        "commit": _baked_build()["commit"],
        "openai_api_key_configured": bool(os.environ.get("OPENAI_API_KEY")),
        "configured_means": "A configured key is not proof that it is valid or that the account has balance. A connection check is not a completed research run.",
        "validation": check,
    }


@router.post("/api/system/validate")
def validate_provider(body: ValidateRequest, request: Request):
    if not body.confirm_charge:
        raise _http(
            DashboardError(
                "A connection test can call the model provider and may incur charges. Confirm before continuing.",
                status=422,
                code="confirm_required",
            )
        )
    host, fingerprint = credential_fingerprint()
    result = probe_openai()
    result["endpoint"] = host
    result["credential_id"] = fingerprint
    saved = request.app.state.store.save_provider_check(result)
    return _current_validation(saved)


@router.get("/api/auth/status")
def auth_status():
    email = signed_in_as()
    return {
        "provider": "chatgpt",
        "signed_in": email is not None,
        "email": email,
        "message": None if email else LOGIN_HINT,
    }


@router.get("/api/config/options")
def options():
    return config_options()


@router.get("/api/preferences")
def get_preferences(request: Request):
    return request.app.state.store.get_preferences()


@router.put("/api/preferences")
def put_preferences(body: CapitalPreferences, request: Request):
    return request.app.state.store.save_preferences(body.model_dump())


@router.get("/api/watchlist")
def get_watchlist(request: Request, as_of: str | None = None):
    day = as_of or research_calendar_date()
    rows = []
    for item in request.app.state.store.list_watchlist():
        quote = quote_summary(item["ticker"], day)
        quote["added_at"] = item["created_at"]
        rows.append(quote)
    return {"as_of": day, "source": "yfinance", "items": rows}


@router.post("/api/watchlist")
def add_watch(body: WatchlistAdd, request: Request):
    try:
        ticker = canonical_ticker(body.ticker)
    except DashboardError as exc:
        raise _http(exc) from exc
    request.app.state.store.add_watch(ticker)
    return {"ticker": ticker}


@router.delete("/api/watchlist/{ticker}")
def remove_watch(ticker: str, request: Request):
    try:
        symbol = canonical_ticker(ticker)
    except DashboardError as exc:
        raise _http(exc) from exc
    request.app.state.store.remove_watch(symbol)
    return {"ticker": symbol}


@router.get("/api/market/{ticker}")
def market(ticker: str, as_of: str | None = None):
    try:
        day = parse_calendar_date(as_of) if as_of else research_calendar_date()
        symbol = canonical_ticker(ticker)
        return load_chart(symbol, day)
    except DashboardError as exc:
        raise _http(exc) from exc
    except MarketDataError as exc:
        raise _market_http(exc) from exc


@router.post("/api/position-size")
def position_size(body: PositionSizeRequest):
    sizing = calculate_position(
        PositionInputs(
            entry_price=body.entry_price,
            stop_loss=body.stop_loss,
            price_target=body.price_target,
            action=body.action,
            available_capital=body.available_capital,
            available_cash=body.available_cash,
            max_risk_amount=body.max_risk_amount,
            max_risk_percent=body.max_risk_percent,
            max_position_percent=body.max_position_percent,
            cost_bps=body.cost_bps,
            scale_in_prices=list(body.scale_in_prices),
            take_profit_prices=list(body.take_profit_prices),
            level_source="manual",
        )
    )
    wrapped = {key: sizing[key] for key in _SIZING_WRAP}
    core = {key: value for key, value in sizing.items() if key not in _SIZING_WRAP}
    return {
        "disclaimer": DISCLAIMER,
        "orders_sent": False,
        "limitations": LIMITATIONS,
        "explanation": None,
        "calculated_at": utcnow(),
        **wrapped,
        "sizing": core,
    }


@router.post("/api/analyses")
def start_analysis(body: AnalysisCreate, request: Request):
    try:
        settings = prepare_settings(body)
        return _public(request.app.state.runner.start(settings))
    except DashboardError as exc:
        raise _http(exc) from exc


@router.get("/api/analyses/active")
def active_analyses(request: Request):
    rows = request.app.state.store.list_analyses(limit=20, statuses=ACTIVE_STATUSES)
    return [_public(row) for row in rows]


@router.post("/api/analyses/{analysis_id}/cancel")
def cancel_analysis(analysis_id: str, request: Request):
    record = request.app.state.runner.cancel(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Analysis not found."})
    return _public(record)


@router.get("/api/analyses")
def list_analyses(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    return [_public(row) for row in request.app.state.store.list_analyses(limit=limit)]


@router.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str, request: Request):
    record = request.app.state.runner.get(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Analysis not found."})
    return _public(record)


@router.get("/api/analyses/{analysis_id}/events")
async def analysis_events(analysis_id: str, request: Request):
    try:
        mailbox = request.app.state.runner.subscribe(analysis_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Analysis not found."},
        ) from exc

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                event = await asyncio.to_thread(_next_event, mailbox)
                if event is None:
                    break
                if event.get("type") == "heartbeat":
                    yield ": heartbeat\n\n"
                    continue
                payload = json.dumps(event, default=str)
                yield f"event: {event['type']}\ndata: {payload}\n\n"
                if event.get("type") in TERMINAL:
                    break
        finally:
            request.app.state.runner.unsubscribe(analysis_id, mailbox)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/analyses/{analysis_id}/trade-plan")
def rebuild_trade_plan(analysis_id: str, body: TradePlanUpdate, request: Request):
    store = request.app.state.store
    runner = request.app.state.runner
    record = runner.get(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Analysis not found."})
    prices = {
        "scale_in_prices": list(body.scale_in_prices),
        "take_profit_prices": list(body.take_profit_prices),
    }
    snapshot = {
        "analysis_id": analysis_id,
        "ticker": record["ticker"],
        "capital": {
            "available_capital": body.available_capital,
            "available_cash": body.available_cash,
            "max_risk_amount": body.max_risk_amount,
            "max_risk_percent": body.max_risk_percent,
            "max_position_percent": body.max_position_percent,
            "cost_bps": body.cost_bps,
        },
        "scale_in_prices": prices["scale_in_prices"],
        "take_profit_prices": prices["take_profit_prices"],
        "save_as_default": body.save_as_default,
    }
    verified = frozen_research_market(record.get("data_sources") or {}, record.get("trade_plan"))
    calculation = _calculation_market(reference_quote(record["ticker"], record["analysis_date"]))
    plan = assemble_trade_plan(
        ticker=record["ticker"],
        analysis_date=record["analysis_date"],
        reports=record.get("reports") or {},
        reference=verified,
        preferences=snapshot["capital"],
        price_inputs=prices,
        input_snapshot=snapshot,
    )
    plan["verified_market"] = verified
    plan["calculation_market"] = calculation
    try:
        saved_version = store.commit_rebuilt_plan(
            analysis_id=analysis_id,
            ticker=record["ticker"],
            snapshot=snapshot,
            plan=plan,
            expected_plan_version=body.expected_plan_version,
            preferences=snapshot["capital"] if body.save_as_default else None,
        )
    except PlanConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "plan_conflict",
                "message": "This plan was saved again after you opened it. Reload the saved plan before saving.",
                "current_plan_version": exc.current,
            },
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Analysis not found."}) from exc
    runner.remember_trade_plan(analysis_id, saved_version["plan"])
    return saved_version["plan"]


@router.get("/api/analyses/{analysis_id}/plan-versions")
def list_plan_versions(analysis_id: str, request: Request):
    if request.app.state.runner.get(analysis_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Analysis not found."})
    return request.app.state.store.list_plan_versions(analysis_id)


@router.get("/api/analyses/{analysis_id}/plan-versions/{version}")
def get_plan_version(analysis_id: str, version: int, request: Request):
    row = request.app.state.store.get_plan_version(analysis_id, version)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Plan version not found."})
    return row


@router.get("/api/analyses/{analysis_id}/report")
def analysis_html(analysis_id: str, request: Request):
    record = request.app.state.runner.get(analysis_id)
    if record is None or not record.get("html_report_path"):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "HTML report not found."})
    try:
        path = resolve_html_report(record["html_report_path"])
    except DashboardError as exc:
        raise _http(exc) from exc
    return FileResponse(path, media_type="text/html")


@router.get("/api/history")
def history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    ticker: str | None = None,
    status: str | None = None,
    analysis_date: str | None = None,
    cursor: str | None = None,
):
    allowed = {
        "queued",
        "running",
        "cancel_requested",
        "cancelling",
        "completed",
        "failed",
        "timed_out",
        "stopped",
        "interrupted",
    }
    if status and status not in allowed:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid", "message": "Unknown analysis status."},
        )
    day = None
    if analysis_date:
        try:
            day = parse_calendar_date(analysis_date)
        except DashboardError as exc:
            raise _http(exc) from exc
    before = None
    if cursor:
        try:
            before = decode_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid", "message": "Unknown history cursor."}) from exc
    rows = request.app.state.store.list_analyses(
        limit=limit + 1,
        statuses=(status,) if status else None,
        ticker=ticker.strip() if ticker else None,
        analysis_date=day,
        before=before,
    )
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1]["created_at"], page[-1]["id"]) if len(rows) > limit and page else None
    return {"items": [_public(row) for row in page], "next_cursor": next_cursor}


@router.get("/api/history/{analysis_id}")
def history_detail(analysis_id: str, request: Request):
    return get_analysis(analysis_id, request)


@router.get("/api/reports/html")
def report_html(path: str):
    try:
        resolved = resolve_html_report(path)
    except DashboardError as exc:
        raise _http(exc) from exc
    return FileResponse(resolved, media_type="text/html")


def frozen_research_market(sources: dict, plan: dict | None) -> dict:
    """The market record stored with the research, not a quote fetched during recalculation."""
    research = sources.get("research_market") if isinstance(sources, dict) else None
    if isinstance(research, dict):
        market = dict(research)
        market["role"] = "research_snapshot"
        return market
    stored = sources.get("market") if isinstance(sources, dict) else None
    if isinstance(stored, dict):
        market = dict(stored)
        market["role"] = "stored_market_record"
        return market
    verified = plan.get("verified_market") if isinstance(plan, dict) else None
    if isinstance(verified, dict):
        market = dict(verified)
        market["role"] = "stored_market_record"
        return market
    return {
        "status": "unavailable",
        "source": None,
        "price": None,
        "bar_date": None,
        "fetched_at": None,
        "currency": None,
        "error": None,
        "role": "unknown",
    }


def _calculation_market(reference: dict) -> dict:
    return {
        "role": "calculation_snapshot",
        "status": reference.get("status"),
        "source": reference.get("source"),
        "price": reference.get("price"),
        "bar_date": reference.get("bar_date"),
        "fetched_at": reference.get("fetched_at"),
        "currency": reference.get("currency"),
        "error": reference.get("error"),
    }


def _next_event(mailbox: queue.Queue):
    try:
        return mailbox.get(timeout=15)
    except queue.Empty:
        return {"type": "heartbeat"}
