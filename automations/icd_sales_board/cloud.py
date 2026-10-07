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
# fill._client() CHECKS FOR THE CLIENT JSON BEFORE IT EVER READS THE TOKEN
# and raises if it is missing, so materialising the token alone still left a
# hosted app unable to open a single sheet.
_SECRET_CLIENT = "sheets_oauth_client"
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


_SECRET_TABLE = "gcp_oauth"
# Exactly what google.oauth2.credentials.Credentials.from_authorized_user_file
# reads. token_uri and scopes have sane defaults; the rest must be present.
_AU_REQUIRED = ("refresh_token", "client_id", "client_secret")
_AU_OPTIONAL = ("token", "token_uri", "scopes", "expiry", "universe_domain")


def _authorized_user_from_table():
    """The [gcp_oauth] secrets table as an authorized-user JSON string.

    Returns None when the table is absent or missing a field that would
    make the file unusable -- writing a half file would turn a clear
    "no credentials" into a confusing auth error on the first sheet read.
    """
    tbl = _secret(_SECRET_TABLE)
    if not tbl:
        return None
    try:
        tbl = dict(tbl)
    except (TypeError, ValueError):
        return None
    if any(not tbl.get(k) for k in _AU_REQUIRED):
        return None
    out = {k: tbl[k] for k in _AU_REQUIRED}
    for k in _AU_OPTIONAL:
        if tbl.get(k):
            out[k] = list(tbl[k]) if k == "scopes" else tbl[k]
    out.setdefault("token_uri", "https://oauth2.googleapis.com/token")
    try:
        return json.dumps(out)
    except (TypeError, ValueError):
        return None


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
        # THE SECRETS THAT ARE ALREADY THERE. This app's secrets carry the
        # OAuth credentials as a [gcp_oauth] table, whose keys are exactly
        # Google's authorized-user format -- asking for a second copy under
        # a different name would be two things to rotate instead of one.
        raw = _authorized_user_from_table()
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
    _ensure_client_json()
    return True


def _ensure_client_json() -> bool:
    """The other half: fill._client() raises on a missing client JSON before
    it looks at the token at all."""
    from automations.recruiting_report.fill import OAUTH_CLIENT_PATH

    if OAUTH_CLIENT_PATH.exists():
        return True
    raw = _secret(_SECRET_CLIENT) or os.environ.get("SHEETS_OAUTH_CLIENT")
    if not raw:
        # _client() only checks that this file EXISTS -- the credentials it
        # actually uses come from the token. Built from the same table so
        # there is one place to rotate.
        tbl = _secret(_SECRET_TABLE)
        try:
            tbl = dict(tbl or {})
        except (TypeError, ValueError):
            tbl = {}
        if tbl.get("client_id") and tbl.get("client_secret"):
            raw = json.dumps({"installed": {
                "client_id": tbl["client_id"],
                "client_secret": tbl["client_secret"],
                "token_uri": tbl.get("token_uri",
                                     "https://oauth2.googleapis.com/token"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth"}})
    if not raw:
        return False
    try:
        data = raw if isinstance(raw, str) else json.dumps(dict(raw))
        json.loads(data)
    except (TypeError, ValueError):
        return False
    OAUTH_CLIENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OAUTH_CLIENT_PATH.write_text(data, encoding="utf-8")
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
