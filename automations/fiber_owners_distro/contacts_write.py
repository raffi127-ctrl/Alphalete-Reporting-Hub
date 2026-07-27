"""Read-WRITE Google Contacts auth + group-membership sync.

Mirrors automations.shared.contacts_auth, but with the full `contacts` scope (not
readonly) and a per-account token, so it can actually reset a distribution group.
Raf's "AT&T Fiber Owners" list lives in raffi127's contacts; the reporting distros
live in alphaletereporting's — so token path is keyed by account.

    # one-time interactive consent (opens a browser — sign in as the account shown):
    python -m automations.fiber_owners_distro.contacts_write --authorize --account raffi127@gmail.com

    # smoke test after authorizing (lists a group, no writes):
    python -m automations.fiber_owners_distro.contacts_write --account raffi127@gmail.com --list "AT&T Fiber Owners"

Prereqs (GCP project rafael-crm): People API enabled (already is) and, while the
OAuth consent screen is in "Testing", the account must be a Test User. The scope
requested is sensitive ("See, edit, download, and permanently delete your
contacts") — you'll get an "unverified app" screen; a test user can approve it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

WRITE_SCOPES = ["https://www.googleapis.com/auth/contacts"]
_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"          # reuse existing desktop client


def token_path(account: str) -> Path:
    local = account.split("@")[0].replace(".", "_")
    return _CONFIG_DIR / f"contacts-rw-token-{local}.json"


def authorize(account: str) -> None:
    """One-time interactive OAuth flow (read-write contacts) → saves a token."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(f"OAuth client not found at {OAUTH_CLIENT_PATH}.")
    flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT_PATH), WRITE_SCOPES)
    creds = flow.run_local_server(
        port=0,
        login_hint=account,
        prompt="select_account consent",
        authorization_prompt_message=(
            "Opening your browser to authorize Contacts (read + WRITE).\n"
            f"➡  Sign in as {account} and approve.\n"
            "If it doesn't open, copy this URL into your browser:\n{url}"),
        success_message="Done — close this tab and return to the terminal.",
    )
    granted = set(creds.scopes or [])
    if not granted.issuperset(WRITE_SCOPES):
        raise RuntimeError(
            f"Authorization came back without the write scope (got {granted or 'none'}). "
            "Re-run and approve the Contacts (edit) permission.")
    tp = token_path(account)
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(creds.to_json(), encoding="utf-8")
    print(f"✓ Saved read-write contacts token for {account} → {tp}")
    print("  Scopes:", ", ".join(sorted(granted)))


