"""What the 6pm nudge read: how many BOB calls this office still owes today.

THE POP-UP HALF OF THE NUDGE NEEDS AN ANSWER IT CANNOT WORK OUT ITSELF.
Megan, 2026-11-18: the nudge "should pop up on app stream and send DM in
slack". The DM half (`second_round_contacts.bob_nudge`) reads the calendar's
SECOND INTERVIEWS table with a real browser, through a login, applying rules
that took a day of probing to get right -- which rows count as turned up,
which four marks count as answered, which of the calendar's several
same-headed tables is the right one. A Chrome extension on the admin's own
ApplicantStream page could try to re-derive all of that in JavaScript, and
then there would be TWO answers to one question. The day they disagree, the
pop-up tells an office it owes calls the DM says are made, and both get
ignored.

So the nudge PUBLISHES what it read, here, and the pop-up asks. One row per
office per day, updated in place -- the nudge ticks hourly through the evening
(16:05-20:05, because 6pm in Los Angeles is 8pm in Chicago), so appending
would be five rows an office a day for one answer.

NEXT TO THE PRESS, DELIBERATELY. `bob_calls` ("I've made today's calls") is
the other half of the pop-up's question and lives on the same workbook, so the
relay answers both from one book and one read. Two books would be two failure
modes for one pop-up.

NO SNAPSHOT IS NOT ZERO. `owed()` answers None when this office has no row for
the day, and that is the same safety stop the DM half has: an office with
nothing on today and an office whose calendar would not load look identical
from here, and a pop-up on the second trains people to dismiss the first. The
nudge writes a row saying 0 when it really read 0, and writes NOTHING at all
when the read failed -- so None means "nobody has looked", which nudges
nobody.

THE SNAPSHOT CARRIES ITS OWN DEADLINE. `Nudge` is TRUE only once the office
has reached its own local 6pm, decided by the nudge off the office's own
`timezone` -- the one place that knows an office's clock stays the one place
that decides it. The relay compares nothing but freshness.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Dict, List, Optional

from automations.office_admin import sheets as S

TAB = "BOB Calls Owed"
HEADERS = ["Office Key", "Day", "Outstanding", "Names JSON", "Nudge",
           "Read At", "Read By"]

# How old a snapshot may be and still be worth putting on somebody's screen.
# The nudge ticks hourly, so a healthy snapshot is under an hour old; three
# hours is "two ticks have failed", which is a read that is not working and
# therefore not something to pop a window about. The relay enforces it (it is
# what answers the extension); it is named here because this is the file that
# defines what a snapshot is, and the test holds the two to the same number.
STALE_MINUTES = 180


def _tab(sheet_id: str = ""):
    return S.open_tab(TAB, HEADERS, sheet_id)


def _day(day: Optional[dt.date] = None) -> str:
    return (day or dt.date.today()).isoformat()


def _stamp() -> str:
    """Now, as an instant anybody can read without knowing where we are.

    NOT `sheets.now_str()`, which is the writing machine's naive local time.
    The relay is what works out whether a snapshot is stale, and it runs in
    Apps Script's own timezone -- so a naive stamp means the freshness check
    is wrong by however many hours apart the two happen to be, silently, and
    in the direction that shows stale nudges.
    """
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def rows(ws=None, sheet_id: str = "") -> List[Dict[str, str]]:
    ws = ws or _tab(sheet_id)
    return S.records(S._retry(ws.get_all_values))


def _find(got: List[Dict[str, str]], key: str, want_day: str):
    for r in got:
        if str(r.get("Office Key", "")).strip().lower() != key:
            continue
        if str(r.get("Day", "")).strip() == want_day:
            return r
    return None


def publish(office_key: str, names, *, nudge: bool,
            day: Optional[dt.date] = None, by: str = "",
            ws=None, sheet_id: str = "") -> bool:
    """Record what the nudge read for this office today. True when written.

    `names` is everybody still owed -- an EMPTY LIST is a real answer and gets
    written (the office's calendar was read and everyone is marked). A read
    that failed must not call this at all: see the module docstring.

    UPDATED IN PLACE. The nudge reads again every hour through the evening and
    the answer changes as calls get made; the pop-up wants the latest one, and
    a history of five is of no use to anybody.

    RAW, so the Day and Read At cells stay the text they were written as.
    Sheets parses '2026-11-24' into a Date given the chance, and then the
    press's own lookup -- which compares strings -- stops matching it
    (the bug the relay's own `_dayKey` exists for).
    """
    key = str(office_key or "").strip().lower()
    if not key:
        raise ValueError("no office key")
    clean = [" ".join(str(n or "").split()) for n in (names or [])]
    clean = [n for n in clean if n]
    ws = ws or _tab(sheet_id)
    want = _day(day)
    row = {"Office Key": key, "Day": want, "Outstanding": str(len(clean)),
           "Names JSON": json.dumps(clean), "Nudge": "TRUE" if nudge else "FALSE",
           "Read At": _stamp(), "Read By": by}
    line = [row.get(h, "") for h in HEADERS]
    found = _find(rows(ws), key, want)
    if found is not None:
        S._retry(ws.update, [line], "A%d:%s%d"
                 % (found["_row"], chr(ord("A") + len(HEADERS) - 1),
                    found["_row"]),
                 value_input_option="RAW")
        return True
    S._retry(ws.append_row, line, value_input_option="RAW")
    return True


def owed(office_key: str, day: Optional[dt.date] = None, *,
         ws=None, sheet_id: str = "") -> Optional[dict]:
    """The snapshot for this office and day, or None when there isn't one.

    NONE IS NOT ZERO, and the difference is the whole safety stop -- see the
    module docstring. An unreadable sheet is also None: a pop-up that appears
    when the read failed is worse than no pop-up, because it is the one that
    teaches people to dismiss the real ones.
    """
    key = str(office_key or "").strip().lower()
    if not key:
        return None
    want = _day(day)
    try:
        found = _find(rows(ws, sheet_id), key, want)
    except Exception:          # noqa: BLE001 -- see the docstring
        return None
    if found is None:
        return None
    try:
        names = json.loads(found.get("Names JSON") or "[]")
        names = [str(n) for n in names] if isinstance(names, list) else []
    except ValueError:
        names = []
    try:
        count = int(str(found.get("Outstanding") or "0").strip() or 0)
    except ValueError:
        count = len(names)
    return {"office": key, "day": want, "count": count, "names": names,
            "nudge": str(found.get("Nudge", "")).strip().upper() == "TRUE",
            "read_at": str(found.get("Read At", "")).strip(),
            "read_by": str(found.get("Read By", "")).strip()}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--office", required=True, help="ECO office key")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (default today)")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.day) if a.day else None
    got = owed(a.office, day)
    if got is None:
        print("%s: no snapshot for %s -- nothing has read that office's "
              "calendar, so nothing is nudged." % (a.office, _day(day)))
        return 0
    print("%s: %d outstanding as of %s (nudge=%s)%s"
          % (a.office, got["count"], got["read_at"] or "?",
             "yes" if got["nudge"] else "not yet",
             "".join("\n  - %s" % n for n in got["names"])))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
