"""READ-ONLY: what the SECOND INTERVIEWS table on the calendar actually says.

WHY THIS EXISTS. The 6pm nudge and the daily update both need per-person
answers the Retention Report cannot give. That report counts rows per label per
day; it can say three people were BOB'd, never that Alma was BOB'd for Nov 30,
Jesse was disqualified and Jacob was only left a voicemail. Megan, 2026-11-18:
"it has to be off the calendar so that you can see what was marked."

So before anything is rebuilt on it, this asks the page three questions:

  1. WHICH DAY IS SHOWN, and can we move it? `open_calendar_for` is documented
     best-effort -- it drives window.cal through jQuery, which patchright's
     isolated world cannot see, so it often returns False. If we cannot move
     the calendar, a 6pm nudge can only ever read today, and "look at yesterday
     too" (the 7pm rule's own window) is not available here. Better to know
     that now than to build a chase that silently only ever sees one day.

  2. WHAT ARE THE REAL FOLLOW UP STATUS OPTIONS. Reading the selected value is
     not enough: the whole point is to split "resolved" from "still owed a
     call", and that split has to name every option, including the ones nobody
     happened to pick yesterday. The <select> carries the full list, so this
     dumps it. Asking the page is the lesson from LABEL_BOB, which was wrong
     for a day and a half because it came from a screenshot.

  3. WHAT DOES THE ACTION COLUMN SAY, verbatim. That is where the BOB DATE
     lives -- "Brought on Board (Nov 30)" -- and the disqualify stamp,
     "Disqualified (11-17 9:20 AM)". Neither exists anywhere else.

CHANGES NOTHING. One office, one page, no writes, nothing clicked.

    PYTHONPATH=. .venv/bin/python -m automations.second_round_contacts.calendar_probe \\
        --office 11280 --date 2026-11-17

Office and date are positional too, which is the form the mini can pass:

    lucy rerun second_round_calendar_probe 24232 2026-11-18
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

# Every cell is found by its HEADER text, never by position: this table has ~19
# columns and an unlabelled icon column, and a new column would silently shift
# every index (house rule, and the reason the fills survive template changes).
# The reader lives in second_interviews so the probe and the nudge can
# never drift into reading the table two different ways.
from automations.second_round_contacts.second_interviews import (  # noqa: E402
    ROW_JS, shown_date)



def main(argv=None) -> int:
    # Office and date are POSITIONAL as well as flags. The mini's `lucy rerun`
    # passes extra arguments through as positionals and its own argparse eats
    # anything starting with "-", so `lucy rerun second_round_calendar_probe
    # 24232 2026-11-18` has to work -- `-- --office 24232` does not reach here.
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("office_pos", nargs="?", default=None,
                    help="AppStream office id (positional form)")
    ap.add_argument("date_pos", nargs="?", default=None,
                    help="YYYY-MM-DD (positional form)")
    ap.add_argument("--office", default=None, help="AppStream office id")
    ap.add_argument("--date", default=None,
                    help="YYYY-MM-DD to try to move the calendar to "
                         "(default: yesterday, the day the 7pm rule looks at)")
    args = ap.parse_args(argv)

    office = args.office or args.office_pos or "11280"
    when = args.date or args.date_pos
    want = (dt.date.fromisoformat(when) if when
            else dt.date.today() - dt.timedelta(days=1))

    from automations.applicant_tracker.applicantstream import session

    with session() as app:
        owner = app.select_office(office)
        print("office %s -> %s" % (office, owner))

        app.open_calendar()
        print("calendar opens on: %s" % shown_date(app))

        moved = app.open_calendar_for(want)
        print("open_calendar_for(%s) -> %s" % (want, moved))
        print("calendar now shows: %s" % shown_date(app))
        if not moved:
            print("  !! could not drive the date picker. Anything built on this "
                  "read can only see whatever day the calendar happens to be "
                  "on, so the look-back at yesterday is NOT available this way.")

        data = app.page.evaluate(ROW_JS)

    if data.get("error"):
        print("\n%s" % data["error"])
        return 1

    # WHICH TABLE. The page has several with the same "Follow Up Status"
    # header; printing the heading is how a wrong-table read gets caught.
    print("\n=== TABLE READ ===\n   heading: %r"
          % (data.get("section") or "(none -- would have REFUSED)"))

    print("\n=== HEADERS (%d) ===\n   %s" % (len(data["headers"]), data["headers"]))

    print("\n=== EVERY FOLLOW UP STATUS THE DROPDOWN OFFERS ===")
    for opt in sorted(o for o in data["options"] if o):
        print("   %r" % opt)

    rows = data["rows"]
    print("\n=== %d PERSON ROW(S) ===" % len(rows))
    for r in rows:
        print("   %-22s showed=%-8s offer=%-5s status=%-26r action=%r"
              % ((r["first"] + " " + r["last"]).strip(), r["showed"] or "-",
                 r["offered"] or "-", r["status"], r["action"]))

    print("\n=== SHOW UP: WHAT THE CELL ACTUALLY CONTAINS ===")
    print("   %d <tr> seen, %d kept, %d skipped"
          % (data.get("seen") or 0, len(rows), len(data.get("skipped") or [])))
    for sk in (data.get("skipped") or []):
        print("   SKIPPED (%s): %s" % (sk.get("why"), sk.get("text")))
    shapes = {}
    for r in rows:
        raw = r.get("show_raw") or {}
        key = ("select" if raw.get("has_select") else
               "radios(%d checked=%s)" % (
                   len(raw.get("radios") or []),
                   ",".join(str(x.get("value")) for x in (raw.get("radios") or [])
                            if x.get("checked")) or "none"))
        shapes.setdefault(key, []).append(
            ((r["first"] + " " + r["last"]).strip(), r["showed"], raw.get("text", "")))
    for key, who in sorted(shapes.items(), key=lambda kv: -len(kv[1])):
        print("   %-34s x%-3d  e.g. %s -> showed=%r  cell=%r"
              % (key, len(who), who[0][0], who[0][1], who[0][2]))

    print("\n=== STATUS -> HOW OFTEN, AND WHAT THE ACTION SAYS ===")
    seen = {}
    for r in rows:
        seen.setdefault(r["status"], []).append(r["action"])
    for status, actions in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        uniq = sorted({a for a in actions if a})
        print("   %-28r x%-3d  %s" % (status, len(actions), uniq[:3]))

    out = "output/second_interviews_probe_%s.json" % office
    try:
        with open(out, "w") as fh:
            json.dump(data, fh, indent=2)
        print("\n(full rows written to %s)" % out)
    except OSError as exc:
        print("\n(could not save the json: %s)" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
