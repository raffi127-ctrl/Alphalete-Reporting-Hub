"""What goes in each cell of an individual section, and where it came from.

Every value carries its source so the run can print workbook -> tab -> row/col
for any number on the sheet. [[feedback_cite_source_location]]

SOURCES, and the traps each one already cost us:

  Gross Paycheck last week?   the P&Ls, ONE WEEK BEHIND the column it lands in.
      The label says "last week" and reps_gross_paycheck/week.py says the same:
      what a rep collects Thursday settled the week before. Proven against
      Raf's own hand-typed figures 3/3 — Alyssa Moreno's WE 8/02 cell holds the
      P&L's WE 7/26 ($770), 8/23 holds 8/16 ($976), 9/13 holds 9/06 ($557).
      Filling the same-week value would be wrong AND look right.

  2. Recruiting (Monthly)      `2nd rds %'s`, the MONTH the week ends in.
      Monthly is what Raf asked for and all the source has, so the four week
      columns inside a month carry the same figure — which is why the section
      label now says "(Monthly)".

  BreakEven / Money Saved / all of 4. Culture / What are we going to do better?
  / Goal / Focus                MANUAL. Never written. 'Breakeven' exists as a
      column on every P&L and is empty for all 446 named reps, so it is not a
      gap this can close.

A CELL WITH NO SOURCE IS LEFT ALONE, never zeroed. A leader who is not in a
month's block of `2nd rds %'s` was not conducting second rounds that month;
writing 0 would state that they conducted none, which is a different claim.
[[feedback_dont_explain_away_a_zero]]
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]

# label on the section  ->  key in second_rounds.WANT
#
# TWO BOXES, TWO VOCABULARIES. The individual box (Individual Template) carries
# the EXPANDED seven rows; the TEAM box at the top of each tab carries Raf's
# older CONDENSED four. Mapping only the expanded set left every team box's
# whole recruiting block blank — the labels simply never matched.
# Which of the recruiting rows are COUNTS. A leader with no row in the month's
# block conducted none (Megan 2026-09-28: "the ones missing from 2nd rounds
# just haven't done any of them"), and Raf wants that shown as 0 rather than
# blank — a real zero he can talk about, not an empty cell that reads as "we
# don't know". The PERCENTAGES stay blank in that case: 0 out of 0 is not 0%,
# it is undefined, and printing 0% would state a closing rate nobody has.
COUNT_ROWS = {"conducted", "offered", "bob_num", "ns_sched", "ns_showed"}

RECRUITING = {
    # expanded — Individual Template r23-29
    "2nd rds Conducted":        "conducted",
    "Job Offered":              "offered",
    "2nd rds closed":           "bob_num",     # Raf: "that should be a number"
    "BOB % / 2nd rd closing":   "bob_pct",
    "New Starts Scheduled":     "ns_sched",
    "New Starts Showed":        "ns_showed",
    # 'New starts Retention %' is NOT in this map. It looked like the source's
    # 'NS Showed %' and is a different number. Raf, 2026-09-28: "this is
    # judging how many new starts they kept that were assigned to their team.
    # So if seven sins is training 7 people this week, how many of those people
    # are still around, that's the new start retention." That is retained over
    # trained, which run.py already computes from the Trainer column — a show
    # rate would have been quietly wrong in a row Raf reads every week.
    # condensed — TEAM Template box 1
    "2nd Closing numbers":      "bob_num",
    "2nd Closing %":            "bob_pct",
    "New Starts showed / Scheduled": "ns_showed",
}

# The row computed from the Trainer chain rather than the recruiting tab.
RETENTION_ROW = "New starts Retention %"

# Labels that exist in ONE box variant only. A TEAM box carries the condensed
# recruiting spellings and an individual box the expanded ones, so each kind of
# section is always missing the other's rows. Reporting that as a gap produced
# three false notes per individual section, and a notes list full of expected
# misses is how a real one gets skipped. [[feedback_fill_but_flag]]
VARIANT_ONLY = {
    # TEAM box only
    "2nd closing numbers", "2nd closing %", "new starts showed / scheduled",
    "new / app goal",
    # Individual box only — a TEAM box carries the condensed four instead, so
    # these are always "missing" from one of the two kinds of section.
    "2nd rds conducted", "job offered", "2nd rds closed",
    "bob % / 2nd rd closing", "new starts scheduled", "new starts showed",
}

# EVERY ROW THIS REPORT OWNS. A row here is cleared when the run has no value
# for it, so a number from a previous run cannot outlive its source.
#
# Why that is needed: the fill is additive by design — it writes what it has and
# leaves everything else alone, which is what protects the manual rows. But it
# also meant a wrong value SURVIVED its own fix. The fabricated '0.0%' talk-to
# rate was stopped at the source, the run re-ran, and the sheet still showed
# 0.0% because nothing overwrote the cell the earlier run had written.
#
# Clearing is scoped to exactly these labels. Nothing outside the list is ever
# blanked, so the Culture rows, BreakEven, Money Saved and the weekly goal are
# untouchable. [[feedback_dont_touch_user_data]]
OWNED = [
    # 1. Sales
    "New INT", "Upgrades", "DTV's", "Wireless Lines", "Total Apps",
    # 2. Recruiting (Monthly)
    "2nd rds Conducted", "Job Offered", "2nd rds closed",
    "BOB % / 2nd rd closing", "New Starts Scheduled", "New Starts Showed",
    "New starts Retention %",
    # the knocking block
    "Monday - Friday Total Knocks", "Monday - Friday AVG Doors knocked / Day",
    "Monday - Friday Total Talk Too's", "Monday % Talk To's Per knocks",
    "Mon - Friday avg Talk To's Day", "Monday - Saturday Total Apps",
    "AVG Talk Too's per App", "Mon - Friday AVG First Knock",
    "Mon - Friday AVG Last Knock", "Saturday Avg Doors / Day",
    "Saturday First knock", "Saturday Last Knock",
    "Saturday avg Talk To's Day",
    # 2. Recruiting — the TEAM box's condensed spellings
    "2nd Closing numbers", "2nd Closing %", "New Starts showed / Scheduled",
    # 3. Training / Team Building
    "Trained This week?", "Retained?",
    # 5. Finances — the one money row with a source
    "Gross Paycheck last week?",
    # the Owner 1on1's roll-up, including the two per-rep averages that used
    # to be sheet formulas
    "Team Structure - All", "Team Structure - Leaders", "Active Reps",
    "Leaders", "New Starts started", "New Starts alive?", "New Start Retention",
    "New INTS", "App AVG per rep", "New INT AVG per rep",
]

# Never written by this report.
MANUAL = {
    "breakeven", "money saved", "what are we going to do better",
    "listening to x book", "dress code 1 out of", "last week punctuality",
    "atmo engagement 1 out", "slack / chat engagement 1 out", "networking",
    "goal / focus for the week",
}


@dataclass
class Cell:
    row_label: str
    week: dt.date
    value: str
    source: str


@dataclass
class Filled:
    cells: List[Cell] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)

    def add(self, label, week, value, source):
        if value is None or value == "":
            return
        self.cells.append(Cell(label, week, str(value), source))


def month_of(week_ending: dt.date) -> str:
    return MONTHS[week_ending.month - 1]


def for_leader(name: str, weeks: List[dt.date], *, pay, months,
               pay_name: Optional[str] = None,
               rec_name: Optional[str] = None) -> Filled:
    """Everything this build can source for one person, across `weeks`."""
    out = Filled()

    for wk in weeks:
        # --- money: the week BEFORE the column it lands in
        if pay_name:
            src_week = wk - dt.timedelta(weeks=1)
            amount = pay.got_paid(pay_name, src_week)
            if amount is None:
                out.gaps.append(f"{name}: no Got Paid for WE {src_week:%-m/%-d}")
            else:
                out.add("Gross Paycheck last week?", wk, f"${amount:,.2f}",
                        f"{pay.where(pay_name, src_week)} WE {src_week:%-m/%-d} 'Got Paid'")

        # --- recruiting: the month this week ends in
        if rec_name:
            m = month_of(wk)
            block = months.get(m, {}).get(rec_name.strip().lower())
            if not block:
                # Not a gap — they conducted none. Counts read 0, rates stay
                # blank. Deliberately NOT reported as missing data: a gap list
                # full of merely-inactive people is how a real gap gets missed.
                for label, k in RECRUITING.items():
                    if k in COUNT_ROWS:
                        out.add(label, wk, "0",
                                f"absent from the {m} block of \"2nd rds %'s\" "
                                f"— conducted none")
            else:
                for label, k in RECRUITING.items():
                    out.add(label, wk, block.get(k, ""),
                            f"\"2nd rds %'s\" {m} block, {label}")
    return out
