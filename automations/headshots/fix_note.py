"""Correct a stale OwnerVille line on the bot's own headshot post.

When an upload throws but actually went through (or a retry fixes it), the
thread is left saying "upload didn't go through — please upload this one
manually" about a photo that IS on the profile. Rather than pile another
reply onto a long thread, this EDITS the bot's original post for that person
so the thread reads true (Megan 2026-08-31).

Only ever touches a message that is ALL of: in the headshot thread, posted
by us, and whose first line is "*<Name>* — headshot ready". Only the
OwnerVille line is rewritten; the photo and everything else stay put.

    python -m automations.headshots.fix_note --name "Luis Valenzuela" --dry-run
    python -m automations.headshots.fix_note --name "Luis Valenzuela"
"""
from __future__ import annotations

import argparse
import sys

OK_LINE = "OwnerVille: uploaded to their profile :white_check_mark:"


def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def find_post(cl, channel: str, anchor_ts: str, name: str) -> dict | None:
    """Our own "<Name> — headshot ready" post in the thread."""
    want = f"*{name}* —".lower()
    msgs = cl.conversations_replies(channel=channel, ts=anchor_ts,
                                    limit=1000).get("messages", [])
    for m in msgs:
        if m.get("ts") == anchor_ts:
            continue
        ours = m.get("bot_id") or m.get("subtype") == "bot_message"
        text = (m.get("text") or "")
        if ours and text.lower().startswith(want):
            return m
    return None


def corrected(text: str) -> str:
    """Swap the failure line for the success line, keep everything else."""
    out = []
    for line in text.splitlines():
        low = line.lower()
        if "ownerville" in low and ("didn't go through" in low
                                    or "couldn't find" in low
                                    or "⚠" in line):
            out.append(OK_LINE)
        else:
            out.append(line)
    return "\n".join(out)


def main(argv=None) -> int:
    from automations.headshots import weekly_thread as wt
    ap = argparse.ArgumentParser(description="Fix a stale OV line in-thread.")
    ap.add_argument("--name", required=True)
    ap.add_argument("--channel", default=wt.CHANNEL_ID)
    ap.add_argument("--thread", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cl = _client()
    anchor_ts = args.thread
    if not anchor_ts:
        a = wt.find_week_anchor(cl, args.channel)
        if not a:
            print("no headshot thread this week")
            return 1
        anchor_ts = a["ts"]

    m = find_post(cl, args.channel, anchor_ts, args.name)
    if not m:
        print(f"no post found for {args.name!r} in thread {anchor_ts}")
        return 1
    old = m.get("text") or ""
    new = corrected(old)
    if new == old:
        print(f"{args.name}: nothing to correct — already reads clean")
        return 0
    print(f"--- {args.name} ({m['ts']}) ---\nBEFORE:\n{old}\nAFTER:\n{new}")
    if args.dry_run:
        print("\n(dry run — not edited)")
        return 0
    cl.chat_update(channel=args.channel, ts=m["ts"], text=new)
    print("edited")
    return 0


if __name__ == "__main__":
    sys.exit(main())
