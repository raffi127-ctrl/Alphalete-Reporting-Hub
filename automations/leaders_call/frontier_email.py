"""Auto-fetch the weekly Frontier scorecard from alphaletereporting@gmail.com.

The "Frontier - Sales Verification - For Abyl Acquisition Group" email lands
Monday ~2pm CST. This reads it via the Gmail API (read-only) and saves the
attachment into frontier.UPLOAD_DIR so frontier.parse_uploaded() picks it up —
replacing the manual Hub preflight upload.

Auth: a SEPARATE read-only token from the gmail.compose draft token, stored at
~/.config/recruiting-report/gmail-readonly-token.json. Reuses the same OAuth
client (oauth-client.json). One-time interactive authorization (sign in as
alphaletereporting@gmail.com — the mailbox the scorecard lands in):

    python -m automations.leaders_call.frontier_email --authorize

After that, run_all() calls fetch_latest_scorecard() automatically each run.
"""
from __future__ import annotations

import base64
import datetime as dt
from pathlib import Path
from typing import Optional

GMAIL_READONLY = ["https://www.googleapis.com/auth/gmail.readonly"]
ACCOUNT = "alphaletereporting@gmail.com"
# Stable subject prefix (the full subject is "Frontier - Sales Verification -
# For Abyl Acquisition Group"); we match the prefix then confirm 'Abyl'.
SUBJECT_QUERY = 'subject:"Frontier - Sales Verification" has:attachment'
SUBJECT_CONFIRM = "abyl"

_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"
TOKEN_PATH = _CONFIG_DIR / "gmail-readonly-token.json"


def authorize() -> None:
    """One-time interactive OAuth — sign in as alphaletereporting@gmail.com and
    approve read-only Gmail. Writes the token to TOKEN_PATH."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(f"OAuth client not found at {OAUTH_CLIENT_PATH}.")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(OAUTH_CLIENT_PATH), GMAIL_READONLY)
    creds = flow.run_local_server(
        port=0, login_hint=ACCOUNT, prompt="consent",
        authorization_prompt_message=(
            "Opening your browser to authorize read-only Gmail.\n"
            f"➡  Sign in as {ACCOUNT} and approve.\n"
            "If it doesn't open, copy this URL:\n{url}"),
        success_message="Done — close this tab and return to the terminal.")
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"✓ Saved read-only Gmail token to {TOKEN_PATH} "
          f"(account: {getattr(creds, 'account', '') or ACCOUNT})")


def _creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"No read-only Gmail token at {TOKEN_PATH}. Run the one-time "
            "authorization: python -m automations.leaders_call.frontier_email "
            "--authorize  (sign in as alphaletereporting@gmail.com).")
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), GMAIL_READONLY)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("Gmail read token invalid — re-run --authorize.")
    return creds


def _iter_parts(payload):
    """Walk a Gmail message payload yielding every part (handles nesting)."""
    stack = [payload]
    while stack:
        p = stack.pop()
        yield p
        for sub in p.get("parts", []) or []:
            stack.append(sub)


def fetch_latest_scorecard(dest_dir: Path, today: Optional[dt.date] = None,
                           max_age_days: int = 4, verbose: bool = True) -> Path:
    """Find the newest 'Frontier - Sales Verification … Abyl' email and save its
    spreadsheet attachment into dest_dir. Returns the saved path.

    Raises if no matching recent email or no .xlsx/.xls/.csv attachment — the
    caller (run_all) treats that as 'no Frontier this run' (section skipped), so
    a missing email never crashes the report."""
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=_creds())
    resp = svc.users().messages().list(
        userId="me", q=SUBJECT_QUERY, maxResults=10).execute()
    msgs = resp.get("messages", [])
    if not msgs:
        raise RuntimeError("no 'Frontier - Sales Verification' email with an "
                           "attachment found in alphaletereporting inbox.")
    # messages.list returns newest first.
    for m in msgs:
        msg = svc.users().messages().get(userId="me", id=m["id"],
                                         format="full").execute()
        headers = {h["name"].lower(): h["value"]
                   for h in msg.get("payload", {}).get("headers", [])}
        subj = headers.get("subject", "")
        if SUBJECT_CONFIRM not in subj.lower():
            continue
        # Recency guard: internalDate is ms since epoch.
        sent = dt.datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000)
        age = (dt.datetime.now() - sent).days
        if max_age_days is not None and age > max_age_days:
            raise RuntimeError(
                f"newest matching Frontier email is {age}d old (subject {subj!r}, "
                f"sent {sent:%Y-%m-%d}) — older than {max_age_days}d, not this "
                "week's. Has the 2pm email arrived?")
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved = None
        for part in _iter_parts(msg["payload"]):
            fn = part.get("filename") or ""
            if not fn.lower().endswith((".xlsx", ".xls", ".csv")):
                continue
            att_id = (part.get("body") or {}).get("attachmentId")
            if not att_id:
                continue
            att = svc.users().messages().attachments().get(
                userId="me", messageId=m["id"], id=att_id).execute()
            data = base64.urlsafe_b64decode(att["data"])
            saved = dest_dir / fn
            saved.write_bytes(data)
            if verbose:
                print(f"-> Frontier scorecard fetched from email "
                      f"({subj!r}, sent {sent:%-m/%-d}): {saved.name} "
                      f"({len(data)} bytes)", flush=True)
        if saved:
            return saved
        raise RuntimeError(f"matching email {subj!r} had no .xlsx/.xls/.csv "
                           "attachment.")
    raise RuntimeError("no 'Frontier … Abyl Acquisition' email matched.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--authorize", action="store_true",
                    help="one-time interactive read-only Gmail authorization")
    ap.add_argument("--fetch", action="store_true",
                    help="fetch the latest scorecard into frontier.UPLOAD_DIR")
    args = ap.parse_args()
    if args.authorize:
        authorize()
    elif args.fetch:
        from automations.leaders_call import frontier as fr
        path = fetch_latest_scorecard(fr.UPLOAD_DIR)
        print(f"saved: {path}")
    else:
        ap.print_help()
