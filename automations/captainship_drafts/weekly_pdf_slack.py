"""Post the Weekly Knock Dispositions PDF into the daily 'Metrics for:' thread
in #alphalete-sales — SUNDAYS AND MONDAYS ONLY.

Rafael, in that very thread (2026-09-07 09:49): *"can we get weekly knocks
posted in here on sundays and mondays please?"* — as the PDF, which is the
shape he asked for on 2026-09-01 ("I specifically want a PDF because when I'm
doing the 1on1s with the owners, if we have a lot of owners in there, it's
just hard to scroll through") and which has ridden along with every daily
Captainship email since 2026-08-27.

WHAT LANDS IN THE THREAD. The SAME one-PDF-per-captainship document the emails
carry (weekly_pdf): Captainship Summary first, then one Mon–Sat per-rep board
per OWNER. That is strictly more than the thread already had — Sunday's
weekly_knock_dispositions run posts a single board, Rafael's own office.

WHY SUN+MON AND NOT EVERY DAY. Those are the two days the weekly section is
current for the reader: Sunday the completed week lands, Monday it is re-shown
for the one-on-ones (config.SECTION_DAYS, Raf 2026-08-23 — "Monday should re
duplicate sundays post so I can see it again"). The gate here reads that SAME
table instead of keeping its own weekday list, so the day the emails change
days, this follows.

WHAT IT DOES NOT DO: pull, render or re-capture anything. It prints from the
PNGs Sunday's capture already wrote and, when those are swept, falls back to
the PDF printed earlier that week — exactly weekly_pdf.build's contract. So
this costs no ownerville session and cannot be the thing that makes a morning
late.

WHICH MACHINE. Lucy 3, the one that runs captainship_knocks + captainship_drafts:
the render dir and output/weekly_dispositions/ are LOCAL to that build (see
schedule_config's _machine_note on captainship_drafts). Anywhere else there is
no PDF to find.

    python -m automations.captainship_drafts.weekly_pdf_slack            # DRY-RUN
    python -m automations.captainship_drafts.weekly_pdf_slack --live     # post
    python -m automations.captainship_drafts.weekly_pdf_slack --live --force
    python -m automations.captainship_drafts.weekly_pdf_slack --date 2026-09-06
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

try:                                 # Windows consoles are cp1252, and an
    sys.stdout.reconfigure(encoding="utf-8")   # emoji in a print() has killed
except Exception:  # noqa: BLE001              # a run before now.
    pass

from automations.captainship_drafts import config
from automations.captainship_drafts import weekly_pdf as WP

REPORT_ID = "weekly_dispo_pdf_slack"
CARD_NAME = "Weekly Knock Dispositions PDF"
# Whose PDF. #alphalete-sales IS Rafael's office channel, so his captainship is
# the one whose owners the readers there hold one-on-ones about. A key that
# isn't a captainship with a knock_dispo section is a loud error, never a
# silent empty post.
DEFAULT_CAPTAIN = "rafael"

# The dedupe marker, and why it is not just "Weekly Knock Dispositions": on
# Sunday the weekly_knock_dispositions run posts its board into this same
# thread with that exact wording, and matching it would make this report think
# it had already posted and skip every Sunday.
MARKER = "Weekly Knock Dispositions (PDF)"


def runs_today(today: dt.date) -> bool:
    """Sun+Mon — read off the table the captainship emails gate on, never a
    second copy of the weekday list."""
    return config.kind_runs_on("knock_dispo", today)


def _captain(key: str):
    for c in config.CAPTAINS:
        if c.key == key:
            if "knock_dispo" not in {k for _h, k in c.sections}:
                raise SystemExit(
                    f"captainship {key!r} has no Weekly Knock Dispositions "
                    "section, so there is no PDF for it (b2b/nds knock other "
                    "campaigns).")
            return c
    raise SystemExit(f"unknown captainship {key!r} — known: "
                     f"{[c.key for c in config.CAPTAINS]}")


def already_posted(client, thread_ts: str, *, marker: str = MARKER,
                   channel_id: str | None = None) -> bool:
    """Is the PDF already in today's thread? Keeps a rerun (or the orchestrator
    retrying the step) from stacking a second copy on the same day. A read
    failure answers False: a duplicate is a smaller problem than a silent
    no-post, and the run log says which happened."""
    from automations.shared import slack_metrics_post as smp
    chan = channel_id or smp.CHANNEL_ID
    cursor = None
    try:
        for _ in range(5):        # 5 x 200 replies is far past any real day
            r = client.conversations_replies(channel=chan, ts=thread_ts,
                                             limit=200, cursor=cursor)
            for m in r.get("messages", []):
                if marker in (m.get("text") or ""):
                    return True
            cursor = (r.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except Exception as e:  # noqa: BLE001
        print(f"[wdpdf]   (dedupe check skipped: {type(e).__name__}: "
              f"{str(e)[:120]})", flush=True)
    return False


def run(today: dt.date | None = None, *, dry_run: bool = True,
        captain_key: str = DEFAULT_CAPTAIN, force: bool = False) -> int:
    from automations.total_knocks.pull import central_today
    today = today or central_today()
    captain = _captain(captain_key)

    if not runs_today(today) and not force:
        print(f"[wdpdf] {today} is a {today.strftime('%A')} — Sun+Mon only "
              "(config.SECTION_DAYS['knock_dispo']). Nothing to post.",
              flush=True)
        return 0

    built = WP.build(captain, today, config.RENDER_DIR,
                     logfn=lambda s: print(f"[wdpdf] {s}", flush=True))
    if not built:
        print(f"[wdpdf] ❌ no Weekly Knock Dispositions PDF on disk for "
              f"{captain.key} — nothing posted. The boards come from "
              "captainship_knocks / captainship_drafts on THIS machine; if "
              "they didn't run today, their own alert says why.", flush=True)
        return 1
    pdf, file_name = Path(built[0]), built[1]

    sat = WP.last_report_saturday(today)
    comment = (f":page_facing_up: {MARKER} — {captain.display_name}'s "
               f"Captainship — {WP._span(sat)}")

    from automations.shared import slack_metrics_post as smp
    if dry_run:
        print(f"[wdpdf] --dry-run — would post to {smp.CHANNEL_ID} "
              f"(+ mirrors {smp.mirror_channels(smp.CHANNEL_ID)}) in today's "
              f"Metrics thread:\n         {comment}\n         {pdf} "
              f"({pdf.stat().st_size // 1024} KB) as {file_name!r}",
              flush=True)
        return 0

    client = smp._client()
    try:
        thread_ts = smp.find_metrics_thread_ts(client, today)
    except Exception as e:  # noqa: BLE001
        print(f"[wdpdf] ❌ no 'Metrics for:' thread in #alphalete-sales today: "
              f"{e}", flush=True)
        return 1
    if already_posted(client, thread_ts) and not force:
        print("[wdpdf] ⤳ already in today's thread — nothing to do "
              "(--force reposts).", flush=True)
        return 0

    resp = smp.post_reply_with_file(pdf, comment=comment, today=today,
                                    file_name=file_name)
    if resp.get("ok") and resp.get("landed") is not False:
        print(f"[wdpdf] ✅ posted {file_name} into the Metrics thread "
              f"({thread_ts}).", flush=True)
        return 0
    print(f"[wdpdf] ❌ Slack did not take the PDF: {resp}", flush=True)
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="weekly_pdf_slack",
        description="Weekly Knock Dispositions PDF -> the #alphalete-sales "
                    "'Metrics for:' thread, Sundays and Mondays only.")
    ap.add_argument("--date", help="run as of this date (YYYY-MM-DD); "
                                   "default: today, Central time")
    ap.add_argument("--captain", default=DEFAULT_CAPTAIN,
                    help=f"captainship whose PDF to post "
                         f"(default: {DEFAULT_CAPTAIN})")
    ap.add_argument("--live", action="store_true",
                    help="POST into the thread (default: dry-run, no post)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be posted and stop (the default)")
    ap.add_argument("--force", action="store_true",
                    help="ignore BOTH the Sun+Mon gate and the "
                         "already-posted check — reposts on any day")
    args = ap.parse_args(argv)
    if args.live and args.dry_run:
        # `lucy rerun` appends extra args AFTER base_args (--live), so a safe
        # probe arrives as `--live --dry-run`. The safe flag wins — the same
        # rule weekly_knock_dispositions.run applies.
        print("[wdpdf] both --live and --dry-run given — dry-run wins.",
              flush=True)
    return run(dt.date.fromisoformat(args.date) if args.date else None,
               dry_run=(args.dry_run or not args.live),
               captain_key=args.captain, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
