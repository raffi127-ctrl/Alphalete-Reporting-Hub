"""What the sales board site needs to run as a hosted link instead of locally.

Two things change the moment this stops being localhost.

CREDENTIALS. `recruiting_report.fill` authorises Google Sheets from a token file
in the runner's home directory. A hosted app has no such file, so the token has
to come from `st.secrets` and be materialised on disk before anything opens a
sheet. That is all `ensure_sheets_credentials()` does — and only when the file
is genuinely missing, so running locally is completely unchanged.

ACCESS. The board carries every rep's name and their daily production. A public
URL with no gate publishes that to anyone who guesses it, so each office gets a
code, and the code decides WHICH office you see. That is also what makes the
per-owner links Megan described work: one app, one link per owner, each landing
on their own board and nobody else's.

Secrets expected when hosted (Streamlit → App settings → Secrets):

    sheets_oauth_token = '''{ ...the contents of oauth-token.json... }'''

    [office_codes]
    "rafael-2026"  = "Rafael Hidalgo"
    "megan-admin"  = "__ALL__"        # sees every office

Nothing here is required locally: with no secrets set the app runs exactly as
it does today.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ADMIN = "__ALL__"
_SECRET_TOKEN = "sheets_oauth_token"
_SECRET_CODES = "office_codes"


def _secret(name: str, default=None):
    """Read a secret without exploding when there is no secrets file."""
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default


def ensure_sheets_credentials() -> bool:
    """Write the OAuth token from secrets to where fill.py looks for it.

    Returns True when a token is in place (already there, or just written).
    Never overwrites an existing token — a developer's own credentials on their
    own machine win over anything in secrets."""
    from automations.recruiting_report.fill import OAUTH_TOKEN_PATH

    if OAUTH_TOKEN_PATH.exists():
        return True

    raw = _secret(_SECRET_TOKEN) or os.environ.get("SHEETS_OAUTH_TOKEN")
    if not raw:
        return False
    try:
        # accept either a JSON string or an already-parsed mapping
        data = raw if isinstance(raw, str) else json.dumps(dict(raw))
        json.loads(data)                      # fail early on malformed JSON
    except (TypeError, ValueError):
        return False

    OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    OAUTH_TOKEN_PATH.write_text(data, encoding="utf-8")
    return True


def office_for_code(code: str):
    """Which office a link's code may see.

    Returns the ICD name, ADMIN for the org-wide link, or None when the code is
    unknown. An unknown code shows nothing at all — no hint about which offices
    exist."""
    codes = _secret(_SECRET_CODES) or {}
    try:
        codes = dict(codes)
    except (TypeError, ValueError):
        return None
    return codes.get((code or "").strip()) or None


def gate_enabled() -> bool:
    """True when office codes are configured — i.e. this is the hosted app.

    Locally there are no codes and the gate stays out of the way."""
    return bool(_secret(_SECRET_CODES))


def code_from_url() -> str:
    """The code from ?code=… so an owner's link opens straight onto their
    board, with no password to remember."""
    try:
        import streamlit as st
        return str(st.query_params.get("code", "") or "").strip()
    except Exception:
        return ""
