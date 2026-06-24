"""Drive OAuth — a SEPARATE token from the Sheets one, mirroring gmail_auth.py.

Why separate (NOT re-authorizing the Sheets token):
  * The Sheets/gspread token (~/.config/recruiting-report/oauth-token.json) is
    authorized as raffi127@gmail.com and scoped to spreadsheets only — the ~52
    ICD tabs + Tableau Custom Views depend on it. Re-consenting would break them.
  * PNG delivery goes to alphaletereporting's Drive, so THAT account grants this
    token (same account as the Gmail draft token).

Scope is drive.file (NON-sensitive: the app only sees/manages files it creates),
so no Google app verification is needed — just a one-time consent.

Stores its own token at:
  ~/.config/recruiting-report/drive-token.json   (gitignored, NEVER commit)

One-time authorization (interactive — opens a browser; sign in as
alphaletereporting@gmail.com):

  python -m automations.fiber_activations.drive_auth
"""
from __future__ import annotations

from pathlib import Path

# drive.file = create/read/update/delete ONLY files this app creates. Enough to
# make the "Captainship Activations - PNGs" folder + overwrite the PNGs in it.
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_ACCOUNT = "alphaletereporting@gmail.com"

_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"   # reuse existing client
DRIVE_TOKEN_PATH = _CONFIG_DIR / "drive-token.json"     # separate token


def authorize() -> None:
    """One-time interactive OAuth; saves the Drive token to DRIVE_TOKEN_PATH.
    Sign in as alphaletereporting@gmail.com (NOT raffi127) and approve."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(
            f"OAuth client not found at {OAUTH_CLIENT_PATH}. Ask Megan for "
            "oauth-client.json.")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(OAUTH_CLIENT_PATH), DRIVE_SCOPES)
    creds = flow.run_local_server(
        port=0,
        login_hint=DRIVE_ACCOUNT,
        prompt="consent",
        authorization_prompt_message=(
            "Opening your browser to authorize Drive uploads.\n"
            f"➡  Sign in as {DRIVE_ACCOUNT} (NOT raffi127) and approve.\n"
            "If it doesn't open, copy this URL:\n{url}"),
        success_message="Done — close this tab and return to the terminal.",
    )

    granted = set(creds.scopes or [])
    if not granted.issuperset(DRIVE_SCOPES):
        raise RuntimeError(
            f"Authorization came back without the drive.file scope "
            f"(got {granted or 'none'}). Re-run and approve the Drive permission.")

    DRIVE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    DRIVE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    acct = getattr(creds, "account", "") or ""
    print(f"✓ Saved Drive token to {DRIVE_TOKEN_PATH}"
          + (f"  (account: {acct})" if acct else ""))


def load_credentials():
    """Load saved Drive credentials, refreshing if expired."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not DRIVE_TOKEN_PATH.exists():
        raise RuntimeError(
            f"No Drive token at {DRIVE_TOKEN_PATH}. Run the one-time "
            "authorization:  python -m automations.fiber_activations.drive_auth")

    creds = Credentials.from_authorized_user_file(
        str(DRIVE_TOKEN_PATH), DRIVE_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            DRIVE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Drive token invalid and can't refresh. Re-run authorization: "
                "python -m automations.fiber_activations.drive_auth")
    return creds


if __name__ == "__main__":
    authorize()
