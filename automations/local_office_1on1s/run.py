#!/usr/bin/env python3
"""Local Office 1on1s — fill the five team tabs.

    python -m automations.local_office_1on1s.run                 # preview
    python -m automations.local_office_1on1s.run --write
    python -m automations.local_office_1on1s.run --tab "Se7en Sins"
    python -m automations.local_office_1on1s.run --weeks 9       # back from the last completed Sunday

PREVIEW BY DEFAULT. Nothing is written without --write.

WHAT IT DOES NOT TOUCH: every manual row (all of 4. Culture / Atmo / HTP,
'What are we going to do better?', 'BreakEven', 'Money Saved?', 'Goal / Focus
for the week'), and any cell it has no source for. A row it cannot place by
label is REPORTED, never written to a nearby row. [[feedback_fill_but_flag]]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict

from automations.local_office_1on1s import (fill as F, layout as LO,
                                            ov_knocks as OV, paycheck as PC,
                                            people as PEO, roster as R,
                                            sales as SA, second_rounds as SR,
                                            teamblock as TB, weeks as W)

BOOK = "1KhCZ4fzIbXh9LKWeHMfvfswcHdlXEa14IK5KsmRgwZM"


def _a1(col: int) -> str:
    s = ""
    while col > 0:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


def last_completed_sunday(today: dt.date) -> dt.date:
    """The most recent Sunday that has already ended."""
    return today - dt.timedelta(days=(today.weekday() + 1) % 7 or 7)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--tab", action="append", dest="tabs")
    ap.add_argument("--weeks", type=int, default=9)
    a = ap.parse_args(argv)

    from automations.recruiting_report.fill import open_by_key

    notes_boot = []
    today = dt.date.today()
    wks = W.sundays_back(last_completed_sunday(today), a.weeks)
    print(f"weeks: {wks[0]:%-m/%-d} .. {wks[-1]:%-m/%-d}  ({len(wks)})")

    allinone = open_by_key(PC.SHEET_ID)
    pay = PC.load(allinone)
    print(f"  P&L: read {', '.join(pay.tabs)}")
    for s in pay.skipped:
        print(f"       skipped {s}")
    for c in pay.conflicts:
        print(f"       ! {c}")
    _teams, months = SR.read(allinone.worksheet(SR.TAB).get_all_values())
    rec_names = sorted({n for m in months.values() for n in m})

    rosters = R.build(logfn=print)

    # The weekly sales boards: products AND 11 of the 13 knock rows.
    from automations.terminated_reps import board as BD
    boardbook = open_by_key(BD.SHEET_ID)
    tabs_by_week = SA.week_tabs([w.title for w in boardbook.worksheets()],
                                wks[-1].year)
    weekly = {}
    for wk in wks:
        t = tabs_by_week.get(wk)
        if not t:
            notes_boot.append(f"no sales board tab for WE {wk:%-m/%-d}")
            continue
        g = boardbook.worksheet(t).get_all_values()
        weekly[wk] = (SA.read_week(g, t, wk), SA.read_days(g, t))
    print(f"  sales boards: {len(weekly)}/{len(wks)} weeks")

    # A TEAM BOX IS A HISTORY. Each week's structure comes from THAT week's
    # board, not from today's roster repeated across the row.
    week_rosters = {}
    for wk in wks:
        t = tabs_by_week.get(wk)
        if not t:
            continue
        try:
            week_rosters[wk] = R.build(tab=t, logfn=lambda *a: None)
        except Exception as e:                      # a week the tree cannot read
            notes_boot.append(f"roster for WE {wk:%-m/%-d} ({t}): {e}")
    print(f"  week rosters: {len(week_rosters)}/{len(wks)}")

    # OWNERVILLE OUTRANKS THE BOARD FOR THE KNOCK BLOCK, where it is cached.
    # The board answers 9 of the 13 rows and only from ~WE 9.6 ('Sales Board
    # WE 8.2'/'8.16'/'8.30' carry no TK or Talk-To's columns at all), and it
    # records no TIMES, so 'Mon-Fri AVG First/Last Knock' and the two Saturday
    # ones can only come from here. A 1on1 column is week-ending SUNDAY; the
    # ownerville week is the Mon-Sat before it, keyed by that SATURDAY.
    ov_weeks = {}
    for wk in wks:
        got = OV.week(wk - dt.timedelta(days=1), logfn=lambda *a: None)
        if got:
            ov_weeks[wk] = got
    print(f"  ownerville knocks: {len(ov_weeks)}/{len(wks)} weeks from cache")
    if not ov_weeks:
        notes_boot.append(
            "no ownerville knock weeks cached on THIS machine — the knock block "
            "falls back to the sales board, which has no times and nothing "
            "before ~WE 9/6. The cache is written where the pull ran: run "
            "`lucy rerun local_1on1s_knock_backfill`, and run this fill on the "
            "same machine.")

    book = open_by_key(BOOK)

    gaps, notes, wrote = [], list(notes_boot), 0
    for team in (a.tabs or R.TEAMS):
        rost = rosters[team]
        ws = book.worksheet(team)
        grid = ws.get_all_values()
        secs = LO.find_sections(grid)
        by_name = {PEO.key(s.name): s for s in secs if s.name.strip()}
        print(f"\n{team}  ({len(secs)} sections)")

        updates = []

        # section 1: the team block. The head's personal rows stay EMPTY when
        # they have no production of their own (Raf on Alphaletes).
        head_sec = by_name.get(PEO.key(rost.head))
        if head_sec is None:
            gaps.append(f"{team}: no section for the head {rost.head!r}")
        else:
            hrows = LO.label_rows(grid, head_sec)
            hhdr = W.read_header(head_sec.header, year=wks[-1].year)
            n = 0
            for wk in wks:
                rw = week_rosters.get(wk, {}).get(team)
                if rw is None:
                    gaps.append(f"{team}: no roster for WE {wk:%-m/%-d} — team box left blank")
                    continue
                wcol = W.find(hhdr, wk)
                if wcol is None:
                    continue
                cells = TB.compute(rw).as_cells()
                wsales = weekly.get(wk, (None, None))[0]
                if wsales is not None:
                    live = [m.name for m in rw.members if not m.terminated]
                    cells.update(TB.sales_totals(live, wsales))
                for label, value in cells.items():
                    r = LO.find_row(hrows, label)
                    if r is None:
                        notes.append(f"{team}: team box has no row {label!r}")
                        continue
                    updates.append({"range": f"{_a1(wcol.col)}{r}", "values": [[value]]})
                    n += 1
            print(f"    {rost.head + ' (team box)':<32} {n:>3} cells")

        for name in rost.leaders:
            sec = by_name.get(PEO.key(name))
            if sec is None:
                gaps.append(f"{team}: no section for {name}")
                continue
            hdr = W.read_header(sec.header, year=wks[-1].year)
            for bad in [h for h in hdr if not h.ok]:
                notes.append(f"{team} r{sec.start}: header {bad.raw!r} — {bad.suspect}")
            rows = LO.label_rows(grid, sec)

            rn, note = PEO.resolve(name, rec_names)
            if note:
                notes.append(f"{team}: {note}")
            filled = F.for_leader(name, wks, pay=pay, months=months,
                                  pay_name=name, rec_name=rn)
            gaps.extend(filled.gaps)

            # products + knocks, per week
            for wk, (wsales, wdays) in weekly.items():
                for lab, val, src in SA.cells_for(name, wsales):
                    filled.add(lab, wk, val, src)

                rec = ov_weeks.get(wk, {}).get(PEO.key(name))
                if rec is not None:
                    for lab, val, src in OV.cells_for(rec, f"WE {wk:%-m/%-d}"):
                        filled.add(lab, wk, val, src)
                    continue          # ownerville answered the knock block

                d = wdays.get(PEO.key(name))
                if d is None:
                    gaps.append(f"{name}: no row on the WE {wk:%-m/%-d} sales board")
                    continue
                for lab, val, src in SA.day_cells(d, wsales.tab):
                    filled.add(lab, wk, val, src)

            placed = 0
            for cell in filled.cells:
                r = LO.find_row(rows, cell.row_label)
                col = W.find(hdr, cell.week)
                if r is None:
                    notes.append(f"{team} {name}: no row {cell.row_label!r}")
                    continue
                if col is None:
                    continue           # that week has no column on this tab
                updates.append({"range": f"{_a1(col.col)}{r}", "values": [[cell.value]]})
                placed += 1
            print(f"    {name:<32} {placed:>3} cells")

        if not a.write:
            print(f"  PREVIEW — {len(updates)} cells not written")
            continue
        for i in range(0, len(updates), 400):
            ws.batch_update(updates[i:i + 400])
        wrote += len(updates)
        print(f"  wrote {len(updates)} cells")

    if notes:
        print("\nNOTES")
        for n in dict.fromkeys(notes):
            print("  -", n)
    if gaps:
        print("\nGAPS")
        for g in dict.fromkeys(gaps):
            print("  -", g)
    print(f"\n{'wrote' if a.write else 'would write'} {wrote if a.write else 'n/a'} cells")
    return 0


if __name__ == "__main__":
    sys.exit(main())