def load_credentials(account: str):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    tp = token_path(account)
    if not tp.exists():
        raise RuntimeError(
            f"No read-write contacts token for {account} at {tp}. Run:\n"
            f"  python -m automations.fiber_owners_distro.contacts_write "
            f"--authorize --account {account}")
    creds = Credentials.from_authorized_user_file(str(tp), WRITE_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(f"Token for {account} invalid/expired — re-authorize.")
    return creds


def _service(account: str):
    from googleapiclient.discovery import build
    return build("people", "v1", credentials=load_credentials(account),
                 cache_discovery=False)


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def find_group(svc, name: str) -> Optional[dict]:
    token = None
    while True:
        resp = svc.contactGroups().list(pageSize=200, pageToken=token).execute()
        for g in resp.get("contactGroups", []) or []:
            if _norm(g.get("formattedName") or g.get("name")) == _norm(name):
                return g
        token = resp.get("nextPageToken")
        if not token:
            return None


def group_member_emails(svc, group: dict) -> Dict[str, str]:
    """email(lower) -> person resourceName, for current group members."""
    full = svc.contactGroups().get(
        resourceName=group["resourceName"], maxMembers=1000).execute()
    rns = full.get("memberResourceNames", []) or []
    out: Dict[str, str] = {}
    for i in range(0, len(rns), 200):
        resp = svc.people().getBatchGet(
            resourceNames=rns[i:i + 200], personFields="emailAddresses").execute()
        for r in resp.get("responses", []):
            person = r.get("person", {})
            rn = person.get("resourceName")
            for e in (person.get("emailAddresses") or []):
                val = _norm(e.get("value"))
                if val and rn:
                    out.setdefault(val, rn)
    return out


def group_members_full(svc, group: dict) -> List[dict]:
    """One entry PER PERSON in the group: {resourceName, name, emails:[lower...]}.
    Group membership is per-person, so all sync decisions must be person-level —
    an owner can carry old + new addresses on a single contact."""
    full = svc.contactGroups().get(
        resourceName=group["resourceName"], maxMembers=1000).execute()
    rns = full.get("memberResourceNames", []) or []
    out: List[dict] = []
    for i in range(0, len(rns), 200):
        resp = svc.people().getBatchGet(
            resourceNames=rns[i:i + 200],
            personFields="names,emailAddresses").execute()
        for r in resp.get("responses", []):
            p = r.get("person", {})
            emails = [_norm(e.get("value")) for e in (p.get("emailAddresses") or [])
                      if e.get("value")]
            out.append({
                "resourceName": p.get("resourceName"),
                "name": (p.get("names") or [{}])[0].get("displayName", ""),
                "emails": emails,
            })
    return out


def _chunks(seq, n=500):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def apply_adds(svc, group: dict, adds: List[Tuple[str, str]]) -> List[str]:
    """Add (email, name) people to the group, creating contacts as needed.
    Returns the list of emails for which a new contact was created."""
    created: List[str] = []
    rns: List[str] = []
    for email_, name in adds:
        rn = _find_contact_by_email(svc, email_)
        if rn is None:
            rn = _create_contact(svc, name, email_)
            created.append(email_)
        rns.append(rn)
    for chunk in _chunks(rns):
        svc.contactGroups().members().modify(
            resourceName=group["resourceName"],
            body={"resourceNamesToAdd": chunk}).execute()
    return created


def remove_members(svc, group: dict, members: List[dict]) -> None:
    """Remove given member dicts (from plan_sync) FROM THE GROUP (contacts kept)."""
    rns = [m["resourceName"] for m in members if m.get("resourceName")]
    for chunk in _chunks(rns):
        svc.contactGroups().members().modify(
            resourceName=group["resourceName"],
            body={"resourceNamesToRemove": chunk}).execute()


def plan_sync(svc, group: dict, target: List[Tuple[str, str]],
              protect: Optional[List[str]] = None) -> dict:
    """Person-centric diff, split for the Slack safety net. Returns:
      add:             [(email, name)] target addresses not covered by any member
      true_departures: [member dict]   people leaving with NO other staying contact
      stale_duplicates:[member dict]   off-roster contacts of someone who STAYS
      protected:       [member dict]   kept though off-target (still a current owner)
    Removing a stale_duplicate never drops the person (they stay via another contact);
    only true_departures are the "did they leave?" list worth announcing.
    """
    from automations.fiber_owners_distro.roster import canonical
    members = group_members_full(svc, group)
    tgt_by_canon = {canonical(e): (e, n) for e, n in target}
    protected = {canonical(e) for e in (protect or [])}
    keep_canon = set(tgt_by_canon) | protected
    covered = {canonical(e) for m in members for e in m["emails"]}

    def stays(m):
        return any(canonical(e) in keep_canon for e in m["emails"])

    staying_names = {(_norm(m["name"])) for m in members if stays(m) and m["name"]}
    removing = [m for m in members if not stays(m)]
    stale = [m for m in removing if _norm(m["name"]) in staying_names]
    departures = [m for m in removing if _norm(m["name"]) not in staying_names]
    protected_members = [m for m in members if stays(m)
                         and not any(canonical(e) in tgt_by_canon for e in m["emails"])]
    add = sorted(tgt_by_canon[c][0] for c in set(tgt_by_canon) - covered)
    return {"add": [(e, tgt_by_canon[canonical(e)][1]) for e in add],
            "true_departures": departures, "stale_duplicates": stale,
            "protected": protected_members}


def _find_contact_by_email(svc, email_: str) -> Optional[str]:
    """resourceName of an existing contact with this email, else None."""
    svc.people().searchContacts(query=email_, readMask="emailAddresses",
                                pageSize=10).execute()  # warm-up (API requirement)
    resp = svc.people().searchContacts(
        query=email_, readMask="emailAddresses", pageSize=10).execute()
    for r in resp.get("results", []):
        person = r.get("person", {})
        for e in (person.get("emailAddresses") or []):
            if _norm(e.get("value")) == _norm(email_):
                return person.get("resourceName")
    return None


def _create_contact(svc, name: str, email_: str) -> str:
    body = {"names": [{"givenName": name or email_}],
            "emailAddresses": [{"value": email_}]}
    person = svc.people().createContact(body=body).execute()
    return person["resourceName"]


def sync_group(account: str, group_name: str,
               target: List[Tuple[str, str]],  # (email, display_name)
               dry_run: bool = True,
               create_group_if_missing: bool = False,
               protect: Optional[List[str]] = None) -> dict:
    """Reset `group_name` in `account` to exactly `target` (plus any `protect`ed
    members that are already in the group).

    Returns a report dict. When dry_run, computes adds/removes but writes nothing.
    Removing a member only removes them FROM THE GROUP — the contact is not deleted.
    `protect` = addresses to NEVER remove even if they're not on the roster (internal
    team, captains, alt emails).
    """
    svc = _service(account)
    grp = find_group(svc, group_name)
    if grp is None:
        if not create_group_if_missing:
            raise RuntimeError(
                f"Group {group_name!r} not found in {account}. Create it first, or "
                "pass create_group_if_missing=True.")
        if not dry_run:
            grp = svc.contactGroups().create(
                body={"contactGroup": {"name": group_name}}).execute()

    from automations.fiber_owners_distro.roster import canonical

    members = group_members_full(svc, grp) if grp else []
    tgt_by_canon = {canonical(e): (e, n) for e, n in target}
    protected = {canonical(e) for e in (protect or [])}
    keep_canon = set(tgt_by_canon) | protected      # a person survives on ANY of these
    covered = {canonical(e) for m in members for e in m["emails"]}

    # PERSON-CENTRIC removals: drop a person only if NONE of their addresses is on
    # the roster target or protected. Prevents removing an owner who keeps an old +
    # a current address on one contact.
    remove_people = [m for m in members
                     if not any(canonical(e) in keep_canon for e in m["emails"])]
    protected_people = [m for m in members
                        if any(canonical(e) in protected for e in m["emails"])
                        and not any(canonical(e) in tgt_by_canon for e in m["emails"])]

    # ADDs: target addresses not already covered by any current person's emails.
    to_add = sorted(tgt_by_canon[c][0] for c in set(tgt_by_canon) - covered)

    report = {"account": account, "group": group_name, "dry_run": dry_run,
              "current": len(members), "target": len(tgt_by_canon),
              "add": to_add,
              "remove": sorted(f"{m['name']} <{','.join(m['emails'])}>"
                               for m in remove_people),
              "created_contacts": [],
              "protected_kept": sorted(m["name"] for m in protected_people)}
    if dry_run:
        return report

    # resolve/create resourceNames for adds
    add_rns: List[str] = []
    for em in to_add:
        rn = _find_contact_by_email(svc, em)
        if rn is None:
            name = tgt_by_canon[canonical(em)][1]
            rn = _create_contact(svc, name, em)
            report["created_contacts"].append(em)
        add_rns.append(rn)
    remove_rns = [m["resourceName"] for m in remove_people]

    # members.modify caps at 1000 resource names per call
    def _chunked(seq, n=500):
        for i in range(0, len(seq), n):
            yield seq[i:i + n]

    for chunk in _chunked(add_rns):
        svc.contactGroups().members().modify(
            resourceName=grp["resourceName"],
            body={"resourceNamesToAdd": chunk}).execute()
    for chunk in _chunked(remove_rns):
        svc.contactGroups().members().modify(
            resourceName=grp["resourceName"],
            body={"resourceNamesToRemove": chunk}).execute()
    return report


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Read-write Contacts auth / smoke test.")
    ap.add_argument("--account", required=True, help="Google account to authorize.")
    ap.add_argument("--authorize", action="store_true",
                    help="Run the one-time interactive OAuth consent.")
    ap.add_argument("--list", metavar="GROUP",
                    help="List a group's current members (smoke test, no writes).")
    a = ap.parse_args(argv)
    if a.authorize:
        authorize(a.account)
        return 0
    if a.list:
        svc = _service(a.account)
        grp = find_group(svc, a.list)
        if grp is None:
            print(f"group {a.list!r} not found in {a.account}")
            return 1
        emails = group_member_emails(svc, grp)
        print(f"{a.list!r} in {a.account}: {len(emails)} member(s)")
        for e in sorted(emails):
            print("  ", e)
        return 0
    ap.error("nothing to do — pass --authorize or --list")


if __name__ == "__main__":
    sys.exit(main())
