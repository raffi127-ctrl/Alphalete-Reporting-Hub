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
    # NON-INTERACTIVE — never fall into gspread.oauth's browser fallback in the
    # unattended batch (it pops a 'random Chrome' + hangs, 2026-07-04). Load +
    # refresh + authorize; raise on failure instead of opening a browser.
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if not _OAUTH_TOKEN_PATH.exists():
        raise RuntimeError(f"No Sheets OAuth token at {_OAUTH_TOKEN_PATH}.")
    creds = Credentials.from_authorized_user_file(str(_OAUTH_TOKEN_PATH), _SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _OAUTH_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("Sheets OAuth token invalid and can't refresh — "
                               "re-run the one-time authorization.")
    return gspread.authorize(creds)


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
