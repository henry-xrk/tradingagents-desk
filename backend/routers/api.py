"""Dashboard HTTP API."""

from __future__ import annotations

import asyncio
import json
import os
import queue

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
from backend.services.provider_check import probe_openai
from backend.services.reports import resolve_html_report
from backend.services.runner import TERMINAL
from backend.services.settings import canonical_ticker, parse_calendar_date, prepare_settings
from backend.services.trade_plan import (
    DISCLAIMER,
    LIMITATIONS,
    PositionInputs,
    assemble_trade_plan,
    calculate_position,
)
from backend.storage.db import ACTIVE_STATUSES, utcnow
from tradingagents.dataflows.date_window import get_current_date
from tradingagents.llm_clients.chatgpt_auth import LOGIN_HINT, signed_in_as

router = APIRouter()

_HIDDEN = {"fingerprint"}
_SIZING_WRAP = {"entry_zone", "limit_entries", "exits", "invalidation", "assumptions", "inputs"}


def _public(record: dict) -> dict:
    return {key: value for key, value in record.items() if key not in _HIDDEN}


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


@router.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "tradingagents-dashboard",
        "version": tradingagents.__version__,
        "commit": os.environ.get("TRADINGAGENTS_BUILD_COMMIT") or "unknown",
        "today": get_current_date(),
    }


@router.get("/api/system")
def system_status(request: Request):
    check = request.app.state.store.latest_provider_check()
    return {
        "service": "tradingagents-dashboard",
        "version": tradingagents.__version__,
        "commit": os.environ.get("TRADINGAGENTS_BUILD_COMMIT") or "unknown",
        "openai_api_key_configured": bool(os.environ.get("OPENAI_API_KEY")),
        "configured_means": "A configured key is not proof that it is valid or that the account has balance.",
        "validation": check
        or {
            "checked_at": None,
            "ok": None,
            "code": "not_checked",
            "message": "No connection test has been run.",
        },
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
    result = probe_openai()
    return request.app.state.store.save_provider_check(result)


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
    day = as_of or get_current_date()
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
        day = parse_calendar_date(as_of) if as_of else get_current_date()
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
    preferences = store.save_preferences(body.model_dump())
    prices = {
        "scale_in_prices": list(body.scale_in_prices),
        "take_profit_prices": list(body.take_profit_prices),
    }
    version = int((record.get("trade_plan") or {}).get("plan_version") or 0) + 1
    snapshot = {
        "analysis_id": analysis_id,
        "ticker": record["ticker"],
        "plan_version": version,
        "capital": preferences,
        "scale_in_prices": prices["scale_in_prices"],
        "take_profit_prices": prices["take_profit_prices"],
    }
    store.save_plan_draft(analysis_id, record["ticker"], version, snapshot)
    reference = reference_quote(record["ticker"], record["analysis_date"])
    plan = assemble_trade_plan(
        ticker=record["ticker"],
        analysis_date=record["analysis_date"],
        reports=record.get("reports") or {},
        reference=reference,
        preferences=preferences,
        price_inputs=prices,
        plan_version=version,
        input_snapshot=snapshot,
    )
    market = {
        "source": reference.get("source"),
        "status": reference.get("status"),
        "bar_date": reference.get("bar_date"),
        "fetched_at": reference.get("fetched_at"),
        "error": reference.get("error"),
    }
    saved = runner.set_trade_plan(analysis_id, plan, market)
    return saved


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
    rows = request.app.state.store.list_analyses(
        limit=limit,
        statuses=(status,) if status else None,
        ticker=ticker.strip() if ticker else None,
        analysis_date=day,
    )
    return [_public(row) for row in rows]


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


def _next_event(mailbox: queue.Queue):
    try:
        return mailbox.get(timeout=15)
    except queue.Empty:
        return {"type": "heartbeat"}
