"""Errors the dashboard can show without leaking credentials."""

from __future__ import annotations

import ast
import json
import re

_SECRET_KEY = re.compile(
    r"(?i)^(authorization|api[-_]?key|access[-_]?token|refresh[-_]?token|id[-_]?token|client[-_]?secret|secret|password|bearer)$"
)
_QUOTED_SECRET = re.compile(
    r"""(?ix)(["'])?(api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|secret|password|authorization)\1\s*[:=]\s*(["'])[^"']+\3"""
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|bearer)\b(\s*[:=]\s*|\s+)([^\s,;]+)"
)
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|key|token|secret|password)=)[^&\s]+"
)
_USERINFO = re.compile(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@")
_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+=*")
_QUOTA_CODES = {"insufficient_quota", "billing_hard_limit_reached", "credit_balance_exhausted", "insufficient_funds"}
_RATE_CODES = {"rate_limit_exceeded", "rate_limit", "too_many_requests"}
_AUTH_CODES = {"invalid_api_key", "incorrect_api_key", "incorrect_hostname"}


class DashboardError(Exception):
    """A request or run failure with a status code and a public message."""

    def __init__(self, message: str, *, status: int = 400, code: str = "error", ref: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.ref = ref


def redact(value):
    """Remove credentials from text or nested data before it is stored or returned."""
    if isinstance(value, dict):
        return {
            key: ("redacted" if _SECRET_KEY.match(str(key)) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    parsed = _parse_structured(value)
    if parsed is not None:
        return json.dumps(redact(parsed), ensure_ascii=False)
    return _redact_text(value)


def _parse_structured(text: str):
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    try:
        parsed = ast.literal_eval(stripped)
    except (ValueError, SyntaxError, MemoryError):
        return None
    if isinstance(parsed, (dict, list, tuple)):
        return parsed
    return None


def _redact_text(text: str) -> str:
    cleaned = _QUOTED_SECRET.sub(
        lambda match: match.group(0).split(match.group(3), 1)[0] + match.group(3) + "redacted" + match.group(3),
        text,
    )
    cleaned = _USERINFO.sub(r"\1***@", cleaned)
    cleaned = _QUERY_SECRET.sub(r"\1redacted", cleaned)
    cleaned = _BEARER.sub("Bearer redacted", cleaned)
    cleaned = _SECRET_ASSIGNMENT.sub(r"\1\2redacted", cleaned)
    return _SK_TOKEN.sub("sk-redacted", cleaned)


def public_exception(exc: BaseException, limit: int = 500) -> str:
    """A short redacted error string. Truncation happens after redaction."""
    text = redact(" ".join(str(exc).split()))
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def classify_exception(exc: BaseException, *, ref: str | None = None) -> tuple[str, str]:
    """Map an engine exception to a stable code and a public message."""
    from tradingagents.dataflows.errors import (
        NoMarketDataError,
        VendorNotConfiguredError,
        VendorUnavailableError,
    )
    from tradingagents.llm_clients.chatgpt_auth import ChatGPTAuthError, ChatGPTUnreachable

    if isinstance(exc, ChatGPTUnreachable):
        code, message = "network", "The model service could not be reached."
    elif isinstance(exc, ChatGPTAuthError):
        code, message = "auth", "The model provider rejected the credentials."
    elif isinstance(exc, NoMarketDataError):
        code, message = "market_data", public_exception(exc)
    elif isinstance(exc, VendorNotConfiguredError):
        code, message = "vendor_config", public_exception(exc)
    elif isinstance(exc, VendorUnavailableError):
        code, message = "vendor", public_exception(exc)
    elif isinstance(exc, DashboardError):
        code, message = exc.code, exc.message
    elif isinstance(exc, TimeoutError):
        code, message = "timeout", "The operation timed out."
    else:
        code, message = _classify_provider(exc) or _classify_text(public_exception(exc))
    if ref:
        message = f"{message} (ref {ref})"
    return code, message


def _classify_provider(exc: BaseException) -> tuple[str, str] | None:
    code = _provider_code(exc)
    if code in _QUOTA_CODES:
        return "quota", "The model provider reported a quota or billing limit. The request was not retried."
    if code in _RATE_CODES:
        return "rate_limit", _rate_message(exc)
    if code == "incorrect_hostname":
        return "auth", "The API key is for a different regional OpenAI host."
    if code in _AUTH_CODES:
        return "auth", "The model provider rejected the credentials."
    return None


def _provider_code(exc: BaseException) -> str | None:
    for attr in ("code", "error_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value:
            return value
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        code = payload["error"].get("code")
        if isinstance(code, str):
            return code
    return None


def _rate_message(exc: BaseException) -> str:
    message = "The model provider rate limit was reached."
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or getattr(exc, "headers", {}) or {}
    try:
        retry = headers.get("Retry-After")
    except Exception:
        retry = None
    if retry is not None and str(retry).isdigit():
        message += f" Retry after {retry} seconds."
    return message


def _classify_text(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if any(marker in lowered for marker in ("invalid api key", "incorrect api key", "authentication", "unauthorized", "permission denied")):
        return "auth", "The model provider rejected the credentials."
    if any(marker in lowered for marker in ("insufficient_quota", "quota", "billing", "usage limit", "exceeded your current quota")):
        return "quota", "The model provider reported a quota or billing limit. The request was not retried."
    if any(marker in lowered for marker in ("rate limit", "too many requests", "429")):
        return "rate_limit", "The model provider rate limit was reached."
    if any(marker in lowered for marker in ("timed out", "timeout", "read timed out")):
        return "timeout", "The operation timed out."
    if any(marker in lowered for marker in ("connection", "name resolution", "unreachable", "network", "dns")):
        return "network", "The network request failed."
    if "no market data" in lowered or "yfinance" in lowered:
        return "market_data", text
    if "valueerror" in lowered:
        return "invalid", text
    return "error", text
