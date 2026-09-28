"""'Gross Paycheck last week?' — across all THREE P&Ls, not just Raf's.

Raf's Loom: "there's a couple different PLs here, so it would have to search
the three PLs, and then it would just grab got paid."

    Raf PNL 2026            gid 1300001293    ~440 named reps
    MJ-Alphaletes PNL 2026  gid 325879371       3 named reps
    OG-Alphaletes PNL 2026  gid 1122999014      3 named reps

THEY ARE A HANDOFF, NOT THREE PLACES TO SEARCH. Measured 2026-09-27:

    Hayden Wilson     Raf PNL: 8/30 $800,   then BLANK all September
                      OG PNL:  9/6 $800 · 9/13 $1,460 · 9/20 $750
    Thomas Crenshaw   Raf PNL: 8/30 $1,200, then BLANK
                      OG PNL:  9/6 $1,200 · 9/13 $1,200 · 9/20 $1,443
    Ana Griffin       Raf PNL: 8/30 $800,   then BLANK
                      MJ PNL:  9/6 $2,475 · 9/13 $1,965 · 9/20 $2,030

Raf PNL stops at WE 8/30 for these people and the sub-P&Ls take over from
WE 9/6. The one overlapping week AGREES in all three, so the handoff is clean.

Reading only 'Raf PNL 2026' — which is what reps_gross_paycheck does today —
returns BLANK September for three of the four leaders Raf named by name in the
Loom. That is the bug this exists to fix.

WHERE TWO P&LS DISAGREE ON A WEEK, NEITHER IS WRITTEN. A silent pick between
two different paycheques is worse than a blank and a flag.
[[feedback_dont_explain_away_a_zero]]

'Breakeven' (col C) is NOT read here. The column exists on all three tabs and
is EMPTY for all 446 named reps — it stays a manual cell.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.reps_gross_paycheck import names, pnl as pnl_mod

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TABS = ["Raf PNL 2026", "MJ-Alphaletes PNL 2026", "OG-Alphaletes PNL 2026"]


@dataclass
class Merged:
    paid: Dict[Tuple[str, dt.date], float] = field(default_factory=dict)
    source: Dict[Tuple[str, dt.date], str] = field(default_factory=dict)
    conflicts: List[str] = field(default_factory=list)

    def got_paid(self, who: str, sunday: dt.date) -> Optional[float]:
        return self.paid.get((names.key(who), sunday))

    def where(self, who: str, sunday: dt.date) -> str:
        return self.source.get((names.key(who), sunday), "")


def load(spreadsheet, tabs: List[str] = None) -> Merged:
    out = Merged()
    for tab in (tabs or TABS):
        p = pnl_mod.load(spreadsheet, tab=tab)
        for person in p.people.values():
            k = names.key(person.raw)
            for sunday, amount in person.paid.items():
                cell = (k, sunday)
                if cell in out.paid and abs(out.paid[cell] - amount) > 0.005:
                    out.conflicts.append(
                        f"{person.raw} WE {sunday:%-m/%-d}: "
                        f"{out.source[cell]} says ${out.paid[cell]:,.2f}, "
                        f"{tab} says ${amount:,.2f} — neither written")
                    del out.paid[cell]
                    out.source[cell] = f"CONFLICT ({out.source[cell]} vs {tab})"
                elif cell not in out.paid and not out.source.get(cell, "").startswith("CONFLICT"):
                    out.paid[cell] = amount
                    out.source[cell] = tab
    return out
