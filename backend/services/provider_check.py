"""Optional provider connectivity check.

A configured key is not treated as valid or funded. The network call runs only
after the caller confirms that it may incur charges. Response bodies are not stored.
"""

from __future__ import annotations

import os

import requests

from backend.errors import redact


def probe_openai(environ: dict[str, str] | None = None) -> dict:
    env = environ if environ is not None else os.environ
    if not env.get("OPENAI_API_KEY"):
        return {
            "ok": False,
            "code": "missing_key",
            "message": "OPENAI_API_KEY is not set. No request was sent. A configured key would still not prove the account has balance.",
        }
    try:
        response = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {env['OPENAI_API_KEY']}"},
            timeout=10,
        )
    except requests.Timeout:
        return {"ok": False, "code": "timeout", "message": "The provider did not respond in time."}
    except requests.RequestException:
        return {"ok": False, "code": "network", "message": "The provider could not be reached."}
    if response.status_code in {401, 403}:
        return {"ok": False, "code": "auth", "message": "The provider rejected the credentials."}
    if response.status_code == 429:
        return {"ok": False, "code": "rate_limit", "message": "The provider rate limit was reached."}
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
