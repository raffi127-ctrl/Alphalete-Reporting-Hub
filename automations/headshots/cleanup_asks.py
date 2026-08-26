"""List (and, if YOU confirm, remove) the bot's duplicate "who is it?" asks.

2026-08-25: a broken self-check let the tick ask for a name on every headshot
it had already posted, filling the thread with identical messages. The bug is
fixed (run.py `_is_our_post` + a per-run ask cap); this is the cleanup for the
noise it left behind.

Deliberately narrow. It only ever matches messages that are ALL of:
  * inside the headshot thread it was pointed at,
  * posted by us (bot_id / bot_message / our own user id),
  * carrying the exact ask wording,
  * carrying NO file — a real headshot post can never match.

Run it with no flags first: it prints what it would remove and touches
nothing. Deleting is irreversible, so it needs --confirm, typed by a person.

    python -m automations.headshots.cleanup_asks              # list only
    python -m automations.headshots.cleanup_asks --confirm    # remove them
"""
from __future__ import annotations

import argparse
import sys

ASK_MARKER = "got the photo"          # our ask wording, nothing else uses it


def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def find_asks(cl, channel: str, anchor_ts: str) -> list[dict]:
    me = None
    try:
        me = cl.auth_test().get("user_id")
    except Exception:
        pass
    msgs = cl.conversations_replies(channel=channel, ts=anchor_ts,
                                    limit=1000).get("messages", [])
    out = []
    for m in msgs:
        if m.get("ts") == anchor_ts:
            continue
        if m.get("files"):                      # never touch a photo post
            continue
        ours = (m.get("bot_id") or m.get("subtype") == "bot_message"
                or (me and m.get("user") == me))
        if ours and ASK_MARKER in (m.get("text") or ""):
            out.append(m)
    return out


def main(argv=None) -> int:
    from automations.headshots import weekly_thread as wt
    ap = argparse.ArgumentParser(
        description="Clean up the bot's duplicate name-asks in a thread.")
    ap.add_argument("--channel", default=wt.CHANNEL_ID)
    ap.add_argument("--thread", default=None,
                    help="thread ts (default: this week's headshot thread)")
    ap.add_argument("--confirm", action="store_true",
                    help="actually remove them — irreversible")
    args = ap.parse_args(argv)

    cl = _client()
    anchor_ts = args.thread
    if not anchor_ts:
        a = wt.find_week_anchor(cl, args.channel)
        if not a:
            print("No headshot thread found this week — pass --thread <ts>.")
            return 1
        anchor_ts = a["ts"]

    asks = find_asks(cl, args.channel, anchor_ts)
    if not asks:
        print("Nothing to clean up — no duplicate asks in that thread.")
        return 0
    print(f"{len(asks)} duplicate ask(s) in thread {anchor_ts}:")
    for m in asks[:5]:
        print(f"  {m['ts']}  {(m.get('text') or '')[:70]}…")
    if len(asks) > 5:
        print(f"  … and {len(asks) - 5} more, all identical")
    if not args.confirm:
        print("\nListed only — nothing removed. Re-run with --confirm to "
              "remove them (cannot be undone).")
        return 0

    gone = failed = 0
    for m in asks:
        try:
            cl.chat_delete(channel=args.channel, ts=m["ts"])
            gone += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            if failed == 1:
                print(f"  couldn't remove {m['ts']}: {type(e).__name__}: "
                      f"{str(e)[:120]}")
    print(f"removed {gone}; {failed} could not be removed"
          if failed else f"removed {gone}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
