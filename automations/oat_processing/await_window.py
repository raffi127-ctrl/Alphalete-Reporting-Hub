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


def await_clause(now: dt.datetime, windows=None, step: int = None,
                 next_label: str = "TOMORROW", next_windows=None) -> str:
    """The 'available …?' clause the template should carry at `now`, for an
    office's `windows` (default: Carlos's). Always starts with 'available', so
    the template editor can splice it over the old clause with one regex.

    The first slot more than LEAD_MIN away is offered ("between <slot>-<end of
    its window>", or "at <slot>" when it is that window's last), followed by any
    later windows today. None left -> every window, TOMORROW."""
    windows = list(windows or WINDOWS)
    step = int(step or SLOT_STEP_MIN)
    mins = now.hour * 60 + now.minute
    for wi, (start, end) in enumerate(windows):
        slot = start
        while slot <= end:
            if slot - mins > LEAD_MIN:
                first = ("at %s" % _fmt(slot) if slot == end
                         else "between %s" % _span(slot, end))
                rest = [_span(a, b) for a, b in windows[wi + 1:]]
                return "available TODAY " + " or ".join([first] + rest)
            slot += step
    return ("available %s between " % next_label) + " or ".join(
        _span(a, b) for a, b in (next_windows or windows))


# --- from an office's own AppStream schedule ---------------------------------
# Settings > Office Level Settings > "Current Active Interview Slots" (Megan
# 2026-10-28): one row per slot, one column per weekday, cells like
# "8:00 AM - 4:00 PM"; plus "Calendar Time Increment" (5..60 minutes).
DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday"]


def parse_span(text: str):
    """'8:00 AM - 4:00 PM' -> (480, 960), else None."""
    import re
    m = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)\s*[-\u2013]\s*(\d{1,2}):(\d{2})"
                  r"\s*([AP]M)", text or "", re.I)
    if not m:
        return None

    def mins(h, mi, ap):
        h = int(h) % 12 + (12 if ap.upper() == "PM" else 0)
        return h * 60 + int(mi)
    a = mins(m.group(1), m.group(2), m.group(3))
    b = mins(m.group(4), m.group(5), m.group(6))
    return (a, b) if b > a else None


def offerable_windows(day_spans, step: int):
    """The schedule's open hours -> windows of offerable START times: the
    last start is one increment before close (8:00-4:00 at 15 -> last 3:45),
    the way Carlos's own text ends at 3:45."""
    out = []
    for a, b in sorted(day_spans):
        last = b - step
        if last >= a:
            out.append((a, last))
    return out


def clause_from_schedule(now: dt.datetime, schedule: dict, step: int,
                         lead: int = None) -> str:
    """`schedule` = {weekday name: [(start, end), ...]} straight off the page.
    Today's offerable slots first; none left -> the next day that HAS slots,
    'TOMORROW' if that is tomorrow, else its name ('MONDAY')."""
    global LEAD_MIN
    keep = LEAD_MIN
    if lead is not None:
        LEAD_MIN = lead
    try:
        today = DAYS[(now.weekday() + 1) % 7]
        nxt_label, nxt = "TOMORROW", None
        for k in range(1, 8):
            d = DAYS[(now.weekday() + 1 + k) % 7]
            w = offerable_windows(schedule.get(d, []), step)
            if w:
                nxt_label, nxt = ("TOMORROW" if k == 1 else d.upper()), w
                break
        todays = offerable_windows(schedule.get(today, []), step)
        if not todays:
            if not nxt:
                return ""
            return ("available %s between " % nxt_label) + " or ".join(
                _span(a, b) for a, b in nxt)
        return await_clause(now, todays, step, nxt_label, nxt or todays)
    finally:
        LEAD_MIN = keep
