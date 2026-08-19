"""Read/write the Indeed Ad Performance dashboard's hidden DATA tab.

Auth prefers the PERSONAL OAuth token, unlike funnel_board: this workbook is
Carlos's own file, so his identity is the one guaranteed to be on it. The
applicant_tracker service account is the fallback and only works once the file
has been shared with it.
"""
from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request

SPREADSHEET_ID = os.environ.get(
    "INDEED_SOURCE_SPREADSHEET_ID", "1yUvxSL5gsVEBTzlVNMyrmP_IH_vmcUcWIO_ZRtjzImo")
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
    creds, which = _oauth(), "personal OAuth token (%s)" % TOKEN.name
    if creds is None:
        creds, which = _service_account(), "applicant_tracker service account"
    if creds is None:
        raise SystemExit(
            "No Google credential on this machine. Drop %s (Carlos's identity, the "
            "workbook owner) or share the workbook with the applicant_tracker "
            "service account." % TOKEN)
    if verbose:
        print("[indeed_source_report] Sheets auth: %s" % which, flush=True)
    return AuthorizedSession(creds)


def get_values(sess, rng):
    r = sess.get("%s/%s/values/%s" % (API, SPREADSHEET_ID, rng),
                 params={"valueRenderOption": "UNFORMATTED_VALUE"})
    r.raise_for_status()
    return r.json().get("values", [])


def put_values(sess, rng, values):
    r = sess.put("%s/%s/values/%s" % (API, SPREADSHEET_ID, rng),
                 params={"valueInputOption": "RAW"},
                 json={"majorDimension": "ROWS", "values": values})
    r.raise_for_status()
    return r.json()


def clear(sess, rng):
    r = sess.post("%s/%s/values/%s:clear" % (API, SPREADSHEET_ID, rng), json={})
    r.raise_for_status()
