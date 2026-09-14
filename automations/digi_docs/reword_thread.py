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
    ap.add_argument("--collapse", action="store_true",
                    help="ONE summary carrying every name and the instruction "
                         "once, and every other post shrunk to a single line. "
                         "For a thread that has already flooded.")
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
    if args.collapse:
        return _collapse(client, sp, parent, tags, live=args.live)
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




def _refusals(client, sp, parent):
    """Every per-person refusal post in the thread, oldest first."""
    out, cursor = [], None
    while True:
        resp = client.conversations_replies(channel=sp.CHANNEL, ts=parent,
                                            limit=200, cursor=cursor)
        for m in resp["messages"]:
            text = m.get("text") or ""
            if not text.startswith("*Digi Docs —"):
                continue
            bullets = [l for l in text.split("\n") if l.startswith("• ")]
            if not bullets:
                continue
            line = html.unescape(bullets[0][2:])
            out.append((m["ts"], line, sp.headline_and_need(line)))
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return out


def _collapse(client, sp, parent, tags, *, live: bool) -> int:
    """One readable post, and no wall.

    Megan 2026-09-14, looking at thirty-six paragraphs: "this is insane --
    there's a million things, no one will know what to do or read that."

    She is right, and re-wording each post made it worse: the ask is 60 words
    and it went onto every one of them. The instruction is the SAME for
    everybody, so it belongs in ONE place with the names under it. The
    remaining posts shrink to a single line each and drop their tags -- the
    people who have to act are pinged once, at the top, not once per name.

    Nothing is deleted. A post that has already been read stays where the
    reader left it, just smaller.
    """
    posts = _refusals(client, sp, parent)
    if not posts:
        print("no refusal posts in this thread")
        return 0

    first_of = {}
    for ts, line, (head, _need) in posts:
        who = line.split(":", 1)[0].strip()
        first_of.setdefault((who, head), (ts, line))

    by_head = {}
    for (who, head), (_ts, line) in first_of.items():
        by_head.setdefault(head, []).append(who)

    summary_ts = posts[0][0]
    blocks = []
    for head, whos in by_head.items():
        _h, need = sp.headline_and_need(
            first_of[(whos[0], head)][1])
        blocks.append("*{}* ({})\n{}\n{}".format(
            head.replace("Digi Docs — ", "").capitalize(), len(whos),
            "\n".join("   • " + w for w in sorted(whos)), need))
    body = ("*🗂️ Digi Docs — {} new start(s) are blocked*\n\n".format(
        len(first_of)) + "\n\n".join(blocks) + "\n" + tags)

    print("--- summary post ({}) ---\n{}\n".format(summary_ts, body))
    if live:
        client.chat_update(channel=sp.CHANNEL, ts=summary_ts, text=body)

    shrunk = 0
    for ts, line, (head, _need) in posts:
        if ts == summary_ts:
            continue
        who = line.split(":", 1)[0].strip()
        short = "• {} — {}".format(
            who, "needs adding in OwnerVille" if "adding" in head
            else head.replace("Digi Docs — ", ""))
        shrunk += 1
        if live:
            try:
                client.chat_update(channel=sp.CHANNEL, ts=ts, text=short)
            except Exception as e:                          # noqa: BLE001
                print("    ⚠ {}: {}".format(type(e).__name__, str(e)[:80]))
                shrunk -= 1

    print("{} post(s) {} to one line; 1 carries the whole ask".format(
        shrunk, "shrunk" if live else "would shrink"))
    if not live:
        print("(dry run — add --live to apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
