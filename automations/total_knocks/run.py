"""Run — the Total Knocks daily pipeline (Hub entry point).

  1. Scrape Ownerville 'Disposition by Rep' for the day prior.
  2. Replace the rep list on the Total Knocks tab (daily snapshot).
  3. Render the full table as a PNG.
  4. Post the PNG as a reply in today's 'Metrics for:' thread in
     #alphalete-sales, with a 🚪 reaction on the parent.

Default target date = yesterday. The Hub action runs this with no args.

Flags:
  --test-tab   write to the '… - TEST' sandbox tab instead of prod
  --no-slack   do everything EXCEPT post to Slack (write + render only)
  --dry-run    scrape + render a preview only; NO Sheet write, NO Slack post
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

# Make emoji / checkmarks safe on the Windows console (cp1252 default).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.total_knocks import fill as _fill
from automations.total_knocks import render as _render
from automations.total_knocks.pull import (
    KnocksPullFailed,
    central_today,
    pull_disposition_day,
)

# ONE post to the Metrics thread: (comment label, reaction short-name). The
# comment leads with the workflow emoji + Title Case title, matching every
# other metrics post; the same emoji is also added as a reaction on the parent.
# Raf's Loom 2026-08-22: the Total Knocks board now CARRIES Gaps + Total Gaps,
# so the separate Time Gaps post retired (the Sheet tab still fills both).
POST_TOTAL_KNOCKS = ("🚪 Total Knocks", "door")

# Offices whose TOTAL line rides ABOVE ours on the daily board (Raf
# 2026-08-23: "add Chan's totals above ours daily"). Their reps don't show —
# just the one totals row each. Best-effort: a pull failure here never blocks
# the Local Office post. Comma-separated env override, blank disables.
import os as _os
EXTRA_TOTALS_OFFICES = [o.strip() for o in
                        _os.environ.get("KNOCKS_EXTRA_TOTALS",
                                        "Chan Park").split(",") if o.strip()]


# WHOSE OFFICE THIS RUN IS. The knocks history tab is keyed by owner name the
# way the per-office runs write it ('Cyrus Wade'), and this run is the master
# ownerville session, which IS Raf's office 11280.
LOG_OFFICE = _os.environ.get("KNOCKS_OFFICE") or "Rafael Hidalgo"


def _log_day(target: dt.date, office_name: str, rows: list) -> None:
    """Keep the day, the way every per-office knocks run already does.

    THIS RUN WAS THE ONE OFFICE MISSING FROM THE HISTORY. rashad_metrics'
    knocks_run logs its rows to AUTOMATION MASTER → 'Knocks Daily', so the 14
    offices it covers have a day-over-day record — and Raf's own office, the
    most looked-at board in the org, had none, because this run renders its
    PNGs and forgets (verified 2026-09-22: 3,294 rows, 14 offices, no Rafael
    Hidalgo).

    Costs no second pull and no extra ownerville session: these are the rows
    the run already has. Idempotent (a logged day is skipped) and never fatal —
    a logging failure must not take down a post that would otherwise go out."""
    if not rows:
        return
    try:
        from automations.icd_sales_board import knocks_log
        n = knocks_log.append_day(target, office_name, rows)
        print(f"[total_knocks] knocks log: {n} row(s) kept for "
              f"{office_name}.", flush=True)
    except Exception as e:                        # noqa: BLE001
        print(f"[total_knocks] knocks log: SKIPPED for {office_name} "
              f"({type(e).__name__}: {e})", flush=True)


def _yesterday() -> dt.date:
    return central_today() - dt.timedelta(days=1)


def run(target: dt.date | None = None, *, test_tab: bool = False,
        no_slack: bool = False, dry_run: bool = False) -> int:
    target = target or _yesterday()
    tab = _fill.TAB_TEST if test_tab else _fill.TAB_PROD
    print(f"[total_knocks] Starting — data date {target.isoformat()} "
          f"-> tab {tab!r}", flush=True)
    print("[total_knocks] Opening Ownerville… please don't touch or close "
          "the browser window while it works.", flush=True)

    # 1. Pull (Disposition + Time Tracker gaps, merged).
    try:
        target, rows = pull_disposition_day(target)
    except KnocksPullFailed as e:
        # A FAILED scrape, not a quiet day. Post nothing — the 'No data
        # available' line below is reserved for a VERIFIED empty day, and a
        # failure wearing that line is exactly what hid this for a week — and
        # exit non-zero so the retry + failure alert fire.
        print(f"[total_knocks] ❌ Pull FAILED (not an empty day) — {e}",
              flush=True)
        print("[total_knocks] Nothing written or posted; the retry + failure "
              "alert take it from here.", flush=True)
        return 1
    print(f"[total_knocks] Scraped {len(rows)} rep(s).", flush=True)

    # REPS WHO KNOCK UNDER THIS OFFICE BUT AREN'T ITS OWN come off the board
    # here, before anything is written or drawn (Carlos's fourteen, dispatching
    # on Raf's ownerville since 2026-09-25). Everything downstream — the tab,
    # the history, the TOTAL, the rate columns, the team bands — is computed
    # from `rows`, so taking them out at the pull is the whole change. Their
    # own board is built further down, off the rows kept here: one pull, two
    # boards. An office with no guests gets its list back untouched.
    from automations.total_knocks import guests as _guests
    rows, guest_rows = _guests.split(LOG_OFFICE, rows, logfn=lambda m:
                                     print(f"[total_knocks] {m}", flush=True))
    if guest_rows:
        print(f"[total_knocks] {len(rows)} rep(s) left on "
              f"{LOG_OFFICE}'s board.", flush=True)

    if not rows:
        # VERIFIED no knocks for that day (the scrape completed and the office
        # logged nothing — e.g. a Sunday nobody door-knocked). Post an
        # explicit 'No data available' one-liner to each metric in today's
        # thread so the absence is visible — NOT a silent failure — and the
        # parent reactions still mark both metrics done. (Eve, 2026-06-22)
        print("[total_knocks] ⚠ No rows for that day — posting "
              "'No data available' to the Metrics thread.", flush=True)
        if dry_run or no_slack:
            why = "--dry-run" if dry_run else "--no-slack"
            print(f"[total_knocks] {why} — would post 'No data available' "
                  f"for {POST_TOTAL_KNOCKS[0]}.", flush=True)
            print("[total_knocks] ✅ Finished (no data).", flush=True)
            return 0
        from automations.shared.slack_metrics_post import post_reply_text_only
        slack_today = central_today()   # post into TODAY's thread (Texas time)
        label, emoji = POST_TOTAL_KNOCKS
        text = (f"{label} — {target.strftime('%b')} {target.day} "
                f"— No data available")
        resp = post_reply_text_only(text, react_emoji=emoji,
                                    today=slack_today)
        if resp.get("ok"):
            print(f"[total_knocks] ✅ Posted '{label}' no-data notice.",
                  flush=True)
        else:
            print(f"[total_knocks] ⚠ Slack response for '{label}': {resp}",
                  flush=True)
        print("[total_knocks] ✅ Finished (no data).", flush=True)
        return 0

    # 2. Fill the tab (skipped on dry-run).
    if dry_run:
        print("[total_knocks] DRY-RUN — skipping Sheet write, render & post.",
              flush=True)
        print("[total_knocks] ✅ Finished (dry-run).", flush=True)
        return 0
    stats = _fill.fill_total_knocks(rows, tab=tab)
    print(f"[total_knocks] Wrote {stats['reps']} rep(s) to "
          f"{stats['write_range']}.", flush=True)
    _log_day(target, LOG_OFFICE, rows)

    # 3. Extra offices' totals (Chan) for the rows above ours — pulled in
    #    their own ownerville session AFTER ours closed. Best-effort.
    extra_totals = []
    for extra_office in EXTRA_TOTALS_OFFICES:
        try:
            from automations.rashad_metrics.knocks_pull import pull_office_knocks
            _, x_rows = pull_office_knocks(extra_office, target)
            if x_rows:
                extra_totals.append((extra_office, x_rows))
                print(f"[total_knocks] {extra_office}: {len(x_rows)} rep(s) "
                      "for the totals row.", flush=True)
                # Their rows are in hand and nothing else pulls them, so the
                # history gets them too rather than only their totals line.
                _log_day(target, extra_office, x_rows)
            else:
                print(f"[total_knocks] ⚠ {extra_office}: no rows — posting "
                      "without that totals line.", flush=True)
        except Exception as e:                        # noqa: BLE001
            print(f"[total_knocks] ⚠ {extra_office} totals pull failed "
                  f"({type(e).__name__}: {e}) — posting without it.",
                  flush=True)

    # 4. Render the ONE combined board (knocks + gaps) from the filled tab.
    img_tk = _render.render_total_knocks(target, tab=tab,
                                         extra_totals=extra_totals)
    print(f"[total_knocks] Rendered -> {img_tk}", flush=True)

    # 4b. The guest offices' own boards — same day, same Chan comparison
    #     line, their reps only. Rendered even on --no-slack (the file is the
    #     deliverable when nothing is being sent); delivery is dry-run unless
    #     this run is posting for real.
    for guest, g_rows in (guest_rows or {}).items():
        try:
            from automations.total_knocks import guest_board as _gb
            png, _shape = _gb.build(target, guest, g_rows,
                                    extra_totals=extra_totals,
                                    logfn=lambda m: print(
                                        f"[total_knocks] {m}", flush=True))
            if png is None:
                continue
            cap = (f"🚪 *Total Knocks — {guest} — "
                   f"{target.strftime('%b')} {target.day}*")
            _gb.deliver(png, guest, cap, dry_run=(dry_run or no_slack),
                        logfn=lambda m: print(f"[total_knocks] {m}",
                                              flush=True))
        except Exception as e:                        # noqa: BLE001
            # A guest's board must never cost the host his — the host's post
            # is the one the whole channel is waiting on.
            print(f"[total_knocks] ⚠ {guest} board failed "
                  f"({type(e).__name__}: {e}) — {LOG_OFFICE}'s post is "
                  "unaffected.", flush=True)

    # 5. Slack — the single combined post.
    if no_slack:
        print("[total_knocks] Skipping Slack post (--no-slack).", flush=True)
        print("[total_knocks] ✅ Finished.", flush=True)
        return 0

    from automations.shared.slack_metrics_post import post_reply_with_image
    slack_today = central_today()   # post into TODAY's thread in Texas time
    label, emoji = POST_TOTAL_KNOCKS
    comment = f"{label} — {target.strftime('%b')} {target.day}"
    resp = post_reply_with_image(Path(img_tk), comment=comment,
                                 react_emoji=emoji, today=slack_today)
    if resp.get("ok"):
        print(f"[total_knocks] ✅ Posted '{label}' (file {resp.get('file')}).",
              flush=True)
    else:
        print(f"[total_knocks] ⚠ Slack response for '{label}': {resp}",
              flush=True)
    print("[total_knocks] ✅ Finished.", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Total Knocks daily pipeline.")
    ap.add_argument("date", nargs="?", default=None,
                    help="YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--test-tab", action="store_true",
                    help="write to the '… - TEST' sandbox tab instead of prod")
    ap.add_argument("--no-slack", action="store_true",
                    help="write + render but do NOT post to Slack")
    ap.add_argument("--dry-run", action="store_true",
                    help="preview only: no Sheet write, no Slack post")
    args = ap.parse_args()
    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    return run(target, test_tab=args.test_tab, no_slack=args.no_slack,
               dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
