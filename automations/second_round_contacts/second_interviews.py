"""The SECOND INTERVIEWS table on the calendar: what each person was marked.

WHY THE CALENDAR AND NOT THE RETENTION REPORT (Megan, 2026-11-18: "it has to
be off the calendar so that you can see what was marked"). The report counts
rows per label per day. It can say three people were BOB'd; it cannot say Alma
was BOB'd for Nov 30 while Jesse was disqualified and Jacob only got a
voicemail. Those three need completely different follow-up, and a chase built
on "are they on the BOB list" treats them all the same.

THE WHOLE MODEL, in Megan's words (2026-11-18):

    "you just look at those marked no show - those go on the daily update as
     'No Show' and then those marked showed - get 1 of the 4 status :
     BOB date, Declined, Disqualified, LM"

So there are exactly two questions, in order:

  1. DID THEY TURN UP? Marked No Show -> they are a No Show on the daily
     update and nothing else is owed. Marked showed -> question 2. Neither
     ticked -> nobody has said yet, which is its own answer and not a no-show.

  2. WHAT HAPPENED ON THE CALL? One of FOUR, and only these four count as
     marked:
        BOB          -- brought on board. The DATE comes with it, and only
                        from the Action column: "Brought on Board (Nov 30)".
        Declined     -- the applicant turned the role down.
        Disqualified -- the leader did not want to move forward.
        LM           -- left message. We rang to offer it and got voicemail.

ANYTHING ELSE MEANS THE CALL HAS NOT BEEN MARKED. The dropdown holds thirty
options (probed, office 11280, 2026-11-18) and most belong to other steps of
the funnel. `Confirmed by Text` is the one that matters here: it is the most
common status on people who showed up, and it confirms the SECOND INTERVIEW,
not the call (Megan: "that's not a status of the BOB call"). Reading it as
done would have silently dropped nine of yesterday's eleven.

That is also why the four are an allow-list rather than a block-list of
statuses to ignore. A new option added in ApplicantStream then shows up as
"not marked yet" -- visible, and chased -- instead of being silently counted
as a call that was made.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

# The four, as the dropdown spells them -> what we call them.
# Compared whitespace-collapsed and lower-cased, never with `in`, so
# "BOB - Waiting Answer" cannot match on "bob -" and count as a landed call.
BOB = "bob - booked"
DECLINED = "declined next round"
DISQUALIFIED = "rejected or not qualified"
LM = "left message"

MARKED = {BOB: "BOB", DECLINED: "Declined",
          DISQUALIFIED: "Disqualified", LM: "LM"}

# What the dropdown shows when nothing has been picked.
UNSET = "-select follow up-"


def norm(s) -> str:
    return " ".join(str(s or "").split()).strip().lower()


def showed_up(row: Dict) -> Optional[bool]:
    """True / False / None -- and None is NOT a no-show.

    Nobody having ticked the box means nobody has said yet. Counting that as a
    no-show would put people on the daily update as not turning up when the
    truth is that the admin has not got to it, which is the exact failure the
    chart's Show Up note is about.
    """
    got = norm(row.get("showed"))
    if got == "yes":
        return True
    if got == "no":
        return False
    return None


def mark_of(row: Dict) -> str:
    """"BOB" | "Declined" | "Disqualified" | "LM" | "" for somebody who showed."""
    return MARKED.get(norm(row.get("status")), "")


def bob_date(action: str, today: Optional[dt.date] = None) -> Optional[dt.date]:
    """The start date out of "Brought on Board (Nov 30)", or None.

    THE YEAR IS NOT ON THE PAGE, so it is inferred as the next occurrence,
    allowing a few weeks back. A BOB read on Dec 28 that says "Jan 5" means
    next January; taking the current year would put the start eleven months in
    the past and make every window built on it wrong.
    """
    m = re.search(r"brought on board\s*\(([^)]+)\)", str(action or ""), re.I)
    if not m:
        return None
    raw = " ".join(m.group(1).split())
    today = today or dt.date.today()
    for fmt in ("%b %d", "%B %d", "%m-%d", "%m/%d"):
        try:
            # A year is pinned on before parsing. Without one, 3.15 changes
            # what a bare "Nov 30" means and 3.9 already warns, and the year
            # we actually want is chosen below.
            got = dt.datetime.strptime(raw + " 2000", fmt + " %Y")
        except ValueError:
            continue
        best = None
        for year in (today.year - 1, today.year, today.year + 1):
            try:
                cand = dt.date(year, got.month, got.day)
            except ValueError:                  # Feb 29 in a non-leap year
                continue
            if (cand - today).days >= -45 and (best is None or cand < best):
                best = cand
        return best
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def disqualified_at(action: str) -> str:
    """The stamp out of "Disqualified (11-17 9:20 AM)", verbatim, or ""."""
    m = re.search(r"disqualified\s*\(([^)]+)\)", str(action or ""), re.I)
    return " ".join(m.group(1).split()) if m else ""


def fmt_date(when: dt.date) -> str:
    """11/30/2026. Built by hand: %-d is glibc/BSD only and %#d is Windows
    only, and every report here has to run on both."""
    return "%d/%d/%d" % (when.month, when.day, when.year)


def name_of(row: Dict) -> str:
    return " ".join(str(x or "").strip()
                    for x in (row.get("first"), row.get("last"))).strip()


def owed(rows: List[Dict]) -> List[Dict]:
    """Showed up, and the call has not been marked with any of the four."""
    return [r for r in rows if showed_up(r) is True and not mark_of(r)]


def describe(row: Dict, today: Optional[dt.date] = None) -> str:
    """One line for a person: the mark, and the date when there is one."""
    name, mark = name_of(row), mark_of(row)
    if mark == "BOB":
        when = bob_date(row.get("action", ""), today)
        return ("%s - brought on board %s" % (name, fmt_date(when)) if when
                else "%s - brought on board (no date on the page)" % name)
    if mark == "Disqualified":
        stamp = disqualified_at(row.get("action", ""))
        return "%s - disqualified%s" % (name, " (%s)" % stamp if stamp else "")
    if mark == "Declined":
        return "%s - declined the role" % name
    if mark == "LM":
        return "%s - left message, no answer yet" % name
    return "%s - not marked yet" % name


def daily_update(rows: List[Dict], today: Optional[dt.date] = None) -> Dict:
    """The day in the shape the update needs.

    The people who SHOWED are in it, not only the ones still outstanding: an
    update that lists nothing but problems reads as a telling-off rather than a
    picture of the day (Megan asked for the showed list explicitly).
    """
    out = {"no_show": [], "bob": [], "declined": [], "disqualified": [],
           "lm": [], "not_marked": [], "show_up_not_ticked": [],
           "total": len(rows)}
    for r in rows:
        up = showed_up(r)
        if up is False:
            out["no_show"].append(name_of(r))
            continue
        if up is None:
            out["show_up_not_ticked"].append(name_of(r))
            continue
        mark = mark_of(r)
        if mark == "BOB":
            out["bob"].append((name_of(r), bob_date(r.get("action", ""), today)))
        elif mark == "Declined":
            out["declined"].append(name_of(r))
        elif mark == "Disqualified":
            out["disqualified"].append(
                (name_of(r), disqualified_at(r.get("action", ""))))
        elif mark == "LM":
            out["lm"].append(name_of(r))
        else:
            out["not_marked"].append(name_of(r))
    return out


def counts(rows: List[Dict]) -> Tuple[int, int, int]:
    """(showed, no show, show-up not ticked) -- the header line."""
    ups = [showed_up(r) for r in rows]
    return (sum(1 for u in ups if u is True),
            sum(1 for u in ups if u is False),
            sum(1 for u in ups if u is None))
