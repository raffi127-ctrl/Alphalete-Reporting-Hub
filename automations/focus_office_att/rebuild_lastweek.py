"""Recovery: rebuild the frozen LAST WEEK block for a week that got lost.

Use when the bottom "LAST WEEK" block was wiped or corrupted (e.g. a daily run
was killed mid-flight and left the frozen block empty). It REPLAYS the exact
known-good Monday->Tuesday sequence daily.py runs every week, but forced for the
target week — there is no new fill/format logic here, just the tested pieces in
the right order:

  1. label the top block as LAST week
  2. scrape last week's activity (ownerville) into the top
  3. fill last week's production (Tableau)            [full run only]
  4. FREEZE the top into the bottom LAST WEEK block    <-- HARD GATE
  5. label the top as THIS week
  6. clear the top
  7. scrape this week's activity into the top
  8. fill this week's production (Tableau)             [full run only]

THE HARD GATE (step 4) is the safety this report was missing: if the freeze
writes 0 tabs, we ABORT before the wipe — so a failed freeze can never erase
last week again (the failure mode that lost the data in the first place).

Runs on the MINI only (the ownerville session lives there; a laptop scrape
would knock out the session every other report shares).

Preview ONE tab first (ownerville + freeze + this-week refill for that tab; no
Tableau, which is org-wide and can't be scoped):
    .venv/bin/python -m automations.focus_office_att.rebuild_lastweek \
        --monday 2026-06-15 --only "Marcellus Butler"

Then the full run (all tabs + Tableau):
    .venv/bin/python -m automations.focus_office_att.rebuild_lastweek --monday 2026-06-15

Add --plan to print the steps + computed dates without doing anything.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.recruiting_report import fill as _fill
from automations.focus_office_att.daily import (
    DEST_SPREADSHEET_ID, LOG_DIR, NON_OWNER_TABS, LAST_WEEK_DATA_ROW,
    PHASE2_TIMEOUT_S, PHASE3_TIMEOUT_S, PHASE_TIMEOUT_EXIT,
    CURRENT_ZONE_LAST_ROW, _q, _run_phase,
    set_current_week_dates, set_all_current_week_dates,
    wipe_all_owner_tabs, rollover_to_last_week, rollover_all_tabs,
)

RUN_ALL = "automations.focus_office_att.run_all_owners"
STEP7 = "automations.focus_office_att.step7_download_tableau"

# The rebuild scrapes a FULL WEEK (7 days × ~28 owners, ~3 min/owner) — far
# heavier than the daily 2-day window that PHASE2_TIMEOUT_S (60 min) is sized
# for. A full-week scrape needs ~85 min, so the 60-min cap killed it around
# owner 20 EVERY time — the silent reason the full rebuild never finished
# (Megan 2026-06-25). Give the rebuild's scrapes real headroom.
REBUILD_SCRAPE_TIMEOUT_S = 150 * 60


class Abort(Exception):
    pass


def _scoped_wipe_current(sh, title: str) -> None:
    """Clear ONE tab's current-week block (rows 3..109) + formatting — the
    single-tab version of wipe_all_owner_tabs, so --only never touches another
    owner. The frozen block (110+) is below this range and is never touched."""
    ws = sh.worksheet(title)
    sid = ws.id
    last = CURRENT_ZONE_LAST_ROW
    meta = sh.fetch_sheet_metadata({"ranges": [title], "fields": "sheets.basicFilter"})
    bf = meta["sheets"][0].get("basicFilter")
    if bf:
        sh.batch_update({"requests": [{"clearBasicFilter": {"sheetId": sid}}]})
    sh.values_batch_clear(body={"ranges": [f"{_q(title)}!A3:CR{last}"]})
    sh.batch_update({"requests": [{"updateCells": {
        "range": {"sheetId": sid, "startRowIndex": 2, "endRowIndex": last,
                  "startColumnIndex": 0, "endColumnIndex": 96},
        "fields": "userEnteredFormat"}}]})
    if bf:
        sh.batch_update({"requests": [{"setBasicFilter": {"filter": bf}}]})


def _finalize(sh, say) -> None:
    """Apply the daily run's full finalization to every owner tab so a rebuild's
    output matches a clean daily run: the headroom SPACER between the current
    block and the LAST WEEK block, the OV-access banners, the amber tab colors,
    and the frozen-block conditional SHADING (must be the last conditional op).
    The rebuild used to only re-shade — missing the spacer + banners + colors,
    which is why rebuilt tabs read 'no gap + wrong formatting' (Megan
    2026-06-25). Each pass is best-effort so one hiccup doesn't drop the rest.
    Reusable standalone: `from rebuild_lastweek import _finalize`."""
    import time as _t
    from automations.focus_office_att.daily import (
        collapse_headroom, _refresh_pending_banners, refresh_tab_colors,
        _normalize_lastweek_conditional)
    try:
        n = collapse_headroom(sh, logfn=say)
        say(f"   ✓ headroom spacer collapsed on {n} tab(s)")
    except Exception as e:
        say(f"   headroom spacer skipped — {type(e).__name__}: {str(e)[:80]}")
    try:
        _refresh_pending_banners(sh, say)
    except Exception as e:
        say(f"   banner refresh skipped — {type(e).__name__}")
    try:
        refresh_tab_colors(sh)
        say("   ✓ tab colors refreshed")
    except Exception as e:
        say(f"   tab-color refresh skipped — {type(e).__name__}")
    nc = 0
    for ws in sh.worksheets():
        if ws.title in NON_OWNER_TABS:
            continue
        for _att in range(3):
            try:
                _normalize_lastweek_conditional(ws)
                nc += 1
                break
            except Exception as e:
                if "429" in str(e) and _att < 2:
                    _t.sleep(20)
                    continue
                say(f"   {ws.title}: shading skipped — {type(e).__name__}")
                break
        _t.sleep(0.4)
    say(f"   ✓ re-extended shading on {nc} tab(s)")


def _phase(module, args, log_fh, say, timeout_s, label) -> None:
    say(f"  $ {module} {' '.join(args)}")
    rc = _run_phase(module, args, log_fh, timeout_s=timeout_s)
    if rc == PHASE_TIMEOUT_EXIT:
        raise Abort(f"{label} TIMED OUT after {timeout_s // 60} min — "
                    f"rerun (the scrape checkpoints, so it resumes).")
    if rc != 0:
        raise Abort(f"{label} failed (exit {rc}). Nothing destructive has run yet.")


def rebuild(monday: dt.date, only: str | None, log_fh, say,
            from_freeze: bool = False) -> int:
    last_monday = monday
    last_sunday = monday + dt.timedelta(days=6)
    this_monday = monday + dt.timedelta(days=7)
    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    scope = f'"{only}"' if only else "ALL owner tabs"
    say(f"=== Rebuild LAST WEEK ({last_monday}..{last_sunday}) → {scope} ===")

    if from_freeze:
        # Resume an interrupted run: last week is assumed already scraped into
        # the top (steps 1-3 done before the interruption). Go straight to the
        # freeze. Finish any straggler tabs with a separate --only scrape first.
        say("(--from-freeze) skipping steps 1-3 — last week already filled up top.")
    else:
        # 1. Label the top as LAST week, so the freeze snapshot carries last
        #    week's dates (the freeze copies row 1 into the frozen date row).
        say("1. labeling top block as last week…")
        if only:
            set_current_week_dates(sh.worksheet(only), last_monday)
        else:
            set_all_current_week_dates(sh, last_monday, logfn=say)

        # 2. Scrape last week's ownerville activity into the top block.
        say("2. scraping last week's activity (ownerville)…")
        a = ["--week-start", last_monday.isoformat()] + (["--only", only] if only else [])
        _phase(RUN_ALL, a, log_fh, say, REBUILD_SCRAPE_TIMEOUT_S, "last-week scrape")

        # 3. Fill last week's production (Tableau). Org-wide export — can't scope
        #    to one tab, so SKIP in --only preview. Non-fatal if it fails.
        if only:
            say("3. (skipping Tableau production — org-wide, added in the full run)")
        else:
            say("3. filling last week's production (Tableau)…")
            try:
                _phase(STEP7, ["--format", "csv", "--fill", "--week-ending",
                               last_sunday.isoformat()], log_fh, say,
                       PHASE3_TIMEOUT_S, "last-week Tableau")
            except Abort as e:
                say(f"   ⚠ {e}  — continuing; freeze will capture activity only.")

    # 4. FREEZE the top into the bottom LAST WEEK block. HARD GATE: if it froze
    #    nothing, abort BEFORE the wipe so last week can't be lost again.
    say("4. freezing last week into the LAST WEEK block…")
    n = (rollover_to_last_week(sh, only=[only], logfn=say) if only
         else rollover_all_tabs(sh, logfn=say))
    if not n:
        raise Abort("FREEZE wrote 0 tabs — aborting BEFORE the wipe so last "
                    "week is not erased. The top block still holds last week's "
                    "data; investigate the freeze, do not wipe.")
    say(f"   ✓ froze {n} tab(s)")

    # SAFETY GATE: confirm the freeze actually PERSISTED rep names into the
    # frozen block before the wipe destroys the current week. The freeze can
    # log success yet leave an empty block (the Marcellus --only failure); if
    # that happens here we ABORT before the wipe, so last week is never lost.
    check = ([only] if only else
             [t.title for t in sh.worksheets() if t.title not in NON_OWNER_TABS][:5])
    for title in check:
        col_b = sh.worksheet(title).col_values(2)
        froz = [v for i, v in enumerate(col_b, 1)
                if i >= LAST_WEEK_DATA_ROW and (v or "").strip()]
        if not froz:
            raise Abort(f"freeze did NOT persist on {title!r} — frozen block has "
                        f"no rep names. ABORTING before the wipe; the current "
                        f"block still holds last week, so nothing is lost.")
        say(f"   ✓ verified frozen block on {title}: {len(froz)} rep row(s)")

    # 5–6. Now safe: last week is preserved below. Relabel + clear the top.
    say("5. labeling top block as this week…")
    if only:
        set_current_week_dates(sh.worksheet(only), this_monday)
    else:
        set_all_current_week_dates(sh, this_monday, logfn=say)
    say("6. clearing the top block for this week…")
    if only:
        _scoped_wipe_current(sh, only)
    else:
        wipe_all_owner_tabs(sh)

    # 7. Scrape this week's activity into the (now clean) top block.
    say("7. scraping this week's activity (ownerville)…")
    a = ["--week-start", this_monday.isoformat()] + (["--only", only] if only else [])
    _phase(RUN_ALL, a, log_fh, say, REBUILD_SCRAPE_TIMEOUT_S, "this-week scrape")

    # 8. Fill this week's production (Tableau) — full run only.
    if only:
        say("8. (skipping Tableau production — org-wide, added in the full run)")
    else:
        say("8. filling this week's production (Tableau)…")
        try:
            _phase(STEP7, ["--format", "csv", "--fill"], log_fh, say,
                   PHASE3_TIMEOUT_S, "this-week Tableau")
        except Abort as e:
            say(f"   ⚠ {e}  — this week's production may be incomplete; re-run "
                f"the normal daily report to finish it.")

    # 9. Finalize formatting to MATCH a clean daily run — the headroom spacer
    #    between the current block and LAST WEEK, the OV-access banners, the
    #    amber tab colors, and the frozen-block conditional shading (last op).
    #    The rebuild used to only re-shade, so rebuilt tabs were missing the
    #    spacer + banners + colors (Megan 2026-06-25). Full run only.
    if not only:
        say("9. finalizing formatting (spacer + banners + colors + shading)…")
        _finalize(sh, say)

    say("=== DONE ===")
    if only:
        say(f'Verify "{only}": bottom = last week (activity), top = this week, '
            f'no duplicate reps. Then run WITHOUT --only for all tabs + Tableau.')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild the frozen LAST WEEK block.")
    ap.add_argument("--monday", required=True, metavar="YYYY-MM-DD",
                    help="Monday of the week to restore into the LAST WEEK block.")
    ap.add_argument("--only", default="", metavar="TAB",
                    help="Preview ONE owner tab (ownerville + freeze + this-week "
                         "refill; no org-wide Tableau).")
    ap.add_argument("--from-freeze", action="store_true",
                    help="Resume an interrupted run: skip the last-week scrape "
                         "(already done) and start at the freeze.")
    ap.add_argument("--plan", action="store_true",
                    help="Print the steps + computed dates and exit (no writes).")
    args = ap.parse_args()

    try:
        monday = dt.date.fromisoformat(args.monday)
    except ValueError:
        print(f"Bad --monday {args.monday!r}; expected YYYY-MM-DD", file=sys.stderr)
        return 2
    if monday.weekday() != 0:
        print(f"--monday {monday} is a {monday.strftime('%A')}, not a Monday.",
              file=sys.stderr)
        return 2
    only = args.only.strip() or None

    if args.plan:
        ls = monday + dt.timedelta(days=6)
        tm = monday + dt.timedelta(days=7)
        print(f"PLAN — restore week {monday}..{ls} into LAST WEEK; "
              f"top becomes week of {tm}.")
        print(f"  scope: {only or 'ALL owner tabs'}")
        print("  steps: label→scrape last→"
              f"{'(skip Tableau)' if only else 'Tableau'}→FREEZE(hard-gated)→"
              "label→wipe→scrape this→"
              f"{'(skip Tableau)' if only else 'Tableau'}")
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    log_path = LOG_DIR / f"rebuild-lastweek-{stamp}.log"
    with open(log_path, "w") as log_fh:
        def say(m: str) -> None:
            print(m, flush=True)
            log_fh.write(m + "\n")
            log_fh.flush()
        try:
            return rebuild(monday, only, log_fh, say, from_freeze=args.from_freeze)
        except Abort as e:
            say(f"\n✗ ABORTED: {e}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
