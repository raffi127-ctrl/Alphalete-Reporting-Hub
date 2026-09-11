"""Turn an ICD's raw OwnerVille rows into the fields a board is drawn from.

THE VOCABULARY LIVES HERE, NOT ON THE LAPTOP. The agent relays rows keyed by
whatever the grid called its columns, because fiber, wireless and Energy Wells
all render different dispositions and a laptop that shipped opinions about
column names would need a release every time one was renamed. This is where
those names become something we can draw.

BY LABEL, NEVER BY POSITION -- the repo rule, and the reason it exists: a grid
that gains a column shifts every index after it, and the board would keep
drawing, with the wrong numbers in the right places.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

# Each canonical field and the header texts that have meant it. Normalised
# (lower case, collapsed whitespace) the same way ownerville_knocks reads them.
ALIASES = {
    "rep": ("rep", "rep name", "name", "agent", "user name"),
    "total_knocks": ("total knocks", "knocks", "total knock"),
    "total_leads": ("total leads knocked", "leads knocked", "total leads"),
    "first_knock": ("first knock", "first knock time"),
    "last_knock": ("last knock", "last knock time"),
    "sale": ("sale", "sales"),
}


def _pick(row: Dict[str, str], field: str) -> str:
    for alias in ALIASES[field]:
        if alias in row:
            return (row.get(alias) or "").strip()
    return ""


def _int(v) -> int:
    try:
        return int(float(re.sub(r"[^\d.\-]", "", str(v)) or 0))
    except (TypeError, ValueError):
        return 0


def parse_clock(value: str, day: dt.date) -> Optional[dt.datetime]:
    """A 'Last Knock' cell as a datetime on `day`.

    The grid has shown this as a bare time ('7:42 PM'), a 24-hour time, and a
    full date-time. Each is tried; an unparseable cell returns None and the rep
    simply has no gap, which is the safe direction -- inventing a timestamp
    would put somebody on an inactive list for a knock they did make.
    """
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
                "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    for fmt in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            t = dt.datetime.strptime(text, fmt).time()
            return dt.datetime.combine(day, t)
        except ValueError:
            continue
    return None


def to_reps(rows: List[Dict[str, str]], day: dt.date) -> List[Dict]:
    """[{name, total_knocks, first_knock, last_knock, last_knock_at}] per rep.

    Rows with no rep name are dropped: DataTables renders a 'no data
    available' row, and a totals row is not a person.
    """
    out = []
    for row in rows or []:
        # Keys arrive normalised from the agent, but a hand-made row (a test,
        # a paste into the sheet) may not be -- so normalise again here rather
        # than trusting the sender.
        row = {re.sub(r"\s+", " ", str(k or "")).strip().lower(): v
               for k, v in row.items()}
        name = _pick(row, "rep")
        if not name or name.lower() in ("total", "totals"):
            continue
        last = _pick(row, "last_knock")
        out.append({
            "name": name,
            "total_knocks": _int(_pick(row, "total_knocks")),
            "total_leads": _int(_pick(row, "total_leads")),
            "first_knock": _pick(row, "first_knock"),
            "last_knock": last,
            "last_knock_at": parse_clock(last, day),
        })
    return out


def gaps(reps: List[Dict], now: dt.datetime, threshold_min: int = 15) -> List[Dict]:
    """The reps who have not knocked for `threshold_min`, worst first.

    A rep with NO parseable last knock is not listed. They may not have started
    yet, and 'inactive for 1,183 minutes' in front of their team because a cell
    was blank is a mistake that lands on a person.
    """
    out = []
    for rep in reps:
        when = rep.get("last_knock_at")
        if not when:
            continue
        mins = int((now - when).total_seconds() // 60)
        if mins >= threshold_min:
            out.append({"name": rep["name"],
                        "minutesSinceLastKnock": mins,
                        "lastKnockDate": rep.get("last_knock") or ""})
    out.sort(key=lambda r: -r["minutesSinceLastKnock"])
    return out
