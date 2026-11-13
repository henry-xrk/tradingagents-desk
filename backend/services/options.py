"""Provider, model, and analyst choices for the research form."""

from __future__ import annotations

import os
import time

from backend.services.progress import ANALYST_NAMES, ANALYST_ORDER
from backend.services.settings import auth_requirement, provider_catalog, resolve_rounds
from tradingagents.dataflows.date_window import get_current_date
from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.chatgpt_auth import LOGIN_HINT, signed_in_as
from tradingagents.llm_clients.model_catalog import get_model_options

_MODEL_CACHE: dict = {"at": 0.0, "models": None, "error": None}
_CACHE_SECONDS = 60


def clear_model_cache() -> None:
    _MODEL_CACHE["at"] = 0.0
    _MODEL_CACHE["models"] = None
    _MODEL_CACHE["error"] = None


def config_options() -> dict:
    email = None
    _debate, _risk, round_notes = resolve_rounds(1)
    providers = []
    for label, key, url in provider_catalog():
        if key == "chatgpt":
            continue
        models = _models_for(key)
        providers.append(
            {
                "id": key,
                "label": label,
                "default_url": url,
                "requires_url": key in {"openai_compatible", "azure"} or url is None,
                "api_key_env": get_api_key_env(key),
                "auth_message": auth_requirement(key),
                "models": models["models"],
                "models_note": models["note"],
            }
        )
    return {
        "today": get_current_date(),
        "default_provider": "chatgpt" if email else "openai",
        "signed_in_email": email,
        "analysts": [{"id": key, "label": ANALYST_NAMES[key]} for key in ANALYST_ORDER],
        "languages": ["English", "Chinese"],
        "depths": [
            {"id": 1, "label": "Shallow"},
            {"id": 3, "label": "Medium"},
            {"id": 5, "label": "Deep"},
        ],
        "environment_notes": round_notes,
        "environment": {
            "TRADINGAGENTS_MAX_DEBATE_ROUNDS": os.environ.get("TRADINGAGENTS_MAX_DEBATE_ROUNDS") or None,
            "TRADINGAGENTS_MAX_RISK_ROUNDS": os.environ.get("TRADINGAGENTS_MAX_RISK_ROUNDS") or None,
        },
        "providers": providers,
        "orders_sent": False,
    }


def _models_for(provider: str) -> dict:
    if provider == "chatgpt":
        if not signed_in_as():
            return {"models": {"quick": [], "deep": []}, "note": LOGIN_HINT}
        models, error = chatgpt_models()
        rows = [{"id": model_id, "label": name} for name, model_id in models]
        return {"models": {"quick": rows, "deep": rows}, "note": error}
    try:
        quick = get_model_options(provider, "quick")
        deep = get_model_options(provider, "deep")
    except KeyError:
        note = "Enter a model ID. This provider has no built-in list."
        if provider == "openrouter":
            note = "Enter an OpenRouter model ID. The dashboard does not download that catalog."
        return {"models": {"quick": [], "deep": []}, "note": note}
    return {
        "models": {"quick": _clean(quick), "deep": _clean(deep)},
        "note": None,
    }


def _clean(options: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"id": model_id, "label": label} for label, model_id in options if model_id != "custom"]


def chatgpt_models() -> tuple[list[tuple[str, str]], str | None]:
    """Live plan models. Failures stay empty rather than falling back to another provider."""
    now = time.time()
    if _MODEL_CACHE["models"] is not None and now - _MODEL_CACHE["at"] < _CACHE_SECONDS:
        return _MODEL_CACHE["models"], _MODEL_CACHE["error"]
    from tradingagents.llm_clients.chatgpt_auth import list_models

    try:
        models = list_models()
        error = None
    except Exception as exc:
        models = []
        error = f"Could not list ChatGPT plan models ({type(exc).__name__}). Enter a model ID instead."
    _MODEL_CACHE["at"] = now
    _MODEL_CACHE["models"] = models
    _MODEL_CACHE["error"] = error
    return models, error
