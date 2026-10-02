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
                                            obcl as OB, ov_knocks as OV,
                                            paycheck as PC, people as PEO,
                                            roster as R, sales as SA,
                                            second_rounds as SR,
                                            teamblock as TB, weeks as W)

BOOK = "1KhCZ4fzIbXh9LKWeHMfvfswcHdlXEa14IK5KsmRgwZM"


def _a1(col: int) -> str:
    s = ""
    while col > 0:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


_TERM_LOG = {}


def _terminated_on_or_before(name: str, week: dt.date) -> bool:
    """Is this person in the master Terminated Reps log by `week`?

    The log is append-only and never cleared on a rehire, so a date alone does
    not prove someone is gone today — but for one WEEK it answers exactly the
    right question: had they left by then? Loaded once per run.
    """
    if not _TERM_LOG:
        try:
            from automations.reps_gross_paycheck import (names as RN,
                                                         terminated_log as TL)
            from automations.recruiting_report.fill import open_by_key
            from automations.shared.workbooks import ALL_IN_ONE_RAF
            # load() gives {join key: LogEntry}, keyed by reps_gross_paycheck's
            # OWN normaliser and holding the LAST departure. We want the
            # EARLIEST one on or before the week in question, so re-key by the
            # entry's date and keep the oldest.
            for k, entry in TL.load(open_by_key(ALL_IN_ONE_RAF)).items():
                if entry.we and (k not in _TERM_LOG or entry.we < _TERM_LOG[k]):
                    _TERM_LOG[k] = entry.we
            _TERM_LOG["_key"] = RN.key
        except Exception:                       # a log we cannot read != gone
            _TERM_LOG["_failed"] = True
    if _TERM_LOG.get("_failed"):
        return False
    keyer = _TERM_LOG.get("_key")
    when = _TERM_LOG.get(keyer(name) if keyer else name)
    return bool(when and when <= week)


def _latest(filled, label: str, week: dt.date):
    """The value this run last put in `label` for `week`, as a number.

    Later adds win, which is the same rule run.py applies when it maps cells,
    so this sees ownerville's figure where ownerville supplied one and the
    board's where it did not.
    """
    out = None
    for c in filled.cells:
        if c.week == week and LO.fold(c.row_label) == LO.fold(label):
            try:
                out = float(str(c.value).replace(",", "").replace("%", ""))
            except ValueError:
                pass
    return out


