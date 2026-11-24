""""I have made today's brought-on-board calls" -- the press, and the gate.

Megan, 2026-11-24: *"there should be some button that says, I've made the
brought on board calls for today, after they've already marked them in
applicant stream and scheduled them. And that will trigger the daily update
being ran ... the daily update should be sent out every day, but it can't be
sent out until the BOB calls are done. So that's a manual trigger that has to
happen."*

WHY A PRESS AND NOT A CLOCK. The daily update's whole content is what happened
to each person marked offered -- their follow-up, who ran it, the BOB and its
date. All of that is written by a recruiter DURING the calls, so an update
posted before they finish is an update with the answers missing, sent to the
office as though it were the day's record. One office already works around
this by covering YESTERDAY at noon, which is a day late rather than gated.

ONE ROW PER OFFICE PER DAY, on the relay workbook. Not a state file: the press
happens on an admin's machine or in the extension and the gate is read by
whichever box runs that office's update, so the answer has to be somewhere both
can see. A second press on the same day changes nothing.

IT GATES, IT DOES NOT SEND. `done()` is a question the update asks on its way
in. Pressing it does not post anything by itself -- the update's own run is
what posts, and it may be minutes later. A press that posted directly would
mean a mis-press sends an office its day's record with nothing in it.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.office_admin import config as C
from automations.office_admin import sheets as S

TAB = "BOB Calls Done"
HEADERS = ["Office Key", "Day", "Marked At", "By", "Note"]


def _tab(sheet_id: str = ""):
    return S.open_tab(TAB, HEADERS, sheet_id)


def _day(day: Optional[dt.date] = None) -> str:
    return (day or dt.date.today()).isoformat()


def rows(ws=None, sheet_id: str = "") -> List[Dict[str, str]]:
    ws = ws or _tab(sheet_id)
    return S.records(S._retry(ws.get_all_values))


def done(office_key: str, day: Optional[dt.date] = None, *,
         ws=None, sheet_id: str = "") -> bool:
    """Has this office said its calls are made for that day?

    FALSE WHEN IT CANNOT BE READ. The gate has to fail CLOSED: an update that
    posts because the sheet was unreachable is the exact thing the gate exists
    to stop, and a held update is visible the moment somebody looks for it.
    """
    key = str(office_key or "").strip().lower()
    if not key:
        return False
    want = _day(day)
    try:
        for r in rows(ws, sheet_id):
            if str(r.get("Office Key", "")).strip().lower() != key:
                continue
            if str(r.get("Day", "")).strip() == want:
                return True
    except Exception:          # noqa: BLE001 -- see the docstring
        return False
    return False


def mark(office_key: str, *, by: str = "", day: Optional[dt.date] = None,
         note: str = "", ws=None, sheet_id: str = "") -> bool:
    """Record the press. True when it was written, False when it already was.

    IDEMPOTENT BY DAY, so a second press -- somebody pressing again because
    nothing visibly happened -- is not a second row and not a second anything.
    """
    key = str(office_key or "").strip().lower()
    if not key:
        raise ValueError("no office key")
    ws = ws or _tab(sheet_id)
    if done(key, day, ws=ws):
        return False
    row = {"Office Key": key, "Day": _day(day), "Marked At": S.now_str(),
           "By": by, "Note": note}
    S._retry(ws.append_row, [row.get(h, "") for h in HEADERS],
             value_input_option="RAW")
    return True


def waiting_on(office_keys, day: Optional[dt.date] = None,
               *, sheet_id: str = "") -> List[str]:
    """Which of these offices has not pressed it yet today -- what the 6pm
    nudge is about, and what holds each one's update."""
    try:
        ws = _tab(sheet_id)
        got = rows(ws)
    except Exception:          # noqa: BLE001 -- unreadable: everybody is owed
        return [str(k).strip().lower() for k in office_keys if str(k).strip()]
    want = _day(day)
    said = {str(r.get("Office Key", "")).strip().lower()
            for r in got if str(r.get("Day", "")).strip() == want}
    return [k for k in (str(x).strip().lower() for x in office_keys)
            if k and k not in said]


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--office", required=True, help="ECO office key")
    ap.add_argument("--mark", action="store_true",
                    help="record that today's calls are made")
    ap.add_argument("--by", default="", help="who pressed it")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (default today)")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.day) if a.day else None
    if a.mark:
        wrote = mark(a.office, by=a.by or "by hand", day=day)
        print("recorded" if wrote else "already recorded for that day")
    print("%s: BOB calls %s for %s"
          % (a.office, "DONE" if done(a.office, day) else "not marked",
             _day(day)))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
