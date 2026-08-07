#!/usr/bin/env python3
"""SCI Campaigns — weekly fill of the 'SCI Campaigns' tab from Adriana's
"Residential Telecom Tracker – RANKED" email.

Each run:
  1. Reads alphaletereporting@gmail.com for tracker emails (email_source).
  2. For each week to fill, parses BOTH PDFs into the tab's 13 campaign rows
     (parse) and cross-checks them against the by-day Grand Total.
  3. Writes that week's MM/DD/YY column (fill). 'Total Units' is a sheet
     formula and is never touched.
  4. Posts 'WE <M/D> Complete' as a reply under that MONTH's 'SCI Campaigns'
     thread in #l10-alphalete — one top-level post a month, tagging Rafael &
     Maud only on the note that opens a new month (slack_post). Only with
     --notify, and only for weeks that actually wrote something.

The week comes from the EMAIL SUBJECT, never the calendar: the email for a
Saturday week-ending lands the following Friday and has slipped to Sunday more
than once. So the default run is "fill every tracker week that isn't filled
yet", which makes it idempotent AND self-healing after a missed Friday.

  python -m automations.sci_campaigns.run                      # sandbox, catch up
  python -m automations.sci_campaigns.run --dry-run            # plan only
  python -m automations.sci_campaigns.run --week 2026-07-18    # one week
  python -m automations.sci_campaigns.run --since 2026-03-28   # backfill window
  python -m automations.sci_campaigns.run --list               # what's in the inbox
  python -m automations.sci_campaigns.run --real --i-mean-it   # PROD tab
  python -m automations.sci_campaigns.run --notify             # + the Slack post

SANDBOX BY DEFAULT. `--real` targets the tab the VAs read and is refused unless
paired with `--i-mean-it`, mirroring country_sales_board / org_sales_board.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

from automations.recruiting_report.fill import open_by_key, _retry
from automations.sci_campaigns import email_source as es
from automations.sci_campaigns import fill as scf
from automations.sci_campaigns import manual
from automations.sci_campaigns import parse as scp

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
PROD_TAB = "SCI Campaigns"
SANDBOX_TAB = "SCI Campaigns (sandbox)"
CENTRAL = ZoneInfo("America/Chicago")   # [[project_central-time-for-texas-reports]]
# Backtrack floor Megan set 2026-07-27: 3/28/2026 was the first unfilled week.
DEFAULT_SINCE = dt.date(2026, 3, 28)


def _find_ws(sh, title: str):
    want = title.strip().casefold()
    for w in sh.worksheets():
        if w.title.strip().casefold() == want:
            return w
    raise SystemExit(f"tab {title!r} not found in the workbook.")


def resolve_week(we: dt.date, got: dict) -> tuple:
    """Assemble one week's values, sourcing the two halves INDEPENDENTLY.

    The tab's rows come from two different PDFs, and Adriana has dropped either
    one on its own. Both PDFs restate the prior week in full, so each half falls
    back to the FOLLOWING week's 'Previous Week Ending' column separately —
    which recovers WE 6.6.2026 (own by-day PDF present, RANKED PDF missing)
    without needing the next week to be complete.

    -> (Parsed | None, source description, [notes to print])
    """
    notes: List[str] = []
    own, nxt = got.get(we), got.get(we + dt.timedelta(days=7))
    nxt_label = es.we_label(nxt.week_ending) if nxt else None

    def _try(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except scp.ParseError as e:
            notes.append(f"  · {e}")
            return None

    byday = src_b = None
    if own and own.byday_pdf:
        byday, src_b = _try(scp.parse_byday, own.byday_pdf), "own email"
    if byday is None and nxt and nxt.byday_pdf:
        byday = _try(scp.parse_byday, nxt.byday_pdf, prev=True)
        src_b = f"WE {nxt_label} prior-week column"
    if byday is None and we in manual.BYDAYS:
        m = manual.BYDAYS[we]
        byday = (dict(m.values), m.grand, dict(m.extra), [], [])
        src_b = "HAND-RECOVERED (see manual.py)"

    foot = src_f = None
    if own and own.main_pdf:
        foot, src_f = _try(scp.parse_footer, own.main_pdf), "own email"
    if foot is None and nxt and nxt.main_pdf:
        foot = _try(scp.parse_footer, nxt.main_pdf, prev=True)
        src_f = f"WE {nxt_label} prior-week column"
    if foot is None and we in manual.FOOTERS:
        foot = dict(manual.FOOTERS[we])
        src_f = "HAND-RECOVERED (see manual.py)"

    if byday is None:
        notes.append("  ✗ no 'Campaign Totals By Day' PDF for this week, and "
                     "the following week's can't cover it.")
        return None, "", notes
    if foot is None:
        notes.append("  ✗ no RANKED PDF for this week (it carries AT&T NDS + "
                     "the 'Selling … Wireless' rows), and the following week's "
                     "can't cover it. Filling would zero five real rows.")
        return None, "", notes
    vals, grand, extra, weeks, unknown = byday
    vals = dict(vals)
    vals.update(foot)
    src = src_b if src_b == src_f else f"by-day {src_b} + RANKED {src_f}"
    return scp.Parsed(vals, grand, extra, weeks, unknown), src, notes


def _filled_weeks(grid) -> set:
    """Week-endings whose column already has at least one campaign value —
    used to decide what a catch-up run still owes."""
    rows = scf.campaign_rows(grid)
    out = set()
    for we, col in scf.week_columns(grid).items():
        for row in rows.values():
            if scf._as_int(scf._existing(grid, row, col)) is not None:
                out.add(we)
                break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SCI Campaigns weekly fill")
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan and print the writes; touch nothing.")
    ap.add_argument("--real", action="store_true",
                    help=f"Target {PROD_TAB!r} instead of the sandbox tab.")
    ap.add_argument("--i-mean-it", action="store_true",
                    help="Required alongside --real (writing the live tab).")
    ap.add_argument("--week", metavar="YYYY-MM-DD",
                    help="Fill only this week ending (a Saturday).")
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help=f"Oldest week a catch-up run will fill "
                         f"(default {DEFAULT_SINCE}).")
    ap.add_argument("--replace", action="store_true",
                    help="Overwrite cells that already hold a DIFFERENT value "
                         "(default: keep the VAs' hand-typed number).")
    ap.add_argument("--list", action="store_true",
                    help="List the tracker weeks in the inbox and what the "
                         "tab already has, then exit.")
    ap.add_argument("--notify", action="store_true",
                    help="Post the 'WE … complete' note to #l10-alphalete after "
                         "a successful fill.")
    ap.add_argument("--keep-pdfs", metavar="DIR",
                    help="Keep the downloaded PDFs here instead of a temp dir.")
    args = ap.parse_args(argv)

    if args.real and not args.i_mean_it:
        print(f"refusing to write {PROD_TAB!r} without --i-mean-it. "
              f"Build against the sandbox first.")
        return 2

    tab = PROD_TAB if args.real else SANDBOX_TAB
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    today = dt.datetime.now(CENTRAL).date()
    since = (dt.date.fromisoformat(args.since) if args.since else DEFAULT_SINCE)
    print(f"=== SCI Campaigns — {tab!r} — {mode} — today={today} ===")

    sh = open_by_key(SHEET_ID)
    ws = _find_ws(sh, tab)
    grid = _retry(ws.get_all_values)
    have = _filled_weeks(grid)
    cols = scf.week_columns(grid)

    print("reading the reporting inbox…")
    inbox = es.available_weeks()
    if not inbox:
        print("  ✗ no 'Residential Telecom Tracker' emails found — nothing to do.")
        return 1

    # An email week may be labelled a day off the tab's Saturday header (Adriana
    # has used the Friday twice); snap so "already filled" compares like for like.
    snap = {w: scf.snap_to_column(w, cols) for w in inbox}

    if args.list:
        print(f"\n{'week':>10}  {'email':>6}  {'tab column':>10}  filled")
        for we in sorted(set(inbox) | set(cols), reverse=True):
            if we < since and we not in inbox:
                continue
            tgt = snap.get(we, we if we in cols else None)
            note = "" if tgt in (we, None) else f"  (-> {tgt:%m/%d/%y})"
            print(f"{we:%m/%d/%y}  {'yes' if we in inbox else '-':>6}  "
                  f"{(scf.a1col(cols[tgt]) if tgt in cols else '-'):>10}  "
                  f"{'yes' if tgt in have else 'no'}{note}")
        return 0

    # ---- which weeks this run owes ----
    # A week can also be fillable with NO email of its own — manual.py holds
    # weeks recovered by hand from a neighbouring week's images (the Apr-May
    # 2026 outage). Treat those as available alongside the inbox.
    recoverable = set(manual.BYDAYS) | set(manual.FOOTERS)
    fillable = set(inbox) | recoverable
    for w in recoverable:
        snap.setdefault(w, scf.snap_to_column(w, cols))

    if args.week:
        want = [dt.date.fromisoformat(args.week)]
        missing = [w for w in want if w not in fillable]
        if missing:
            print(f"  ✗ no tracker email for {missing[0]:%m/%d/%y} and no "
                  f"hand-recovered entry in manual.py "
                  f"(inbox has {es.we_label(max(inbox))} newest).")
            return 1
    else:
        want = sorted(w for w in fillable
                      if w >= since and (args.replace or snap.get(w) not in have))
        skipped_old = sorted(w for w in fillable if w < since)
        if skipped_old:
            print(f"  ({len(skipped_old)} tracker week(s) older than "
                  f"{since:%m/%d/%y} left alone — raise --since to include them)")
    if not want:
        print("  nothing to fill — every tracker week in range is already on "
              "the tab.")
        return 0
    print(f"  {len(want)} week(s) to fill: "
          f"{', '.join(es.we_label(w) for w in want)}")

    # Weeks the tab has no column for would raise per-week; say it up front.
    no_col = [w for w in want if snap.get(w) is None]
    if no_col:
        print(f"  ⚠ no header column on {tab!r} for: "
              f"{', '.join(es.we_label(w) for w in no_col)} — those will be "
              f"reported as errors below; add the week to row 1 to fill them.")

    tmp = None
    if args.keep_pdfs:
        dest = Path(args.keep_pdfs)
    else:
        tmp = tempfile.TemporaryDirectory(prefix="sci_campaigns_")
        dest = Path(tmp.name)

    try:
        print("downloading the tracker PDFs…")
        # Also pull each week's FOLLOWER (W+7): both PDFs restate the prior week
        # in full, so a week whose own email is unusable is recovered from the
        # next one's 'Previous Week Ending' column (see parse.parse_week).
        followers = [w + dt.timedelta(days=7) for w in want]
        trackers = es.fetch(dest, sorted(set(want) | (set(followers) & set(inbox))))
        got = {t.week_ending: t for t in trackers}

        filled: list = []
        failed: list = []
        for we in want:
            label = es.we_label(we)
            print(f"\n--- WE {label} ---")
            parsed, source, notes = resolve_week(we, got)
            for n in notes:
                print(n)
            if parsed is None:
                failed.append((we, "no usable PDFs (own email or the next week's)"))
                continue
            print(f"  source: {source}")
            for w in scp.check_consistency(parsed):
                print(f"  ⚠ {w}")
            try:
                plan = scf.plan_week(grid, we, parsed.values,
                                     replace=args.replace)
            except KeyError as e:
                print(f"  ✗ {e}")
                failed.append((we, "no column"))
                continue
            for line in scf.audit_missing(plan, grid):
                print(line)
            scf.apply_plan(ws, plan, dry_run=args.dry_run)
            print(f"  {len(plan.updates)} cell(s) "
                  f"{'planned' if args.dry_run else 'written'}, "
                  f"{len(plan.unchanged)} already correct, "
                  f"{len(plan.skipped)} left alone")
            if plan.updates:
                filled.append(we)
            if plan.updates and not args.dry_run:
                grid = _retry(ws.get_all_values)     # keep the audit honest
    finally:
        if tmp:
            tmp.cleanup()

    # ---- notify ----
    if filled and args.notify:
        from automations.sci_campaigns import slack_post
        for we in filled:
            # The Sheet is already written by here. A Slack failure must NOT be
            # silent (nobody would know the week landed) but it also must not
            # look like the fill failed — so it's its own reported failure, with
            # the one-liner that re-sends just the note.
            try:
                out = slack_post.notify(we, dry_run=args.dry_run)
                print(f"  slack: {out}")
                if not args.dry_run and not out.get("ok"):
                    raise RuntimeError(f"Slack returned {out}")
            except Exception as e:
                print(f"  ✗ the fill SUCCEEDED but the Slack post failed for WE "
                      f"{es.we_label(we)}: {type(e).__name__}: {str(e)[:120]}")
                print(f"    re-send just the note with:  python -m "
                      f"automations.sci_campaigns.slack_post "
                      f"--week {we.isoformat()} --post")
                failed.append((we, "filled OK, Slack post failed"))
    elif filled:
        print(f"\n  (--notify not set — no Slack post sent for "
              f"{', '.join(es.we_label(w) for w in filled)})")

    print(f"\n=== {len(filled)} week(s) "
          f"{'planned' if args.dry_run else 'filled'}"
          f"{f', {len(failed)} failed' if failed else ''} — done ===")
    if failed:
        for we, why in failed:
            print(f"  ✗ WE {es.we_label(we)}: {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
