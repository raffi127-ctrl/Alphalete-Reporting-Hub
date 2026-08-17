"""One-off: backfill a Carlos-1on1s ICD tab's WEEKLY SALE rows from the
week-windowed B2B SALES SUMMARY.

Why this exists
---------------
Amos White Jr joined the *Carlos 1on1s - Focus Report* roster on 2026-08-17, so
only WE 8/16 got filled; every earlier column on his tab is blank. Carlos's OPT
engine can't go back on its own:

  * `d2d1` (rows 29, 33-36, 40, 41) is hardwired to "B2B - Current Week"
    (`week_filter_field=None`) — there is no way to aim it at an older week.
  * cancel / activation / churn / penetration / Direct Deposit are ROLLING
    windows (6-week average, 31-60 day buckets, office-age cohorts). They have
    no notion of "week of 6/14" at all.
  * `ATTTRACKER-B2B / SALESSUMMARY` takes its window from its own Start Date /
    End Date boxes, so it — and only it — can be pinned to any past Mon..Sun.

Same shape as the ATT-side `att_backfill_sales_2026-08-17.py`, pointed at the
B2B source instead of PRODUCT SALES SUMMARY (which is Raf's residential view and
does NOT contain the B2B owners — checked, Amos is in none of the cached
`ps_*.csv`).

Summing an owner's own rep rows in that crosstab reproduces the official B2B
numbers exactly. Checked against WE 2026-08-16, already in the Sheet from the
live run:

    Amos White Jr    NI 9 · VOIP 0 · NL 32 · AIR 3   apps 44  hc 8
                     Personal Production "3 NI / 5 NL"

all six exact, including the blank Voice cell (a 0 is written as blank, which is
what the live pipeline does).

What it writes
--------------
Only the rows a date-windowed crosstab can honestly answer:

    Active Headcount on Tableau · New Internets · Voice Sales · Wireless
    · New Lines · Personal Production

Total Apps (37) and the two AVG rows (38, 39) are LEFT ALONE: in every unfilled
column they still hold the template's own formulas (`=SUM(U33:U36)`,
`=iferror(U37/U29,0)`, `=IFERROR(U33/U29,0)`), which recompute the moment rows
29/33-36 land. The live pipeline replaces them with computed values; a backfill
has no reason to.

Everything else in the OPT block — Scorecard Ranking, National AVG Apps,
0-30 Day Cancel Rate, Activation %, the five churn rows, Penetration, Direct
Deposit — comes from rolling-window views with no week control and is NOT
recoverable for a past week. Those cells are left untouched, never guessed.

Rows 2-23 (the recruiting funnel) are a separate matter entirely: Amos has no
AppStream office under Raf's login, so there is no source for them in any week.
See office-mapping-carlos.json → sales_only.

Never overwrites: a cell that already holds anything (a value OR a formula) is
skipped and logged.

Rows are found by their column-B label and weeks by the date header, so this
survives a template that shifts rows around.

Usage
-----
    # 1. download the week-pinned crosstabs (resumable — skips cached weeks)
    python output/carlos_b2b_backfill_sales_2026-08-17.py --download

    # 2. dry run: parse the cache, show what would land
    python output/carlos_b2b_backfill_sales_2026-08-17.py

    # 3. write
    python output/carlos_b2b_backfill_sales_2026-08-17.py --write
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# CAPTAINSHIP has to be set BEFORE `fill` is imported: fill.SPREADSHEET_ID is
# resolved at import time, so setting it later leaves us pointed at Raf's sheet
# (the wrong-sheet bug that wore a missing-tab costume in carlos_noah_nds).
os.environ.setdefault("CAPTAINSHIP", "Carlos")

from gspread.utils import rowcol_to_a1  # noqa: E402

from automations.recruiting_report import fill  # noqa: E402
from automations.recruiting_report.opt_phase_carlos import (  # noqa: E402
    VIEWS, download_view_crosstab, metric_row_for_tab,
)
from automations.shared import b2b_sales_summary as B2BSS  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEFAULT_TAB = "Amos White Jr"
DEFAULT_CACHE = Path(__file__).resolve().parent / "_carlos_b2b_weeks"

# Product label (from b2b_sales_summary.PRODUCT_COLUMNS) -> the column-B label
# of the sheet row it belongs in. Label variants mirror ROW_TO_LABEL in
# opt_phase_carlos: a few Carlos tabs abbreviate these.
PRODUCT_TO_LABEL = [
    ("NI",   "New Internets"),
    ("VOIP", ("Voice Sales", "Voice Count")),
    ("NL",   ("Wireless", "Wireless Sales")),
    ("AIR",  ("New Lines", "AIR / AWB")),
]
HEADCOUNT_LABEL = "Active Headcount on Tableau"
PP_LABEL = "Personal Production"


def _read_crosstab(path: Path) -> list:
    """Tableau crosstabs are UTF-16, tab-delimited. Parse with csv, NOT
    splitlines: the 'Owner & Office' cell holds a real newline inside quotes
    ('"AMOS WHITE JR.\\n [eagles peak enterprises, inc.]"') and naive line
    splitting tears every owner row in half."""
    raw = path.read_text(encoding="utf-16")
    return list(csv.reader(io.StringIO(raw), delimiter="\t"))


def _num(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _norm_owner(s: str) -> str:
    """Owner cells arrive as 'AMOS WHITE JR.\\n [eagles peak enterprises, inc.]'.
    Strip the office suffix and the punctuation Tableau's spelling carries — the
    tab is 'Amos White Jr', the crosstab 'Amos White Jr.'."""
    s = re.sub(r"\[.*?\]", "", (s or "").replace("\n", " "))
    s = re.sub(r"[^a-z0-9 ]", "", s.lower())
    return " ".join(s.split())


def office_week(path: Path, owner: str) -> dict:
    """One office's totals for the Mon..Sun window this crosstab was pinned to.

    Reads the 'Total Volume' row of each rep's 3-row measure block — the
    like-for-like row with the sale counts the old source gave (NOT Total
    Activations). Same choice b2b_sales_summary.MEASURE_ROW documents.
    """
    rows = _read_crosstab(path)
    if not rows:
        return {"values": {}, "headcount": 0, "personal_production": "",
                "expanded": False}
    headers = [(h or "").strip() for h in rows[0]]
    lower = [h.lower() for h in headers]
    if "rep" not in lower:
        # No Rep column == the Owner->Rep hierarchy was never expanded, so this
        # export is owner-level. Reading it would silently pass owner totals off
        # as personal production. Refuse it instead.
        return {"values": {}, "headcount": 0, "personal_production": "",
                "expanded": False}
    rep_i = lower.index("rep")
    target = _norm_owner(owner)

    totals = {label: 0 for label, _ in B2BSS.PRODUCT_COLUMNS}
    sold: set = set()
    personal = None
    cur_owner = cur_rep = ""
    for r in rows[1:]:
        if len(r) < 3:
            continue
        o = (r[0] or "").strip()
        if o:
            cur_owner = o
        rep = (r[rep_i] or "").strip() if rep_i < len(r) else ""
        if rep:
            cur_rep = rep
        if _norm_owner(cur_owner) != target:
            continue
        if not cur_rep or cur_rep.lower() in ("total", "grand total"):
            continue
        if (r[2] or "").strip() != B2BSS.MEASURE_ROW:
            continue
        rec = {}
        for label, cols in B2BSS.PRODUCT_COLUMNS:
            s = 0
            for c in cols:
                if c in headers:
                    i = headers.index(c)
                    if i < len(r):
                        s += _num(r[i])
            rec[label] = s
        if sum(rec.values()) <= 0:
            continue
        for k, v in rec.items():
            totals[k] += v
        # 'Active Headcount on Tableau' is d2d1's 'Rep Count' = reps with at
        # least one sale in the week. Same definition the ATT backfill uses.
        sold.add(cur_rep.lower())
        if _norm_owner(cur_rep) == target:      # the owner's own production
            personal = rec
    return {
        "values": totals,
        "total_apps": sum(totals.values()),
        "headcount": len(sold),
        "personal_production": B2BSS.format_pp(personal) if personal else "",
        "expanded": True,
    }


def _tab_weeks(grid: list) -> dict:
    return fill.find_sunday_columns(grid, header_row_idx=0)


def _last_completed_sunday(today: dt.date) -> dt.date:
    """The WE Sunday of the most recently COMPLETED week — same rule as
    opt_phase_carlos._current_we_sunday."""
    days_back = (today.weekday() + 1) % 7 or 7
    return today - dt.timedelta(days=days_back)


def _cached_and_expanded(path: Path) -> bool:
    """True only if `path` holds a crosstab taken WITH the Owner→Rep hierarchy
    expanded (i.e. it has a `Rep` column).

    The expand is a pixel click on a canvas-painted `+` and it misses sometimes
    — on the first sweep 8 of 19 weeks came back owner-level, a ~41KB file
    instead of ~500KB. Those are worthless here (owner totals can't tell you the
    ICD's own production, or how many reps sold), so an unexpanded cache counts
    as NOT cached and gets re-fetched on the next --download. That makes the
    whole thing self-healing on a re-run instead of needing a hand-built week
    list."""
    if not path.exists():
        return False
    try:
        rows = _read_crosstab(path)
    except Exception:      # noqa: BLE001 — truncated/half-written file
        return False
    if not rows:
        return False
    return "rep" in [(h or "").strip().lower() for h in rows[0]]


def download_weeks(weeks: list, cache: Path, force: bool = False) -> None:
    """Pull one SALESSUMMARY crosstab per week into `cache`. Resumable: a week
    already on disk is skipped, so a session that dies halfway (or a run that
    walks into the mini's 30-minute job cap) can just be re-run."""
    from automations.shared.tableau_patchright import tableau_session

    pp_view = next(v for v in VIEWS if v.key == "personal_production")
    cache.mkdir(parents=True, exist_ok=True)
    todo = [w for w in weeks
            if force or not _cached_and_expanded(cache / f"b2bss_{w}.csv")]
    if not todo:
        print("all weeks already cached — nothing to download")
        return
    print(f"downloading {len(todo)} week(s): {todo[0]} … {todo[-1]}", flush=True)
    with tableau_session(verbose=True) as page:
        for i, w in enumerate(todo, start=1):
            out = cache / f"b2bss_{w}.csv"
            start, end = B2BSS.week_bounds(dt.date.fromisoformat(w))
            print(f"\n[{i}/{len(todo)}] WE {w}  window {start} → {end}",
                  flush=True)
            try:
                download_view_crosstab(
                    pp_view, out, week=dt.date.fromisoformat(w), page=page,
                    pre_download_hook=B2BSS.expand_hook(start, end))
                print(f"  ✓ saved {out.name} ({out.stat().st_size} bytes)",
                      flush=True)
            except Exception as e:   # noqa: BLE001 — one bad week must not
                                     # cost the other eighteen
                print(f"  ✗ {w}: {type(e).__name__}: {str(e)[:200]}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tab", default=DEFAULT_TAB, help="Sheet tab name.")
    ap.add_argument("--owner", help="Owner name in the crosstab, if it differs "
                                    "from the tab name. Default: the tab name "
                                    "(punctuation is ignored when matching).")
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE),
                    help="Where b2bss_YYYY-MM-DD.csv crosstabs live.")
    ap.add_argument("--from", dest="frm", help="Earliest WE Sunday to touch. "
                                               "Default: the tab's first week.")
    ap.add_argument("--to", dest="to", help="Latest WE Sunday to touch. "
                                            "Default: last completed week.")
    ap.add_argument("--download", action="store_true",
                    help="Fetch the missing weeks from Tableau first. Needs a "
                         "Tableau session.")
    ap.add_argument("--redownload", action="store_true",
                    help="With --download: re-fetch weeks already cached.")
    ap.add_argument("--write", action="store_true",
                    help="Actually write. Default is a dry run.")
    args = ap.parse_args()

    owner = args.owner or args.tab
    cache = Path(args.cache_dir)
    dry = not args.write

    sh = fill.open_sheet()
    ws = fill._retry(sh.worksheet, args.tab)
    # TWO renders, on purpose.
    #  * FORMATTED for the layout: row 1's WE headers are a `=prev+7` chain, so
    #    a FORMULA render hands find_sunday_columns '=C1+7' and it finds no
    #    weeks at all.
    #  * FORMULA for the occupancy check: rows 37-39 hold formulas that DISPLAY
    #    as '0'/'0.00'. Both renders see them as non-empty, so the guard works
    #    either way, but the formula text makes the [kept: …] log honest about
    #    what is actually in the cell.
    grid = fill._retry(ws.get_all_values)
    raw = fill._retry(ws.get_all_values, value_render_option="FORMULA")
    sunday_to_col = _tab_weeks(grid)
    if not sunday_to_col:
        print(f"[SKIP] {args.tab}: no WE date headers in row 1")
        return 1
    col_b = [r[1] if len(r) > 1 else "" for r in grid]

    last = (dt.date.fromisoformat(args.to) if args.to
            else _last_completed_sunday(dt.date.today()))
    first = dt.date.fromisoformat(args.frm) if args.frm else min(sunday_to_col)
    weeks = sorted(w for w in sunday_to_col if first <= w <= last)
    if not weeks:
        print("no week columns in range")
        return 1

    if args.download:
        download_weeks([w.isoformat() for w in weeks], cache,
                       force=args.redownload)

    # Label -> row, resolved once against THIS tab's column B.
    rows = {}
    for _plabel, label in PRODUCT_TO_LABEL:
        rows[_plabel] = metric_row_for_tab(col_b, label)
    hc_row = metric_row_for_tab(col_b, HEADCOUNT_LABEL)
    pp_row = metric_row_for_tab(col_b, PP_LABEL)

    updates, log = [], []
    for sunday in weeks:
        col = sunday_to_col[sunday]
        f = cache / f"b2bss_{sunday.isoformat()}.csv"
        if not f.exists():
            log.append(f"  {sunday}  no crosstab cached — run --download")
            continue
        res = office_week(f, owner)
        if not res["expanded"]:
            log.append(f"  {sunday}  crosstab has no Rep column (the Owner→Rep "
                       f"expand missed) — REFUSED, re-download this week")
            continue
        if not res["total_apps"] and not res["headcount"]:
            log.append(f"  {sunday}  no rows for {owner!r} — skipped "
                       f"(office likely wasn't selling yet)")
            continue

        cells = [(rows[p], f"{p}", v) for p, v in res["values"].items()]
        cells.append((hc_row, HEADCOUNT_LABEL, res["headcount"]))
        if res["personal_production"]:
            cells.append((pp_row, PP_LABEL, res["personal_production"]))

        wrote, held = [], []
        for r, name, value in cells:
            if r is None:
                held.append(f"{name}=NO ROW")
                continue
            # A 0 is written as blank — that's what the live pipeline does
            # (Amos's WE 8/16 Voice cell is empty, not '0', and Total Apps
            # still sums to 44).
            if value in (0, "", None):
                continue
            existing = (raw[r - 1][col - 1]
                        if r - 1 < len(raw) and col - 1 < len(raw[r - 1])
                        else "")
            if str(existing).strip() != "":
                held.append(f"{name} already {str(existing)[:24]!r}")
                continue
            updates.append({"range": rowcol_to_a1(r, col), "values": [[value]]})
            wrote.append(f"{name}={value}")
        log.append(f"  {sunday}  col {col}  " + ", ".join(wrote)
                   + (f"   [kept: {'; '.join(held)}]" if held else ""))

    print(f"\n{'DRY RUN' if dry else 'WRITE'} — {args.tab} "
          f"(crosstab owner {owner!r})")
    for line in log:
        print(line)
    print(f"{len(updates)} cell(s) to fill")
    if updates and not dry:
        fill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        print("written — rows 37/38/39 recompute from their own formulas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
