"""What the Await-text's time window should say RIGHT NOW (Carlos 2026-10-28).

Office 11580's "Await Call AI" SMS template offers interview times. Those times
were static, so afternoon applicants were offered mornings that had already
passed. Before each push pass the pusher recomputes the clause and edits the
template (await_template.py drives the browser; this module is the pure logic,
so the rules are testable without a browser).

Carlos's rules, his corrections applied:
- First-round interview slots run 8:15-10:45 and 12:15-3:45, every 30 minutes
  (:15 and :45).
- A slot under 30 minutes away is too soon — "it skips to the next time slot".
- After the last offerable slot (now past 3:15), offer tomorrow instead.
"""

import datetime as dt

# EACH OFFICE'S OWN interview windows, (start, end) minutes-from-midnight
# (Megan 2026-10-28: "build this in to all resume pushing going forward so
# we're sending out the correct times"). A per-office fact -- an office with no
# row here is NEVER given someone else's times; its template is left alone.
def _w(h1, m1, h2, m2):
    return (h1 * 60 + m1, h2 * 60 + m2)


WINDOWS_BY_OFFICE = {
    # Carlos, 2026-10-28: 8:15-10:45 and 12:15-3:45, every 30 minutes.
    "11580": [_w(8, 15, 10, 45), _w(12, 15, 15, 45)],
}
# Kept for callers that predate the table: Carlos's.
WINDOWS = WINDOWS_BY_OFFICE["11580"]
SLOT_STEP_MIN = 30
LEAD_MIN = 30          # a slot this close or closer is skipped


def _fmt(minutes: int) -> str:
    """615 -> '8:15am', 825 -> '1:45pm' — the template's own style (probed live
    2026-10-28: 'Are you available TODAY between 12:15pm-3:45pm for a quick
    ZOOM…')."""
    h, m = divmod(minutes, 60)
    return "%d:%02d%s" % (h % 12 or 12, m, "am" if h < 12 else "pm")


def _span(a: int, b: int) -> str:
    return "%s-%s" % (_fmt(a), _fmt(b))


def await_clause(now: dt.datetime, windows=None) -> str:
    """The 'available …?' clause the template should carry at `now`, for an
    office's `windows` (default: Carlos's). Always starts with 'available', so
    the template editor can splice it over the old clause with one regex.

    The first slot more than LEAD_MIN away is offered ("between <slot>-<end of
    its window>", or "at <slot>" when it is that window's last), followed by any
    later windows today. None left -> every window, TOMORROW."""
    windows = list(windows or WINDOWS)
    mins = now.hour * 60 + now.minute
    for wi, (start, end) in enumerate(windows):
        slot = start
        while slot <= end:
            if slot - mins > LEAD_MIN:
                first = ("at %s" % _fmt(slot) if slot == end
                         else "between %s" % _span(slot, end))
                rest = [_span(a, b) for a, b in windows[wi + 1:]]
                return "available TODAY " + " or ".join([first] + rest)
            slot += SLOT_STEP_MIN
    return "available TOMORROW between " + " or ".join(
        _span(a, b) for a, b in windows)
