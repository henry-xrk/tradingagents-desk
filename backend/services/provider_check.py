"""Optional provider connectivity check.

A configured key is not treated as valid or funded. The network call runs only
after the caller confirms that it may incur charges. Response bodies are not stored.
"""

from __future__ import annotations

import hashlib
import os
from urllib.parse import urlsplit

import requests

from backend.errors import classify_exception, redact

_DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"


class _ProviderStatus(Exception):
    def __init__(self, status: int, code: str | None, retry_after: str | None):
        super().__init__(f"HTTP {status}")
        self.status_code = status
        self.code = code
        self.headers = {"Retry-After": retry_after} if retry_after else {}


def _error_code(response) -> str | None:
    try:
        payload = response.json()
    except Exception:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"]
    return None


def credential_fingerprint(environ: dict[str, str] | None = None) -> tuple[str, str]:
    """Host plus a short digest. The digest is not reversible to the API key."""
    env = environ if environ is not None else os.environ
    raw = (env.get("TRADINGAGENTS_LLM_BACKEND_URL") or _DEFAULT_OPENAI_BASE).strip()
    host = urlsplit(raw).hostname or ""
    digest = hashlib.sha256(f"{host}\n{env.get('OPENAI_API_KEY') or ''}".encode()).hexdigest()[:16]
    return host, digest


def _models_url(env: dict[str, str]) -> str | None:
    raw = (env.get("TRADINGAGENTS_LLM_BACKEND_URL") or _DEFAULT_OPENAI_BASE).strip()
    if not raw.startswith(("http://", "https://")) or not urlsplit(raw).hostname:
        return None
    return raw.rstrip("/") + "/models"


def probe_openai(environ: dict[str, str] | None = None) -> dict:
    env = environ if environ is not None else os.environ
    if not env.get("OPENAI_API_KEY"):
        return {
            "ok": False,
            "code": "missing_key",
            "message": "OPENAI_API_KEY is not set. No request was sent. A configured key would still not prove the account has balance.",
        }
    url = _models_url(env)
    if url is None:
        return {
            "ok": False,
            "code": "error",
            "message": "TRADINGAGENTS_LLM_BACKEND_URL must be an http or https address. No request was sent.",
        }
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {env['OPENAI_API_KEY']}"},
            timeout=10,
        )
    except requests.Timeout:
        return {"ok": False, "code": "timeout", "message": "The provider did not respond in time."}
    except requests.RequestException:
        return {"ok": False, "code": "network", "message": "The provider could not be reached."}
    provider_code = _error_code(response)
    if provider_code == "incorrect_hostname":
        host = urlsplit(url).hostname or "the configured host"
        return {
            "ok": False,
            "code": "auth",
            "message": f"The API key is for a different regional OpenAI host. The credentials were not accepted at {host}.",
        }
    if response.status_code in {401, 403} or response.status_code == 429 or provider_code:
        code, message = classify_exception(
            _ProviderStatus(response.status_code, provider_code, response.headers.get("Retry-After"))
        )
        if response.status_code in {401, 403, 429} or code in {"auth", "quota", "rate_limit"}:
            return {"ok": False, "code": code, "message": message}
    if response.status_code >= 500:
        return {"ok": False, "code": "network", "message": "The provider returned a server error."}
    if response.status_code >= 400:
        return {
            "ok": False,
            "code": "error",
            "message": redact(f"The provider returned status {response.status_code}."),
        }
    return {
        "ok": True,
        "code": "ok",
        "message": "The provider accepted the key. This check does not show remaining balance or credit.",
    }
