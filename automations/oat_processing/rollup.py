"""ONE to-do thread for a set of offices that share a Slack channel.

WHY THIS EXISTS: the daily "who needs a hand" post (summary.post_nophone_report)
is per OFFICE — one parent + one reply in that office's own channel. That is
right for Carlos, Atef and Khalil, who each have their own channel. Raf does
not: he owns THREE ApplicantStream streams and one recruiting channel, so the
per-office post would open three parents a day in the same channel and leave
whoever reads it to add them up.

Megan, 2026-09-18: "we just need to have a general overview post and then in the
thread break down each account and what is needed in it." So:

    PARENT   ONE line: the group's totals for the day, nothing else
    REPLY    one per stream, in POST_GROUPS order, each using the SAME
             account-grouped format Carlos's post uses (summary.render_section)

The parent carried a per-stream bullet block until 2026-09-20, when Raf asked
for "a cleaner thread" — those counts are already in the replies, so repeating
them above the fold was noise in the channel.

Re-running the same day does NOT add a second thread or a second set of replies:
the parent's counts are refreshed in place and each stream's existing reply is
rewritten, so the noon thread is what the 4 PM pass updates. A stream that had
no reply yet (it was empty at noon, or is new) gets one added.

    python -m automations.oat_processing.rollup --group raf --dry-run
    python -m automations.oat_processing.rollup --group raf

Reads each office's own flagged snapshot (output/oat-flagged-<date><suffix>.json,
written by that office's last COMPLETE walk) — never a cumulative log, so the
list is the queue as it stands now. An office whose walk has not written one
today is reported as such rather than shown as zero: "no walk yet today" and a
silent 0 look identical to a reader, and only one of them means there is
nothing to do.
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

import argparse
import datetime as dt

from automations.applicant_push import offices
from automations.oat_processing import summary


def _office_snapshot(office_id: str) -> dict:
    """This office's current flagged queue: {nophone: [...], retext: [...]}.

    activate() is what points config.FILE_SUFFIX (and everything else) at the
    office, so the snapshot has to be read THROUGH it — reading the path by hand
    is how one stream ends up showing another stream's names.
    """
    offices.activate(office_id)
    return summary._load_flagged_snapshot(dt.date.today()) or {}


def _counts(snap: dict):
    return (summary._entries_of(snap.get("nophone")),
            summary._entries_of(snap.get("retext")))


def build(group_name: str, date: dt.date = None) -> dict:
    """Compose the overview parent and one reply per stream. No Slack, no I/O
    beyond the snapshots — so the wording can be tested and previewed."""
    date = date or dt.date.today()
    g = offices.group(group_name)
    date_str = date.strftime("%a, %b ") + str(date.day)

    streams, tot_num, tot_txt, missing = [], 0, 0, []
    for oid in g["offices"]:
        o = offices.get(oid)
        snap = _office_snapshot(oid)
        no_number, needs_text = _counts(snap)
        # An EMPTY snapshot is not the same as an empty queue — see the module
        # docstring. `queue_total` is written by every complete walk, so its
        # absence means no walk has written today.
        walked = bool(snap)
        tot_num += len(no_number)
        tot_txt += len(needs_text)
        if not walked:
            missing.append(o["short"])
        streams.append({
            "office_id": oid,
            "name": o["label"].split("—", 1)[-1].strip(),
            "short": o["short"],
            "walked": walked,
            "no_number": no_number,
            "needs_text": needs_text,
            "queue_total": snap.get("queue_total"),
        })

    # THE PARENT IS ONE LINE (Raf, 2026-09-20: "I don't like all these words and
    # clutters, can we make this a cleaner thread please"). It used to repeat a
    # per-stream bullet block — counts that the thread's own replies already
    # carry, one per stream, right underneath. In the channel you now see the
    # total and nothing else; open the thread for who and where.
    parent = ("\U0001F4CB %s — %s's recruiting to-do: %d need a number, "
              "%d need a manual text" % (date_str, g["short"], tot_num, tot_txt))
    if missing:
        # The ONE thing a reader cannot infer from a total: that a stream is not
        # in it. Kept to a short clause rather than its own paragraph — a total
        # that silently omits a stream is the understated-backlog failure again,
        # and "13 need a number" must not read as the whole picture when it is
        # only two of the three streams.
        parent += (" · %d of %d streams (the rest have not walked yet)"
                   % (len(streams) - len(missing), len(streams)))

    replies = []
    for st in streams:
        if not st["walked"]:
            body = ("*%s*\nNo walk has finished for this stream today, so there "
                    "is nothing to list yet." % st["name"])
        elif not st["no_number"] and not st["needs_text"]:
            body = "*%s*\nNothing needs a hand here today ✅" % st["name"]
        else:
            # Only the buckets that HAVE someone in them. A reply that says
            # "0 — (none today ✅)" under a list of real names is the clutter Raf
            # objected to, and it is not information: a bucket with nobody in it
            # asks nothing of the reader. When BOTH are empty the branch above
            # already says so in one line, so nothing is ever silently dropped.
            parts = ["*%s*" % st["name"]]
            if st["no_number"]:
                parts.append(summary.render_section(
                    "\U0001F4DE Need a number pulled from Indeed",
                    st["no_number"]))
            if st["needs_text"]:
                parts.append(summary.render_section(
                    "\U0001F4AC Need a manual text (thread too old to see)",
                    st["needs_text"]))
            body = "\n".join(parts[:1]) + "\n" + "\n\n".join(parts[1:])
        replies.append({"office_id": st["office_id"], "text": body})

    return {"channel": g["channel"], "parent": parent, "replies": replies,
            "no_number": tot_num, "needs_text": tot_txt, "streams": streams,
            "date_str": date_str, "group": group_name}


def _find_parent(c, channel: str, date_str: str, short: str):
    """Today's overview parent in this channel, or None. Matches on the group's
    own header text so it can never adopt an office's per-office parent (they
    read 'recruiting to-do' too) posted into the same channel."""
    want = "%s's recruiting to-do" % short
    try:
        hist = c.conversations_history(channel=channel, limit=60)
    except Exception:  # noqa: BLE001
        return None
    for m in hist.get("messages", []):
        txt = m.get("text") or ""
        if want in txt and date_str in txt:
            return m.get("ts")
    return None


def post(group_name: str, dry_run: bool = True) -> dict:
    built = build(group_name)
    ch = built["channel"]

    # A DAY NOTHING WAS WALKED POSTS NOTHING (the rule summary.py learned on
    # 2026-09-04, pinned by test_no_walk_no_post). Inside the weekend quiet
    # window — Fri 1PM -> Sun 1PM CST — or behind a wedged session, no stream
    # writes a snapshot, every bucket reads empty, and a thread saying
    # "0 need a number ✅" tells Raf his queue is clear when it simply was not
    # looked at. Note the test is ANY stream, not all: once one has walked, the
    # thread is worth posting and the others say "no walk yet today" for
    # themselves.
    if not any(st["walked"] for st in built["streams"]):
        print("[rollup] no stream has a walk snapshot for %s — posting NOTHING "
              "(an unwalked day is not an empty queue)" % built["date_str"],
              flush=True)
        return {"ok": True, "skipped": "no walk today",
                "no_number": 0, "needs_text": 0}

    if dry_run:
        print("[rollup] DRY-RUN — would post to %s (%s), nothing sent:"
              % (ch, group_name), flush=True)
        print("\n  PARENT:\n    " + built["parent"].replace("\n", "\n    "),
              flush=True)
        for r in built["replies"]:
            print("\n  REPLY (office %s):\n    " % r["office_id"]
                  + r["text"].replace("\n", "\n    "), flush=True)
        return {"ok": True, "dry_run": True, **{k: built[k]
                                                for k in ("no_number", "needs_text")}}

    from automations.shared import slack_metrics_post as smp
    c = smp._client()
    parent_ts = _find_parent(c, ch, built["date_str"],
                             offices.group(group_name)["short"])
    if parent_ts is None:
        parent_ts = c.chat_postMessage(channel=ch, text=built["parent"])["ts"]
        print("[rollup] opened today's thread %s" % parent_ts, flush=True)
    else:
        # Best-effort but NOT silent: the parent is the half everyone reads in
        # the channel, and a refresh that failed used to look exactly like one
        # that worked (the lesson summary.py learned on 2026-09-13).
        try:
            c.chat_update(channel=ch, ts=parent_ts, text=built["parent"])
            print("[rollup] refreshed the overview on %s" % parent_ts, flush=True)
        except Exception as e:  # noqa: BLE001
            print("[rollup] WARN overview refresh FAILED on %s: %s: %s"
                  % (parent_ts, type(e).__name__, e), flush=True)

    # One reply per stream, rewritten in place on later passes. Each reply is
    # identified by its own bold stream title, so the 4 PM pass updates the noon
    # reply instead of stacking a second copy under it.
    try:
        existing = c.conversations_replies(channel=ch, ts=parent_ts).get("messages", [])
    except Exception as e:  # noqa: BLE001
        print("[rollup] could not read the thread (%s) — adding replies fresh" % e,
              flush=True)
        existing = []
    by_title = {}
    for m in existing:
        if m.get("ts") == parent_ts:
            continue
        first = (m.get("text") or "").split("\n", 1)[0].strip()
        if first:
            by_title[first] = m.get("ts")

    added = updated = 0
    for r in built["replies"]:
        title = r["text"].split("\n", 1)[0].strip()
        ts = by_title.get(title)
        if ts:
            try:
                c.chat_update(channel=ch, ts=ts, text=r["text"])
                updated += 1
            except Exception as e:  # noqa: BLE001
                print("[rollup] WARN update failed for %s: %s" % (title, e), flush=True)
        else:
            try:
                c.chat_postMessage(channel=ch, thread_ts=parent_ts, text=r["text"])
                added += 1
            except Exception as e:  # noqa: BLE001
                print("[rollup] WARN reply failed for %s: %s" % (title, e), flush=True)

    print("[rollup] %s: %d need a number, %d need a manual text "
          "(%d replies added, %d updated, thread %s)"
          % (group_name, built["no_number"], built["needs_text"],
             added, updated, parent_ts), flush=True)
    return {"ok": True, "thread_ts": parent_ts, "added": added,
            "updated": updated, "no_number": built["no_number"],
            "needs_text": built["needs_text"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Post ONE to-do thread (overview + a reply per stream) for a "
                    "group of offices that share a Slack channel")
    p.add_argument("--group", default="raf", choices=sorted(offices.POST_GROUPS),
                   help="which post group (default: %(default)s)")
    # Dry-run is the DEFAULT here, as it is everywhere else in this package: the
    # post names real applicants in a real channel.
    p.add_argument("--post", action="store_true",
                   help="actually post (default: print what would be posted)")
    a = p.parse_args(argv)
    res = post(a.group, dry_run=not a.post)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
