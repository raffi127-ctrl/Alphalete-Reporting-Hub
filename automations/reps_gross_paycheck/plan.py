"""Decide every change before making any of them.

The plan is built entirely from data already read, prints in full under
--plan, and is the same object --real applies. Nothing decides anything at
write time — so what Eve approves in the preview is exactly what lands.

THE FOUR DECISIONS, in the order they're taken for each rep:

  1. Terminated on the sales board?   -> delete the tab, write nothing into it
  2. Tab exists, PNL has money        -> write the number
  3. Tab exists, PNL has none         -> write '-'
  4. On the board, no tab, not gone   -> make the tab, then 2/3 for its weeks

'no money' at step 3 covers three different situations that all mean the same
thing to the rep: the PNL cell is blank, the person isn't in the PNL at all,
or the cell literally says $0.00. All three become '-'. A zero is folded in
deliberately — Eve's rule is "no tiene $ ... completar con '-'", and a tab
where some empty weeks read '-' and others read '$0' would look like two
different states when it's one.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from automations.reps_gross_paycheck import records, week as wk
from automations.reps_gross_paycheck.records import TabModel, Extension

# A zero in the PNL means the same thing to a rep as a blank: no paycheck.
# Flip to False to write a real 0 instead of '-'.
ZERO_IS_DASH = True


@dataclass
class Write:
    tab: str
    a1: str
    value: object
    sunday: dt.date
    source: str
    note: str = ""


@dataclass
class NewTab:
    name: str
    first_week: dt.date
    reason: str
    start: Optional[dt.date] = None


@dataclass
class Delete:
    tab: str
    sheet_id: int
    termination: dt.date
    reason: str


@dataclass
class Plan:
    target: dt.date
    sundays: List[dt.date]
    writes: List[Write] = field(default_factory=list)
    extensions: List[Extension] = field(default_factory=list)
    creates: List[NewTab] = field(default_factory=list)
    deletes: List[Delete] = field(default_factory=list)
    already_filled: int = 0
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def dashes(self) -> int:
        return sum(1 for w in self.writes if w.value == records.DASH)

    def week_split(self, sunday: dt.date) -> tuple:
        """(cells written for that week, how many carry a real number)."""
        cells = [w for w in self.writes if w.sunday == sunday]
        return len(cells), sum(1 for w in cells if w.value != records.DASH)


def _value_for(pnl, join_key: str, target: dt.date):
    """(cell value, source path) for one rep-week, applying the '-' rule."""
    src_week = wk.source_sunday(target)
    amount = pnl.got_paid(join_key, src_week)
    if amount is None or (ZERO_IS_DASH and abs(amount) < 0.005):
        why = ("no row in the PNL" if join_key not in pnl.people
               else f"'Got Paid' WE {wk.md(src_week)} is "
                    f"{'0' if amount is not None else 'blank'}")
        return records.DASH, why
    return amount, pnl.source_path(join_key, src_week)


def gone(key: str, board: Dict, term_log: Dict, current: Optional[dt.date]):
    """Is this person terminated, and what says so? -> (bool, reason).

    Two records, and they disagree in both directions, so neither alone is the
    answer:

      * the sales board's 'Termination Date' — authoritative when filled, but
        often left blank for someone who simply stopped appearing;
      * the 'Terminated Reps' log — catches those, but is append-only and keeps
        a stale row for anyone who came BACK.

    So: a board date terminates outright. A log row only terminates someone who
    is ALSO missing from the newest board — being on this week's board beats
    any historical departure (Tadana Manyangadze is logged as gone 5/29 and is
    on the 8/9 board right now).
    """
    rep = board.get(key)
    if rep is not None and rep.terminated:
        return True, (f"'Termination Date' {rep.termination_raw} on "
                      f"{rep.seen_on[-1]}")
    entry = term_log.get(key)
    if entry is None:
        return False, ""
    if rep is not None and current is not None and rep.last_seen == current:
        return False, ""                      # rehired — on this week's board
    return True, entry.where


def build(*, tabs: List[TabModel], board: Dict, pnl, sundays: List[dt.date],
          target: dt.date, term_log: Optional[Dict] = None,
          create_new: bool = True, delete_terminated: bool = True,
          overwrite: bool = False, only_week2: bool = True,
          prototype: Optional[TabModel] = None) -> Plan:
    """Assemble the full plan. Reads nothing; pure function of what was read."""
    term_log = term_log or {}
    current = max((r.last_seen for r in board.values() if r.last_seen),
                  default=None)
    plan = Plan(target=target, sundays=sorted(sundays))
    index, dupes = records.index_by_key(tabs)
    # Every tab that names the same person, keyed once. Built from the group
    # (not per-member) so the mapping can't end up holding a partial list and
    # queueing one sheet for deletion twice.
    twins = {group[0].key: list(group) for group in dupes}

    for group in dupes:
        keep, rest = group[0], group[1:]
        plan.warnings.append(
            f"duplicate tabs for one person: keeping {keep.title!r} (its weeks "
            f"run furthest), leaving {[t.title for t in rest]} untouched")

    # ---------- 1. existing tabs ----------
    for tab in sorted(tabs, key=lambda t: t.title.lower()):
        if index.get(tab.key) is not tab:
            continue                                  # the duplicate we dropped
        rep = board.get(tab.key)
        is_gone, why = gone(tab.key, board, term_log, current)

        if is_gone:
            if delete_terminated:
                # A terminated rep with two tabs loses BOTH — leaving the
                # runner-up behind would put a stale copy of a departed rep
                # back on the list of people who look like they need filling.
                when = (rep.termination if rep and rep.termination
                        else getattr(term_log.get(tab.key), "we", None))
                for doomed in twins.get(tab.key, [tab]):
                    plan.deletes.append(Delete(
                        tab=doomed.title, sheet_id=doomed.sheet_id,
                        termination=when, reason=why))
            else:
                plan.notes.append(f"{tab.title}: terminated ({why}) — left in "
                                  f"place (--keep-terminated)")
            continue

        if rep is None:
            # Not on any sales board we read. Either a leftover from a previous
            # season or a rep the board dropped without a Termination Date.
            # Fill the columns they already have — a '-' there is honest — but
            # never GROW the tab: adding columns to someone who has gone quiet
            # rearranges a layout for nobody.
            if tab.last_week is None or tab.last_week < min(plan.sundays):
                plan.notes.append(
                    f"{tab.title}: not on any sales board and its weeks end "
                    f"{wk.md(tab.last_week) if tab.last_week else 'nowhere'} — "
                    "left alone (previous-season tab)")
                continue
            plan.warnings.append(
                f"{tab.title}: has a tab but is on NO sales board — filling "
                f"the columns it already has; if they left, the board needs a "
                f"Termination Date")
            _plan_tab(plan, tab, tab.key, pnl, overwrite, grow=False)
            continue

        _plan_tab(plan, tab, tab.key, pnl, overwrite)

    # ---------- 2. tabs that should exist and don't ----------
    if create_new:
        have = set(index)
        ncols = len(prototype.weeks) if prototype and prototype.weeks else 9
        earliest = target - dt.timedelta(days=7 * (ncols - 1))
        # Only people on the NEWEST board get a tab. Plenty of names sit on a
        # June board and never appear again with no Termination Date ever
        # filled in — they're gone, just not written down, and giving each of
        # them a fresh tab in August would add ~40 tabs for reps who left.
        for key, rep in sorted(board.items(), key=lambda kv: kv[1].raw.lower()):
            if key in have or gone(key, board, term_log, current)[0]:
                continue
            if current and rep.last_seen != current:
                continue
            if only_week2 and not rep.is_week2(target):
                continue
            first = earliest
            if rep.start:
                first = max(first, wk.week_sunday(rep.start))
            first = min(first, target)
            plan.creates.append(NewTab(
                name=rep.raw, first_week=first, start=rep.start,
                reason=("2nd Wk on the newest sales board" if rep.is_week2(target)
                        else f"on the sales board ({rep.seen_on[-1]}), no tab")))
    return plan


def _plan_tab(plan: Plan, tab: TabModel, join_key: str, pnl,
              overwrite: bool, grow: bool = True) -> None:
    """Queue the week writes for one tab, growing its week run if needed."""
    weeks = dict(tab.weeks)
    ext = records.plan_extension(tab, max(plan.sundays)) if grow else None
    if ext:
        plan.extensions.append(ext)
        for i, w in enumerate(ext.new_weeks):
            weeks[w] = ext.first_new_col + i
        if ext.inserts:
            plan.notes.append(
                f"{tab.title}: out of spare columns — inserting {ext.inserts} "
                f"before the expenses block to reach {wk.md(max(plan.sundays))}")

    missing = []
    for sunday in plan.sundays:
        col = weeks.get(sunday)
        if col is None:
            missing.append(sunday)
            continue
        if tab.is_filled(sunday) and not overwrite:
            plan.already_filled += 1
            continue
        value, source = _value_for(pnl, join_key, sunday)
        plan.writes.append(Write(
            tab=tab.title, a1=f"{records.a1_col(col)}{tab.gp_row}",
            value=value, sunday=sunday, source=source))

    if missing:
        plan.notes.append(
            f"{tab.title}: no column for "
            f"{', '.join(wk.md(s) for s in missing)} — its weeks end "
            f"{wk.md(tab.last_week) if tab.last_week else 'nowhere'} and "
            + ("the tab wasn't grown (rep is off the boards)" if not grow
               else f"that's more than {records.MAX_EXTEND_WEEKS} weeks back"))
