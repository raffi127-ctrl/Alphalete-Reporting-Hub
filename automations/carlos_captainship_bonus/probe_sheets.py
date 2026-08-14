"""Inspect the Carlos bonus source view: what worksheets it offers, and what
shape each one actually has.

READ-ONLY with respect to report data: it downloads crosstabs to a scratch dir
and writes its findings to a DIAGNOSTIC tab. It never touches the
*All In One - CARLOS* sheet.

Why this exists: when ATTTRACKER-B2B was restructured on 2026-08-13 the old
`CaptainsTeam` sheet vanished and every worksheet on the replacement view had
been renamed, so the pull failed on the FIRST worksheet and its error only
named that one. Reading the failure through `lucy logtail` didn't help either —
the result cell caps at ~470 chars and the dialog's name list is one long line,
so it always came back truncated.

Two modes:

  # names only (fast, no downloads) — one per line, prefixed XTAB:
  lucy rerun probe_carlos_bonus_sheets --machine "Lucy 2"
  lucy logtail <that log> XTAB 15

  # names + column headers + sample rows for the candidate worksheets
  lucy rerun probe_carlos_bonus_sheets --dump --machine "Lucy 2"
  ...then read the '<DIAG_TAB>' tab (too big for logtail).

Re-run this after any republish of the workbook, then re-map
tableau_pull.SHEETS. [[project_carlos-captainship-bonus-view-dead]]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

# Same scratch workbook the ATT Order Log probe writes to — a diagnostics-only
# book, so a new tab here is never someone's filled-in work.
DIAG_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
DIAG_TAB = "Carlos Bonus Probe"

# Worksheets worth dumping when --dump is on: the ones whose names suggest they
# could carry what tableau_pull needs. Names come from the 2026-08-13 listing.
# The (LW)/(LW2) pair matters: the plain "_Captain View" sales sheet ignores the
# week param and always renders the IN-PROGRESS week as day columns, so the
# completed week has to come from a last-week sheet.
CANDIDATES = (
    "Sales By ICD (ATT) (V2)_Captain View",
    "Sales By ICD (ATT) (V2) (LW2)",
    "ICD Summary - ATT (V2) (LW)_Captain's View",
    "ICD Summary - ATT (V2) (TW) (3)",
    "ICD Churn Rate- Captain's View",
    "Churn, Activation and Tiers",
    "Captains View - Non pmt%",
    "Activation Rate- Captains View",
)

# The captain-team filter, same field captainship_drafts drives (proven live
# 2026-07-22). Applying it is what collapses the new views' CRU/IRU split into a
# single "Grand Total" row per team — which is the shape the old, now-deleted
# 'Captain Team Check' worksheets had.
TEAM_FIELD = "B2B Captain's Teams (SFDC)"
TEAM_VALUE = "Carlos's Team"

# GROUND TRUTH for identifying the replacement worksheet. These are the values
# the report itself wrote into the 'Carlos B2B Captainship' tab for WE 8.9 — the
# last week that filled BEFORE the workbook was restructured. A candidate sheet
# that reproduces them (pinned to that week, team-filtered) is the replacement;
# one that doesn't, isn't. Beats guessing from worksheet names, which no longer
# resemble the old ones at all.
FINGERPRINT_WEEK_SAT = "2026-08-08"      # the Saturday of WE 8.9
FINGERPRINT_TOTAL = 827
FINGERPRINT_REPS = {
    "atef choudhury": 221, "carlos hidalgo": 90, "george hipolito": 101,
    "jamis garay": 87, "joey ramirez": 81, "justin wood": 70,
    "kinsey guenther": 76, "joseph eckhart": 48, "sabrina alicea": 34,
    "gary whitaker": 19,
}


def _fingerprint(rows, rec) -> None:
    """Does this crosstab carry the WE 8.9 per-owner numbers the report already
    wrote? Scans EVERY cell of each row for the expected integer, so it works
    regardless of which column ends up holding the weekly total."""
    from automations.carlos_captainship_bonus import tableau_pull as T

    def _is(cell, name) -> bool:
        # startswith, not equality: ACTIVATIONRATES' member is
        # "CARLOS HIDALGO\r [alphalete …]" — the office is glued onto the name.
        c = T._norm(str(cell).replace("\r", " ").replace("\n", " "))
        return c == name or c.startswith(name + " ")

    found, missing = [], []
    for name, want in sorted(FINGERPRINT_REPS.items()):
        row = next((r for r in rows if any(_is(c, name) for c in r[:3])), None)
        if row is None:
            missing.append(f"{name}=<no row>")
            continue
        hit = next((f"col{ci}" for ci, c in enumerate(row)
                    if T._parse_int(c) == want and (c or "").strip()), None)
        (found if hit else missing).append(
            f"{name}={want}@{hit}" if hit else
            f"{name}!={want} (row={[str(c)[:10] for c in row[:8]]})")
    rec(f"  FINGERPRINT: {len(found)}/{len(FINGERPRINT_REPS)} owners matched WE 8.9")
    if found:
        rec("    hit : " + ", ".join(found[:10]))
    if missing:
        rec("    miss: " + ", ".join(missing[:4]))


def _upload(lines) -> None:
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(DIAG_SHEET_ID)
    try:
        ws = sh.worksheet(DIAG_TAB)
    except Exception:  # noqa: BLE001 — tab may not exist yet
        ws = sh.add_worksheet(title=DIAG_TAB, rows=800, cols=1)
    ws.clear()
    ws.update("A1", [[ln[:900]] for ln in lines[:800]])


def main(argv=None) -> int:
    from automations.carlos_captainship_bonus import tableau_pull as T
    from automations.recruiting_report.opt_phase import list_crosstab_sheets

    ap = argparse.ArgumentParser(prog="carlos_captainship_bonus.probe_sheets")
    ap.add_argument("--url", action="append", default=None,
                    help="view to probe; repeatable. Default: the report's. "
                         "Names-only listing runs for EVERY url given, so one "
                         "run can settle 'which dashboard did these worksheets "
                         "move to' across several candidates. --dump uses the "
                         "FIRST url only.")
    ap.add_argument("--dump", action="store_true",
                    help="also download each CANDIDATE worksheet and print its "
                         "columns + first rows")
    ap.add_argument("--no-upload", action="store_true",
                    help="print only; don't write the diag tab")
    ap.add_argument("--team", action="store_true",
                    help=f"apply the {TEAM_FIELD!r}={TEAM_VALUE!r} URL filter")
    ap.add_argument("--cached", action="store_true",
                    help="skip Tableau entirely: dump the crosstab CSVs the LAST "
                         "GOOD run left in CACHE_DIR. These are the deleted "
                         "worksheets' exact output — the spec any replacement has "
                         "to reproduce.")
    ap.add_argument("--week-sat", default=None, metavar="YYYY-MM-DD",
                    help="pin the activation week to this SATURDAY (ISO only — "
                         "M/D/YYYY silently no-ops) instead of last cycle's")
    ap.add_argument("--no-week", action="store_true",
                    help="never append the week param. The (LW)/(LW2) sheets are "
                         "already scoped to last week, so pinning a week on top "
                         "may be what empties them.")
    ap.add_argument("--sheet", action="append", default=None, metavar="NAME",
                    help="dump these EXACT worksheet names instead of CANDIDATES; "
                         "repeatable. Lets --dump work on any view, not just the "
                         "report's own.")
    ap.add_argument("--only", action="append", default=None, metavar="SUBSTR",
                    help="restrict --dump to CANDIDATES containing SUBSTR "
                         "(case-insensitive); repeatable. Each sheet costs "
                         "5-10 min, so narrow it or blow the timeout.")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    buf = []

    def rec(msg=""):
        print(msg, flush=True)
        buf.append(str(msg))

    from urllib.parse import quote

    urls = args.url or [T.VIEW]

    def _url(week_sat=None) -> str:
        """Base view + optional team filter + optional pinned activation week."""
        parts = []
        if args.team:
            parts.append(f"{quote(TEAM_FIELD)}={quote(TEAM_VALUE)}")
        if week_sat:
            parts.append(f"{T.WEEK_FIELD}={week_sat}")
        parts.append(":iid=1")
        return f"{urls[0]}?" + "&".join(parts)

    rec(f"Carlos bonus source probe @ {dt.datetime.now().isoformat(timespec='seconds')}")
    rec(f"team filter: {TEAM_VALUE!r}" if args.team else "team filter: (none)")
    rec(f"week pinned to Sat: {args.week_sat or '(last cycle)'}")

    if args.cached:
        # The four files pull_carlos() writes every run. They are still whatever
        # the LAST SUCCESSFUL run downloaded, so after the source view died they
        # are the only surviving record of the deleted worksheets' shape.
        import time
        names = {"sales": "cb_owner_sales.csv",
                 "check2": "captain_team_check_2.csv",
                 "check4": "captain_team_check_4.csv",
                 "metrics": "cb_owner_metrics.csv"}
        for key, fn in names.items():
            p = Path(T.CACHE_DIR) / fn
            rec("")
            rec(f"=== {key}: {T.SHEETS[key]!r}  ({fn}) ===")
            if not p.exists():
                rec("  MISSING — no cached copy on this machine")
                continue
            age_h = (time.time() - p.stat().st_mtime) / 3600.0
            rec(f"  downloaded {age_h:.1f}h ago ({p.stat().st_size} bytes)")
            try:
                rows = T._read(p)
            except Exception as e:  # noqa: BLE001
                rec(f"  !! unreadable: {type(e).__name__}: {str(e)[:120]}")
                continue
            if not rows:
                rec("  (empty)")
                continue
            rec(f"  {len(rows)} rows, {len(rows[0])} columns")
            for c, h in enumerate(rows[0]):
                rec(f"  COL [{c:>2}] {h!r}")
            rec("  first 15 data rows:")
            for r in rows[1:16]:
                rec("    " + " | ".join(str(c or "")[:26] for c in r[:10]))
        if not args.no_upload:
            try:
                _upload(buf)
                rec("")
                rec(f"findings -> {DIAG_TAB!r} tab")
            except Exception as e:  # noqa: BLE001
                print(f"diag upload failed: {e}", flush=True)
        return 0

    names = []
    for u in urls:
        rec("")
        rec(f"### view: {u}")
        try:
            found = list_crosstab_sheets(u, verbose=False)
        except Exception as e:  # noqa: BLE001 — a dead view must not kill the run
            rec(f"  !! could not open: {type(e).__name__}: {str(e)[:160]}")
            continue
        rec(f"  dialog offers {len(found)} worksheet(s):")
        for n in found:
            rec(f"XTAB: {n}")
        hit = [w for w in T.SHEETS.values() if w in found]
        rec(f"  MATCHES the report's needs: {len(hit)}/{len(T.SHEETS)}"
            + (f" -> {hit}" if hit else ""))
        if u == urls[0]:
            names = found

    rec("")
    for key, want in sorted(T.SHEETS.items()):
        rec(f"NEED: {key:<8} {want!r} -> "
            f"{'PRESENT' if want in names else 'MISSING'} (on first url)")

    if args.dump:
        from automations.fiber_activations import pull as P
        from automations.shared.tableau_patchright import download_crosstab_patchright
        today = dt.date.today()
        scratch = Path(T.CACHE_DIR) / "probe"
        scratch.mkdir(parents=True, exist_ok=True)
        wanted = args.sheet or CANDIDATES
        if args.only:
            subs = [s.lower() for s in args.only]
            wanted = [c for c in CANDIDATES if any(s in c.lower() for s in subs)]
            rec("")
            rec(f"--only {args.only} -> dumping {len(wanted)}: {list(wanted)}")
        for i, sheet in enumerate(wanted):
            if sheet not in names:
                rec("")
                rec(f"=== {sheet!r}: NOT OFFERED by this view, skipping ===")
                continue
            rec("")
            rec(f"=== {sheet!r} ===")
            # The per-rep sales sheet is the only one that needs the week pinned;
            # the rate sheets degenerate if you pin it (see tableau_pull._rates_url).
            # An explicit --week-sat wins everywhere: the is_sales guess only
            # knows this report's own view, and we now probe others too.
            is_sales = "Sales By ICD" in sheet or "ICD Summary" in sheet
            if args.no_week:
                sat = None
            elif args.week_sat:
                sat = args.week_sat
            else:
                sat = P.cycle_saturday(today).isoformat() if is_sales else None
            url = _url(sat)
            rec(f"  url: {url}")
            out = scratch / f"probe_{i}.csv"
            try:
                download_crosstab_patchright(url, sheet, out, verbose=False)
                rows = T._read(out)
            except Exception as e:  # noqa: BLE001 — one bad sheet must not kill the probe
                rec(f"  !! download/parse failed: {type(e).__name__}: {str(e)[:160]}")
                for ln in traceback.format_exc().splitlines()[-4:]:
                    rec("    " + ln[:180])
                continue
            if not rows:
                rec("  (empty export)")
                continue
            rec(f"  {len(rows)} rows, {len(rows[0])} columns")
            for c, h in enumerate(rows[0]):
                rec(f"  COL [{c:>2}] {h!r}")
            rec("  first 12 data rows:")
            for r in rows[1:13]:
                rec("    " + " | ".join(str(c or "")[:26] for c in r[:10]))
            # Does Carlos' team actually appear, and where?
            hits = [(ri, r) for ri, r in enumerate(rows[1:], 1)
                    if any(T._norm(c) == T.TEAM for c in r[:3])]
            rec(f"  rows whose first 3 cols contain {T.TEAM!r}: {len(hits)}")
            for ri, r in hits[:6]:
                rec(f"    [row {ri}] " + " | ".join(str(c or "")[:26] for c in r[:10]))
            _fingerprint(rows, rec)

    if not args.no_upload:
        try:
            _upload(buf)
            rec("")
            rec(f"findings -> {DIAG_TAB!r} tab")
        except Exception as e:  # noqa: BLE001 — never fail the probe on upload
            print(f"diag upload failed: {e}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
