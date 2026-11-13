"""Errors the dashboard can show without leaking credentials."""

from __future__ import annotations

import re

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|bearer)\b(\s*[:=]\s*|\s+)([^\s,;]+)"
)
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|key|token|secret|password)=)[^&\s]+"
)
_USERINFO = re.compile(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@")
_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+=*")


class DashboardError(Exception):
    """A request or run failure with a status code and a public message."""

    def __init__(self, message: str, *, status: int = 400, code: str = "error", ref: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.ref = ref


def redact(text: str) -> str:
    """Remove credentials before text is stored or returned."""
    cleaned = _USERINFO.sub(r"\1***@", text)
    cleaned = _QUERY_SECRET.sub(r"\1redacted", cleaned)
    cleaned = _BEARER.sub("Bearer redacted", cleaned)
    cleaned = _SECRET_ASSIGNMENT.sub(r"\1\2redacted", cleaned)
    cleaned = _SK_TOKEN.sub("sk-redacted", cleaned)
    return cleaned


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
        code, message = _classify_text(public_exception(exc))
    if ref:
        message = f"{message} (ref {ref})"
    return code, message


def _classify_text(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if any(marker in lowered for marker in ("invalid api key", "incorrect api key", "authentication", "unauthorized", "permission denied")):
        return "auth", "The model provider rejected the credentials."
    if any(marker in lowered for marker in ("rate limit", "too many requests", "429")):
        return "rate_limit", "The model provider rate limit was reached."
    if any(marker in lowered for marker in ("insufficient_quota", "quota", "billing", "usage limit", "exceeded your current quota")):
        return "quota", "The model provider reported a quota or billing limit."
    if any(marker in lowered for marker in ("timed out", "timeout", "read timed out")):
        return "timeout", "The operation timed out."
    if any(marker in lowered for marker in ("connection", "name resolution", "unreachable", "network", "dns")):
        return "network", "The network request failed."
    if "no market data" in lowered or "yfinance" in lowered:
        return "market_data", text
    if "valueerror" in lowered:
        return "invalid", text
    return "error", text
