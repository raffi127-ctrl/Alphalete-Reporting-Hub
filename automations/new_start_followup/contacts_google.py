"""Fill the leader phone overlay from alphaletereception@gmail.com's Google
Contacts — the account that has every leader's number (Megan 2026-08-23).

This replaced the OBCL phone fill THE SAME DAY it was built: the OBCL Phone
column is the NEW START'S number, never the interviewer's, so numbers must
come from a source that actually stores LEADER contacts. Reception's Google
Contacts is that source.

Flow (laptop, where a human can click the OAuth consent):

    # one-time: browser opens — sign in as alphaletereception@gmail.com
    python -m automations.new_start_followup.contacts_google --auth

    # see the matches without writing anything
    python -m automations.new_start_followup.contacts_google

    # write/merge the machine-local overlay
    python -m automations.new_start_followup.contacts_google --write

    # ship the overlay to the machine that texts (Lucy 1)
    lucy push_cred_file new-start-leader-phones 'Lucy 1'

Matching: contact display names are normalized with roster._norm and matched
against each leader's name + OBCL aliases. A hand-entered overlay number WINS
over a Contacts match (only blanks are filled) unless --overwrite. A leader
matching two contacts with DIFFERENT numbers is skipped and reported — a
wrong number is worse than no number.

Auth mirrors shared/contacts_auth.py (same OAuth client, separate token so
the alphaletereporting contacts token is untouched). The overlay itself is
machine-local and NEVER committed — the repo is PUBLIC.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

CONTACTS_SCOPES = ["https://www.googleapis.com/auth/contacts.readonly"]
ACCOUNT = "alphaletereception@gmail.com"
_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"
TOKEN_PATH = _CONFIG_DIR / "contacts-token-alphaletereception.json"


def authorize() -> None:
    """One-time interactive OAuth flow → saves the reception contacts token."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(
            "OAuth client not found at {}. Ask Megan for oauth-client.json."
            .format(OAUTH_CLIENT_PATH))
    flow = InstalledAppFlow.from_client_secrets_file(
        str(OAUTH_CLIENT_PATH), CONTACTS_SCOPES)
    creds = flow.run_local_server(
        port=0,
        login_hint=ACCOUNT,
        prompt="select_account consent",
        authorization_prompt_message=(
            "Opening your browser to authorize Contacts (read-only).\n"
            "-> Sign in as {} and approve.\n"
            "If it doesn't open, copy this URL into your browser:\n{{url}}"
            .format(ACCOUNT)),
        success_message="Done - close this tab and return to the terminal.",
    )
    granted = set(creds.scopes or [])
    if not granted.issuperset(CONTACTS_SCOPES):
        raise RuntimeError(
            "Authorization came back without contacts.readonly (got {}). "
            "Re-run and approve the Contacts permission.".format(granted or "none"))
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass
    print("OK - saved reception contacts token to {}".format(TOKEN_PATH))


def _load_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            "No reception contacts token at {}. Run the one-time authorization "
            "first:  python -m automations.new_start_followup.contacts_google "
            "--auth".format(TOKEN_PATH))
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), CONTACTS_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(
                "Reception contacts token is invalid/expired without a refresh "
                "token - re-run with --auth")
    return creds


def fetch_contacts() -> List[Tuple[str, List[str]]]:
    """Every (display name, [phone, ...]) on the reception account."""
    from googleapiclient.discovery import build
    svc = build("people", "v1", credentials=_load_credentials(),
                cache_discovery=False)
    out, token = [], None
    while True:
        resp = svc.people().connections().list(
            resourceName="people/me", pageSize=1000, pageToken=token,
            personFields="names,phoneNumbers").execute()
        for p in resp.get("connections", []) or []:
            names = p.get("names") or []
            phones = [ph.get("value") or "" for ph in (p.get("phoneNumbers") or [])]
            display = (names[0].get("displayName") or "") if names else ""
            if display and any(phones):
                out.append((display, [x for x in phones if x]))
        token = resp.get("nextPageToken")
        if not token:
            break
    return out


