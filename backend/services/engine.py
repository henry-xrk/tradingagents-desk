"""Run one TradingAgents graph and translate its stream into dashboard status."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import tradingagents
from backend.errors import DashboardError, public_exception
from backend.services.market_data import reference_quote
from backend.services.progress import ProgressState, extract_reports
from backend.services.reports import relativize_report_path
from backend.services.settings import build_run_config
from backend.services.trade_plan import assemble_trade_plan
from tradingagents.agents.rating import run_rating
from tradingagents.graph.trading_graph import TradingAgentsGraph

logger = logging.getLogger(__name__)

# One graph at a time. The engine keeps process-wide config and a shared memory log.
_ENGINE_LOCK = threading.Lock()


def execute_analysis(job, handle) -> None:
    """Run the real graph. ``job`` and ``handle`` come from the dashboard runner."""
    handle.update(message="Waiting for the analysis engine")
    with _ENGINE_LOCK:
        if handle.should_stop():
            return
        handle.update(status="running", phase="analysts", message="Starting analysis")
        _run_graph(job, handle)


def _run_graph(job, handle) -> None:
    settings = job.settings
    config = build_run_config(settings)
    selected = list(settings["analysts"])
    asset_type = settings["asset_type"]
    graph = TradingAgentsGraph(selected, config=config, debug=False)
    init_state = graph.create_run_state(job.ticker, job.analysis_date, asset_type)
    args = graph.propagator.get_graph_args()
    checkpoint_id = graph.begin_checkpoint(job.ticker, job.analysis_date, asset_type)
    if checkpoint_id is not None:
        configurable = args.setdefault("config", {}).setdefault("configurable", {})
        configurable["thread_id"] = checkpoint_id

    progress = ProgressState(selected)
    progress.begin_analysts()
    handle.update(
        phase=progress.phase,
        agent_status=dict(progress.agent_status),
        message="Analysts are running",
    )
    trace: list[dict] = []
    usage = {"input_tokens": 0, "output_tokens": 0, "calls_with_usage": 0}
    steps = 0
    budget = _call_budget()
    try:
        stream = graph.stream_run(graph.checkpoint_input(init_state), **args)
        for messages, chunk in stream:
            if handle.should_stop():
                return
            steps += 1
            _collect_usage(messages, usage)
            notes = progress.apply_chunk(chunk if isinstance(chunk, dict) else None)
            message = notes[-1] if notes else activity_from_messages(messages)
            handle.update(
                phase=progress.phase,
                agent_status=dict(progress.agent_status),
                reports=dict(progress.reports),
                message=message,
            )
            if isinstance(chunk, dict):
                trace.append(chunk)
            if steps >= budget:
                raise DashboardError(
                    f"Stopped after {budget} model or tool steps. "
                    "This is a call-count guard, not a verified dollar cap.",
                    status=429,
                    code="call_budget",
                )
        if handle.should_stop():
            return
        final_state: dict = {}
        for chunk in trace:
            final_state.update(chunk)
        _finish(graph, job, handle, final_state, config, usage)
    finally:
        graph.end_checkpoint()


def _finish(graph, job, handle, final_state: dict, config: dict, usage: dict | None = None) -> None:
    if handle.should_stop():
        return
    if not final_state:
        raise DashboardError(
            "The analysis ended without any state.",
            status=500,
            code="empty",
        )
    _fill_state(final_state, job.ticker, job.analysis_date)
    handle.update(phase="saving_report", message="Saving the research report")

    memory_error = None
    try:
        graph.record_decision(job.ticker, job.analysis_date, final_state)
    except Exception as exc:
        logger.warning("Memory log write failed for %s", job.id)
        memory_error = public_exception(exc)

    markdown_path = None
    html_path = None
    report_error = None
    try:
        saved = graph.save_reports(final_state, job.ticker)
        markdown_path = relativize_report_path(str(saved))
        html_candidate = Path(saved).parent / "complete_report.html"
        if html_candidate.is_file():
            html_path = relativize_report_path(str(html_candidate))
    except Exception as exc:
        logger.warning("Report writer failed for %s", job.id)
        report_error = public_exception(exc)

    try:
        graph.clear_checkpoint_on_success(
            job.ticker, job.analysis_date, job.settings.get("asset_type", "stock")
        )
    except Exception:
        logger.warning("Checkpoint cleanup failed for %s", job.id, exc_info=True)

    if handle.should_stop():
        return

    reports = extract_reports(final_state)
    reference = reference_quote(job.ticker, job.analysis_date)
    plan = assemble_trade_plan(
        ticker=job.ticker,
        analysis_date=job.analysis_date,
        reports=reports,
        reference=reference,
        preferences=handle.preferences(),
    )
    handle.update(
        status="completed",
        phase="completed",
        reports=reports,
        rating=run_rating(final_state),
        trade_plan=plan,
        data_sources={
            "version": tradingagents.__version__,
            "llm_provider": config.get("llm_provider"),
            "quick_think_llm": config.get("quick_think_llm"),
            "deep_think_llm": config.get("deep_think_llm"),
            "data_vendors": dict(config.get("data_vendors") or {}),
            "output_language": config.get("output_language"),
            "market": _market_record(reference),
            "research_market": {**_market_record(reference), "role": "research_snapshot"},
            "memory_error": memory_error,
            "report_error": report_error,
            "tools": {
                "memory": "failed" if memory_error else "ok",
                "report": "failed" if report_error else "ok",
            },
            "usage": usage if usage and usage.get("calls_with_usage") else {"status": "unknown"},
            "estimated_cost": {
                "status": "unknown",
                "reason": "No verified model price is configured, so cost is not calculated.",
            },
            "call_budget": _call_budget(),
            "call_budget_note": "The call budget counts steps. It is not a dollar cap.",
            "round_notes": list(job.settings.get("round_notes") or []),
        },
        html_report_path=html_path,
        markdown_report_path=markdown_path,
        message="Analysis completed",
    )


def _fill_state(state: dict, ticker: str, analysis_date: str) -> None:
    """Give the report writer the keys it indexes, using blanks when a section never arrived."""
    state.setdefault("company_of_interest", ticker)
    state.setdefault("trade_date", analysis_date)
    for key in (
        "market_report",
        "sentiment_report",
        "news_report",
        "fundamentals_report",
        "investment_plan",
        "trader_investment_plan",
        "final_trade_decision",
    ):
        state.setdefault(key, "")
    debate = state.get("investment_debate_state")
    if not isinstance(debate, dict):
        debate = {}
        state["investment_debate_state"] = debate
    for key in ("bull_history", "bear_history", "history", "current_response"):
        debate.setdefault(key, "")
    risk = state.get("risk_debate_state")
    if not isinstance(risk, dict):
        risk = {}
        state["risk_debate_state"] = risk
    for key in ("aggressive_history", "conservative_history", "neutral_history", "history"):
        risk.setdefault(key, "")


def _call_budget() -> int:
    raw = os.environ.get("TRADINGAGENTS_MAX_MODEL_CALLS", "80")
    try:
        value = int(raw)
    except ValueError:
        return 80
    return max(1, value)


def _collect_usage(messages, usage: dict) -> None:
    if not messages:
        return
    for message in list(messages):
        meta = getattr(message, "usage_metadata", None)
        if not isinstance(meta, dict):
            continue
        input_tokens = meta.get("input_tokens")
        output_tokens = meta.get("output_tokens")
        if input_tokens is None and output_tokens is None:
            continue
        usage["input_tokens"] += int(input_tokens or 0)
        usage["output_tokens"] += int(output_tokens or 0)
        usage["calls_with_usage"] += 1


def _market_record(reference: dict) -> dict:
    return {
        "source": reference.get("source"),
        "status": reference.get("status"),
        "bar_date": reference.get("bar_date"),
        "fetched_at": reference.get("fetched_at"),
        "currency": reference.get("currency"),
        "error": reference.get("error"),
    }


def activity_from_messages(messages) -> str | None:
    """Name the latest tool. Arguments and tool output stay out of the activity line."""
    if not messages:
        return None
    for message in reversed(list(messages)):
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            call = tool_calls[-1]
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                return f"Tool call: {name}"
        if type(message).__name__ == "ToolMessage":
            name = getattr(message, "name", None)
            if name:
                return f"Tool result: {name}"
    return None
