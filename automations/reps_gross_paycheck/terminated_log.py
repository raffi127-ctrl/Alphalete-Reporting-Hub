"""The second opinion on who's gone: the 'Terminated Reps' tab.

Lives in the PNL workbook (same file as 'Raf PNL 2026'), one row per departure
since 2024: Rep Name | Lead Rep | # Days Worked | Termination Date WE |
Ownerville | Slack Deact | Notes | Year. ~2,300 people.

WHY BOTH SOURCES. Checked against the sales board 2026-08-07: all 20 tabs the
board flagged are in this log too — the two agree completely on those. But the
log knows about ELEVEN MORE people who still had tabs and whose board row never
got a Termination Date (Jackie Williams, Kevin Gentry, Luis Aguilera, Marcus
Watson, plus the older ones). Going off the board alone kept paying attention
to reps who left in June.

WHY THE LOG CANNOT STAND ALONE EITHER: it is append-only and nobody removes a
row when someone comes BACK. Tadana Manyangadze is logged as terminated
5/29/2026 and is on the WE 8.9 board right now as '5th wk+'. So a log row only
counts when the rep is ALSO absent from the newest board — presence there
outranks any historical departure. That rehire is the exact case a
log-only rule would get wrong, and it's a live rep, not a hypothetical.

Names in column A sometimes separate first and last with a TAB character
('Christian\\tWilliams'), and carry the same drifting suffixes as everywhere
else ('Daniel Brito (Wk 3)' here vs '(Wk 2)' on the tab). names.key handles
both.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, Optional

from automations.reps_gross_paycheck import names

TAB = "Terminated Reps"
NAME_COL = 0
WE_COL = 3                      # 'Termination Date WE'
YEAR_COL = 7


@dataclass
class LogEntry:
    raw: str
    row: int
    we: Optional[dt.date]
    we_raw: str
    year: str

    @property
    def where(self) -> str:
        return f"'{TAB}' row {self.row} ({self.raw}, WE {self.we_raw or '—'})"


def _parse(s: str) -> Optional[dt.date]:
    s = str(s or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def load(spreadsheet, tab: str = TAB) -> Dict[str, LogEntry]:
    """{join key: most recent LogEntry}. Latest row wins — someone logged
    twice (left, came back, left again) is described by their last departure."""
    from automations.recruiting_report.fill import _retry
    grid = _retry(spreadsheet.worksheet(tab).get_all_values)
    out: Dict[str, LogEntry] = {}
    for i, row in enumerate(grid[1:], start=2):
        raw = str(row[NAME_COL] if row else "").strip()
        if not raw or raw.lower() == "rep name":
            continue
        k = names.key(raw)
        if not k:
            continue
        we_raw = str(row[WE_COL]).strip() if len(row) > WE_COL else ""
        entry = LogEntry(raw=raw.replace("\t", " "), row=i, we=_parse(we_raw),
                         we_raw=we_raw,
                         year=str(row[YEAR_COL]).strip() if len(row) > YEAR_COL else "")
        prev = out.get(k)
        if prev is None or (entry.we and (prev.we is None or entry.we >= prev.we)):
            out[k] = entry
    return out
