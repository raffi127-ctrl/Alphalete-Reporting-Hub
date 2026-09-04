"""Drive OAuth for the commission-sheet run — its OWN token, full drive scope.

Step 1 of JD's payroll Loom is "copy last week's sheet, rename it, move the old
ones into Raf's folder, keep the last two". That is three Drive operations on
files this code did NOT create, which decides both the scope and the account:

  * SCOPE is `drive`, not `drive.file`. The Hub's existing Drive token
    (fiber_activations.drive_auth) is `drive.file` — create/read/update only
    files the app itself made — which is right for uploading PNGs it generated
    and useless here: it cannot even SEE a workbook JD made in his browser,
    let alone copy it or move it between folders. `drive` is a restricted
    scope, so the consent screen shows an "unverified app" warning; that is
    expected for this client and is cleared with Advanced -> Go to (unsafe).

  * ACCOUNT is raffi127@gmail.com — the account whose Sheets token already
    opens both the commission workbook and the All in One. The other Drive
    token belongs to alphaletereporting, which is a different Drive.

  * The TOKEN IS SEPARATE, at drive-full-token.json. Re-consenting the existing
    ~/.config/recruiting-report/oauth-token.json would hand it a new scope set
    and break every report that rides it — the ~52 ICD tabs included. Never
    point this flow at that file.

One-time, interactive (opens a browser; Megan signs in and approves):

    python -m automations.commission_sheet.drive_auth

Afterwards, prove it reaches the real folder without writing anything:

    python -m automations.commission_sheet.drive_auth --check
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

#: Full Drive. See the module docstring for why drive.file cannot work here.
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
#: The account that already sees both workbooks.
DRIVE_ACCOUNT = "raffi127@gmail.com"

_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"        # reuse the client
DRIVE_TOKEN_PATH = _CONFIG_DIR / "drive-full-token.json"     # our own token


def authorize() -> None:
    """One-time interactive OAuth; writes DRIVE_TOKEN_PATH."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(f"OAuth client not found at {OAUTH_CLIENT_PATH}.")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(OAUTH_CLIENT_PATH), DRIVE_SCOPES)
    creds = flow.run_local_server(
        port=0,
        login_hint=DRIVE_ACCOUNT,
        prompt="consent",
        authorization_prompt_message=(
            "Opening your browser to authorize Drive for the commission sheets.\n"
            f"-> Sign in as {DRIVE_ACCOUNT}.\n"
            "-> Google will warn the app is unverified: Advanced -> Go to (unsafe).\n"
            "-> Approve the 'See, edit, create and delete all your Drive files' box.\n"
            "If the browser doesn't open, copy this URL:\n{url}"),
        success_message="Done — close this tab and return to the terminal.",
    )

    granted = set(creds.scopes or [])
    if not granted.issuperset(DRIVE_SCOPES):
        raise RuntimeError(
            "Authorization came back WITHOUT full Drive scope "
            f"(got {sorted(granted) or 'none'}). The copy/move step needs it — "
            "re-run and tick the Drive permission.")

    DRIVE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    DRIVE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    DRIVE_TOKEN_PATH.chmod(0o600)
    print(f"OK — saved Drive token to {DRIVE_TOKEN_PATH}")


def load_credentials():
    """Saved Drive credentials, refreshed if expired."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not DRIVE_TOKEN_PATH.exists():
        raise RuntimeError(
            f"No Drive token at {DRIVE_TOKEN_PATH}. Run the one-time "
            "authorization:  python -m automations.commission_sheet.drive_auth")

    creds = Credentials.from_authorized_user_file(
        str(DRIVE_TOKEN_PATH), DRIVE_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            DRIVE_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Drive token invalid and can't refresh. Re-run: "
                "python -m automations.commission_sheet.drive_auth")
    return creds


def service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=load_credentials(),
                 cache_discovery=False)


def check() -> int:
    """Read-only proof the token reaches the real commission folder."""
    from automations.commission_sheet import config as C

    svc = service()
    who = svc.about().get(fields="user(emailAddress)").execute()
    email = who.get("user", {}).get("emailAddress", "?")
    print(f"authorized as : {email}")
    if email.lower() != DRIVE_ACCOUNT:
        print(f"  !! expected {DRIVE_ACCOUNT} — the wrong account was used",
              file=sys.stderr)

    for label, fid in (("live folder   ", C.COMMISSION_FOLDER_ID),
                       ("archive folder", C.ARCHIVE_FOLDER_ID)):
        meta = svc.files().get(fileId=fid, fields="id,name,capabilities(canEdit)",
                               supportsAllDrives=True).execute()
        res = svc.files().list(
            q=f"'{fid}' in parents and trashed=false",
            fields="files(id,name,modifiedTime)", orderBy="modifiedTime desc",
            pageSize=100, supportsAllDrives=True,
            includeItemsFromAllDrives=True).execute()
        files = res.get("files", [])
        editable = meta.get("capabilities", {}).get("canEdit")
        print(f"{label}: {meta['name']!r} — {len(files)} file(s), "
              f"{'writable' if editable else 'READ-ONLY (moves will fail)'}")
        for f in files[:8]:
            print(f"    {f['modifiedTime'][:10]}  {f['name']}")
        if len(files) > 8:
            print(f"    … {len(files) - 8} more")

    # The copy step reads the workbook itself, which lives outside that folder.
    wb = svc.files().get(fileId=C.WORKBOOK_ID, fields="name,capabilities(canCopy)",
                         supportsAllDrives=True).execute()
    print(f"can copy {wb['name']!r}: "
          f"{wb.get('capabilities', {}).get('canCopy')}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="verify an existing token (read-only); don't re-authorize")
    args = ap.parse_args(argv)
    if args.check:
        return check()
    authorize()
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
