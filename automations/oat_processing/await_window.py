"""What the Await text's interview times should say RIGHT NOW.

Started as Carlos's 11580-only rule (2026-10-28): his slots 8:15-10:45 and
12:15-3:45 every 30 minutes, nothing under 30 minutes away, tomorrow after the
last one. The same day Megan made it every chosen office's own schedule, and
set the target window from our show-up data:

  * offer starts **3 to 6 hours from now** -- the show-up sweet spot (10/12
    audit: 1-4h 55.6% show, 4-8h 52.5%, 24h+ 38-42%);
  * none that far out today -> **today's remaining starts anyway** (more than
    30 minutes away): same-day beats tomorrow ("Today's remaining slots
    anyway ... That's under 3 hours, but same-day" -- Megan 10/28);
  * none left today -> the next day that has interviews, all of its starts.

Pure logic, so the rules are testable without a browser; await_template.py
reads the office's schedule and edits the template.
"""

import datetime as dt
import re


def _w(h1, m1, h2, m2):
    return (h1 * 60 + m1, h2 * 60 + m2)


# Offices whose windows were GIVEN to us rather than read off AppStream.
# (start of first slot, start of last slot), every SLOT_STEP_MIN minutes.
WINDOWS_BY_OFFICE = {
    # Carlos, 2026-10-28: 8:15-10:45 and 12:15-3:45, every 30 minutes.
    "11580": [_w(8, 15, 10, 45), _w(12, 15, 15, 45)],
}
WINDOWS = WINDOWS_BY_OFFICE["11580"]
SLOT_STEP_MIN = 30
LEAD_MIN = 30                 # a start this close or closer is never offered
SWEET_MIN, SWEET_MAX = 180, 360   # 3 to 6 hours out

DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday"]


def _fmt(minutes: int) -> str:
    """615 -> '8:15am', 825 -> '1:45pm' -- the template's own style."""
    h, m = divmod(minutes, 60)
    return "%d:%02d%s" % (h % 12 or 12, m, "am" if h < 12 else "pm")


# --- slot starts ---------------------------------------------------------------
def starts_from_windows(windows, step: int = SLOT_STEP_MIN):
    """Given windows (first start, last start), inclusive."""
    out = []
    for a, b in windows:
        s = a
        while s <= b:
            out.append(s)
            s += step
    return sorted(set(out))


def parse_span(text: str):
    """'8:00 AM - 4:00 PM' -> (480, 960), else None."""
    m = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)\s*[-–]\s*(\d{1,2}):(\d{2})"
                  r"\s*([AP]M)", text or "", re.I)
    if not m:
        return None

    def mins(h, mi, ap):
        return (int(h) % 12 + (12 if ap.upper() == "PM" else 0)) * 60 + int(mi)
    a = mins(m.group(1), m.group(2), m.group(3))
    b = mins(m.group(4), m.group(5), m.group(6))
    return (a, b) if b > a else None


def starts_from_spans(spans, step: int):
    """AppStream's open hours -> interview start times: from the span's start,
    every `step` minutes, while the start is before the span's end. So
    '8:15 AM - 8:30 AM' is one 8:15 start (24065's single morning slots) and
    '12:45 PM - 3:45 PM' at 30 minutes is 12:45 ... 3:15."""
    out = []
    for a, b in spans:
        s = a
        while s < b:
            out.append(s)
            s += step
    return sorted(set(out))


# --- choosing and saying -------------------------------------------------------
def pick_starts(now_min: int, starts):
    sweet = [s for s in starts if SWEET_MIN <= s - now_min <= SWEET_MAX]
    if sweet:
        return sweet
    return [s for s in starts if s - now_min > LEAD_MIN]


def _groups(starts, step: int):
    """Consecutive starts no more than `step` apart run together."""
    groups = []
    for s in sorted(starts):
        if groups and s - groups[-1][-1] <= step:
            groups[-1].append(s)
        else:
            groups.append([s])
    return groups


def phrase(day_label: str, starts, step: int) -> str:
    """'available TODAY between 1:15pm-3:15pm', 'available MONDAY between
    8:15am-10:45am or 12:45pm-3:15pm', 'available TODAY at 3:15pm'. At most
    two runs, so the template's own regex always swallows the whole clause."""
    parts = []
    for g in _groups(starts, step)[:2]:
        parts.append(_fmt(g[0]) if len(g) == 1
                     else "%s-%s" % (_fmt(g[0]), _fmt(g[-1])))
    first = _groups(starts, step)[0]
    lead = "at " if len(first) == 1 else "between "
    return "available %s %s%s" % (day_label, lead, " or ".join(parts))


def _wday(day: dt.date) -> str:
    return DAYS[(day.weekday() + 1) % 7]


def day_label(now: dt.datetime, ahead: int) -> str:
    """Megan 2026-10-28: 'this should say "TODAY, Wednesday"'.
    0 -> 'TODAY, Wednesday'; 1 -> 'TOMORROW, Thursday'; more -> 'MONDAY'."""
    d = (now + dt.timedelta(days=ahead)).date()
    if ahead == 0:
        return "TODAY, %s" % _wday(d)
    if ahead == 1:
        return "TOMORROW, %s" % _wday(d)
    return _wday(d).upper()


def clause_for(now: dt.datetime, today_starts, step: int,
               next_label: str = None, next_starts=None) -> str:
    mins = now.hour * 60 + now.minute
    picked = pick_starts(mins, today_starts or [])
    if picked:
        return phrase(day_label(now, 0), picked, step)
    next_label = next_label or day_label(now, 1)
    if next_starts:
        return phrase(next_label, next_starts, step)
    return ""


def await_clause(now: dt.datetime, windows=None, step: int = None) -> str:
    """Carlos-style given windows (default 11580's), same rules."""
    step = int(step or SLOT_STEP_MIN)
    starts = starts_from_windows(list(windows or WINDOWS), step)
    return clause_for(now, starts, step, day_label(now, 1), starts)


def clause_from_schedule(now: dt.datetime, schedule: dict, step: int) -> str:
    """`schedule` = {weekday name: [(start, end), ...]} off the office's own
    AppStream 1st Interview tab. The next day is named: 'TOMORROW', or the
    day itself ('MONDAY' on a Friday evening)."""
    wd = (now.weekday() + 1) % 7            # Python Mon=0 -> DAYS index
    today = starts_from_spans(schedule.get(DAYS[wd], []), step)
    nxt_label, nxt = None, None
    for k in range(1, 8):
        s = starts_from_spans(schedule.get(DAYS[(wd + k) % 7], []), step)
        if s:
            nxt_label, nxt = day_label(now, k), s
            break
    return clause_for(now, today, step, nxt_label, nxt)
