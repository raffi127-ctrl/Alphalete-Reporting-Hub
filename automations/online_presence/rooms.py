"""Make the Slack room for an office that asked us to (LucyECO Social sign-up).

Megan 2026-11-08: if the office says "No, please create one for me", we make
a channel in OUR Slack named <company-name>-lucyeco-social -- e.g.
"Palace Acquisitions" -> #palace-acquisitions-lucyeco-social (Megan picked the
dashed form; Slack names are lowercase with no spaces).

WHY HERE AND NOT IN THE FORM. The form runs on Streamlit Cloud with a token
that is a stranger to the workspace (same reason icd_signup hands its Slack
work to Lucy 3). So the form only records "create us one"; this runs on a
Lucy with the real token, creates the room, invites the people, and writes the
Channel ID back onto the sign-up row -- so `setup add --from-signup` picks it
up with nothing typed.

PRIVATE, because the token can only create private channels (groups:write),
and because drafts and review replies waiting for approval belong in a room
the public can't wander into.

ONE ROOM PER SIGN-UP, EVER. A name that's already taken is looked up and
reused (a run that created it but died before writing it back), never
"-2"'d into a second room.

    python -m automations.online_presence.rooms            # dry: says what it would make
    python -m automations.online_presence.rooms --live     # makes them
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Dict, List, Optional

LUCY = "U0BCG8F9B5Z"          # Lucy Reporting (resources/owner-slack-ids.md)
MEGAN = "U04G5HJBGFN"
EVE = "U088E2KJEV8"           # Evelyn Sobrino
HUBPOSTER = "U0BBW3TH5DX"     # @hubposter: the bot with files:read
SUFFIX = "-lucyeco-social"


def channel_name(business: str) -> str:
    """'Palace Acquisitions' -> 'palace-acquisitions-lucyeco-social'.
    Each word becomes lowercase with dashes between; punctuation drops out
    ('M Coast, LLC.' -> 'm-coast-llc-lucyeco-social'). Slack caps names at 80."""
    words = re.findall(r"[a-z0-9]+", (business or "").lower())
    slug = "-".join(words)[: 80 - len(SUFFIX)].strip("-")
    return (slug + SUFFIX) if slug else ""


def _wanted(row: Dict) -> bool:
    return (str(row.get("Slack Room") or "") == "create us one"
            and not str(row.get("Slack Channel") or "").strip())


def _people(row: Dict, cl) -> (List[str], List[str]):
    """WHO GOES IN THE ROOM (Megan 2026-11-08): Eve, Megan, the ICD who
    enrolled, Lucy, and the Lucy Reporting app -- plus @hubposter, the bot
    that opens the photos (without it Lucy can't read a single upload).
    Returns (Slack ids, people we couldn't place -- never guessed)."""
    from automations.online_presence.setup import resolve_person
    ids, missed = [MEGAN, EVE, LUCY, HUBPOSTER], []
    owner = str(row.get("Owner") or "").strip()
    try:
        ids.append(resolve_person(owner, cl))
    except ValueError:
        missed.append(owner or "the ICD (no name on the form)")
    # The 'Lucy' DM app, when its token is on this machine (it is on Lucy 1,
    # not on Megan's laptop): its bot user joins too.
    try:
        from automations.shared import slack_metrics_post as smp
        app = smp._client(smp._load_bot_token()).auth_test().get("user_id")
        if app:
            ids.append(app)
    except Exception:
        pass
    return list(dict.fromkeys(ids)), missed


def _existing(cl, name: str) -> Optional[str]:
    cursor = None
    while True:
        kw = {"types": "private_channel,public_channel", "limit": 500,
              "exclude_archived": True}
        if cursor:
            kw["cursor"] = cursor
        r = cl.conversations_list(**kw)
        for c in r.get("channels") or []:
            if c.get("name") == name:
                return c["id"]
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return None


def make_room(row: Dict, cl, *, live: bool) -> Dict:
    name = channel_name(row.get("Business Name"))
    if not name:
        return {"action": "skipped", "note": "no business name"}
    if not live:
        return {"action": "would_create", "channel": name}
    cid = None
    try:
        cid = cl.conversations_create(name=name, is_private=True)["channel"]["id"]
    except Exception as e:
        if "name_taken" not in str(e):
            return {"action": "create_failed", "channel": name, "error": str(e)[:150]}
        cid = _existing(cl, name)
        if not cid:
            return {"action": "create_failed", "channel": name,
                    "error": "name taken by a channel Lucy can't see"}
    ids, missed = _people(row, cl)
    me = (cl.auth_test() or {}).get("user_id")
    invite = [i for i in ids if i != me]
    try:
        if invite:
            cl.conversations_invite(channel=cid, users=",".join(invite))
    except Exception as e:
        if "already_in_channel" not in str(e):
            missed.append(f"invites failed ({str(e)[:60]})")
    return {"action": "created", "channel": name, "id": cid, "missed": missed}


def _write_back(tab, header: List[str], rownum: int, cid: str) -> None:
    col = header.index("Slack Channel") + 1
    tab.update_cell(rownum, col, cid)
    tab.update_cell(rownum, header.index("Slack Room") + 1, "created")


def run(*, live: bool, cl=None, tab=None) -> List[Dict]:
    from automations.online_presence import signup
    tab = tab or signup._tab(create=False)
    if tab is None:
        return []
    rows = tab.get_all_values()
    if not rows:
        return []
    header, out = rows[0], []
    if "Slack Room" not in header:
        return []
    if cl is None:
        from automations.brand_audit.social_inbox import _client
        cl = _client()
    for i, raw in enumerate(rows[1:], start=2):
        row = dict(zip(header, raw))
        if not _wanted(row):
            continue
        res = make_room(row, cl, live=live)
        res["business"] = row.get("Business Name")
        if res.get("id"):
            _write_back(tab, header, i, res["id"])
        out.append(res)
    return out


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="online_presence.rooms")
    ap.add_argument("--live", action="store_true", help="actually create the rooms")
    a = ap.parse_args(argv)
    res = run(live=a.live)
    if not res:
        print("No sign-ups waiting for a room.")
    for r in res:
        line = f"{r['business']}: {r['action']} #{r.get('channel', '')}"
        if r.get("id"):
            line += f" ({r['id']})"
        if r.get("missed"):
            line += " — invite by hand: " + ", ".join(r["missed"])
        if r.get("error"):
            line += f" — {r['error']}"
        print(line)
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
