"""Terminated Reps — SALES BOARD → tracker → Lucy's weekly DM to Evelyn.

Runs once a day. Three steps, in order:

  1. READ the current 'Sales Board WE <m>.<d>' tab of the Alphalete SALES
     BOARD 2025 — BOTH the roster at the top (terminated = a filled
     'Termination Date') and the 'New Starts/Raf' box at the bottom
     (terminated = the first weekday cell reading 'Terminated').
  2. FILE the ones not already there into 'Terminated Reps' on the Raf
     tracker: Rep Name, Lead Rep (always Raf), # Days Worked as the board's
     own formula computes it, Termination Date, Year. Ownerville and Slack
     Deact stay UNTICKED — those are Eve's manual checks.
  3. POST the day's terminations in #revision-emails, as a reply inside that
     week's 'Terminated Reps WE <m>.<d>' thread. Nobody terminated → nothing
     posted. Step 3 reads the BOARD, not step 2's result, so a rep Eve already
     filed by hand still shows up in the day's post.

Dated in CENTRAL time, not the machine clock: this is a Texas office and the
mini and Eve's box are in different zones, so a late-evening UTC run would
otherwise file a Wednesday termination under Thursday.
[[project_central-time-for-texas-reports]]

WRITE TARGETS — safe by default, in the order you'll use them:
  python -m automations.terminated_reps.run                  # preview, writes nothing
  python -m automations.terminated_reps.run --sandbox        # writes to a DUPLICATE tab
  python -m automations.terminated_reps.run --sandbox --post # + really DMs Evelyn
  python -m automations.terminated_reps.run --real --i-mean-it --post   # live

Exit 0 = ran (whether or not anything was terminated). Exit 1 = it could not
read the board or could not write, i.e. a day's terminations may be missing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.terminated_reps import board, slack_post, tracker

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from zoneinfo import ZoneInfo
    CENTRAL = ZoneInfo("America/Chicago")
except Exception:                                               # noqa: BLE001
    CENTRAL = None


def today_central() -> dt.date:
    return (dt.datetime.now(CENTRAL) if CENTRAL else dt.datetime.now()).date()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sandbox", action="store_true",
                    help="write to a DUPLICATE of the 'Terminated Reps' tab "
                         "(created once, then reused). The default while building.")
    ap.add_argument("--fresh-sandbox", dest="fresh_sandbox", action="store_true",
                    help="re-copy the sandbox tab from the real one first, so "
                         "a test starts clean")
    ap.add_argument("--real", action="store_true",
                    help="write to the REAL tracker (needs --i-mean-it too)")
    ap.add_argument("--i-mean-it", dest="i_mean_it", action="store_true",
                    help="confirms --real")
    ap.add_argument("--post", action="store_true",
                    help="actually send the Slack DM (default: print it only)")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="run as if today were this date (backfill / testing)")
    ap.add_argument("--tab", default=None,
                    help="read a specific week tab, e.g. '8.2' or the full "
                         "tab name (default: the week covering --date/today)")
    ap.add_argument("--channel", default=slack_post.CHANNEL,
                    help="Slack channel id to post in (default: "
                         "#revision-emails)")
    args = ap.parse_args(argv)

    if args.real and not args.i_mean_it:
        print("--real needs --i-mean-it as well. Nothing written.")
        return 1

    today = dt.date.fromisoformat(args.date) if args.date else today_central()
    print(f"Terminated Reps — {today.isoformat()} "
          f"(week ending {board.week_sunday(today).isoformat()})")

    # 1 — read the board.
    try:
        rows, tab = board.scan(today, tab=args.tab)
    except Exception as e:                                      # noqa: BLE001
        print(f"❌ couldn't read the SALES BOARD: {type(e).__name__}: {e}")
        return 1

    # Nobody is terminated tomorrow. A row can date into the future when the
    # board is marked for a day the offset then pushes past today (Karla Lopez,
    # marked 2026-08-07, computed 08-08) — filing it would put a future date on
    # the tracker, and CLAMPING it to today would be worse: tomorrow's run would
    # compute the real date, not match the clamped row, and file her twice. So
    # hold it back and let tomorrow's run file it properly.
    future = [t for t in rows if t.term_date > today]
    if future:
        rows = [t for t in rows if t.term_date <= today]
        print(f"  holding {len(future)} row(s) dated after today — "
              f"tomorrow's run files them:")
        for t in future:
            print(f"     {t.term_date.isoformat()}  {t.name}  ({t.source})")

    # 2 — file them.
    sheet_id, tab, dry = tracker.TRACKER_SHEET_ID, tracker.TAB, True
    if args.real:
        dry = False
    elif args.sandbox:
        from automations.terminated_reps import sandbox
        tab, dry = sandbox.ensure(refresh=args.fresh_sandbox), False
    else:
        print("  (preview — no writes. Add --sandbox to write to a duplicate "
              "tab, or --real --i-mean-it to write for real.)")
    print(f"  target: {tab!r}"
          f"{' — THE REAL TAB' if args.real else ''}")
    try:
        result = tracker.append(rows, sheet_id=sheet_id, tab=tab, dry_run=dry)
    except Exception as e:                                      # noqa: BLE001
        print(f"❌ couldn't write {tracker.TAB!r}: {type(e).__name__}: {e}")
        return 1

    # 3 — post the day in #revision-emails. It reports what the BOARD says was
    # terminated today, not what this run happened to file: Eve enters rows by
    # hand too, and a rep she'd already entered would otherwise drop out of the
    # day's post. `--post` is independent of the tracker target for the same
    # reason — the post is derived from the board, not from the write.
    try:
        slack_post.post(rows, today, channel=args.channel,
                        dry_run=not args.post)
    except Exception as e:                                      # noqa: BLE001
        # The rows are already filed; a Slack hiccup must not make the run look
        # like the tracker write failed — but it IS a failure, nobody saw the
        # day's terminations.
        print(f"❌ tracker step done, but the Slack post failed: "
              f"{type(e).__name__}: {e}")
        return 1

    print(f"  {result.tab_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
