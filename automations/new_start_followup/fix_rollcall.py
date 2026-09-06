"""Edit an already-posted roll call IN PLACE so it matches Aisha's screenshot.

Why this exists (2026-08-08): the 8am roll call fell back to the OBCL sheet
because the mini's Slack token can't download files, and tagged three leaders
who had no new start (Bill Hirwa, Anthony Coca, Pranish Shrestha) plus six
inflated counts. Megan: "make sure today's thread is edited to be accurate."

`chat.update`, never a second post — a correction that arrives as a NEW message
leaves two lists in the thread and people answer the wrong one. Slack does not
re-notify on an edit, so removing a phantom @-mention doesn't ping anyone.

TWO MACHINES, because the two halves need different things:

  laptop   can read the screenshot, CANNOT edit Lucy's message (not the author)
  mini     authored the message, CANNOT read the screenshot (no files:read)

So the laptop takes a snapshot, git carries it over, and the mini applies it:

    # on the laptop
    python -m automations.new_start_followup.fix_rollcall --snapshot
    git add automations/new_start_followup/roster_snapshot.json && git push

    # on the mini (via `lucy nsf_fix_rollcall`), dry-run first
    python -m automations.new_start_followup.fix_rollcall --apply
    python -m automations.new_start_followup.fix_rollcall --apply --post

The snapshot holds interviewer -> COUNT only. New-start names never go in it:
this repo is public.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import sys
from pathlib import Path

from automations.new_start_followup import report as report_mod
from automations.new_start_followup import thread as thread_mod
from automations.shared import slack_metrics_post as smp

# Tracked on purpose: git is the only channel to the mini, and output/ is
# gitignored. Safe to commit — interviewer names (already in leaders.json) and
# counts, never a new start's name. Defined in report.py because the normal
# report reads it too, as its stand-in when the screenshot can't be downloaded.
SNAPSHOT_PATH = report_mod.SNAPSHOT_PATH


def take_snapshot(monday: dt.date, path: Path, funnel=None) -> Path:
    """Read the weekly screenshot and write interviewer -> count. Laptop-side."""
    from automations.new_start_followup import screenshot_roster

    funnel = funnel or thread_mod.FUNNELS[0]
    rows = screenshot_roster.fetch_roster_rows(monday.isoformat(),
                                               poster=funnel["poster"])
    # Same filter as the report — declined / failed-background rows don't count
    # (Raf 2026-08-30). Shared helper on purpose: this used to be its own copy
    # of the loop, and a snapshot built on different rules than the roll call
    # is worse than no snapshot.
    owed, dropped_rows = screenshot_roster.owed_counts(rows)
    for line in dropped_rows:
        print("   not counted (declined / failed background): " + line)
    if not owed:
        raise RuntimeError("The screenshot produced no interviewers — refusing "
                           "to write an empty snapshot.")
    src = "{} screenshot".format("Aisha's" if funnel["key"] == "main"
                                 else "Tiffani's")
    body = {
        "_note": ("Roster snapshot for the New-Start roll call ({}), taken "
                  "from the weekly screenshot on a machine that can read it. "
                  "Interviewer -> new-start COUNT only — new-start names must "
                  "never be added, this repo is public.".format(funnel["label"])),
        "monday": monday.isoformat(),
        "source": src,
        "owed": dict(sorted(owed.items(), key=lambda kv: kv[0].lower())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    print("[snapshot] {} new starts across {} interviewers -> {}".format(
        sum(owed.values()), len(owed), path))
    for name in sorted(owed, key=str.lower):
        print("   {:<28} {}".format(name, owed[name]))
    return path


def _find_rollcall(client, friday: dt.date, funnel=None, target="rollcall"):
    """Lucy's roll-call (or checklist) message in this week's thread, or None."""
    funnel = funnel or thread_mod.FUNNELS[0]
    th = thread_mod.read_thread(friday=friday, client=client,
                                poster=funnel["poster"])
    marker = (thread_mod.CHECKLIST_MARKER if target == "checklist"
              else thread_mod.ROLLCALL_MARKER)
    # LAST match, not first: a week can carry more than one checklist if a pass
    # re-ran, and the one people are reading is the latest.
    found = None
    for m in th["replies"]:
        if marker in thread_mod._strip(m.get("text", "")):
            found = m
    return th, found


def apply_fix(monday: dt.date, path: Path, post: bool, funnel=None,
              target: str = "rollcall") -> int:
    funnel = funnel or thread_mod.FUNNELS[0]
    client = smp._client()
    me = client.auth_test()
    print("[identity] this machine is Slack user {} ({})".format(
        me.get("user"), me.get("user_id")))

    friday = monday - dt.timedelta(days=3)
    th, msg = _find_rollcall(client, friday, funnel=funnel, target=target)
    if msg is None:
        print("No {} found in the week-of-{} thread — nothing to fix."
              .format(target, monday.isoformat()), file=sys.stderr)
        return 2

    author = msg.get("user")
    if author != me.get("user_id"):
        # Slack only lets the author edit. Posting instead would leave two
        # competing lists in the thread, so stop and say so rather than
        # improvise.
        print("REFUSING: the roll call was posted by {}, but this machine is {}. "
              "Only the author can chat.update a message. Run this on the "
              "machine that posted it (the mini) — do NOT post a correction as "
              "a new message.".format(author, me.get("user_id")), file=sys.stderr)
        return 3

    # The snapshot bridge exists for a machine that can't read the screenshot.
    # This one may be able to (the mini's token gained files:read), so use the
    # screenshot when there's no snapshot rather than refusing outright — a
    # week-old snapshot is the thing that must never be used, not the absence
    # of one.
    usable_snapshot = path.exists()
    if usable_snapshot:
        # A snapshot for ANOTHER week is worse than none: build() refuses it
        # outright, which killed this correction on 2026-09-06 (Lucy 1 still
        # held the week of 8/24). Check the week here and step over a stale one
        # instead of failing.
        try:
            snap_monday = json.loads(path.read_text(encoding="utf-8")).get("monday")
        except Exception:  # noqa: BLE001
            snap_monday = None
        if snap_monday != monday.isoformat():
            print("[roster] ignoring the snapshot — it's for the week of {}, "
                  "not {}.".format(snap_monday, monday.isoformat()))
            usable_snapshot = False
    if usable_snapshot:
        rec = report_mod.build(monday=monday, client=client, roster_json=path,
                               funnel=funnel)
    else:
        print("[roster] no snapshot at {} — reading the screenshot directly."
              .format(path))
        rec = report_mod.build(monday=monday, client=client, funnel=funnel)
    corrected = (report_mod.render_checklist(rec) if target == "checklist"
                 else report_mod.render_rollcall(rec, tag=funnel["tag"]))
    if not corrected.strip():
        print("The corrected post came out empty — refusing to blank the "
              "posted message.", file=sys.stderr)
        return 2

    old = thread_mod._strip(msg.get("text", ""))
    if old.strip() == corrected.strip():
        print("The posted {} already matches. Nothing to do.".format(target))
        return 0

    print("\n--- BEFORE " + "-" * 55)
    print(old)
    print("\n--- AFTER " + "-" * 56)
    print(corrected)
    print("\n--- CHANGED LINES " + "-" * 48)
    for line in difflib.unified_diff(old.splitlines(), corrected.splitlines(),
                                     lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        print(line)
    print("-" * 66)

    if not post:
        print("\n[dry-run] Message NOT edited. Re-run with --post to apply.")
        return 0

    resp = client.chat_update(channel=th["channel"], ts=msg["ts"], text=corrected)
    print("\n[edited] ts={} in channel {} — same message, no new post.".format(
        resp["ts"], th["channel"]))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Correct an already-posted New-Start roll call in place.")
    ap.add_argument("--snapshot", action="store_true",
                    help="read Aisha's screenshot and write the roster snapshot "
                         "(run on a machine whose Slack token has files:read)")
    ap.add_argument("--apply", action="store_true",
                    help="rebuild from the snapshot and edit the posted roll "
                         "call (run on the machine that posted it)")
    ap.add_argument("--post", action="store_true",
                    help="with --apply, actually edit the message (default: dry-run)")
    ap.add_argument("--monday", help="start-week Monday as YYYY-MM-DD (default: next Monday)")
    ap.add_argument("--funnel", choices=["all", "main", "second"], default="all",
                    help="which funnel to snapshot/fix (--snapshot default: all; "
                         "--apply uses main unless told otherwise)")
    ap.add_argument("--target", choices=["rollcall", "checklist"],
                    default="rollcall",
                    help="which of Lucy's posts to correct in place. "
                         "checklist = the Sunday roll-up")
    ap.add_argument("--path", default="", help="snapshot file path override "
                    "(single-funnel runs only; default: the funnel's own file)")
    args = ap.parse_args(argv)

    from automations.new_start_followup import obcl
    monday = (dt.date.fromisoformat(args.monday) if args.monday
              else obcl.upcoming_monday())

    if args.snapshot:
        funnels = (thread_mod.FUNNELS if args.funnel == "all"
                   else [thread_mod.funnel_by_key(args.funnel)])
        for funnel in funnels:
            path = Path(args.path) if (args.path and len(funnels) == 1) \
                else report_mod.snapshot_path(funnel)
            try:
                take_snapshot(monday, path, funnel=funnel)
            except RuntimeError as exc:
                if funnel["required"]:
                    raise
                # A week with no 2nd-funnel post just means no 2nd-funnel
                # starts — and a stale old snapshot must not linger, or the
                # mini would resurrect it the next week the Mondays line up.
                print("[snapshot] {}: {} — skipping{}".format(
                    funnel["label"], exc,
                    "; removed the stale snapshot" if path.exists() else ""))
                if path.exists():
                    path.unlink()
        return 0
    if args.apply:
        funnel = thread_mod.funnel_by_key(
            "main" if args.funnel == "all" else args.funnel)
        path = Path(args.path) if args.path else report_mod.snapshot_path(funnel)
        return apply_fix(monday, path, args.post, funnel=funnel,
                         target=args.target)
    ap.error("choose --snapshot (laptop) or --apply (the machine that posted it)")


if __name__ == "__main__":
    sys.exit(main())
