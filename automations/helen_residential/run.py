"""Fill Helen Assefaw's tab on the ATT Program - Focus Report. Runs MONDAYS.

Why this exists as its own report
---------------------------------
Helen is a RESIDENTIAL Verizon Wireless ICD (Edge Concepts, Falls Church VA).
She is in NO AppStream office and in NO ATT-program Tableau view, so neither
`recruiting_report.run` nor `opt_phase` can ever put a number on her tab —
their sources are D2D/B2B and she is residential. Her tab uses the
Frontier/Verizon layout and is fed entirely by three weekly emails to
alphaletereporting (see `sources.py`).

Cadence: Monday, after `att_focus_raf`. Only ONE of the three sources has
landed by Monday — Madilyn's recruiting mail arrives Monday ~07:00. The rep
count comes Thursday night and the sales tracker runs 8-15 days behind its
week and sometimes skips an edition entirely. That is fine and is the whole
design: this scans a WIDE window every week and only ever writes cells that
are still EMPTY, so a late edition is picked up by the next Monday's run
without touching anything already filled. Re-running is always safe.

What it writes, and nothing else:
    Total Sales Frontier           <- RANKED Residential Wireless tracker
    Active Headcount on Scorecard  <- Residential Rep Count `Headcount`
    Headcount Beginning of week    <- Residential Rep Count `Existing`
    1ST BOOKED / 1ST SHOWED / 2ND BOOKED / 2ND SHOWED /
    New Starts Scheduled / New Starts Showed /
    Retention to Call list / Retention 1st showed Booked for 2nd
                                   <- Madilyn Komis' recruiting mail

Rows found by their column-B label, weeks by the date header — never by index.

These rows have NO source for her and stay blank on purpose (checked live
2026-08-17): Leaders, New Starts in classroom / by EOW, Personal Production,
Total Store Count Frontier, the Store rows, Approval, Canceled, Pending,
GIG %, VAS %, ABP %, Direct Deposit and the whole financial block. They are
Frontier-Events / Alphalete-downline metrics and she is in neither.

Usage:
    python -m automations.helen_residential.run
    python -m automations.helen_residential.run --dry-run
    python -m automations.helen_residential.run --days 120
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

# Emoji/arrows in progress lines must not blow up the Windows console (cp1252),
# the same guard every other report uses.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from gspread.utils import rowcol_to_a1

from automations.recruiting_report import fill
from automations.shared import email_ingest
from automations.helen_residential import sources as S

TAB = "Helen Assefaw"      # resolved by PREFIX — see _resolve_tab
DEFAULT_DAYS = 75          # wide enough to catch a tracker edition that is
                           # two weeks late, cheap enough to run weekly.


def _resolve_tab(sh, wanted: str):
    """The worksheet whose title is `wanted`, or that STARTS WITH it.

    The tab was renamed 'Helen Assefaw' -> 'Helen Assefaw (Vz)' the same day it
    was built, and an exact-title lookup died with WorksheetNotFound. Owners
    annotate these titles (campaign suffixes, initials), so match on the prefix
    and say which one was picked rather than failing on a cosmetic edit."""
    tabs = fill._retry(sh.worksheets)
    for ws in tabs:
        if ws.title.strip().lower() == wanted.strip().lower():
            return ws
    hits = [ws for ws in tabs
            if ws.title.strip().lower().startswith(wanted.strip().lower())]
    if len(hits) == 1:
        print(f"[helen] tab {hits[0].title!r} (matched prefix {wanted!r})")
        return hits[0]
    if not hits:
        raise RuntimeError(f"no tab named or starting with {wanted!r}")
    raise RuntimeError(f"{wanted!r} is ambiguous: {[w.title for w in hits]}")


def _rows_by_label(grid):
    out = {}
    for i, r in enumerate(grid, start=1):
        b = (r[1] if len(r) > 1 else "").strip()
        if b and b.lower() not in out:
            out[b.lower()] = i
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and report, write nothing.")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"Email window in days (default {DEFAULT_DAYS}).")
    ap.add_argument("--tab", default=TAB)
    args = ap.parse_args(argv)
    dry = args.dry_run
    today = dt.date.today()

    workdir = Path(tempfile.mkdtemp(prefix="helen-residential-"))
    print(f"[helen] window {args.days}d, workdir {workdir}", flush=True)

    # ---- gather -----------------------------------------------------------
    try:
        tr_files = email_ingest.fetch_all(
            S.TRACKER_SENDER, S.TRACKER_GLOBS, workdir,
            since_days=args.days, verbose=False, unique_by_message=True)
    except Exception as e:                                  # noqa: BLE001
        print(f"[helen] tracker fetch failed ({type(e).__name__}: {e})")
        tr_files = []
    try:
        rc_files = email_ingest.fetch_all(
            S.REPCOUNT_SENDER, S.REPCOUNT_GLOBS, workdir,
            since_days=args.days, verbose=False, unique_by_message=True)
    except Exception as e:                                  # noqa: BLE001
        print(f"[helen] rep-count fetch failed ({type(e).__name__}: {e})")
        rc_files = []

    units = S.parse_tracker(list(tr_files), today.year)
    heads = S.parse_rep_counts(list(rc_files))

    recruiting = {}
    try:
        M = email_ingest._connect()
        try:
            since = (today - dt.timedelta(days=args.days)).strftime("%d-%b-%Y")
            _t, data = M.search(None, f'(SINCE {since} FROM "{S.RECRUITING_SENDER}")')
            ids = sorted((data[0] or b"").split(), key=lambda b: int(b))

            def _fetch(i):
                _t, raw = M.fetch(i, "(RFC822)")
                return raw[0][1] if raw and raw[0] else None
            recruiting = S.parse_recruiting(ids, _fetch)
        finally:
            M.logout()
    except Exception as e:                                  # noqa: BLE001
        print(f"[helen] recruiting fetch failed ({type(e).__name__}: {e})")

    print(f"[helen] sources: {len(tr_files)} tracker pdf(s) -> {len(units)} "
          f"sales week(s); {len(rc_files)} rep count(s) -> {len(heads)} "
          f"headcount week(s); {len(recruiting)} recruiting week(s)")

    # ---- write ------------------------------------------------------------
    sh = fill.open_sheet()
    ws = _resolve_tab(sh, args.tab)
    grid = fill._retry(ws.get_all_values)
    cols = fill.find_sunday_columns(grid, header_row_idx=0)
    rows = _rows_by_label(grid)
    if not cols:
        print(f"[helen] {ws.title}: no date headers on row 1 — is C1 a SUNDAY?")
        return 1

    plan = {}      # week -> [(label, value, source)]
    for wk, rec in units.items():
        plan.setdefault(wk, []).append(
            ("Total Sales Frontier", rec["units"], rec["source"]))
    for wk, rec in heads.items():
        if "Headcount" in rec:
            plan.setdefault(wk, []).append(
                ("Active Headcount on Scorecard", rec["Headcount"], rec["source"]))
        if "Existing" in rec:
            plan.setdefault(wk, []).append(
                ("Headcount Beginning of week", rec["Existing"], rec["source"]))
    for wk, vals in recruiting.items():
        for _rx, label, kind in S.RECRUITING_COLS:
            v = S.to_number(vals.get(label, ""), kind)
            if v is not None:
                plan.setdefault(wk, []).append((label, v, "recruiting mail"))

    updates, filled, kept, nocol, norow = [], [], 0, [], set()
    for wk in sorted(plan):
        col = cols.get(wk)
        if col is None:
            nocol.append(str(wk))
            continue
        wrote = []
        for label, value, _src in plan[wk]:
            r = rows.get(label.lower())
            if r is None:
                norow.add(label)
                continue
            row = grid[r - 1] if r - 1 < len(grid) else []
            existing = row[col - 1] if col - 1 < len(row) else ""
            if str(existing).strip() != "":
                kept += 1
                continue
            updates.append({"range": rowcol_to_a1(r, col), "values": [[value]]})
            wrote.append(f"{label}={value}")
        if wrote:
            filled.append(f"  {wk}  {rowcol_to_a1(1, col)[:-1]}  " + ", ".join(wrote))

    for line in filled:
        print(line)
    if nocol:
        print(f"[helen] {len(nocol)} week(s) with no column on the tab: "
              f"{nocol[:4]}{' …' if len(nocol) > 4 else ''}")
    if norow:
        print(f"[helen] label(s) not on the tab: {sorted(norow)}")
    print(f"[helen] {len(updates)} cell(s) to fill, {kept} already filled (kept)")

    if not updates:
        print("[helen] nothing new — every week the sources cover is already "
              "on the tab")
        return 0
    if dry:
        print("[helen] DRY RUN — nothing written")
        return 0
    fill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
    print(f"[helen] wrote {len(updates)} cell(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
