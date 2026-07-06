"""Sheets OAuth — the one-time interactive authorization that creates the
gspread token every recruiting/OPT report reads.

Why this exists as its own command: fill.py's runtime client is deliberately
NON-interactive — it never opens a browser (an unattended 4am batch that popped
a Chrome would stall every report, 2026-07-04). So the one-time consent lives
here instead. Run this ONCE on each machine that runs reports; it opens a
browser, you sign in, and it writes the token fill.py then reuses.

The token is authorized as raffi127@gmail.com (Rafael Hidalgo), scoped to
spreadsheets — that account has the ~52 ICD tabs + Tableau Custom Views. Sign in
as raffi127, NOT alphaletereporting (that's the Gmail-drafts account).

Token: ~/.config/recruiting-report/oauth-token.json  (gitignored, NEVER commit)
Reuses the same OAuth client (oauth-client.json) the installer drops in.

One-time authorization (interactive — opens a browser):

  python -m automations.recruiting_report.sheets_auth
"""
from __future__ import annotations

from pathlib import Path

# Mirror fill.py exactly (kept local so this script imports nothing heavy —
# fill.py pulls in gspread etc. and resolves the sheet config at import time).
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEETS_ACCOUNT = "raffi127@gmail.com"   # the account with the ICD tabs

_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"
OAUTH_TOKEN_PATH = _CONFIG_DIR / "oauth-token.json"


def authorize() -> None:
    """Run the one-time interactive OAuth flow and save the Sheets token.

    Opens the default browser; sign in as raffi127@gmail.com and approve the
    spreadsheets scope. Writes the token to OAUTH_TOKEN_PATH so fill.py (and
    every report through it) can read/refresh it non-interactively afterward.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(
            f"OAuth client not found at {OAUTH_CLIENT_PATH}. The installer "
            "normally drops it in — re-run the installer, or ask Megan for "
            "oauth-client.json and save it there.")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(OAUTH_CLIENT_PATH), SHEETS_SCOPES)
    # port=0 = pick a free loopback port (Desktop clients allow loopback).
    # login_hint pre-selects the account; prompt='consent' forces the grant so
    # a refresh_token is always issued (fill.py refreshes off it later).
    creds = flow.run_local_server(
        port=0,
        login_hint=SHEETS_ACCOUNT,
        prompt="consent",
        authorization_prompt_message=(
            "Opening your browser to authorize Google Sheets access.\n"
            f"➡  Sign in as {SHEETS_ACCOUNT} (NOT alphaletereporting) and approve.\n"
            "If it doesn't open, copy this URL into your browser:\n{url}"),
        success_message=(
            "Done — you can close this tab and return to the terminal."),
    )

    granted = set(creds.scopes or [])
    if not granted.issuperset(SHEETS_SCOPES):
        raise RuntimeError(
            f"Authorization came back without the spreadsheets scope "
            f"(got {granted or 'none'}). Re-run and approve the Sheets permission.")

    OAUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    OAUTH_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    acct = getattr(creds, "account", "") or ""
    print(f"✓ Saved Sheets token to {OAUTH_TOKEN_PATH}"
          + (f"  (account: {acct})" if acct else ""))
    print("  Scopes:", ", ".join(sorted(granted)))
    print("  This machine can now run reports.")


if __name__ == "__main__":
    authorize()