def match_leaders(contacts=None):
    """-> (matches: slack_id -> e164, report lines).

    A leader matching two contacts with different numbers is skipped: texting
    a wrong number is worse than texting nobody.
    """
    from automations.new_start_followup import roster as roster_mod
    from automations.swag_welcome.roster import normalize_phone, pretty_phone

    contacts = contacts if contacts is not None else fetch_contacts()
    by_key = {}  # type: Dict[str, set]
    for display, phones in contacts:
        key = roster_mod._norm(display)
        if not key:
            continue
        for raw in phones:
            e164, _ = normalize_phone(raw)
            if e164:
                by_key.setdefault(key, set()).add(e164)

    ros = roster_mod.load()
    matches = {}  # type: Dict[str, str]
    lines = []    # type: List[str]
    unmatched, ambiguous = [], []
    for leader in sorted(ros.leaders, key=lambda l: l.name.lower()):
        nums = set()
        for key in leader.keys():
            nums |= by_key.get(key, set())
        if not nums:
            unmatched.append(leader.name)
            continue
        if len(nums) > 1:
            ambiguous.append("{} ({})".format(
                leader.name, ", ".join(sorted(pretty_phone(n) or n for n in nums))))
            continue
        matches[leader.slack_id] = list(nums)[0]
        lines.append("  {:<26} {}".format(
            leader.name, pretty_phone(matches[leader.slack_id])))
    lines.insert(0, "{} of {} leaders matched a reception contact:".format(
        len(matches), len(ros.leaders)))
    if ambiguous:
        lines.append("SKIPPED — two different numbers in Contacts "
                     "(fix there, or hand-edit the overlay):")
        for a in ambiguous:
            lines.append("  " + a)
    if unmatched:
        lines.append("NO CONTACT MATCH ({}):".format(len(unmatched)))
        for n in unmatched:
            lines.append("  " + n)
    return matches, lines


def numbers_for(names) -> Dict[str, str]:
    """-> {name: e164} for the names reception's Contacts knows, by name only.

    match_leaders() can't answer this: it walks leaders.json, and the people
    this is for are exactly the ones NOT in it — leaders Lucy learned from a
    hand-tag in the thread (shared.slack_tag_learning). Same rules as
    match_leaders: normalized-name match, and a name with two DIFFERENT numbers
    is skipped rather than guessed at.
    """
    from automations.new_start_followup import roster as roster_mod
    from automations.swag_welcome.roster import normalize_phone

    by = {}  # type: Dict[str, set]
    for display, phones in fetch_contacts():
        key = roster_mod._norm(display)
        if not key:
            continue
        for raw in phones:
            e164, _ = normalize_phone(raw)
            if e164:
                by.setdefault(key, set()).add(e164)

    out = {}  # type: Dict[str, str]
    for name in names:
        nums = by.get(roster_mod._norm(name), set())
        if len(nums) == 1:
            out[name] = list(nums)[0]
    return out


def write_overlay(matches: Dict[str, str], overwrite: bool = False) -> Path:
    """Merge matches into the machine-local overlay. Hand-entered numbers WIN
    unless --overwrite."""
    from automations.new_start_followup import roster as roster_mod
    existing = roster_mod.load_phones()
    merged = dict(matches) if overwrite else dict(matches, **existing)
    return roster_mod.save_phones(merged)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Leader phone overlay from alphaletereception@'s Google Contacts")
    ap.add_argument("--auth", action="store_true",
                    help="one-time interactive OAuth as {}".format(ACCOUNT))
    ap.add_argument("--write", action="store_true",
                    help="merge matches into the local phone overlay "
                         "(default: print matches only)")
    ap.add_argument("--overwrite", action="store_true",
                    help="with --write: Contacts numbers replace hand-entered "
                         "overlay numbers instead of losing to them")
    a = ap.parse_args(argv)
    if a.auth:
        authorize()
        return 0
    matches, lines = match_leaders()
    print("\n".join(lines))
    if not a.write:
        print("\n[dry-run] overlay untouched. Re-run with --write to merge, "
              "then push to Lucy 1:\n  lucy push_cred_file "
              "new-start-leader-phones 'Lucy 1'")
        return 0
    path = write_overlay(matches, overwrite=a.overwrite)
    print("\nWrote {} number(s) -> {}".format(len(matches), path))
    print("Now ship it to the texting machine:\n"
          "  lucy push_cred_file new-start-leader-phones 'Lucy 1'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
