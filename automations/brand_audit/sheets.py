"""Thin gspread wrapper for the Brand Health audit.

Reuses the same authorized-user OAuth token the recruiting report already uses
(~/.config/recruiting-report/), so there's nothing new to authorize. Includes
the same 429/5xx retry behavior the other reports rely on.
"""
from __future__ import annotations

import time
from pathlib import Path

import gspread

# Reuse the existing, already-authorized token (spreadsheets scope).
_OAUTH_DIR = Path.home() / ".config" / "recruiting-report"
_OAUTH_CLIENT_PATH = _OAUTH_DIR / "oauth-client.json"
_OAUTH_TOKEN_PATH = _OAUTH_DIR / "oauth-token.json"

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def client() -> gspread.Client:
    return gspread.oauth(
        scopes=_SCOPES,
        credentials_filename=str(_OAUTH_CLIENT_PATH),
        authorized_user_filename=str(_OAUTH_TOKEN_PATH),
    )


def _retry(fn, *args, _tries: int = 4, **kwargs):
    """Retry on transient 429 (quota) / 5xx with exponential backoff."""
    delay = 30
    last = None
    for attempt in range(_tries):
        try:
            return fn(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            last = e
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (429, 500, 502, 503) and attempt < _tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise last  # pragma: no cover


def open_by_key(key: str, gc: gspread.Client | None = None):
    return _retry((gc or client()).open_by_key, key)
