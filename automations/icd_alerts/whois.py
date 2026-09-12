"""Find an owner's Slack id, so the 11am nudge can reach them.

  python -m automations.icd_alerts.whois "Kash Rai"
  python -m automations.icd_alerts.whois kash --channel     # search their room

WHY THIS EXISTS RATHER THAN A LOOKUP AT SEND TIME. Resolving a name every time
we need it means a users.list page-through on a workspace this size, which is
rate limited and answered `ratelimited` the first time it ran. Worse, a name
match is a GUESS -- two people share a first name and the nudge goes to the
wrong one, about a machine they do not own. So the id is resolved ONCE, by a
person, and pinned in offices.py.

--channel is the cheap path: search only the members of a room that office
already posts to, which is a few dozen people rather than the whole workspace.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Dict, List

from automations.icd_alerts import offices as O


def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def _describe(u: Dict) -> Dict:
    prof = u.get("profile") or {}
    return {"id": u.get("id"),
            "name": u.get("real_name") or prof.get("real_name") or u.get("name"),
            "handle": u.get("name"),
            "title": prof.get("title") or ""}


def _matches(u: Dict, needles: List[str]) -> bool:
    if u.get("deleted") or u.get("is_bot") or u.get("id") == "USLACKBOT":
        return False
    prof = u.get("profile") or {}
    hay = " ".join(str(x).lower() for x in
                   (u.get("name"), u.get("real_name"), prof.get("real_name"),
                    prof.get("display_name")) if x)
    # ALL the needles, not any. "Kash Rai" against a substring match on 'rai'
    # also finds "Dontrail Adams" -- and since the suggested line takes the
    # FIRST hit, a loose match is how the nudge gets pinned to the wrong
    # person, about a machine they do not own.
    return all(n in hay for n in needles)


def in_channel(channel_id: str, needles: List[str], log=print) -> List[Dict]:
    """Search one room's members. A few dozen users.info calls, not thousands."""
    client = _client()
    members, cursor = [], None
    while True:
        r = client.conversations_members(channel=channel_id, limit=200,
                                         cursor=cursor)
        members.extend(r.get("members", []))
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    log("searching %d member(s)" % len(members))
    out = []
    for uid in members:
        try:
            u = client.users_info(user=uid)["user"]
        except Exception as e:  # noqa: BLE001
            if "ratelimited" in str(e):
                time.sleep(3)
                continue
            continue
        if _matches(u, needles):
            out.append(_describe(u))
    return out


def workspace(needles: List[str], log=print) -> List[Dict]:
    """Page the whole workspace, backing off when Slack says to."""
    client = _client()
    out, cursor, tries = [], None, 0
    while True:
        try:
            r = client.users_list(limit=200, cursor=cursor)
        except Exception as e:  # noqa: BLE001
            if "ratelimited" in str(e) and tries < 4:
                tries += 1
                log("rate limited — waiting %ds" % (20 * tries))
                time.sleep(20 * tries)
                continue
            raise
        for u in r.get("members", []):
            if _matches(u, needles):
                out.append(_describe(u))
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Find an owner's Slack id")
    ap.add_argument("who", help="a name, or an office key like 'kash'")
    ap.add_argument("--channel", action="store_true",
                    help="search only that office's channel members (cheap, "
                         "and avoids the workspace rate limit)")
    args = ap.parse_args(argv)

    office = O.get(args.who)
    name = office.owner if office else args.who
    needles = [w for w in name.lower().split() if len(w) > 2] or [name.lower()]

    if args.channel:
        if not office:
            print("--channel needs an office key, e.g. kash")
            return 1
        from automations.icd_alerts import approve as A
        room = (office.channels[0].name if office.channels
                else _metrics_channel(office.key))
        if not room:
            print("no channel known for %s — search without --channel" % office.key)
            return 1
        ch = A.find_channel(room)
        if not ch:
            print("could not resolve %s" % room)
            return 1
        print("searching %s for %r ..." % (room, name))
        found = in_channel(ch["id"], needles)
    else:
        print("searching the workspace for %r ..." % name)
        found = workspace(needles)

    if not found:
        print("no match. Try Slack directly: click their name, the three "
              "dots, Copy member ID.")
        return 1
    for f in found:
        print("  %s  %-24s @%-18s %s"
              % (f["id"], f["name"], f["handle"], f["title"][:30]))
    if office:
        print()
        print("Pin it in automations/icd_alerts/offices.py:")
        print('    slack_user_id="%s",   # %s' % (found[0]["id"], found[0]["name"]))
    return 0


def _metrics_channel(key: str) -> str:
    """The room office_metrics already posts this office's numbers into --
    the one place their owner is certain to be."""
    try:
        from automations.office_metrics import offices as om
        o = om.OFFICES.get(key)
        return getattr(o, "channel_name", "") if o else ""
    except Exception:  # noqa: BLE001
        return ""


if __name__ == "__main__":
    sys.exit(main())
