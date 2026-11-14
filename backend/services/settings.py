"""Run settings assembled the same way as the CLI, without prompting."""

from __future__ import annotations

import os
from datetime import datetime

from backend.errors import DashboardError
from backend.schemas.models import AnalysisCreate
from backend.services.progress import ANALYST_ORDER
from cli.prompts import detect_asset_type, provider_default_url, resolve_backend_url
from tradingagents.dataflows.date_window import research_calendar_date
from tradingagents.dataflows.symbols import normalize_symbol, safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.chatgpt_auth import LOGIN_HINT, signed_in_as
from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS, check_endpoint

# Region endpoints the CLI asks for after the main provider menu.
EXTRA_PROVIDERS = {
    "qwen-cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm-cn": "https://open.bigmodel.cn/api/paas/v4/",
    "minimax-cn": "https://api.minimaxi.com/v1",
}

_KEY_OPTIONAL = {"ollama", "openai_compatible", "bedrock"}


def provider_catalog() -> list[tuple[str, str, str | None]]:
    """CLI providers plus the China-region endpoints that menu asks about later."""
    from cli.prompts import _llm_provider_table

    rows = list(_llm_provider_table())
    rows.extend(
        (
            ("Qwen (China)", "qwen-cn", EXTRA_PROVIDERS["qwen-cn"]),
            ("GLM (China)", "glm-cn", EXTRA_PROVIDERS["glm-cn"]),
            ("MiniMax (China)", "minimax-cn", EXTRA_PROVIDERS["minimax-cn"]),
        )
    )
    return rows


def canonical_ticker(value: str) -> str:
    """Yahoo symbol that is also safe to use in a path."""
    try:
        ticker = normalize_symbol(value)
        safe_ticker_component(ticker)
    except ValueError as exc:
        raise DashboardError(str(exc), status=422, code="invalid") from exc
    return ticker


def prepare_settings(body: AnalysisCreate) -> dict:
    """Validate a request into the settings stored with a run."""
    ticker = canonical_ticker(body.ticker)

    analysis_date = _analysis_date(body.analysis_date)
    asset_type = detect_asset_type(ticker).value
    analysts = [key for key in ANALYST_ORDER if key in body.analysts]
    if not analysts:
        raise DashboardError("Select at least one analyst.", status=422, code="invalid")
    if asset_type == "crypto" and "fundamentals" in analysts:
        raise DashboardError(
            "The fundamentals analyst is not available for crypto tickers.",
            status=422,
            code="invalid",
        )

    provider = body.llm_provider.lower()
    known = {key: url for _label, key, url in provider_catalog()}
    if provider not in known:
        raise DashboardError(f"Unknown model provider '{provider}'.", status=422, code="invalid")

    menu_url = known.get(provider)
    if menu_url is None and provider not in EXTRA_PROVIDERS:
        menu_url = provider_default_url(provider)
    backend_url = body.backend_url or resolve_backend_url(
        provider,
        menu_url,
        os.environ.get("TRADINGAGENTS_LLM_BACKEND_URL") or None,
    )
    if provider == "openai_compatible" and not backend_url:
        raise DashboardError(
            "An OpenAI-compatible endpoint needs a backend URL.",
            status=422,
            code="invalid",
        )
    try:
        check_endpoint(provider, backend_url)
    except ValueError as exc:
        raise DashboardError(str(exc), status=422, code="invalid") from exc

    auth_problem = auth_requirement(provider)
    if auth_problem:
        status = 401 if provider == "chatgpt" else 422
        code = "auth" if provider == "chatgpt" else "missing_key"
        raise DashboardError(auth_problem, status=status, code=code)

    debate_rounds, risk_rounds, notes = resolve_rounds(body.research_depth)
    return {
        "ticker": ticker,
        "analysis_date": analysis_date,
        "analysts": analysts,
        "research_depth": body.research_depth,
        "output_language": body.output_language,
        "llm_provider": provider,
        "quick_think_llm": body.quick_think_llm.strip(),
        "deep_think_llm": body.deep_think_llm.strip(),
        "backend_url": backend_url,
        "asset_type": asset_type,
        "max_debate_rounds": debate_rounds,
        "max_risk_discuss_rounds": risk_rounds,
        "round_notes": notes,
    }


def build_run_config(settings: dict) -> dict:
    """The graph config for one dashboard run."""
    config = DEFAULT_CONFIG.copy()
    config["quick_think_llm"] = settings["quick_think_llm"]
    config["deep_think_llm"] = settings["deep_think_llm"]
    config["llm_provider"] = settings["llm_provider"]
    config["backend_url"] = settings.get("backend_url")
    config["output_language"] = settings["output_language"]
    config["max_debate_rounds"] = settings["max_debate_rounds"]
    config["max_risk_discuss_rounds"] = settings["max_risk_discuss_rounds"]
    return config


def resolve_rounds(requested: int) -> tuple[int, int, list[str]]:
    """Match the CLI: an explicit env override wins over the depth control."""
    debate = requested
    risk = requested
    notes: list[str] = []
    if os.environ.get("TRADINGAGENTS_MAX_DEBATE_ROUNDS"):
        debate = int(DEFAULT_CONFIG["max_debate_rounds"])
        notes.append(
            "max_debate_rounds comes from TRADINGAGENTS_MAX_DEBATE_ROUNDS, "
            "so the selected research depth does not apply to the research debate."
        )
    if os.environ.get("TRADINGAGENTS_MAX_RISK_ROUNDS"):
        risk = int(DEFAULT_CONFIG["max_risk_discuss_rounds"])
        notes.append(
            "max_risk_discuss_rounds comes from TRADINGAGENTS_MAX_RISK_ROUNDS, "
            "so the selected research depth does not apply to the risk debate."
        )
    return debate, risk, notes


def auth_requirement(provider: str) -> str | None:
    """A message when this provider cannot start, or None when it can."""
    if provider == "chatgpt":
        if signed_in_as():
            return None
        return LOGIN_HINT
    if provider in _KEY_OPTIONAL:
        return None
    spec = OPENAI_COMPATIBLE_PROVIDERS.get(provider)
    if spec is not None and spec.key_optional:
        return None
    env_name = get_api_key_env(provider)
    if env_name and not os.environ.get(env_name):
        return (
            f"{provider} requires {env_name} in the environment. "
            "The dashboard does not collect or store API keys."
        )
    return None


def parse_calendar_date(value: str) -> str:
    return _analysis_date(value)


def _analysis_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise DashboardError(
            "analysis_date must be YYYY-MM-DD.",
            status=422,
            code="invalid",
        ) from exc
    canonical = parsed.strftime("%Y-%m-%d")
    if canonical != value:
        raise DashboardError("analysis_date must be YYYY-MM-DD.", status=422, code="invalid")
    if canonical > research_calendar_date():
        raise DashboardError("analysis_date cannot be in the future.", status=422, code="invalid")
    return canonical
