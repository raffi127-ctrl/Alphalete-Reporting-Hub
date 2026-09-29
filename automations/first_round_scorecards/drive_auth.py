"""Drive access for the 1st round audit docs -- alphaletereporting, full drive scope.

The docs live in Rafael's folder "1st rd Transcribes" (Eve, 2026-09-29), where
everyone who reads them already has access. That folder is Rafael's, not the
bot's, so the Hub's usual Drive token (fiber_activations.drive_auth,
`drive.file`: only files the app made itself) cannot even see it. This is a
SEPARATE token with `drive` scope for alphaletereporting@gmail.com, which is
already an editor of the folder. Its own file, so no other report's token
changes.

One time, on Eve's Windows (opens a browser, sign in as alphaletereporting):

    python -m automations.first_round_scorecards.drive_auth

It checks the folder is writable, then queues the token to the mini
(`set_cred_file drive-full-reporting-token`, Args blanked when done).

    python -m automations.first_round_scorecards.drive_auth --check   # read-only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
DRIVE_ACCOUNT = "alphaletereporting@gmail.com"
AUDIT_FOLDER_ID = "1_WJB0Bb8FiTfFBuicajzMFO4fvpiseet"    # ARS > 1st rd Transcribes

_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"
DRIVE_TOKEN_PATH = _CONFIG_DIR / "drive-full-reporting-token.json"


def authorize() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not OAUTH_CLIENT_PATH.exists():
        raise SystemExit(f"OAuth client not found at {OAUTH_CLIENT_PATH}.")
    flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT_PATH), DRIVE_SCOPES)
    creds = flow.run_local_server(
        port=0, login_hint=DRIVE_ACCOUNT, prompt="consent",
        authorization_prompt_message=(
            "Opening your browser to let Lucy save the 1st round audits in Drive.\n"
            f"-> Sign in as {DRIVE_ACCOUNT}.\n"
            "-> If Google says the app is unverified: Advanced -> Go to (unsafe).\n"
            "-> Tick the Drive box and approve.\n"
            "If the browser doesn't open, copy this URL:\n{url}"),
        success_message="Done - close this tab and go back to Claude.")
    if not set(creds.scopes or []).issuperset(DRIVE_SCOPES):
        raise SystemExit("The Drive box wasn't ticked - run it again and tick it.")
    DRIVE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    DRIVE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print("OK - Drive permission saved")


def load_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not DRIVE_TOKEN_PATH.exists():
        raise RuntimeError(f"No Drive token at {DRIVE_TOKEN_PATH} - run "
                           "python -m automations.first_round_scorecards.drive_auth on Windows")
    creds = Credentials.from_authorized_user_file(str(DRIVE_TOKEN_PATH), DRIVE_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            DRIVE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("Drive token invalid and can't refresh - run drive_auth again")
    return creds


def service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=load_credentials(), cache_discovery=False)


def check() -> bool:
    svc = service()
    email = svc.about().get(fields="user(emailAddress)").execute()["user"]["emailAddress"]
    meta = svc.files().get(fileId=AUDIT_FOLDER_ID, fields="name,capabilities(canAddChildren)").execute()
    ok = email.lower() == DRIVE_ACCOUNT and meta["capabilities"].get("canAddChildren")
    print(f"account: {email}{'' if email.lower() == DRIVE_ACCOUNT else '  <- WRONG ACCOUNT, run it again'}")
    print(f"folder : {meta['name']!r} - {'can save docs here' if meta['capabilities'].get('canAddChildren') else 'CANNOT save here'}")
    return bool(ok)


def push() -> None:
    from automations.day_orchestrator import mini_control as mc
    mc.enqueue("set_cred_file", "drive-full-reporting-token "
               + json.dumps(json.loads(DRIVE_TOKEN_PATH.read_text(encoding="utf-8"))), by="Eve")
    print("queued for the mini (the Sheet cell is blanked when it's done)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_round_scorecards.drive_auth")
    ap.add_argument("--check", action="store_true", help="read-only: account + folder access")
    args = ap.parse_args(argv)
    if args.check:
        return 0 if check() else 1
    authorize()
    if not check():
        return 1
    push()
    return 0


if __name__ == "__main__":
    sys.exit(main())
