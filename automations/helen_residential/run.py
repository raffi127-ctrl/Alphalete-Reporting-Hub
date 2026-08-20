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

A hole in a row this DOES own is invisible on the tab -- it looks exactly like
the blanks above. So every run also checks the weeks it could still repair and,
when one is past its source's normal lag, pings by manifest `kind="source"` and
still exits 0 (Eve's rule: a late source that costs rows must not leave the Hub
card red for weeks). A clean run closes the notice by itself.

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

# Its OWN manifest id, never the report's: the wrapper marks that one clean at
# the end of every good run and would erase this notice.
SOURCE_MANIFEST_ID = "helen_residential_sources"

# The rows this module owns -> (the mail that feeds it, how many CLOSED weeks
# of lag are NORMAL before an empty cell counts as overdue).
#   tracker  : runs 8-15 days behind its Saturday and sometimes skips an
#              edition entirely, so a hole younger than two closed weeks is
#              just the source being itself.
#   rep count: lands the Thursday AFTER its week closes, so by the next Monday
#              run it should be there -- one week of slack is enough.
OWNED_ROWS = {
    "Total Sales Frontier": (
        "RANKED Residential Telecom Tracker PDF (anowrouzi@aptel.com), "
        "middle 'Residential Wireless' table", 2),
    "Active Headcount on Scorecard": (
        "Residential Rep Count values.xlsx (rarchey@thesmartcircle.com), "
        "sheet 'ICD Owner Snapshot', column Headcount", 1),
    "Headcount Beginning of week": (
        "Residential Rep Count values.xlsx (rarchey@thesmartcircle.com), "
        "sheet 'ICD Owner Snapshot', column Existing", 1),
}


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


def _overdue_holes(grid, cols, rows, written, days, today):
    """{label: [WE-Sunday, ...]} -- cells this module owns that are STILL empty
    and are already past their source's normal lag.

    Bounded by the same window the run scans: those are exactly the weeks a
    late edition could still repair. Anything older is out of this report's
    reach and re-flagging it every Monday would be noise, not a signal."""
    last_closed = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    floor = today - dt.timedelta(days=days)
    holes = {}
    for label, (_src, lag) in OWNED_ROWS.items():
        r = rows.get(label.lower())
        if r is None:
            continue
        cutoff = last_closed - dt.timedelta(days=7 * lag)
        for wk in sorted(cols):
            col = cols[wk]
            if not (floor <= wk <= cutoff):
                continue
            if (r, col) in written:            # filled by THIS run
                continue
            row = grid[r - 1] if r - 1 < len(grid) else []
            val = row[col - 1] if col - 1 < len(row) else ""
            if str(val).strip() == "":
                holes.setdefault(label, []).append(wk)
    return holes


def _fmt_weeks(weeks) -> str:
    # never %-m/%-d -- that is Mac-only and this has to run on Windows too
    return ", ".join(f"{w.month}/{w.day}" for w in weeks)


def _source_manifest(holes: dict, log=print) -> None:
    """Ping (or clear) the notice for her weekly mail sources.

    Not a failure: the rest of the tab filled, so the Hub card stays GREEN and
    the step exits 0. But a blank cell in her OPT block is indistinguishable
    from the dozen cells that are blank on purpose, so without this the only
    way anyone finds out is by reading the tab."""
    try:
        from automations.shared import run_manifest as _rm
    except Exception as e:                                  # noqa: BLE001
        log(f"[helen] manifest unavailable ({type(e).__name__}: {e})")
        return
    try:
        if not holes:
            _rm.mark_clean(SOURCE_MANIFEST_ID, kind="source")
            return
        why = [f"{lab} - no edition covering {_fmt_weeks(wks)} "
               f"({OWNED_ROWS[lab][0]})"
               for lab, wks in sorted(holes.items())]
        ask = "; ".join(
            f"{OWNED_ROWS[lab][0].split(' (')[0]} for week(s) ending "
            f"{_fmt_weeks(wks)}" for lab, wks in sorted(holes.items()))
        _rm.write_manifest(
            SOURCE_MANIFEST_ID, failed=sorted(holes), retry_args=[],
            kind="source",
            note=("Helen Assefaw (Vz) - " + "; ".join(why) + ". The rest of "
                  "her tab is filled; only these cells are missing."),
            remediation=_rm.make_remediation(
                reason="The weekly mail behind those rows never arrived for "
                       "those weeks, or arrived without her row on it. She is "
                       "residential Verizon, so there is no Tableau or "
                       "AppStream fallback -- the mail IS the source.",
                fix="Ask the sender for the missing edition. When it lands, "
                    "re-run `python -m automations.helen_residential.run` (or "
                    "just wait for Monday): it writes ONLY empty cells, so "
                    "re-running can never overwrite anything.",
                message=("Hi -- we're missing the " + ask + ". Could you "
                         "resend it to alphaletereporting@gmail.com? "
                         "Thanks!")))
        log("[helen] ! source ping: " + "; ".join(why))
    except Exception as e:                                  # noqa: BLE001
        log(f"[helen] manifest ping failed ({type(e).__name__}: {e})")


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
    tr_files = []
    for sender in S.TRACKER_SENDERS:
        try:
            tr_files += email_ingest.fetch_all(
                sender, S.TRACKER_GLOBS, workdir,
                since_days=args.days, verbose=False, unique_by_message=True)
        except Exception as e:                              # noqa: BLE001
            print(f"[helen] tracker fetch failed for {sender} "
                  f"({type(e).__name__}: {e})")
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
    written = set()                # (row, col) this run is about to fill
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
            written.add((r, col))
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

    if dry:
        print("[helen] DRY RUN — nothing written")
    elif updates:
        fill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        print(f"[helen] wrote {len(updates)} cell(s)")
    else:
        print("[helen] nothing new — every week the sources cover is already "
              "on the tab")

    # What is STILL missing after this run. This runs on the nothing-to-write
    # path too — that is precisely the run where a source has gone quiet.
    # Never alerts on a dry-run: a rehearsal must not ping anyone.
    holes = _overdue_holes(grid, cols, rows, written, args.days, today)
    for lab, wks in sorted(holes.items()):
        print(f"[helen] STILL EMPTY  {lab}: {_fmt_weeks(wks)}")
    if not dry:
        _source_manifest(holes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
