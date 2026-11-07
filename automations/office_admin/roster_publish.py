"""Next week's new starts -> the relay, so the office admin extension can offer them.

WHY (Megan 2026-11-06): on Fridays Aisha sometimes re-sends the Sterling link
to people starting the FOLLOWING week. Their names and emails live on Raf's
onboarding checklist (D2D OBCL rolling tab + that week's dated tab), which the
extension can't read. So this copies that week's roster onto the relay
workbook's 'Office Roster' tab; the extension's "Next week's starts" list reads
it. NOBODY is pre-ticked there -- the admin ticks who needs it.

The roster is read exactly the way bg_check_sync reads it (build_roster), so the
list matches the BG thread in #rafs-office-recruiting-11280.

    python -m automations.office_admin.roster_publish            # next Monday's starts
    python -m automations.office_admin.roster_publish --dry-run  # print, write nothing

bg_check_sync calls publish() after each pass (11:30 / 4pm on Lucy 1), so the
list is never more than a few hours old.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from typing import Dict, List, Optional

TAB = "Office Roster"
HEAD = ["Office", "Week Of", "First", "Last", "Email", "BG Status", "Updated"]
# The OBCL is Raf's checklist, so its roster belongs to office 'raf'.
OFFICE = "raf"
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def next_monday(today: Optional[dt.date] = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=today.weekday()) + dt.timedelta(days=7)


def read_roster(monday: dt.date) -> List[Dict]:
    from automations.bg_check_sync import run as B
    from automations.recruiting_report import fill
    sh = fill.open_by_key(B.SPREADSHEET_ID)
    people, _note = B.build_roster(sh, monday)
    tabs: Dict[str, list] = {}

    def email_of(p) -> str:
        # The dated tab's data can sit a column off its headers (11/9: a
        # checkbox column added under "Email" put TRUE there). So an address
        # only counts if it IS one; otherwise take the cell on their row that is.
        if "@" in (p.email or ""):
            return p.email.strip()
        for tab, row1 in getattr(p, "locations", []) or []:
            if tab not in tabs:
                tabs[tab] = fill._retry(sh.worksheet(tab).get_all_values)
            row = tabs[tab][row1 - 1] if 0 < row1 <= len(tabs[tab]) else []
            hit = next((c.strip() for c in row if _EMAIL.fullmatch(c.strip())), "")
            if hit:
                return hit
        return ""

    out = []
    for p in people:
        if not (p.first or p.last):
            continue
        out.append({"first": p.first.strip(), "last": p.last.strip(),
                    "email": email_of(p), "status": (p.current or "").strip()})
    out.sort(key=lambda r: (r["last"].lower(), r["first"].lower()))
    return out


def rows_for(office: str, monday: dt.date, people: List[Dict], now: str) -> List[List[str]]:
    week = "%d/%d/%d" % (monday.month, monday.day, monday.year)
    return [[office, week, r["first"], r["last"], r["email"], r["status"], now] for r in people]


def write(office: str, rows: List[List[str]]) -> None:
    """Replace this office's rows on the relay's 'Office Roster' tab (other
    offices' rows are kept)."""
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import _retry, open_by_key
    ss = open_by_key(P.RELAY_SPREADSHEET_ID)
    titles = [w.title for w in _retry(ss.worksheets)]
    if TAB in titles:
        ws = _retry(ss.worksheet, TAB)
    else:
        ws = _retry(ss.add_worksheet, title=TAB, rows=200, cols=len(HEAD))
    vals = _retry(ws.get_all_values)
    keep = [r for r in vals[1:] if r and r[0].strip().lower() != office]
    table = [HEAD] + keep + rows
    _retry(ws.clear)
    _retry(ws.update, table, "A1")


def publish(monday: Optional[dt.date] = None, *, dry_run: bool = False, log=print) -> int:
    monday = monday or next_monday()
    people = read_roster(monday)
    now = dt.datetime.now().isoformat(timespec="minutes")
    rows = rows_for(OFFICE, monday, people, now)
    log("office roster: %d new start(s) for the week of %d/%d" % (len(rows), monday.month, monday.day))
    if dry_run:
        for r in rows:
            log("  %s %s  %s  [%s]" % (r[2], r[3], r[4] or "(no email)", r[5] or "-"))
        return len(rows)
    write(OFFICE, rows)
    return len(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Publish next week's new starts for the office admin extension.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--week", help="Monday of the week, YYYY-MM-DD (default: next Monday)")
    a = ap.parse_args(argv)
    monday = dt.date.fromisoformat(a.week) if a.week else None
    publish(monday, dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
