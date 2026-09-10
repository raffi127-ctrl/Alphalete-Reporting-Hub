"""Who is in the 5 AO channels Eve is cleaning up — replayed from history.

`conversations.members` is the obvious call and it is CLOSED to us: the Slack
token on this machine (Evelyn's xoxp) holds only
identify/channels:history/groups:history/chat:write/files:write/mpim:write/
reactions:write. conversations.list, conversations.members, conversations.info,
users.list and users.info all answer `missing_scope`.

What history CAN do: Slack records every join and leave as an ordinary message
with subtype `channel_join` / `channel_leave`. Paging a channel back to its
creation and replaying those events in order reproduces today's member list.
Verified on #top-leaders-alphalete-org (2026-09-10): 30 pages, 5.868 messages,
reached the 2023-12-01 creation message, 93 joins / 10 leaves.

Two known gaps, both small and both flagged in the output rather than hidden:
  * the channel CREATOR never gets a channel_join event, and neither do members
    carried over when a channel is converted — they show up only if they ever
    left and rejoined.
  * this yields user IDs, not names. Name resolution needs `users:read`
    (see resolve_names.py).

    python -m automations.ao_cleanup.channel_members            # all 5
    python -m automations.ao_cleanup.channel_members --channel l10-alphalete
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = REPO_ROOT / "output" / "ao_channel_members.json"

# The exact five channels on the 'Channel' dropdown of the
# 'AO Workspace Cleanup' tab. Ids are hardcoded because the token cannot look a
# channel up by name (conversations.list is missing_scope) — and an id survives
# a rename, which a name does not.
CHANNELS = [
    ("alphalete-sales", "C068PH3RFSM"),
    ("alphalete-lvl1-chat", "C09JG28CD27"),
    ("l10-alphalete", "C075PCEL92M"),            # a.k.a. #level10-alphalete
    ("top-leaders-alphalete-org", "C067TTGFEFR"),
    ("rafs-office-recruiting-11280", "C0AUAS88FGW"),
]

# Generous: the busiest channel must reach its creation message or the replay is
# incomplete. `reached_start` in the output says whether it did.
MAX_PAGES = 400
PAGE_SLEEP_S = 1.1          # conversations.history is Tier 3 (~50/min)


def replay(client, channel_id, max_pages=MAX_PAGES, sleep_s=PAGE_SLEEP_S,
           progress=None):
    # type: (...) -> dict
    """Page a channel to its creation and fold join/leave into a member set."""
    events = {}       # user id -> (ts, "join"|"leave"), newest wins
    posters = set()   # anyone who ever spoke — a floor on "was really here"
    cursor = None     # type: Optional[str]
    pages = messages = 0
    oldest_ts = None
    reached_start = False

    while pages < max_pages:
        resp = client.conversations_history(channel=channel_id, limit=200,
                                            cursor=cursor)
        batch = resp.get("messages", [])
        pages += 1
        messages += len(batch)
        for msg in batch:
            ts = msg.get("ts")
            oldest_ts = ts or oldest_ts
            uid = msg.get("user")
            subtype = msg.get("subtype")
            if uid and not subtype:
                posters.add(uid)
            if subtype not in ("channel_join", "channel_leave"):
                continue
            if not uid:
                continue
            kind = "join" if subtype == "channel_join" else "leave"
            prev = events.get(uid)
            # history pages come newest-first; the FIRST event seen for a user
            # is their latest, so only overwrite with a strictly newer ts.
            if prev is None or ts > prev[0]:
                events[uid] = (ts, kind)
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if progress:
            progress(pages, messages)
        if not cursor:
            reached_start = True
            break
        time.sleep(sleep_s)

    members = sorted(u for u, (_, kind) in events.items() if kind == "join")
    left = sorted(u for u, (_, kind) in events.items() if kind == "leave")
    # Someone who talked but has no join event predates the scan or was carried
    # in at channel creation. They ARE members unless a leave says otherwise.
    silent_members = sorted(posters - set(events))
    return {
        "channel_id": channel_id,
        "pages": pages,
        "messages": messages,
        "reached_start": reached_start,
        "oldest_ts": oldest_ts,
        "oldest_date": (dt.datetime.fromtimestamp(float(oldest_ts))
                        .strftime("%Y-%m-%d") if oldest_ts else ""),
        "joined": {u: events[u][0] for u in members},
        "members": members,
        "spoke": sorted(posters),   # ever posted here -> not a silent invitee
        "left": left,
        "no_join_event": silent_members,
        "member_count": len(members) + len(silent_members),
    }


def run(channels=None, client=None):
    # type: (...) -> dict
    from automations.shared.slack_metrics_post import _client
    client = client or _client()
    channels = channels or CHANNELS
    out = {"built": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "channels": {}}
    for name, cid in channels:
        print("%-30s ..." % name, end="", flush=True)

        def _p(pages, msgs, _n=name):
            print("\r%-30s %3d pages / %6d msgs" % (_n, pages, msgs),
                  end="", flush=True)

        info = replay(client, cid, progress=_p)
        info["name"] = name
        out["channels"][name] = info
        flag = "" if info["reached_start"] else "  <-- DID NOT REACH START"
        print("\r%-30s %3d pages / %6d msgs -> %4d miembros (back to %s)%s"
              % (name, info["pages"], info["messages"], info["member_count"],
                 info["oldest_date"], flag))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Replay AO channel membership")
    ap.add_argument("--channel", action="append", default=[],
                    help="only this channel name (repeatable)")
    args = ap.parse_args(argv)

    chans = CHANNELS
    if args.channel:
        want = {c.lstrip("#").lower() for c in args.channel}
        chans = [(n, i) for n, i in CHANNELS if n.lower() in want]
        if not chans:
            print("unknown channel; known: %s"
                  % ", ".join(n for n, _ in CHANNELS), file=sys.stderr)
            return 2

    data = run(chans)
    if CACHE_PATH.exists() and len(chans) < len(CHANNELS):
        # a single-channel rerun must not throw away the other four
        old = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        merged = old.get("channels", {})
        merged.update(data["channels"])
        data["channels"] = merged
    everyone = set()
    for info in data["channels"].values():
        everyone.update(info["members"])
        everyone.update(info["no_join_event"])
    data["unique_people"] = len(everyone)
    data["rows_for_tab"] = sum(i["member_count"] for i in data["channels"].values())

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("\npersonas distintas : %d" % data["unique_people"])
    print("filas para la tab  : %d" % data["rows_for_tab"])
    print("guardado en        : %s" % CACHE_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
