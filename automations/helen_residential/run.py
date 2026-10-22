"""Fill Helen Assefaw's tab on the ATT Program - Focus Report. Runs MONDAYS.

Since 2026-10-22 it also fills `Joshua Ghorbani (Vz)` (see OWNERS): same
tracker + rep count, no recruiting mail. `--only "<owner>"` runs one of them.

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

# Every Verizon-residential tab this fills. Helen came first (2026-08-17);
# Joshua Ghorbani (First Harvest Sales Group, Gretna LA, AppStream 24119) was
# added 2026-10-22 on Raf's "1on1 for Joshua Ghorbani" mail. He is on the same
# RANKED tracker (middle table) and Rep Count `ICD Owner Snapshot`, but NOT on
# Madilyn's recruiting mail -- his funnel rows come from AppStream through
# att_focus_raf, like Helen's do since 2026-08-18.
#   company  : as the tracker PDF prints it (anchors the row regex)
#   start    : first WE-Sunday with his/her numbers. Nothing earlier is written
#              (the tracker's "previous week" column would put a 0 there) and
#              no hole earlier than it is pinged.
OWNERS = {
    "Helen Assefaw": {
        "company": "Edge Concepts", "tab": TAB, "start": None,
        "recruiting_mail": True, "manifest": SOURCE_MANIFEST_ID},
    "Joshua Ghorbani": {
        "company": "First Harvest Sales Group", "tab": "Joshua Ghorbani",
        "start": dt.date(2026, 10, 11),
        "recruiting_mail": False, "manifest": "joshua_ghorbani_vz_sources"},
}

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


def _overdue_holes(grid, cols, rows, written, days, today, start=None):
    """{label: [WE-Sunday, ...]} -- cells this module owns that are STILL empty
    and are already past their source's normal lag.

    Bounded by the same window the run scans: those are exactly the weeks a
    late edition could still repair. Anything older is out of this report's
    reach and re-flagging it every Monday would be noise, not a signal."""
    last_closed = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    floor = today - dt.timedelta(days=days)
    if start and start > floor:
        floor = start
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


def _source_manifest(holes: dict, log=print, owner: str = "Helen Assefaw",
                     manifest_id: str = SOURCE_MANIFEST_ID,
                     tab: str = "Helen Assefaw (Vz)") -> None:
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
            _rm.mark_clean(manifest_id, kind="source")
            return
        why = [f"{lab} - no edition covering {_fmt_weeks(wks)} "
               f"({OWNED_ROWS[lab][0]})"
               for lab, wks in sorted(holes.items())]
        ask = "; ".join(
            f"{OWNED_ROWS[lab][0].split(' (')[0]} for week(s) ending "
            f"{_fmt_weeks(wks)}" for lab, wks in sorted(holes.items()))
        _rm.write_manifest(
            manifest_id, failed=sorted(holes), retry_args=[],
            kind="source",
            note=(f"{tab} - " + "; ".join(why) + ". The rest of "
                  "the tab is filled; only these cells are missing."),
            remediation=_rm.make_remediation(
                reason="The weekly mail behind those rows never arrived for "
                       "those weeks, or arrived without " + owner + "'s row on "
                       "it. This is residential Verizon, so there is no Tableau or "
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
    ap.add_argument("--only", choices=sorted(OWNERS),
                    help="Fill one owner's tab (default: all of them).")
    ap.add_argument("--tab", help="Override the tab name (needs --only).")
    args = ap.parse_args(argv)
    dry = args.dry_run
    today = dt.date.today()
    owners = [args.only] if args.only else list(OWNERS)
    if args.tab and not args.only:
        ap.error("--tab needs --only")

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

    print(f"[helen] sources: {len(tr_files)} tracker pdf(s), {len(rc_files)} "
          f"rep count(s), {len(recruiting)} recruiting week(s)")

    # ---- write, one tab per owner -------------------------------------------
    # The mails are fetched once above; one owner's broken tab must not cost
    # the other theirs.
    sh = fill.open_sheet()
    rc = 0
    for owner in owners:
        try:
            rc |= _fill_owner(sh, owner, OWNERS[owner], tr_files, rc_files,
                              recruiting, dry, today, args.days, args.tab)
        except Exception as e:                              # noqa: BLE001
            print(f"[helen] {owner} FAILED ({type(e).__name__}: {e})")
            rc = 1
    return rc


def _fill_owner(sh, owner, cfg, tr_files, rc_files, recruiting, dry, today,
                days, tab=None) -> int:
    """Write one owner's still-empty cells; ping (or clear) their holes."""
    tag = f"[{owner.split()[0].lower()}]"
    start = cfg.get("start")
    units = S.parse_tracker(list(tr_files), today.year,
                            row_re=S._tracker_row(owner, cfg["company"]))
    heads = S.parse_rep_counts(list(rc_files), owner=owner)
    if not cfg.get("recruiting_mail"):
        recruiting = {}
    print(f"{tag} {owner}: {len(units)} sales week(s), {len(heads)} "
          f"headcount week(s), {len(recruiting)} recruiting week(s)")

    ws = _resolve_tab(sh, tab or cfg["tab"])
    grid = fill._retry(ws.get_all_values)
    cols = fill.find_sunday_columns(grid, header_row_idx=0)
    rows = _rows_by_label(grid)
    if not cols:
        print(f"{tag} {ws.title}: no date headers on row 1 — is C1 a SUNDAY?")
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
        if start and wk < start:
            continue        # before they started: the tracker's "previous
                            # week" column prints a 0 that is not a real week
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
        print(f"{tag} {len(nocol)} week(s) with no column on the tab: "
              f"{nocol[:4]}{' …' if len(nocol) > 4 else ''}")
    if norow:
        print(f"{tag} label(s) not on the tab: {sorted(norow)}")
    print(f"{tag} {len(updates)} cell(s) to fill, {kept} already filled (kept)")

    if dry:
        print(f"{tag} DRY RUN — nothing written")
    elif updates:
        fill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        print(f"{tag} wrote {len(updates)} cell(s)")
    else:
        print(f"{tag} nothing new — every week the sources cover is already "
              "on the tab")

    # What is STILL missing after this run. This runs on the nothing-to-write
    # path too — that is precisely the run where a source has gone quiet.
    # Never alerts on a dry-run: a rehearsal must not ping anyone.
    holes = _overdue_holes(grid, cols, rows, written, days, today, start)
    for lab, wks in sorted(holes.items()):
        print(f"{tag} STILL EMPTY  {lab}: {_fmt_weeks(wks)}")
    if not dry:
        _source_manifest(holes, owner=owner, manifest_id=cfg["manifest"],
                         tab=ws.title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
