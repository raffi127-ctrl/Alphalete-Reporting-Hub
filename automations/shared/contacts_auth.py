"""Google People API auth + contact-group expansion for the reporting account.

The Org Sales Board email goes to 3 Gmail CONTACT GROUPS ("Alphalete Org Owners",
"Carlos' Captain Team", "Raf's Captain Team") whose membership changes over time,
so we expand them to live email addresses at SEND time via the People API instead
of hardcoding a list (Megan 2026-07-03).

Auth mirrors gmail_auth.py: a SEPARATE token (so it never disturbs the Sheets
token), the SAME OAuth client (oauth-client.json), authorized as
alphaletereporting@gmail.com (the account whose contacts hold those groups), scoped
to contacts.readonly. Token: ~/.config/recruiting-report/contacts-token.json
(gitignored, NEVER commit).

One-time authorization (interactive — opens a browser; sign in as
alphaletereporting@gmail.com and approve the Contacts permission):

    python -m automations.shared.contacts_auth

Prereqs: the People API must be ENABLED in the GCP project, and contacts.readonly
added to the OAuth consent screen (alphaletereporting may need to be a Test User if
the app isn't verified — it's a sensitive scope).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

CONTACTS_SCOPES = ["https://www.googleapis.com/auth/contacts.readonly"]
CONTACTS_ACCOUNT = "alphaletereporting@gmail.com"
_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"          # reuse existing client
CONTACTS_TOKEN_PATH = _CONFIG_DIR / "contacts-token.json"      # separate token


def authorize() -> None:
    """One-time interactive OAuth flow → saves the contacts token."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(
            f"OAuth client not found at {OAUTH_CLIENT_PATH}. Ask Megan for "
            "oauth-client.json.")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(OAUTH_CLIENT_PATH), CONTACTS_SCOPES)
    creds = flow.run_local_server(
        port=0,
        login_hint=CONTACTS_ACCOUNT,
        prompt="select_account consent",   # always show the account chooser
        authorization_prompt_message=(
            "Opening your browser to authorize Contacts (read-only).\n"
            f"➡  Sign in as {CONTACTS_ACCOUNT} (NOT raffi127) and approve.\n"
            "If it doesn't open, copy this URL into your browser:\n{url}"),
        success_message="Done — close this tab and return to the terminal.",
    )
    granted = set(creds.scopes or [])
    if not granted.issuperset(CONTACTS_SCOPES):
        raise RuntimeError(
            f"Authorization came back without contacts.readonly (got "
            f"{granted or 'none'}). Re-run and approve the Contacts permission.")
    CONTACTS_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTACTS_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"✓ Saved contacts token to {CONTACTS_TOKEN_PATH}")
    print("  Scopes:", ", ".join(sorted(granted)))


def load_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if not CONTACTS_TOKEN_PATH.exists():
        raise RuntimeError(
            f"No contacts token at {CONTACTS_TOKEN_PATH}. Run the one-time "
            "authorization first:  python -m automations.shared.contacts_auth")
    creds = Credentials.from_authorized_user_file(
        str(CONTACTS_TOKEN_PATH), CONTACTS_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(
                "Contacts token is invalid/expired without a refresh token — "
                "re-run:  python -m automations.shared.contacts_auth")
    return creds


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def expand_groups(group_names: List[str]) -> Tuple[List[str], List[str]]:
    """Return (emails, missing_group_names) — the deduped union of email addresses
    across the named contact groups. `missing_group_names` lists any requested
    group not found, so a caller can fail loudly rather than silently under-send."""
    from googleapiclient.discovery import build
    svc = build("people", "v1", credentials=load_credentials(),
                cache_discovery=False)

    groups, token = [], None
    while True:
        resp = svc.contactGroups().list(pageSize=200, pageToken=token).execute()
        groups += resp.get("contactGroups", []) or []
        token = resp.get("nextPageToken")
        if not token:
            break

    want = {_norm(g) for g in group_names}
    by_name = {_norm(g.get("formattedName") or g.get("name")): g for g in groups}
    found = {n: by_name[n] for n in want if n in by_name}
    missing = sorted(g for g in group_names if _norm(g) not in found)

    member_rns: List[str] = []
    for g in found.values():
        # maxMembers caps at 1000 on the People API; these groups are far smaller.
        full = svc.contactGroups().get(
            resourceName=g["resourceName"], maxMembers=1000).execute()
        rns = full.get("memberResourceNames", []) or []
        if len(rns) >= 1000:               # truncated — surface it rather than hide
            print(f"⚠ group {g.get('formattedName') or g.get('name')!r} hit the "
                  f"1000-member cap — some members may be missing.")
        member_rns += rns
    member_rns = list(dict.fromkeys(member_rns))          # dedupe people

    emails, seen = [], set()
    for i in range(0, len(member_rns), 200):              # getBatchGet caps at 200
        chunk = member_rns[i:i + 200]
        resp = svc.people().getBatchGet(
            resourceNames=chunk, personFields="emailAddresses").execute()
        for r in resp.get("responses", []):
            for e in (r.get("person", {}).get("emailAddresses") or []):
                val = (e.get("value") or "").strip()
                if val and _norm(val) not in seen:
                    seen.add(_norm(val))
                    emails.append(val)
                    break                                 # one email per person
    return emails, missing


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Contacts auth + group expansion")
    ap.add_argument("--expand", nargs="+", metavar="GROUP",
                    help="list emails for the named contact group(s) and exit "
                         "(smoke test — no email sent)")
    a = ap.parse_args(argv)
    if a.expand:
        emails, missing = expand_groups(a.expand)
        if missing:
            print("⚠ groups NOT found:", ", ".join(missing))
        print(f"{len(emails)} address(es):")
        for e in emails:
            print("  ", e)
        return 0
    authorize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
