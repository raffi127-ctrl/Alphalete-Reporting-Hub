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
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

# Every cell is found by its HEADER text, never by position: this table has ~19
# columns and an unlabelled icon column, and a new column would silently shift
# every index (house rule, and the reason the fills survive template changes).
ROW_JS = """() => {
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim();

    // The SECOND INTERVIEWS table is the one with a "Follow Up Status" header.
    let table = null, headers = [];
    for (const t of document.querySelectorAll('table')) {
        for (const tr of t.querySelectorAll('tr')) {
            const cells = [...tr.children].map(c => norm(c.innerText));
            if (cells.some(c => /^follow up status$/i.test(c))) {
                table = t; headers = cells; break;
            }
        }
        if (table) break;
    }
    if (!table) return {error: 'no table with a Follow Up Status header'};

    const idx = name => headers.findIndex(h => h.toLowerCase().startsWith(name));
    const want = {first: idx('first name'), last: idx('last name'),
                  email: idx('email'), show: idx('show up'),
                  status: idx('follow up status'), by: idx('follow up by'),
                  time: idx('follow up time'), action: idx('action')};

    const rows = [], options = new Set();
    for (const tr of table.querySelectorAll('tr')) {
        const cells = [...tr.children];
        if (cells.length < 5) continue;
        const text = i => (i >= 0 && cells[i]) ? norm(cells[i].innerText) : '';
        const first = text(want.first), last = text(want.last);
        if (!first || /^first name$/i.test(first)) continue;

        // Follow Up Status is a <select>: the chosen one AND every option it
        // offers, which is the vocabulary we have to classify.
        let status = '', picked = '';
        const sel = cells[want.status] && cells[want.status].querySelector('select');
        if (sel) {
            [...sel.options].forEach(o => options.add(norm(o.text)));
            picked = norm(sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : '');
            status = picked;
        } else {
            status = text(want.status);
        }

        // "Show Up" is two different controls: radio Yes/No for a no-show, and
        // an "Offer Position? [Yes/No]" <select> once somebody has turned up.
        // Which control is present is itself the answer to "did they show".
        let showed = '', offered = '';
        const cell = cells[want.show];
        if (cell) {
            const osel = cell.querySelector('select');
            if (osel) {
                showed = 'yes';
                offered = norm(osel.options[osel.selectedIndex] ? osel.options[osel.selectedIndex].text : '');
            } else {
                const checked = [...cell.querySelectorAll('input[type=radio]')]
                    .filter(r => r.checked);
                const lbl = norm(cell.innerText).toLowerCase();
                showed = checked.length
                    ? (/\\byes\\b/.test(lbl) && checked[0].value &&
                       /yes/i.test(checked[0].value) ? 'yes' : 'no')
                    : '';
                if (!showed && checked.length === 0) showed = 'unmarked';
            }
        }

        rows.push({first, last, email: text(want.email),
                   showed, offered, status,
                   follow_up_by: text(want.by), follow_up_time: text(want.time),
                   action: text(want.action)});
    }
    return {headers, rows, options: [...options]};
}"""


def shown_date(app) -> str:
    """Whatever day the calendar is actually displaying, as it writes it."""
    try:
        return app.page.evaluate(
            """() => {
                const p = document.querySelector('#topLevelDatePicker');
                if (p && p.value) return p.value;
                const h = document.body.innerText.match(
                    /\\b\\w+day,?\\s+\\w+\\s+\\d{1,2},?\\s+\\d{4}\\b/);
                return h ? h[0] : '(could not tell)';
            }""")
    except Exception as exc:                                  # noqa: BLE001
        return "(error: %s)" % type(exc).__name__


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office", default="11280", help="AppStream office id")
    ap.add_argument("--date", default=None,
                    help="YYYY-MM-DD to try to move the calendar to "
                         "(default: yesterday, the day the 7pm rule looks at)")
    args = ap.parse_args(argv)

    want = (dt.date.fromisoformat(args.date) if args.date
            else dt.date.today() - dt.timedelta(days=1))

    from automations.applicant_tracker.applicantstream import session

    with session() as app:
        owner = app.select_office(args.office)
        print("office %s -> %s" % (args.office, owner))

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

    print("\n=== STATUS -> HOW OFTEN, AND WHAT THE ACTION SAYS ===")
    seen = {}
    for r in rows:
        seen.setdefault(r["status"], []).append(r["action"])
    for status, actions in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        uniq = sorted({a for a in actions if a})
        print("   %-28r x%-3d  %s" % (status, len(actions), uniq[:3]))

    out = "output/second_interviews_probe.json"
    try:
        with open(out, "w") as fh:
            json.dump(data, fh, indent=2)
        print("\n(full rows written to %s)" % out)
    except OSError as exc:
        print("\n(could not save the json: %s)" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
