"""Read/write the Source Report - Indeed dashboard's hidden data tab.

Auth prefers the applicant_tracker SERVICE ACCOUNT, same as funnel_board and for
the same reason: the dashboard now lives in the Alphalete Org Applicant Tracker,
which is applicant_tracker's own workbook — that key already writes to this exact
file every morning, so it travels with the report and which machine runs it stops
mattering. A machine's personal OAuth identity is NOT guaranteed to be on this
file; funnel_board died on PERMISSION_DENIED exactly that way after a clean pull.

The personal token stays as the fallback, which is what makes this work on a
laptop that has the token but not the key.
"""
from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request

# The Alphalete Org Applicant Tracker. The dashboard lives here as a tab rather
# than in its own workbook so it sits beside the funnel board everyone already
# opens. NOTE: this workbook has a hard 10,000,000-cell ceiling and shares it
# with 2R / Call List / Apps, which append daily — see README before adding
# anything wide here.
SPREADSHEET_ID = os.environ.get(
    "INDEED_SOURCE_SPREADSHEET_ID", "111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA")
DATA_TAB = os.environ.get("INDEED_SOURCE_DATA_TAB", "Indeed Ad Data")


def data_range(a1):
    """A1 range on the hidden data tab, quoted for the spaces in its name."""
    return "'%s'!%s" % (DATA_TAB, a1)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TOKEN = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
API = "https://sheets.googleapis.com/v4/spreadsheets"

DATA_HEADERS = ['Manager', 'Period', 'Account', 'Inbox Email', 'Ad Title', 'City',
                '# Variants', 'Applicants', 'Removed %', 'Sent to Call List',
                '1st Booked', '1st Showed', '1st Retention %', '2nd Booked',
                '2nd Showed', '2nd Retention %', 'Training Booked', 'Training Showed',
                'New Starts Booked', 'New Starts Showed', '2nd Round Conversion %']


def _oauth():
    if not TOKEN.exists():
        return None
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _service_account():
    try:
        from automations.applicant_tracker import config as _cfg
        from google.oauth2 import service_account
    except Exception:  # noqa: BLE001
        return None
    p = Path(_cfg.SERVICE_ACCOUNT_JSON)
    if not p.exists():
        return None
    try:
        return service_account.Credentials.from_service_account_file(str(p), scopes=SCOPES)
    except Exception:  # noqa: BLE001
        return None


def session(verbose=False):
    creds, which = _service_account(), "applicant_tracker service account"
    if creds is None:
        creds, which = _oauth(), "personal OAuth token (%s)" % TOKEN.name
    if creds is None:
        raise SystemExit(
            "No Google credential on this machine. Drop the applicant_tracker "
            "service-account key (preferred — it is already on the tracker), or "
            "%s for an identity that has been shared on the file." % TOKEN)
    if verbose:
        print("[indeed_source_report] Sheets auth: %s" % which, flush=True)
    return AuthorizedSession(creds)


# Google answers a momentary 429 (quota shared with 2R / Call List / Apps, which
# append into this same workbook all morning) or a 5xx server blip on calls that
# succeed seconds later. Left unhandled, ONE of those sinks the whole run: on
# 2026-08-27 the 4:00am pass died in preflight on a single 503 and told the
# channel "this machine can't write the workbook", pointing the fix at
# credentials that were never the problem. Retry the transient statuses HERE, at
# the single HTTP chokepoint, so they never reach the report. 403/404 are NOT in
# the list — a real permission fault still fails on the first answer.
_RETRY_STATUS = (429, 500, 502, 503, 504)
_RETRIES = 6                    # 1+2+4+8+16 ≈ 31s of blip ridden out
_BACKOFF_CAP = 30.0


def request(sess, method, url, **kw):
    """One Sheets API call, retrying a transient 429/5xx or a dropped
    connection. Returns the response; raises like raise_for_status() would."""
    import time

    import requests

    last_exc = None
    for attempt in range(_RETRIES):
        try:
            r = getattr(sess, method)(url, **kw)
        except requests.exceptions.RequestException as e:   # connection reset/timeout
            last_exc = e
            if attempt == _RETRIES - 1:
                raise
            time.sleep(min(2 ** attempt, _BACKOFF_CAP))
            continue
        if r.status_code not in _RETRY_STATUS or attempt == _RETRIES - 1:
            r.raise_for_status()
            return r
        print("  (sheets %d on %s - retry %d/%d)"
              % (r.status_code, method.upper(), attempt + 1, _RETRIES - 1), flush=True)
        time.sleep(min(2 ** attempt, _BACKOFF_CAP))
    # Unreachable: the final attempt always returns or raises above.
    raise last_exc or RuntimeError("sheets request exhausted its retries")


def is_transient(exc):
    """True when a Sheets failure is Google-side and temporary rather than an
    identity problem. What separates 'wait and it works' from 'fix the
    credential' — an abort message that gets this backwards costs an hour."""
    code = getattr(getattr(exc, "response", None), "status_code", None)
    if code is not None:
        return code in _RETRY_STATUS          # a real HTTPError answers exactly
    import requests
    if isinstance(exc, requests.exceptions.RequestException):
        return True                            # never got an answer at all
    s = str(exc)
    return any(w in s for w in ("Service Unavailable", "Internal Server Error",
                                "Bad Gateway", "Gateway Timeout", "timed out"))


def get_values(sess, rng):
    r = request(sess, "get", "%s/%s/values/%s" % (API, SPREADSHEET_ID, rng),
                params={"valueRenderOption": "UNFORMATTED_VALUE"})
    return r.json().get("values", [])


def put_values(sess, rng, values):
    r = request(sess, "put", "%s/%s/values/%s" % (API, SPREADSHEET_ID, rng),
                params={"valueInputOption": "RAW"},
                json={"majorDimension": "ROWS", "values": values})
    return r.json()


def clear(sess, rng):
    request(sess, "post", "%s/%s/values/%s:clear" % (API, SPREADSHEET_ID, rng),
            json={})


def probe_write(sess):
    """Prove this credential can WRITE the workbook, cheaply.

    A read succeeds for anyone-with-the-link, so reading proves nothing. This
    rewrites one throwaway cell on the hidden data tab with what it already
    contains — a real write that changes nothing. Raises on 403/404; a
    transient 429/5xx is retried by `request` and never gets here.
    """
    # Far below the data, but INSIDE the grid — a column past the sheet's
    # width answers 400 Bad Request, which would look like a permission fault.
    cell = data_range("X4999")
    r = request(sess, "get", "%s/%s/values/%s" % (API, SPREADSHEET_ID, cell),
                params={"valueRenderOption": "UNFORMATTED_VALUE"})
    current = (r.json().get("values") or [[""]])[0]
    request(sess, "put", "%s/%s/values/%s" % (API, SPREADSHEET_ID, cell),
            params={"valueInputOption": "RAW"},
            json={"majorDimension": "ROWS", "values": [current or [""]]})
