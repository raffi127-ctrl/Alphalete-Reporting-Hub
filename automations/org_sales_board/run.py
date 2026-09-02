"""Alphalete ORG Sales Board — build steps (work in progress).

Multi-section board on the 'Alphalete ORG Sales Board' tab. Being built
section by section from Megan's walkthrough videos; practice on the duplicated
'Alphalete ORG Sales Board' tab until told to point at the real one.

Sections (top to bottom):
  1. Product Summary - This Week   (Product Type x Mon-Sun + Grand Total)
  2. RAF ORG - Current vs Prior Weeks
  3. ICD leaderboard by campaign x week-ending columns
  4. CAPTAIN TEAM rollups
  5. historical week-list

CORRECTION (2026-05-30): the Product Summary AND the RAF ORG vs-Prior tables are
FORMULA-DRIVEN — they auto-derive from the daily sections (Product Summary pulls
each section's Totals row: `=C85`, `=C103`, …; Grand Total `=SUM`; RAF ORG
references section history rows). They must NOT be cleared/hardcoded. The
new-week reset belongs on the daily SECTION fill areas + the section-history
shift, not here. `clear_product_summary` below is SUPERSEDED and guarded off.
See workflows/org-sales-board-recipe.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
# What to tell a human whose board dropped a day. NOT '=<prev>+1'
# any more: that chain IS the bug — it dies at every month end
# (31 + 1 = 32 lost 9/1 across seven sections, Eve 2026-09-02).
DAYNUM_FIX_CMD = "python -m automations.org_sales_board.daynum_repair --apply"
from automations.org_sales_board.tabs import BOARD_TAB, ARCHIVED_VA_TAB

# Both names live in tabs.py now — a rename is one line there, not six here.
# The aliases stay because ~30 modules already import these two symbols.
SANDBOX_TAB = BOARD_TAB          # the live board (was "Copy of …" until 8/19)
PROD_TAB = ARCHIVED_VA_TAB       # the VAs' old tab — archived + hidden 8/19

OUT_DIR = Path("output")                         # one-off CSVs land here

SUMMARY_TITLE = "Product Summary - This Week"
SUMMARY_END = "RAF ORG"                          # next section (prefix match)
HEADER_LABEL = "Product Type"                    # day-header rows in the section
GRAND_TOTAL_HDR = "Grand Total"


def _col(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _find(colB, pred, start=1):
    for i in range(start, len(colB) + 1):
        if pred((colB[i - 1] or "").strip()):
            return i
    return None


def clear_product_summary(ws, *, dry_run=False, logfn=print):
    """SUPERSEDED — the Product Summary is formula-driven (auto-pulls each
    daily section's Totals row); clearing it would wipe live formulas. Kept
    only for reference; guarded off. Label-anchored clear logic is reusable
    for the daily SECTION fill areas later."""
    raise RuntimeError(
        "clear_product_summary is retired: the Product Summary is "
        "formula-driven and must not be cleared. The new-week reset belongs on "
        "the daily section fill areas + history shift (see recipe)."
    )
    colB = ws.col_values(2)  # noqa: unreachable — retained for reuse
    r_title = _find(colB, lambda v: v.lower() == SUMMARY_TITLE.lower())
    if not r_title:
        raise ValueError(f"Couldn't find '{SUMMARY_TITLE}' in column B.")
    r_end = _find(colB, lambda v: v.upper().startswith(SUMMARY_END.upper()),
                  start=r_title + 1) or (len(colB) + 1)

    # data-column span from a header row (B='Product Type' .. 'Grand Total')
    r_hdr = _find(colB, lambda v: v.lower() == HEADER_LABEL.lower(),
                  start=r_title)
    hdr = ws.row_values(r_hdr)
    first_col = 3                                  # col C — first day, right of B
    gt_col = next((i + 1 for i, c in enumerate(hdr)
                   if c.strip().lower() == GRAND_TOTAL_HDR.lower()), 10)

    # data rows: labelled, not a header, within the section
    data_rows = [r for r in range(r_title + 1, r_end)
                 if (colB[r - 1] or "").strip()
                 and (colB[r - 1] or "").strip().lower() != HEADER_LABEL.lower()
                 and (colB[r - 1] or "").strip().lower() != SUMMARY_TITLE.lower()]

    # contiguous runs -> one clear range each (skips interior header rows)
    runs, run = [], []
    for r in data_rows:
        if run and r == run[-1] + 1:
            run.append(r)
        else:
            if run:
                runs.append(run)
            run = [r]
    if run:
        runs.append(run)
    ranges = [f"{_col(first_col)}{run[0]}:{_col(gt_col)}{run[-1]}" for run in runs]

    logfn(f"  Product Summary: rows {data_rows[0]}-{data_rows[-1]} "
          f"({len(data_rows)} data rows), cols {_col(first_col)}-{_col(gt_col)}")
    logfn(f"  clear ranges: {ranges}")
    if dry_run:
        logfn("  (dry-run — nothing cleared)")
        return ranges
    ws.batch_clear(ranges)
    logfn(f"  cleared {len(ranges)} range(s) ✓")
    return ranges


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="org_sales_board")
    ap.add_argument("--step", default="daily",
                    choices=["clear-summary", "retail-nl", "daily",
                             "captainships", "rollover"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--real", action="store_true",
                    help="Target the REAL tab instead of the sandbox copy.")
    ap.add_argument("--from-csv",
                    help="Parse a saved SARA by-day CSV instead of pulling "
                         "live (offline engine validation).")
    ap.add_argument("--with-captainships", action="store_true",
                    help="On the 'daily' step, also fill the 10 captainship "
                         "leaderboards in the SAME login (one full-board run).")
    ap.add_argument("--sections",
                    help="Comma-separated section labels to fill ONLY (granular "
                         "retry of just the failed daily sections). Omit = all.")
    ap.add_argument("--programs",
                    help="Comma-separated captainship program keys to pull ONLY "
                         "(granular retry of just the failed programs). Omit = all.")
    ap.add_argument("--skip-compare", action="store_true",
                    help="Don't compare against the VA tab after the fill. The "
                         "scheduled 4am run sets this: at 4am the VAs have keyed "
                         "NOTHING yet, so every 'difference' is just the automation "
                         "being ahead — pure noise that marked the fill INCOMPLETE "
                         "every morning. The compare runs on its own at 9am CST "
                         "(report_id 'board_compare'), once the VAs are done.")
    ap.add_argument("--no-manifest", action="store_true",
                    help="Don't write this run's outcome to the 'org-sales-board' "
                         "manifest. For an UNATTENDED SURGICAL re-pull that is not "
                         "the day's board run — the 06:52/06:58 BOX top-off "
                         "(deploy/org_board_box_repull.sh). Without it a one-section "
                         "re-pull OVERWRITES the morning fill's verdict: mark_clean() "
                         "'clears any prior failure manifest', so a successful BOX "
                         "top-off would turn a genuinely INCOMPLETE 04:50 board GREEN "
                         "and take its 'Retry failed only' button with it; and a BOX "
                         "pull that fails would paint an otherwise-perfect board "
                         "orange and fire a drop-org-sales-board alert. Neither "
                         "verdict is this run's to give — it looked at ONE "
                         "section. Do NOT pass it on the Hub's granular retry: THAT "
                         "re-run is supposed to clear the failure it just fixed.")
    args = ap.parse_args(argv)
    _sections = [s.strip() for s in args.sections.split(",") if s.strip()] if args.sections else None
    _programs = [p.strip() for p in args.programs.split(",") if p.strip()] if args.programs else None

    # HARD GUARD (Megan 2026-06-14: "DO NOT change anything on the real tab").
    # A live --real run is refused outright. --real --dry-run is still allowed:
    # it READS the real tab to preview/validate but writes nothing.
    if args.real and not args.dry_run:
        print("Refusing to run LIVE against the REAL tab "
              f"({PROD_TAB!r}). Megan: do not change the real tab. "
              "Run on the sandbox copy, or add --dry-run for a read-only "
              "real-tab preview.")
        return 2

    tab = PROD_TAB if args.real else SANDBOX_TAB
    print(f"=== ORG Sales Board — {args.step} — tab={tab!r} "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")
    ws = open_by_key(SHEET_ID).worksheet(tab)
    if args.step == "clear-summary":
        clear_product_summary(ws, dry_run=args.dry_run)
    elif args.step == "rollover":
        # Tuesday freeze (run_rollover self-guards to weekday==1): shift each
        # leaderboard's current week into history
        # (grow a column), freeze each delta table's "this week" -> "last
        # week", then blank the daily day-cells for the fresh week.
        from automations.org_sales_board import rollover
        rollover.run_rollover(ws, dry_run=args.dry_run)
    elif args.step == "captainships":
        # All 10 captainships under ONE patchright session: each captain's
        # TEAM view + org-wide all-products fallback, filled worksheet-scoped.
        from automations.org_sales_board import captainship
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(verbose=False) as page:
            captainship.run_captainships(ws, page, dry_run=args.dry_run,
                                         programs=_programs)
    else:
        # Both 'daily' (all sections) and 'retail-nl' (just the SARA pair)
        # run through the ONE patchright-session orchestrator — no CDP.
        from automations.org_sales_board import orchestrate
        only = (["Retail NL", "Retail Internet"]
                if args.step == "retail-nl" else None)
        if _sections:                     # granular retry: fill ONLY these sections
            only = _sections
        from_csv = Path(args.from_csv) if args.from_csv else None
        # WEEKLY ROLLOVER — AUTOMATIC AGAIN (2026-07-14), keyed to the REPORTING
        # week rather than a weekday.
        #
        # It was made manual on 2026-06-30 ("a person rolls it Monday night") so an
        # unattended run couldn't double-shift a week a human had already rolled.
        # That trade cost more than it saved: on 2026-07-14 the manual step was
        # simply forgotten, the copy sat a FULL WEEK behind the VA, the daily fill
        # had no columns for the new week so nothing landed at all, and the board
        # email was gated for days before anyone noticed.
        #
        # The double-shift fear is now moot: run_rollover is idempotent (it skips
        # when the leaderboard header already reads the target week), and
        # needs_rollover only fires when the board is not on the week the fill is
        # about to write. So it rolls at most once per week, on the first run of a
        # Tuesday, and re-running is a no-op. If a Tuesday run is missed entirely,
        # the next run rolls and backfills every completed day — it self-heals.
        #
        # Skipped on --dry-run and on a --sections/--programs granular retry (those
        # are surgical re-fills of an already-rolled board, not a fresh week).
        if not (args.dry_run or _sections or _programs):
            from automations.org_sales_board import rollover as _ro
            _cS = ws.get_all_values()
            # No VA cross-check any more. It used to read the VAs' hand-keyed
            # tab and warn when its week differed from ours. That tab has been
            # out of circulation since 2026-07-21 and was archived + hidden on
            # 2026-08-19, so it is FROZEN on WE 07.26 — reading it would warn
            # every single Tuesday about a tab nobody keeps. The rollover
            # decision never depended on it: it comes from the board's own week
            # header (needs_rollover takes vS as optional for exactly this).
            _need, _tgt, _cur, _va = _ro.needs_rollover(_cS)
            if _need:
                print(f"--- weekly rollover: board is on {_cur!r}, this week is "
                      f"{_tgt!r} — rolling before the fill ---")
                _ro.run_rollover(ws, dry_run=False)
                ws = open_by_key(SHEET_ID).worksheet(tab)   # re-open post-roll
                # TWO-WEEK ZERO RULE, hung off the roll (Eve 2026-09-01:
                # "incluilo en el proceso de roleo de los martes, no le crees
                # tarjeta aparte"). The week the roll just closed is now a
                # LITERAL column, which is the only state the rule is defined
                # on — before the roll it is still col C's live formula. The
                # standalone Tuesday card had to guess that, and only worked
                # because its `order` sat after this report's; that ordering was
                # invisible from either entry. It PROPOSES in Slack and removes
                # nothing, and it can never sink the fill.
                from automations.org_sales_board import zero_streak as _zs
                _zs.after_rollover(SHEET_ID, tab)
            else:
                print(f"--- weekly rollover: board already on {_cur!r} — no roll ---")
        _summary = orchestrate.run_daily(ws, dry_run=args.dry_run, only=only,
                              from_csv=from_csv,
                              include_captainships=args.with_captainships,
                              captainship_programs=_programs) or {}
        # Extend the elapsed-day grand-total formulas on the 'Current vs Prior'
        # tables (Sales Last Week / 4 Week AVG) to sum the days completed so far
        # this week — the VAs do this by hand each day; the automation now
        # matches, so Wednesday is no longer dropped (Eve 2026-06-04).
        if args.step == "daily":
            # Sort every leaderboard high->low (campaigns + all captainships),
            # then extend the elapsed-day comparison formulas — both things the
            # VAs do by hand each day (Eve 2026-06-04).
            from automations.org_sales_board import sort as _sort
            _sort.apply_sort(ws, dry_run=args.dry_run)
            # The DELTA boxes, which apply_sort deliberately will not touch:
            # writing their rows back as values freezes the live cells (the
            # per-day =SUMIFs, the Delta %, the =F+I total) and every total
            # still balances afterwards, so nobody sees it — that is the
            # 2026-08-25 incident. They get Sheets-native sortRange instead,
            # which moves cells and re-points formulas. Until today nothing
            # sorted them at all, on any captainship (Eve 2026-09-02: "las
            # cajas de delta las tenes que ordenar todos los dias").
            from automations.org_sales_board import delta_sort as _dsort
            _dsort.apply_delta_sort(ws, dry_run=args.dry_run)
            from automations.org_sales_board.elapsed_totals import apply_elapsed_totals
            apply_elapsed_totals(ws, dry_run=args.dry_run)
            # The delta-box rows with NO daily table to sum. A cross-cutting
            # box (TRANG'S ORG) carries people who have no row anywhere else
            # on the board — Jacob Morgan is a rep under an owner, not an ICD
            # — so their per-day cells are plain numbers somebody typed in off
            # Tableau's PRODUCT SALES SUMMARY. Every morning. A daily manual
            # step nobody is paged about is one that eventually doesn't
            # happen, and it fails silently: the row reads 0, the totals row
            # sums it happily, and the org total is short with nothing saying
            # so (Eve 2026-08-26: "no te voy a recordar todos los días").
            #
            # Costs one extra crosstab download. Wrapped: a fill that cannot
            # reach Tableau must not take down the board fill it rides on —
            # the row simply keeps yesterday's number and says so in the log.
            try:
                from automations.org_sales_board import delta_manual_fill as _dmf
                _dmf.apply_manual_fill(ws, dry_run=args.dry_run)
            except Exception as _edm:  # noqa: BLE001
                print(f"  [!] relleno manual de cajas delta salteado "
                      f"({type(_edm).__name__}: {str(_edm)[:90]})", flush=True)
            # Somebody added to a captainship — and so to its delta box —
            # AFTER Tuesday's rollover has no per-day 'Last week' numbers:
            # that freeze only covered the rows that existed then. The row
            # then shows a real week against 0, its Delta reads a flat 0.00%,
            # and the box's totals row (=SUM over these cells) comes out short
            # by exactly the people who were added. Jairo's box, 2026-08-31:
            # Abdallah Ghousheh and Fernando Munoz had sold 62 and 67 the week
            # it was comparing against (Eve: "hacelo siempre que agregues a
            # alguien a una capitania y a un delta chart").
            #
            # Free on a normal day: it looks for blank cells in the grid it
            # already has and only reads the pre-rollover snapshot tab if it
            # finds some. Wrapped like its neighbour — a backfill that cannot
            # read that tab must not take down the board fill it rides on.
            try:
                from automations.org_sales_board import (
                    delta_lastweek_backfill as _dlb)
                _dlb.apply_backfill(ws, dry_run=args.dry_run)
            except Exception as _edb:  # noqa: BLE001
                print(f"  [!] backfill de 'Last week' por día salteado "
                      f"({type(_edb).__name__}: {str(_edb)[:90]})", flush=True)
            # TRIPWIRE — the delta boxes' per-day 'This week' cells must still
            # be =SUMIFs over their captainship's daily table. A value pasted
            # over one keeps showing the number it froze on and every total
            # still balances, so nothing else on this board can see it: all 602
            # across the twelve FIBER boxes were frozen literals for a week
            # (2026-08-26) before Eve caught it by eye. Lives HERE and not in
            # full_compare because that runs only on demand — `board_compare`
            # was retired from the scheduler 2026-07-21, so a check wired there
            # would never fire on its own.
            #
            # Report-only: it never gates the fill. But LOUD — through the same
            # dropped-section alert the other silent holes use, so it is heard
            # at 4am instead of found a week later. kind='finding': nothing was
            # dropped, an audit found something. The alert opens ONE thread and
            # closes itself on the first clean run.
            try:
                from automations.org_sales_board import rollover as _rodx
                _stale = _rodx.check_delta_live_formulas(
                    ws.get_all_values(), ws=ws)
                if _stale:
                    _dboxes = sorted({b for b, _a1, _rp, _v in _stale})
                    print(f"  [!] {len(_stale)} celda(s) 'This week' por dia en "
                          f"{len(_dboxes)} caja(s) delta son valores congelados, "
                          f"no formulas: {', '.join(_dboxes)}", flush=True)
                    if not args.dry_run:
                        from automations.shared import section_drop_alert as _sda
                        from automations.shared import run_manifest as _rmx
                        _sda.alert(
                            report_id="org_sales_board",
                            kind="finding",
                            failed=[f"{b} — "
                                    f"{sum(1 for x in _stale if x[0] == b)} celdas"
                                    for b in _dboxes],
                            note=("Las celdas 'This week' por dia de esas cajas "
                                  "delta son valores congelados en vez de =SUMIF: "
                                  "muestran el numero del dia en que se pisaron y "
                                  "no levantan ningun dia nuevo. Los totales igual "
                                  "cierran, por eso no se nota mirando el board."),
                            remediation=_rmx.make_remediation(
                                reason="Alguien pego valores encima de los "
                                       "=SUMIF por dia de esas cajas delta.",
                                fix="python -m automations.org_sales_board."
                                    "delta_formula_repair --apply --verify"),
                        )
                else:
                    print("  [ok] cajas delta: las celdas 'This week' por dia "
                          "siguen siendo =SUMIF vivas", flush=True)
            except Exception as _edx:  # noqa: BLE001 — un chequeo que falla
                # no puede tumbar el fill que esta vigilando.
                print(f"  [!] tripwire de cajas delta salteado "
                      f"({type(_edx).__name__}: {str(_edx)[:80]})", flush=True)
        # Auto match-check vs the live VA tab (Megan 2026-06-03): every daily
        # fill ends by confirming the copy matches the VAs. A real glitch
        # (automation behind / mismatched / missing-row) flags the run.
        if args.step == "daily":
            # COMPLETENESS GATE — never report 'done' when data is MISSING
            # (Megan 2026-06-08: a report must NOT say completed if it's
            # missing data). A skipped section pull or a failed captainship
            # program pull = missing data, even if the compare passes (e.g. a
            # Monday run with no completed days to compare).
            _skipped = list(_summary.get("skipped") or [])
            # Sections that filled but LOST a completed day: their day-number
            # row is frozen on last week's dates, so the fill had no column for
            # that day and dropped it (Eve 2026-08-09). Missing data like any
            # other — and a re-run alone won't fix it, so it carries no retry
            # button; the header cell has to be repaired first.
            _dropped = list(_summary.get("dropped_days") or [])
            _caps_summary = _summary.get("captainships") or {}
            _failed_prog = list(_caps_summary.get("failed_programs") or [])
            _failed_caps = list(_caps_summary.get("failed_captainships") or [])
            # Reps the captainship fill AUTO-ADDED this run (VA-only reps that had
            # no copy row — inserted + filled in the same run). Informational: the
            # self-heal worked, so it does NOT gate; surfaced so Megan sees a new
            # rep was added rather than it happening silently.
            _auto_added = list(_caps_summary.get("auto_added") or [])
            _auto_note = ("" if not _auto_added else
                          "✚ added " + str(len(_auto_added)) + " approved new "
                          "rep(s) to their captainship: "
                          + ", ".join(
                              f"{a['name']} ({a['captain']}"
                              + (f", ✅ {a['approved_by']}"
                                 if a.get("approved_by") else "") + ")"
                              for a in _auto_added))
            # NEW OWNERS — people from the 'New Owners' bank who had their first
            # sales this week and were given a row (daily + weekly leaderboard)
            # in this run. Informational like the self-heal above: it WORKED, so
            # it doesn't gate — it's surfaced so an add is never silent. A bank
            # row we couldn't act on (unknown campaign, already on the board) is
            # listed too, because that one needs Eve.
            _no = _summary.get("new_owners") or {}
            _no_added = list(_no.get("added") or [])
            _no_flagged = list(_no.get("flagged") or [])
            _no_note = ""
            if _no_added:
                _no_note = ("✚ New Owners: " + str(len(_no_added))
                            + " added to the board — "
                            + ", ".join(f"{a['name']} ({a['campaign']})"
                                        for a in _no_added))
            if _no_flagged:
                _no_note += (("\n" if _no_note else "")
                             + "⚠ New Owners bank needs a look: "
                             + "; ".join(_no_flagged))
            # ROSTER SYNC — reps on a VA captainship roster with NO row on the
            # copy tab. The fill only fills EXISTING copy rows, so a rep added on
            # the VA but never added to the copy silently sums the total short
            # (Blue Mendoza / Starr, 2026-07-15). Diff the rosters by name and
            # GATE on it so it can never be a silent miss. Runs even under
            # --skip-compare: the rosters are present at 4am even before the VAs
            # key any sales. Advisory guard — must never crash the run.
            # ROSTER — the VA diff is RETIRED (Eve, 2026-08-10). It compared the
            # copy against the VA's own board and gated the run on anyone the
            # copy was missing; that board has not been updated in weeks, so the
            # diff no longer says anything about who is really on a captainship
            # — it would gate on last month's roster and stay silent about this
            # month's. Membership now comes from Tableau through the captainship
            # gate ([[project_new_owners]]): reps wait for a ✅ from Evelyn,
            # and `captainship.run_captainships` adds the approved ones.
            # `_missing_reps` stays as an (always empty) gate input so the
            # manifest/exit wiring below is untouched; what IS surfaced is how
            # many reps are still waiting for their checkmark — informational,
            # never a gate: a pending approval is a person's decision, not a
            # broken run.
            _missing_reps = []
            _pending_note = ""
            try:
                from automations.new_owners import bank as _nb, captain_gate as _cg
                _lws = _nb.open_log(ws.spreadsheet)
                _pend = _cg.pending_rows(_nb.log_entries(_lws))
                if _pend:
                    _pending_note = (
                        f"🕓 {len(_pend)} new captainship rep(s) waiting for a ✅ "
                        f"in #revision-emails: "
                        + ", ".join(f"{p['name']} ({p['scope']})"
                                    for p in _pend))
                    print("  " + _pending_note)
            except Exception:  # noqa: BLE001 — advisory must never fail the run
                pass
            # Cross-reference every owner/ICD pulled onto the board against the
            # 'Terminated ICDs' tab + ALERT the runner (advisory — prints to the
            # output + log, never removes a row). Folded into the manifest note.
            _term_note = None
            try:
                from automations.shared import terminated_icds as _ti
                _hits, _flag = _ti.alert_terminated(
                    _summary.get("owners") or [],
                    report_label="the Org Sales Board")
                if _hits:
                    _term_note = ("terminated ICD(s) still on the board (remove them): "
                                  + ", ".join(h["report_name"] for h in _hits))
            except Exception:  # noqa: BLE001 — advisory must never fail the run
                pass
            _compare_clean = True
            _compare_ndiff = 0
            _va_note = ""
            # The VA compare is DEFERRED to 9am CST (Megan 2026-07-14). Running it
            # straight after the 4am fill compared us against a VA tab the VAs had
            # not touched yet, so every cell we were simply AHEAD on counted as a
            # "difference": the fill logged compare=FLAGGED and closed INCOMPLETE
            # every single morning, which is exactly the kind of routine red that
            # trains everyone to ignore the board. The scheduled run now passes
            # --skip-compare, and report_id 'board_compare' runs the real compare at
            # 9am once the VAs have finished keying. A manual run still compares.
            if not args.dry_run and not args.real and not args.skip_compare:
                from automations.org_sales_board import compare
                _cmp = compare.run_compare()
                _compare_clean = _cmp["clean"]
                # gating disagreements = raw daily glitches + current-week derived
                # concerns (frozen + catch-all are report-only, never counted here)
                _compare_ndiff = (len(_cmp.get("glitches", []))
                                  + len(_cmp.get("derived", [])))
                # WHOLE-SHEET VA check — EVERY labeled cell incl. below row 1000,
                # name-matched so sort/row-order differences don't count (only
                # real value diffs). INFORMATIONAL: surfaced in the completion
                # email so the differences are visible without asking; does NOT
                # gate the run (Megan 2026-07-07).
                try:
                    _va_note = compare.format_va_check(compare.content_diff())
                except Exception as _e:  # noqa: BLE001 — never fail the run on this
                    _va_note = f"VA whole-sheet check errored ({type(_e).__name__})."
            # Standard failure manifest → Hub failure-help callout + a granular
            # "Retry failed only" button where the failure is one clean category
            # (--step captainships / --step daily); mixed/compare failures show
            # the help with no granular button (re-run via the normal Run).
            # --no-manifest: a surgical unattended re-pull leaves the day's
            # verdict exactly as the real board run left it (see the flag's help).
            if not (args.dry_run or args.no_manifest):
                try:
                    from automations.shared import run_manifest as _rm
                    if (_skipped or _failed_prog or _failed_caps
                            or not _compare_clean or _missing_reps or _dropped):
                        _failed_all = (
                            [f"section: {s}" for s in _skipped]
                            + [f"dropped day — {d}; its day-number row does "
                               f"not match real dates — run "
                               f"`{DAYNUM_FIX_CMD}`"
                               for d in _dropped]
                            + [f"program: {c}" for c in _failed_prog]
                            + [f"captainship: {c}" for c in _failed_caps]
                            + [f"roster: {m['name']} ({m['captain']} cap) has no "
                               "copy row — add it" for m in _missing_reps]
                            + ([] if _compare_clean
                               else [f"compare: {_compare_ndiff} cell(s) disagree "
                                     "with the VA tab"]))
                        # GRANULAR retry: re-run ONLY the failed sections and/or
                        # captainship parts, not the whole board. A failed CAPTAIN
                        # forces a full captainship re-run (can't subset by
                        # captain); failed PROGRAMS alone subset via --programs.
                        # A compare-only mismatch stays non-granular (a re-run
                        # can't fix a data disagreement).
                        if _failed_caps:
                            _cap_ra = ["--step", "captainships"]
                        elif _failed_prog:
                            _cap_ra = ["--step", "captainships",
                                       "--programs", ",".join(_failed_prog)]
                        else:
                            _cap_ra = None
                        if _skipped and _cap_ra:
                            _ra = ["--step", "daily",
                                   "--sections", ",".join(_skipped),
                                   "--with-captainships"]
                            if _failed_prog and not _failed_caps:
                                _ra += ["--programs", ",".join(_failed_prog)]
                        elif _skipped:
                            _ra = ["--step", "daily", "--sections", ",".join(_skipped)]
                        elif _cap_ra:
                            _ra = _cap_ra
                        else:
                            _ra = []   # compare-only mismatch — no granular re-run
                        _rm.write_manifest(
                            "org-sales-board", failed=_failed_all, retry_args=_ra,
                            kind="section",
                            note=f"{len(_failed_all)} part(s) missing this run."
                                 + (f" ⚠ {_term_note}" if _term_note else "")
                                 + (f"\n{_auto_note}" if _auto_note else "")
                                 + (f"\n{_no_note}" if _no_note else "")
                                 + (f"\n{_pending_note}" if _pending_note else "")
                                 + (f"\n{_va_note}" if _va_note else ""),
                            remediation=_rm.make_remediation(
                                reason=("Org Sales Board run is missing data — "
                                        + "; ".join(_failed_all) + "."),
                                fix="A skipped section/captainship pull is "
                                    "usually a flaky/slow Tableau load (a re-run "
                                    "often clears it) or a corrupted custom view "
                                    "(re-create it in Tableau if it keeps "
                                    "failing). A compare mismatch means the copy "
                                    "tab disagrees with the VA tab — check those "
                                    "cells. The parts that pulled cleanly ARE "
                                    "filled.",
                                link="",
                                message=("The Org Sales Board couldn't fully "
                                         "complete today — missing: "
                                         + "; ".join(_failed_all) + ". A re-run "
                                         "often clears a flaky Tableau load; if a "
                                         "view keeps failing it may need "
                                         "re-creating in Tableau.")))
                    elif (_term_note or _va_note or _auto_note or _no_note
                          or _pending_note):
                        # Clean run (nothing missing) — still record the whole-
                        # sheet VA check + any auto-added rep so the completion
                        # email shows them. failed=[] keeps it DONE, not INCOMPLETE.
                        _rm.write_manifest(
                            "org-sales-board", failed=[], kind="section", ok=True,
                            note=(("⚠ " + _term_note + "\n") if _term_note else "")
                                 + (_auto_note + "\n" if _auto_note else "")
                                 + (_no_note + "\n" if _no_note else "")
                                 + (_pending_note + "\n" if _pending_note else "")
                                 + _va_note)
                    else:
                        _rm.mark_clean("org-sales-board", kind="section")
                except Exception:
                    pass
            if (_skipped or _failed_prog or _failed_caps or not _compare_clean
                    or _missing_reps or _dropped):
                # RAN but with a note (missing pull or a VA-compare difference).
                # Exit 0 — NOT a hard failure: the manifest written above carries
                # the failed parts, so the orchestrator's verify marks this
                # INCOMPLETE → "Ran — with a note", not "Needs attention". (A
                # non-zero exit is treated as FAILED before verify even runs, so
                # returning 1 wrongly buried a VA-lag/1-cell diff as a failure.
                # "Missing data must not read as COMPLETED" still holds — the
                # manifest keeps it out of DONE; it just lands in the note bucket
                # instead of the fail bucket. Megan 2026-07-01.)
                print("=== daily fill INCOMPLETE (ran — with a note). "
                      f"skipped/failed section pull(s)={_skipped or 'none'}; "
                      f"failed captainship program pull(s)={_failed_prog or 'none'}; "
                      f"failed captainship fill(s)={_failed_caps or 'none'}; "
                      f"missing copy row(s)="
                      f"{[m['name'] for m in _missing_reps] or 'none'}; "
                      f"dropped day(s)={_dropped or 'none'}; "
                      f"compare={'clean' if _compare_clean else 'FLAGGED differences'}. "
                      "Re-run to retry the missing pull(s). ===")
                return 0
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
