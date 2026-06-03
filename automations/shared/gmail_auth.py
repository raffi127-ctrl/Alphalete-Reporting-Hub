"""Gmail OAuth — a SEPARATE token from the Sheets one, so drafts land in
the right mailbox without breaking Sheets access.

Why separate (not re-authorizing the existing token):
  * The Sheets/gspread token (~/.config/recruiting-report/oauth-token.json)
    is authorized as raffi127@gmail.com (Rafael Hidalgo) and scoped to
    spreadsheets only — the ~52 ICD tabs + Tableau Custom Views depend on
    that account. Re-consenting it as another account would break them.
  * Gmail drafts must be created in the mailbox of the account that
    authorizes the token. Reports send FROM alphaletereporting@gmail.com,
    so THAT account has to grant this token.

So this stores its own token at:
  ~/.config/recruiting-report/gmail-token.json   (gitignored, NEVER commit)

It reuses the same OAuth *client* (oauth-client.json) — only the granted
scope + the signed-in account differ.

One-time authorization (interactive — opens a browser; pick / log in as
alphaletereporting@gmail.com):

  python -m automations.shared.gmail_auth

After that, code can call load_credentials() to get a refreshed token for
the Gmail API (users().drafts().create()).
"""
from __future__ import annotations

import json
from pathlib import Path

# gmail.compose = create/read/update/delete drafts + send. The minimal
# scope for draft creation (narrower than gmail.modify).
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

# The Gmail account whose mailbox the drafts go into. Used as a login hint
# so the consent screen pre-selects the right account.
GMAIL_ACCOUNT = "alphaletereporting@gmail.com"

_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"     # reuse existing client
GMAIL_TOKEN_PATH = _CONFIG_DIR / "gmail-token.json"        # separate token


def authorize() -> None:
    """Run the one-time interactive OAuth flow and save the Gmail token.

    Opens the default browser; sign in as alphaletereporting@gmail.com and
    approve the gmail.compose scope. Writes the token to GMAIL_TOKEN_PATH.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(
            f"OAuth client not found at {OAUTH_CLIENT_PATH}. "
            "Ask Megan for oauth-client.json.")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(OAUTH_CLIENT_PATH), GMAIL_SCOPES)
    # port=0 = pick a free loopback port (Desktop clients allow loopback).
    # login_hint pre-selects the account; prompt='consent' forces the scope
    # grant so a refresh_token is always issued.
    creds = flow.run_local_server(
        port=0,
        login_hint=GMAIL_ACCOUNT,
        prompt="consent",
        authorization_prompt_message=(
            "Opening your browser to authorize Gmail drafts.\n"
            f"➡  Sign in as {GMAIL_ACCOUNT} (NOT raffi127) and approve.\n"
            "If it doesn't open, copy this URL into your browser:\n{url}"),
        success_message=(
            "Done — you can close this tab and return to the terminal."),
    )

    granted = set(creds.scopes or [])
    if not granted.issuperset(GMAIL_SCOPES):
        raise RuntimeError(
            f"Authorization came back without the gmail.compose scope "
            f"(got {granted or 'none'}). Re-run and make sure to approve "
            "the Gmail permission.")

    GMAIL_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GMAIL_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    acct = getattr(creds, "account", "") or ""
    print(f"✓ Saved Gmail token to {GMAIL_TOKEN_PATH}"
          + (f"  (account: {acct})" if acct else ""))
    print("  Scopes:", ", ".join(sorted(granted)))


def load_credentials():
    """Load the saved Gmail credentials, refreshing if expired. Raises a
    clear error if authorize() hasn't been run yet."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not GMAIL_TOKEN_PATH.exists():
        raise RuntimeError(
            f"No Gmail token at {GMAIL_TOKEN_PATH}. Run the one-time "
            "authorization first:  python -m automations.shared.gmail_auth")

    creds = Credentials.from_authorized_user_file(
        str(GMAIL_TOKEN_PATH), GMAIL_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GMAIL_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Gmail token is invalid and can't be refreshed. Re-run "
                "the authorization:  python -m automations.shared.gmail_auth")
    return creds


if __name__ == "__main__":
    authorize()