def _num(v: float) -> str:
    return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:.1f}"


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

    # New starts come from the ONBOARDING CHECKLIST, weekly, not from the
    # monthly recruiting tab. Megan 2026-10-01: "scheduled and showed new
    # starts should be weekly not monthly" — the OBCL has one row per
    # scheduled new start, dated, attributed to whoever did their 2nd round.
    try:
        obcl = OB.read(allinone.worksheet(OB.TAB).get_all_values())
        print(f"  OBCL: {len(obcl)} week block(s)")
    except Exception as e:                      # no OBCL ≠ no report
        obcl = {}
        notes_boot.append(f"OBCL unreadable ({e}) — new starts fall back to "
                          f"the monthly figure")
    rec_names = sorted({n for m in months.values() for n in m})

    rosters = R.build(logfn=print)

    # The weekly sales boards: products AND 11 of the 13 knock rows.
    from automations.terminated_reps import board as BD
    boardbook = open_by_key(BD.SHEET_ID)
    tabs_by_week = SA.week_tabs([w.title for w in boardbook.worksheets()],
                                wks[-1].year)
    weekly, classrooms = {}, {}
    for wk in wks:
        t = tabs_by_week.get(wk)
        if not t:
            notes_boot.append(f"no sales board tab for WE {wk:%-m/%-d}")
            continue
        g = boardbook.worksheet(t).get_all_values()
        weekly[wk] = (SA.read_week(g, t, wk), SA.read_days(g, t))
        # The board's 'Classroom / Trainers' block — who showed to day 1 that
        # week, and whose team they are on. Kept per week because Trained and
        # Retained are measured off it, not off the roster.
        try:
            from automations.sales_board_mind_map import run as _MM
            classrooms[wk] = _MM.classroom_trainers(g)
        except Exception as e:                      # a week with no block
            notes_boot.append(f"WE {wk:%-m/%-d}: no classroom block ({e})")
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
        # Make room before reading the layout: a week with no column cannot be
        # filled, and the tabs were only built out to 12/27 by hand.
        try:
            from automations.local_office_1on1s import formatting as FMT
            if FMT.ensure_week_columns(book, team, wks, logfn=print):
                pass
        except Exception as e:                      # never block a fill
            notes.append(f"{team}: could not add week columns ({e})")
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
            # The team block's rows MUST be looked up inside the block. Four
            # of its labels repeat the head's personal sales rows above it, and
            # a section-wide lookup writes the team's totals onto the person.
            owner_at = LO.block_start(grid, head_sec, "Owner 1on1's")
            # The window starts at 'Team Structure - All', NOT at the Owner
            # marker: those two structure rows sit just ABOVE the block and
            # were pushed out of range by narrowing to it. Everything the team
            # box owns lives from there down; the head's personal rows, which
            # repeat four of these labels, are all above it.
            struct_at = None
            for _r in range(head_sec.start + 1, head_sec.end + 1):
                if LO.fold(LO._cell(grid, _r, LO.LABEL_COL)).startswith("team structure"):
                    struct_at = _r
                    break
            hrows = LO.label_rows(grid, head_sec,
                                  first=min(x for x in (struct_at, owner_at) if x)
                                  if (struct_at or owner_at) else None)
            if owner_at is None:
                notes.append(f"{team}: no \"Owner 1on1's\" block on the team box "
                             f"— team totals not written, they would land on "
                             f"the head's personal rows")
            hhdr = W.read_header(head_sec.header, year=wks[-1].year)
            n = 0
            for wk in wks:
                rw = week_rosters.get(wk, {}).get(team)
                if rw is None:
                    # SKIPPING IS NOT THE SAME AS BLANKING. A week with no
                    # roster was being passed over, so the team block kept
                    # whatever an earlier run had put there — 'New Starts
                    # started' read 7/7/7 beside a 'showed / Scheduled' of
                    # 4/4, 2/2, 8/8, which is worse than empty because the two
                    # rows contradict each other. Clear what we own for that
                    # week instead. [[feedback_dont_explain_away_a_zero]]
                    gaps.append(f"{team}: no roster for WE {wk:%-m/%-d} — team box cleared")
                    wcol0 = W.find(hhdr, wk)
                    if wcol0 is not None:
                        for label in list(TB.STRUCTURE) + list(TB.OWNER):
                            rr = LO.find_row(hrows, label)
                            if rr and LO._cell(grid, rr, wcol0.col).strip():
                                updates.append({"range": f"{_a1(wcol0.col)}{rr}",
                                                "values": [[""]]})
                    continue
                wcol = W.find(hhdr, wk)
                if wcol is None:
                    continue
                cells = TB.compute(rw).as_cells()

                # THE TEAM BOX ROW IS THE WHOLE TEAM, not the head's own
                # interviews. Megan 2026-10-01: "this number is the number on
                # the OBCL of people on this team that had people who were
                # scheduled to start and those that actually get marked showed
                # to classroom". Summed over every leader on the team, so a
                # new start interviewed by any of them counts once for the team.
                t_sched = t_showed = 0
                seen_any = False
                _blk2 = classrooms.get(wk) or {}
                for who in [rost.head] + list(rost.leaders):
                    got = OB.for_week(obcl, wk, who,
                                      on_board=lambda n, _b=_blk2: PEO.key(n) in _b)
                    if got:
                        seen_any = True
                        t_sched += got[0]
                        t_showed += got[1]
                if seen_any:
                    # 'New Starts showed / Scheduled' is NOT set here: that row
                    # sits in the head's recruiting block, above this window,
                    # and is written in his personal pass. Setting it in both
                    # places produced a guaranteed "no row" note every run.
                    cells["New Starts started"] = str(t_sched)
                    cells["New Starts alive?"] = str(t_showed)

                wsales = weekly.get(wk, (None, None))[0]
                if wsales is not None:
                    live = [m.name for m in rw.members if not m.terminated]
                    cells.update(TB.sales_totals(live, wsales, rw.active_reps))
                if owner_at is None:
                    continue
                for label, value in cells.items():
                    r = LO.find_row(hrows, label)
                    if r is None:
                        notes.append(f"{team}: team box has no row {label!r}")
                        continue
                    updates.append({"range": f"{_a1(wcol.col)}{r}", "values": [[value]]})
                    n += 1
            print(f"    {rost.head + ' (team box)':<32} {n:>3} cells")

        # THE HEAD IS A PERSON, NOT JUST A ROOF. Their box carries their OWN
        # sales / recruiting / training / finances above the team block, and
        # only Raf is group-only — Megan 2026-09-28: "Raf is the ALphaletes
        # leader but he won't have any personal production info". Filling the
        # team block and stopping there left Algemar Kennel, Willie Henderson,
        # Basil Elhassan and Andrew Sanborn with four empty sections apiece.
        people_to_fill = list(rost.leaders)
        if rost.head and not rost.head_group_only:
            people_to_fill.insert(0, rost.head)
        elif rost.head:
            # A GROUP-ONLY HEAD STILL NEEDS THEIR PERSONAL ROWS CLEARED.
            # Skipping them entirely meant those rows were never written AND
            # never cleared, so Raf's box kept the team totals an earlier bug
            # had put there — his personal 'Total Apps' read 83/93/72/55/64
            # while the corrected team block beside it read 65 for the same
            # week. Removing the bad write does nothing about the bad value
            # already in the cell. He is filled with NOTHING, which is the
            # point: the clearing pass runs and every owned personal row empties.
            people_to_fill.insert(0, rost.head)

        # WHO TO FILL COMES FROM THE WEEKS BEING AUDITED, NOT FROM TODAY.
        # `rosters` is built for today, so a leader who came off the board
        # between the last audit week and this run vanished from the fill
        # completely — their section was never written AND never cleared, so it
        # kept whatever manual.py had lifted out of the OLD tabs and nothing
        # reported a gap, because a person absent from today's roster is not a
        # missing section. Rhea McKee led Hashiras every one of these nine
        # weeks and is off the 10/1 board: her box showed stale hand-typed
        # second-round numbers that looked more filled-in than the leaders
        # whose real rows were being dropped. [[feedback_fill_but_flag]]
        _known = {PEO.key(p) for p in people_to_fill}
        for _wk in wks:
            _rw = week_rosters.get(_wk, {}).get(team)
            if not _rw:
                continue
            for _p in [_rw.head] + list(_rw.leaders):
                if not _p or PEO.key(_p) in _known:
                    continue
                _known.add(PEO.key(_p))
                people_to_fill.append(_p)
                # THE MASTER LOG DECIDES WHO LEFT, NOT THE BOARD. Megan
                # 2026-10-01: "if they aren't on the terminated tab, they are
                # still active." Off today's board therefore means one of two
                # different things, and asking her to work out which, report by
                # report, is the report not doing its job: a terminated leader
                # is simply history, while an ACTIVE one missing from the board
                # is a board fault — the same fault already reported per week
                # for a missing sales-board row.
                if _terminated_on_or_before(_p, wks[-1]):
                    notes.append(
                        f"{team}: {_p} led during these weeks and is "
                        f"TERMINATED per the master log — their section "
                        f"belongs on the TERMINATED tab.")
                else:
                    notes.append(
                        f"{team}: {_p} led during these weeks, is off today's "
                        f"board, and is NOT in the master terminated log — so "
                        f"they are STILL ACTIVE and the board is missing "
                        f"them. Section kept and filled.")

        for name in people_to_fill:
            sec = by_name.get(PEO.key(name))
            if sec is None:
                # A TERMINATED LEADER WITH NO BOX IS THE CORRECT STATE. It was
                # reported as a gap, which sent Megan looking for eight missing
                # sections that should not exist — noise that buries the one
                # case that matters: an ACTIVE leader with nowhere to write.
                if not _terminated_on_or_before(name, wks[-1]):
                    gaps.append(f"{team}: no section for {name} — not in the "
                                f"master terminated log, so they are still "
                                f"active and need a box on this tab")
                continue
            hdr = W.read_header(sec.header, year=wks[-1].year)
            for bad in [h for h in hdr if not h.ok]:
                notes.append(f"{team} r{sec.start}: header {bad.raw!r} — {bad.suspect}")
            # A head's personal rows stop where their team block begins, for
            # the same duplicate-label reason.
            # A head's personal rows stop where the team block begins, which
            # is the 'Team Structure' pair rather than the Owner marker below
            # it — same boundary, read from the other side.
            own_end = None
            for _r in range(sec.start + 1, sec.end + 1):
                if LO.fold(LO._cell(grid, _r, LO.LABEL_COL)).startswith("team structure"):
                    own_end = _r
                    break
            own_end = own_end or LO.block_start(grid, sec, "Owner 1on1's")
            rows = LO.label_rows(grid, sec, last=(own_end - 1) if own_end else None)

            is_head = PEO.key(name) == PEO.key(rost.head)
            group_only = is_head and rost.head_group_only
            if group_only:
                # No sources read for them; `have` stays empty and the owned
                # rows below are cleared. Megan 2026-09-28: "he won't have any
                # personal production info".
                filled = F.Filled()
                rows = LO.label_rows(
                    grid, sec,
                    last=((LO.block_start(grid, sec, "Owner 1on1's") or 0) - 1) or None)
                have = {}
                placed = cleared = 0
                for label in F.OWNED:
                    r = LO.find_row(rows, label)
                    if r is None:
                        continue
                    for wcol in [c for c in hdr if c.ok and c.sunday in wks]:
                        if LO._cell(grid, r, wcol.col).strip():
                            updates.append({"range": f"{_a1(wcol.col)}{r}",
                                            "values": [[""]]})
                            cleared += 1
                print(f"    {name + ' (group only)':<32} {cleared:>3} cleared")
                continue

            rn, note = PEO.resolve(name, rec_names)
            if note:
                notes.append(f"{team}: {note}")
            # `rn or name`: a leader who is in NO month of `2nd rds %'s` must
            # still get zeros, not blanks. resolve() returns None for somebody
            # absent from the tab entirely, and passing that skipped the whole
            # recruiting block — so "conducted none" and "not in the tab"
            # produced different output when they mean the same thing. Passing
            # their own name lets the month lookup miss and write the zeros.
            filled = F.for_leader(name, wks, pay=pay, months=months,
                                  pay_name=name, rec_name=rn or name)
            gaps.extend(filled.gaps)

            # 3. Training / Team Building — never wired until now, blank for
            # everyone in every box. 'Trained This week?' is how many people
            # name this person as their Trainer on THAT week's board and are in
            # their first week; 'Retained?' is how many of those are still not
            # terminated. Both come from the roster this run already builds per
            # week, so there is no new source to read.
            for wk in wks:
                rw = week_rosters.get(wk, {}).get(team)
                if rw is None:
                    continue
                # TRAINED = SHOWED TO DAY 1 CLASSROOM, not "every first-week
                # rep on the roster". Megan 2026-10-01: "trained = showed to
                # day 1 classroom / retained: not marked terminated by sunday
                # pull for this audit". The board's own 'Classroom / Trainers'
                # block is that list — a roster week-one may never have shown,
                # and counting them would credit a leader with somebody who
                # did not turn up.
                #
                # Trainer cells are spelled informally — 'lakeaih' where the
                # leader is 'Lakeaih Gregory' — so matching goes through
                # resolve(), which accepts a unique first-name hit and refuses
                # an ambiguous one.
                trained = []
                for who, trainer in (classrooms.get(wk) or {}).items():
                    if not trainer:
                        continue
                    if PEO.key(trainer) != PEO.key(name):
                        hit, _ = PEO.resolve(trainer, [name])
                        if hit is None:
                            continue
                    trained.append(who)
                # RETAINED = not marked terminated by this audit's Sunday
                # pull. Checked against the master log as at that week, which
                # is the same question asked of a missing board row.
                kept = sum(1 for who in trained
                           if not _terminated_on_or_before(who, wk))
                # NOBODY ASSIGNED READS A DASH, not 0. Megan 2026-10-01, of the
                # recruiting rows and then "same for trained/retained": a dash
                # says the report looked and there was nothing, where 0 claims
                # they were given people and kept none. Same mark the retention
                # row below uses, so the three read consistently.
                filled.add("Trained This week?", wk,
                           str(len(trained)) if trained else F.NONE_MARK,
                           f"WE {wk:%-m/%-d} board: first-week reps trained by {name}"
                           if trained else
                           f"WE {wk:%-m/%-d}: nobody assigned to {name}")
                filled.add("Retained?", wk,
                           str(kept) if trained else F.NONE_MARK,
                           f"WE {wk:%-m/%-d} board: of those, not terminated"
                           if trained else
                           f"WE {wk:%-m/%-d}: nobody assigned to {name}")
                # Raf's definition, not the recruiting tab's show rate: "how
                # many new starts they kept that were assigned to their team...
                # how many of those people are still around".
                #
                # NO NEW STARTS READS '-', NOT 0% AND NOT BLANK. Megan
                # 2026-10-01: "if the % is 0 because no one is scheduled it
                # should just have a line or something". 0% says they kept
                # nobody, which is a different and worse claim than "there was
                # nobody to keep"; blank says the report never ran. A dash is
                # the convention already used elsewhere in this repo for
                # "checked, nothing to report" (reps_gross_paycheck writes '-'
                # for a rep with no money rather than leaving the cell empty).
                # The 0s in Trained and Retained beside it carry the count.
                # [[feedback_dont_explain_away_a_zero]]
                # A DASH MEANS NOBODY, 0% MEANS NOBODY MADE IT. Megan
                # 2026-10-01, on a week showing 1 scheduled and 0 showed:
                # "that's 0% not a dash". Dashing whenever Trained is 0 was too
                # blunt — it hid the weeks where a leader HAD new starts and
                # kept none, which is exactly the week worth talking about in a
                # 1on1. The dash is now only for a week with no new starts at
                # all, by either count.
                _blk3 = classrooms.get(wk) or {}
                _sched = OB.for_week(obcl, wk, name,
                                     on_board=lambda n, _b=_blk3: PEO.key(n) in _b)
                _had_any = bool(trained) or bool(_sched and _sched[0])
                if trained:
                    _ret = f"{round(100 * kept / len(trained))}%"
                    _why = (f"WE {wk:%-m/%-d}: {kept} of {len(trained)} new "
                            f"starts trained by {name} still on the board")
                elif _had_any:
                    _ret = "0%"
                    _why = (f"WE {wk:%-m/%-d}: {_sched[0]} new start(s) scheduled "
                            f"by {name}, none assigned to them still on the board")
                else:
                    _ret = F.NONE_MARK
                    _why = f"WE {wk:%-m/%-d}: no new starts for {name}"
                filled.add(F.RETENTION_ROW, wk, _ret, _why)

            # ON THE HEAD'S SECTION, 'New Starts showed / Scheduled' is the
            # TEAM's figure, not his own. The row sits in his recruiting block
            # (above the team block), but Megan 2026-10-01 defined it as "the
            # number on the OBCL of people on this team" — so it is summed over
            # the head and every leader under him.
            if is_head:
                for wk in wks:
                    ts = tsh = 0
                    any_ = False
                    _blk = classrooms.get(wk) or {}
                    for who in [rost.head] + list(rost.leaders):
                        got = OB.for_week(obcl, wk, who,
                                          on_board=lambda n, _b=_blk: PEO.key(n) in _b)
                        if got:
                            any_ = True
                            ts += got[0]
                            tsh += got[1]
                    if any_:
                        filled.add("New Starts showed / Scheduled", wk,
                                   f"{tsh}/{ts}",
                                   f"OBCL week of {wk:%-m/%-d}: whole team")

            # NEW STARTS, WEEKLY, AFTER the monthly block so these win the
            # cell. Only these two rows move to the OBCL: it holds a row per
            # person who was SCHEDULED, so it cannot count second rounds that
            # never became a new start — the other recruiting rows stay monthly.
            for wk in wks:
                # presence in THAT week's New Starts block = attended day 1
                block = classrooms.get(wk) or {}
                got = OB.for_week(obcl, wk, name,
                                  on_board=lambda n, _b=block: PEO.key(n) in _b)
                if got is None:
                    continue
                sched, showed = got
                filled.add("New Starts Scheduled", wk, str(sched),
                           f"OBCL week of {wk:%-m/%-d}: rows with {name} as "
                           f"2nd Round Interviewer")
                filled.add("New Starts Showed", wk, str(showed),
                           f"OBCL week of {wk:%-m/%-d}: of those, reached classroom")
                filled.add("New Starts showed / Scheduled", wk,
                           f"{showed}/{sched}", f"OBCL week of {wk:%-m/%-d}")

            # products + knocks, per week
            for wk, (wsales, wdays) in weekly.items():
                for lab, val, src in SA.cells_for(name, wsales):
                    filled.add(lab, wk, val, src)

                # NO SALES READS 0 — BUT ONLY IF THEY WERE ON THE BOARD THAT
                # WEEK. Megan 2026-10-01: "Bas will have some sometimes - mark
                # 0 for everyone if it's none", then "only 0 if they have a
                # board row that week".
                #
                # The distinction is the whole point: a 0 says they sold
                # nothing, and that is only true of somebody who was here.
                # Keegan Miller, Hank Tran, Ciniya Weatherspoon and Andres
                # Mejia have no row in early August because they had not
                # started — writing 0 there would put a performance figure
                # against weeks they were not employed. Those stay blank.
                #
                # Written before the real figures so an actual board number
                # overwrites the 0.
                if wdays.get(PEO.key(name)) is not None:
                    for lab in SA.SALES:
                        filled.add(lab, wk, "0",
                                   f"on the WE {wk:%-m/%-d} board with no "
                                   f"{lab} — none sold")

                # BOARD FIRST, THEN OWNERVILLE ON TOP. Ownerville is the better
                # source and wins every row it produces (later writes take the
                # cell), but it does not produce ALL of them: 'Monday - Saturday
                # Total Apps' and 'AVG Talk Too's per App' come only from the
                # board's per-day Apps. Letting ownerville short-circuit the
                # board blanked both rows in every week — a regression that
                # traded two rows for the nine it fixed.
                d = wdays.get(PEO.key(name))
                if d is not None:
                    for lab, val, src in SA.day_cells(d, wsales.tab):
                        filled.add(lab, wk, val, src)

                rec = ov_weeks.get(wk, {}).get(PEO.key(name))
                if rec is not None:
                    for lab, val, src in OV.cells_for(rec, f"WE {wk:%-m/%-d}"):
                        filled.add(lab, wk, val, src)

                    # AVG TALK TO'S PER APP NEEDS BOTH SOURCES AT ONCE: the
                    # talk-to's from ownerville, the apps from the board. It
                    # was computed only inside the board path, which carries no
                    # talk-to's before ~WE 9/6, so it sat blank for every
                    # August week while the talk-to counts right above it were
                    # populated from ownerville. Megan 2026-10-01 asked for it.
                    _apps = _latest(filled, "Monday - Saturday Total Apps", wk)
                    _tt = _latest(filled, "Monday - Friday Total Talk Too's", wk)
                    _sat = _latest(filled, "Saturday avg Talk To's Day", wk)
                    if _apps and _tt is not None:
                        total_tt = _tt + (_sat or 0)
                        filled.add("AVG Talk Too's per App", wk,
                                   _num(total_tt / _apps),
                                   f"WE {wk:%-m/%-d}: ownerville talk-to's / "
                                   f"board apps")
                elif d is None:
                    # TERMINATED AND MISSING-FROM-THE-BOARD ARE NOT THE SAME
                    # THING, and a blank week looks identical either way.
                    # Megan 2026-09-28: "if they aren't on that week's board
                    # they most likely got terminated - you should be looking
                    # at the terminated rep tab." So it is checked rather than
                    # assumed: on WE 9/20 four reps were off the board and NONE
                    # of them were in the 2,688-row log — that tab is simply
                    # short (67 rows against 77 and 80 either side).
                    gaps.append(
                        f"{name}: no row on the WE {wk:%-m/%-d} sales board"
                        + (" — TERMINATED per the master log"
                           if _terminated_on_or_before(name, wk)
                           else " and NOT in the terminated log, so the board "
                                "itself is missing them"))

            # What this run actually has, keyed by the cell it lands in.
            have = {}
            for cell in filled.cells:
                # A VARIANT-ONLY LABEL MUST MATCH EXACTLY. 'New Starts showed /
                # Scheduled' is the TEAM box's condensed row, and find_row's
                # prefix tolerance resolved it onto the individual box's 'New
                # Starts Showed' — so the ratio overwrote the count and that
                # row read '3/3' where it should read '3'. The tolerance is
                # right for drift like 'Dress Code 1 out of 3' vs '/5'; it is
                # wrong when one label is a prefix of another REAL row.
                if LO.fold(cell.row_label) in F.VARIANT_ONLY:
                    r = LO.exact_row(rows, cell.row_label)
                else:
                    r = LO.find_row(rows, cell.row_label)
                col = W.find(hdr, cell.week)
                if r is None:
                    if LO.fold(cell.row_label) not in F.VARIANT_ONLY:
                        notes.append(f"{team} {name}: no row {cell.row_label!r}")
                    continue
                if col is None:
                    continue           # that week has no column on this tab
                have[(r, col.col)] = cell.value

            # OWNED ROWS ARE REWRITTEN, NOT TOPPED UP. A cell this report owns
            # and has no value for is CLEARED, so a number cannot outlive the
            # source that produced it — the fabricated '0.0%' survived its own
            # fix because nothing overwrote it. Only fill.OWNED is in scope;
            # every manual row is untouched.
            placed = cleared = 0
            for label in F.OWNED:
                # RESOLVE EXACTLY AS THE WRITE DID. A VARIANT_ONLY label that
                # find_row is allowed to fuzzy-match lands this clearing pass on
                # a DIFFERENT row than the values went to — 'New Starts showed /
                # Scheduled' prefix-matches the individual box's 'New Starts
                # Showed'. Same rule both sides, or clearing fights writing.
                if LO.fold(label) in F.VARIANT_ONLY:
                    r = LO.exact_row(rows, label)
                else:
                    r = LO.find_row(rows, label)
                if r is None:
                    continue
                for wcol in [c for c in hdr if c.ok and c.sunday in wks]:
                    v = have.get((r, wcol.col))
                    if v is None:
                        if LO._cell(grid, r, wcol.col).strip():
                            updates.append({"range": f"{_a1(wcol.col)}{r}",
                                            "values": [[""]]})
                            cleared += 1
                    else:
                        updates.append({"range": f"{_a1(wcol.col)}{r}",
                                        "values": [[v]]})
                        placed += 1
            print(f"    {name:<32} {placed:>3} cells"
                  + (f", {cleared} cleared" if cleared else ""))

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
