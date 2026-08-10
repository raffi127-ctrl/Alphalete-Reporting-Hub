"""Google credentials for the Funnel Board's five tabs.

Prefer the applicant_tracker service account; fall back to the personal OAuth
token.

Why the service account comes first (2026-08-10): the Funnel Board tabs live in
the Alphalete Org Applicant Tracker, which is applicant_tracker's own workbook —
that service account already writes to this exact file every morning. The
personal token is a per-machine thing that happens to be shared on the file on
one mini and not the other: running the report from Lucy 1 died on
PERMISSION_DENIED after a clean 14/14 pull, purely because that machine's OAuth
identity isn't on the file. The service account travels with the report, so
which machine runs it stops mattering.

The fallback keeps the report working anywhere the key hasn't been dropped —
the repo is public, so the key is gitignored and distributed out-of-band.
"""
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TOKEN = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"


def _service_account_creds():
    """The applicant_tracker key, or None if it isn't on this machine."""
    try:
        from automations.applicant_tracker import config as _cfg
        from google.oauth2 import service_account
    except Exception:  # noqa: BLE001 — never let a missing import lose the run
        return None
    path = Path(_cfg.SERVICE_ACCOUNT_JSON)
    if not path.exists():
        return None
    try:
        return service_account.Credentials.from_service_account_file(
            str(path), scopes=SCOPES)
    except Exception:  # noqa: BLE001 — a malformed key falls back, not crashes
        return None


def _oauth_creds():
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def session(verbose=False):
    """An AuthorizedSession for the Funnel Board workbook."""
    creds = _service_account_creds()
    which = "applicant_tracker service account"
    if creds is None:
        creds, which = _oauth_creds(), "personal OAuth token (%s)" % TOKEN.name
    if verbose:
        # Say which identity is writing. A PERMISSION_DENIED buried in a
        # batchUpdate body reads as a code bug until you know who the caller
        # was; this line is what tells the two apart at a glance.
        print("[funnel_board] Sheets auth: %s" % which, flush=True)
    return AuthorizedSession(creds)
