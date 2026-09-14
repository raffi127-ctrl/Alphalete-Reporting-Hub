"""Re-word today's Digi Docs refusals IN PLACE, in the office thread.

Run:  lucy --machine "Lucy 3" rerun digi_docs_reword_thread          (dry)
      lucy --machine "Lucy 3" rerun digi_docs_reword_thread --live   (applies)

WHY (Megan 2026-09-14, "update/edit the slack post to be correct on what's
needed"). Fifteen people who could not be ADDED to OwnerVille at 11:00 were
announced as "Digi Docs — could not send", ninety minutes before the first
bundle was due, and none of the posts said what the three people tagged
underneath should actually do about it. slack_post.headline_and_need now words
both correctly — but a code fix only reaches the NEXT post, and these are
sitting in front of the office right now.

EDIT, DON'T RE-POST. A second message is a second thing to read and a second
thing to reconcile, in a thread whose whole problem today was volume. Slack does
not notify on an edit either, so nobody is pinged twice about the same person.

IT MUST RUN WHERE THE POSTING IDENTITY IS. chat.update only works for the
identity that wrote the message: these were posted by the Lucy app from Lucy 3,
so running this from a laptop returns `cant_update_message` — not a permission
to widen, just the wrong machine.

It edits existing messages only. It posts nothing, sends nothing, adds nobody.
"""
from __future__ import annotations

import argparse
import html


def main(argv=None) -> int:
    from automations.digi_docs import slack_post as sp
    from automations.shared import slack_metrics_post as smp

    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="actually rewrite. Without it, prints and changes "
                         "nothing.")
    ap.add_argument("--thread-ts", default="",
                    help="a specific thread. Default: today's Digi Docs "
                         "thread, the one the refusals were posted into.")
    args = ap.parse_args(argv)

    parent = args.thread_ts or sp._thread_ts(smp)
    if not parent:
        print("no Digi Docs thread for today — nothing to re-word")
        return 0

    client = smp._client()
    tags = sp._tags()
    cursor, edits, seen = None, 0, 0
    while True:
        resp = client.conversations_replies(channel=sp.CHANNEL, ts=parent,
                                            limit=200, cursor=cursor)
        for m in resp["messages"]:
            text = m.get("text") or ""
            if not text.startswith("*Digi Docs —"):
                continue
            seen += 1
            bullets = [l for l in text.split("\n") if l.startswith("• ")]
            if not bullets:
                continue
            # Slack hands text back HTML-escaped (&lt;id&gt;, RES-AT&amp;T);
            # re-posting that verbatim shows the entities literally.
            line = html.unescape(bullets[0][2:])
            head, need = sp.headline_and_need(line)
            body = f"*{head}*\n• {line}\n"
            if need:
                body += f"{need}\n"
            body = (body + tags).rstrip()
            if body == text:
                continue
            edits += 1
            print(f"  {'edit' if args.live else 'would edit'} {m['ts']}: {head}")
            if args.live:
                try:
                    client.chat_update(channel=sp.CHANNEL, ts=m["ts"],
                                       text=body)
                except Exception as e:                      # noqa: BLE001
                    # One message we cannot touch must not strand the rest.
                    print(f"    ⚠ {type(e).__name__}: {str(e)[:100]}")
                    edits -= 1
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break

    print(f"\n{seen} Digi Docs post(s) in the thread · "
          f"{edits} {'rewritten' if args.live else 'would be rewritten'}")
    if not args.live and edits:
        print("(dry run — re-run with --live to apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
