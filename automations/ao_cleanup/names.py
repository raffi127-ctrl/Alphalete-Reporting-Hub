"""Slack user id -> real name / email, for the AO channel cleanup.

`users.list` and `users.info` are BOTH missing_scope on the reporting token
(it has no `users:read`), so this keeps a cache on disk and fills it from
whichever source is actually available:

  1. `--token-file` / SLACK_READ_TOKEN — any token WITH `users:read`. One
     `users.list` call resolves the whole workspace and never has to run again.
  2. `--members-csv` — the member list a workspace admin exports from
     Slack (Settings -> Manage members -> Export). Needs a user-id column.
  3. hand-fed entries via `add()` — what the Claude session uses when it
     resolves a handful of stragglers one at a time.

Nothing here ever guesses a name. An unresolved id stays unresolved and is
written to the sheet as the raw id, so a blank is never mistaken for a person.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = REPO_ROOT / "output" / "ao_slack_users.json"
_ID_KEYS = ("user id", "userid", "user_id", "id", "slack id")
_NAME_KEYS = ("full name", "real name", "name", "display name", "displayname")
_EMAIL_KEYS = ("email", "email address", "primary email")
_USERNAME_KEYS = ("username", "handle", "user name")


def load():
    # type: () -> Dict[str, dict]
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8")).get("users", {})
        except ValueError:
            return {}
    return {}


def save(users):
    # type: (Dict[str, dict]) -> None
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(
        {"_note": "Slack id -> name/email for the AO workspace cleanup. "
                  "Rebuildable; see automations/ao_cleanup/names.py.",
         "users": users}, indent=2, sort_keys=True), encoding="utf-8")


def add(entries):
    # type: (Iterable[dict]) -> int
    """entries: {"id","name","email","username","deleted"} — id + name required."""
    users = load()
    n = 0
    for e in entries:
        uid = (e.get("id") or "").strip()
        if not uid:
            continue
        users[uid] = {
            "name": (e.get("name") or "").strip(),
            "email": (e.get("email") or "").strip(),
            "username": (e.get("username") or "").strip(),
            "deleted": bool(e.get("deleted")),
            "bot": bool(e.get("bot")),
        }
        n += 1
    save(users)
    return n


def from_token(token):
    # type: (str) -> int
    """One users.list sweep. Needs a token WITH users:read."""
    import ssl
    from slack_sdk import WebClient
    client = WebClient(token=token, ssl=ssl._create_unverified_context())
    cursor, found = None, []
    while True:
        resp = client.users_list(limit=200, cursor=cursor)
        for m in resp.get("members", []):
            prof = m.get("profile") or {}
            found.append({
                "id": m.get("id"),
                "name": (prof.get("real_name") or m.get("real_name")
                         or prof.get("display_name") or ""),
                "email": prof.get("email") or "",
                "username": m.get("name") or "",
                "deleted": m.get("deleted"),
                "bot": m.get("is_bot"),
            })
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return add(found)


def from_csv(path):
    # type: (str) -> int
    """A Slack admin member-list export. Column names are matched loosely."""
    def pick(row, keys):
        for k, v in row.items():
            if (k or "").strip().lower() in keys:
                return (v or "").strip()
        return ""

    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    found = []
    for row in rows:
        uid = pick(row, _ID_KEYS)
        if not uid.upper().startswith("U"):
            continue
        found.append({"id": uid, "name": pick(row, _NAME_KEYS),
                      "email": pick(row, _EMAIL_KEYS),
                      "username": pick(row, _USERNAME_KEYS)})
    if not found:
        raise RuntimeError(
            "No user-id column found in %s (looked for %s). Export the member "
            "list from Slack -> Settings -> Manage members." % (path, list(_ID_KEYS)))
    return add(found)


def missing(ids):
    # type: (Iterable[str]) -> List[str]
    users = load()
    return sorted({i for i in ids if i and i not in users})


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fill the Slack id -> name cache")
    ap.add_argument("--token-file", help="file holding a token WITH users:read")
    ap.add_argument("--members-csv", help="Slack admin member-list export")
    ap.add_argument("--missing-from", help="ao_channel_members.json to audit")
    args = ap.parse_args(argv)

    if args.token_file:
        tok = Path(args.token_file).read_text(encoding="utf-8-sig").strip()
        print("users.list -> %d usuarios cacheados" % from_token(tok))
    elif os.environ.get("SLACK_READ_TOKEN"):
        print("users.list -> %d usuarios cacheados"
              % from_token(os.environ["SLACK_READ_TOKEN"]))
    if args.members_csv:
        print("csv -> %d usuarios cacheados" % from_csv(args.members_csv))

    if args.missing_from:
        data = json.loads(Path(args.missing_from).read_text(encoding="utf-8"))
        ids = set()
        for info in data.get("channels", {}).values():
            ids.update(info.get("members", []))
            ids.update(info.get("no_join_event", []))
        gone = missing(ids)
        print("ids totales %d | sin nombre %d" % (len(ids), len(gone)))
        for uid in gone:
            print(uid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
