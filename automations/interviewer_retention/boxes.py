"""The three ARS boxes, computed in Python from one row per interview.

Megan 2026-11-27: "I really don't like hardcoded formulas - we should take over
so that we're right each time and nothing breaks." So the boxes are worked out
here and written as plain values. The rules below are the ARS tab's own
COUNTIFS, read off 'Rafael Hidalgo' row 5 on 2026-11-25, so a week we fill and a
week the formulas filled mean the same thing. check.py proves that by
re-computing six past weeks from the typed rows and comparing every cell.

THE WEEK. A box is labelled with the Sunday that ENDS its week (`anchor`).
  1st-round boxes: day columns Mon..Fri  = anchor-6 .. anchor-2
                   TOTAL                 = Mon..Sat (after anchor-7, before anchor)
                   interviewers listed   = anyone with a 1st round anchor-7..anchor
  2nd-round box:   day columns Mon..Sat  = anchor-6 .. anchor-1, by 2nd-round DATE
                   TOTAL booked          = the six day columns added up
                   TOTAL showed          = Mon..Sat
                   interviewers listed   = anyone with a 2nd round anchor-6..anchor
  The 2nd-round box is still listed under the 1ST-round interviewer.

THE VALUES (exactly the ARS dropdowns):
  qualify  Qualify | Disqualify | Disqualify - Declined
  answer   Answered | No Answer | Not Contacted
  booked   Booked | Not Booked
  show2    Showed | No Show | Reschedule Requested | Cancelled

Pure: no Google, no browser.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

QUALIFY, DISQUALIFY, DECLINED = "Qualify", "Disqualify", "Disqualify - Declined"
ANSWERED, NO_ANSWER, NOT_CONTACTED = "Answered", "No Answer", "Not Contacted"
BOOKED = "Booked"
SHOWED, NO_SHOW, RESCHEDULE, CANCELLED = "Showed", "No Show", "Reschedule Requested", "Cancelled"


@dataclass(frozen=True)
class Interview:
    interviewer: str                 # the ARS dropdown name ("Victoria", "Valentina R")
    date1: Optional[dt.date]         # Date 1st Rd
    qualify: str = ""
    answer: str = ""
    booked: str = ""
    date2: Optional[dt.date] = None  # Date 2nd Rd
    show2: str = ""


def _pct(num: int, den: int) -> float:
    return num / den if den else 0.0     # IFERROR(x/y, 0)


def _unique(names: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def days_1st(anchor: dt.date) -> List[dt.date]:
    return [anchor - dt.timedelta(days=k) for k in (6, 5, 4, 3, 2)]       # Mon..Fri


def days_2nd(anchor: dt.date) -> List[dt.date]:
    return [anchor - dt.timedelta(days=k) for k in (6, 5, 4, 3, 2, 1)]    # Mon..Sat


def _in_total(d: Optional[dt.date], anchor: dt.date) -> bool:
    return d is not None and anchor - dt.timedelta(days=7) < d < anchor  # Mon..Sat


def qualified_box(rows: List[Interview], anchor: dt.date) -> List[Dict]:
    lo = anchor - dt.timedelta(days=7)
    who = _unique(r.interviewer for r in rows if r.date1 and lo <= r.date1 <= anchor)
    out = []
    for name in who:
        mine = [r for r in rows if r.interviewer == name]

        def cnt(pred) -> Dict[str, int]:
            sub = [r for r in mine if pred(r)]
            return {"Q": sum(r.qualify == QUALIFY for r in sub),
                    "Di": sum(r.qualify == DISQUALIFY for r in sub),
                    "De": sum(r.qualify == DECLINED for r in sub)}

        def with_pct(c: Dict[str, int]) -> Dict:
            t = c["Q"] + c["Di"] + c["De"]
            return {**c, "QR": _pct(c["Q"], t), "DiR": _pct(c["Di"], t), "DR": _pct(c["De"], t)}

        out.append({"interviewer": name,
                    "days": [with_pct(cnt(lambda r, d=d: r.date1 == d)) for d in days_1st(anchor)],
                    "total": with_pct(cnt(lambda r: _in_total(r.date1, anchor)))})
    return out


def answered_box(rows: List[Interview], anchor: dt.date) -> List[Dict]:
    lo = anchor - dt.timedelta(days=7)
    who = _unique(r.interviewer for r in rows if r.date1 and lo <= r.date1 <= anchor)
    out = []
    for name in who:
        mine = [r for r in rows if r.interviewer == name]

        def cnt(pred) -> Dict:
            sub = [r for r in mine if pred(r)]
            c = {"Q": sum(r.qualify == QUALIFY for r in sub),
                 "A": sum(r.answer == ANSWERED for r in sub),
                 "B": sum(r.booked == BOOKED for r in sub),
                 "NC": sum(r.answer == NOT_CONTACTED for r in sub)}
            return {**c, "AR": _pct(c["A"], c["Q"]), "BR": _pct(c["B"], c["Q"]),
                    "NCR": _pct(c["NC"], c["Q"])}

        out.append({"interviewer": name,
                    "days": [cnt(lambda r, d=d: r.date1 == d) for d in days_1st(anchor)],
                    "total": cnt(lambda r: _in_total(r.date1, anchor))})
    return out


def second_box(rows: List[Interview], anchor: dt.date) -> List[Dict]:
    lo = anchor - dt.timedelta(days=6)
    who = _unique(r.interviewer for r in rows if r.date2 and lo <= r.date2 <= anchor)
    out = []
    for name in who:
        mine = [r for r in rows if r.interviewer == name]
        days = []
        for d in days_2nd(anchor):
            sub = [r for r in mine if r.date2 == d]
            c = {"B": sum(r.booked == BOOKED for r in sub),
                 "S": sum(r.show2 == SHOWED for r in sub),
                 "NS": sum(r.show2 == NO_SHOW for r in sub),
                 "RR": sum(r.show2 == RESCHEDULE for r in sub),
                 "C": sum(r.show2 == CANCELLED for r in sub)}
            days.append({**c, "R": _pct(c["S"], c["B"])})
        booked = sum(d["B"] for d in days)
        showed = sum(r.show2 == SHOWED for r in mine if _in_total(r.date2, anchor))
        out.append({"interviewer": name, "days": days,
                    "total": {"Booked": booked, "Showed": showed, "R": _pct(showed, booked)}})
    return out


def week(rows: List[Interview], anchor: dt.date) -> Dict[str, List[Dict]]:
    return {"qualified": qualified_box(rows, anchor),
            "answered": answered_box(rows, anchor),
            "second": second_box(rows, anchor)}
