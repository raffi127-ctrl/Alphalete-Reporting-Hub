"""Applicant NAMES for the Ad Sales Board, joined from the Call List import.

The Source Report (p=702) is aggregate counts — it never says WHO came in. The
names already exist in a sheet, though: applicant_tracker's morning phase
(Lucy 1, 6:45am Mon–Sat) appends every "Sent to Call List" applicant to the old
org tracker's Call List tab with First, Last, Email, a Date-and-Time serial and
the AD they answered. So names are a plain Sheets read — no extra scraping.

What that choice means, honestly stated (also on the visible tab's note):
  * Names exist for ORG offices only — applicant_tracker doesn't cover the 11
    captainship-only offices, so their Names cells stay blank while Pull fills.
  * Names are the applicants SENT TO CALL LIST (the ones worth calling), not
    every processed email — Pull will normally exceed the name count.
  * The morning phase reads YESTERDAY and skips Sunday, so SATURDAY arrivals
    are never imported upstream; a Saturday name can be missing here while the
    Pull still counts it.
  * An applicant is dated by when they were sent to the call list, which can be
    a day after the email that Pull counts — tiny edge-of-week skew is normal.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt
import re

from automations.indeed_source_report import parse

# The old org tracker — applicant_tracker's own workbook. Its Call List tab is
# written by the applicant_tracker service account daily, so the same credential
# this job writes with can always read it.
TRACKER_ID = "1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo"
CALL_LIST_RANGE = "'Call List'!A2:I"

# Some applications arrive wrapped as "[Action required] New application for
# <ad title>" — Indeed's forwarded-notification subject. It is a REAL applicant
# whose ad title sits after the prefix, but parse.NOISE matches "action
# required" (meant for Indeed's billing mail) and would throw the row away.
# Strip the wrapper FIRST, everywhere a subject or Ad string is handled.
# Found 2026-08-26: 37 of Carlos's 375 call-list names in one week wore it.
WRAPPER = re.compile(r"\[action\s+required\]\s*new\s+application\s+for\s*[:\-]?\s*", re.I)


def strip_wrapper(text):
    return WRAPPER.sub("", text or "")


# Call List "Owner Name" is AppStream's own spelling and it DRIFTS: the same
# person appears as "Carlos Hidalgo" and "CARLOS HIDALGO", and Salik Mallick's
# office has been both "Muhammad UI Haque" (capital i — what the roster carries)
# and "Muhammad Ul Haque". Casefold + collapse spaces, then patch the few known
# drifts by hand. An owner this map doesn't know is logged once, not guessed.
_ALIASES = {
    "muhammad ul haque": "Salik Mallick",
}


def _key(owner):
    return " ".join(str(owner).split()).lower()


def owner_map():
    from automations.funnel_board.roster import ORG, CAPTAINSHIP
    m = {}
    for name, _oid, owner in list(ORG) + list(CAPTAINSHIP):
        m[_key(owner)] = name
        m[_key(name)] = name       # some rows carry the display name itself
    m.update(_ALIASES)
    return m


_EPOCH = dt.date(1899, 12, 30)    # Sheets serial epoch


def _serial_date(v):
    try:
        return _EPOCH + dt.timedelta(days=int(float(v)))
    except (TypeError, ValueError):
        return None


def load_call_list(sess, api, verbose=True):
    """All Call List rows as (manager, date, first, last, email, ad_string).

    One full read of the tab (~70k rows in 2026-08) — a few MB once a day is
    cheaper than being clever about offsets and silently missing backfilled
    rows. Rows whose owner the map doesn't know are counted and reported, never
    guessed into someone's board.
    """
    r = sess.get("%s/%s/values/%s" % (api, TRACKER_ID, CALL_LIST_RANGE),
                 params={"valueRenderOption": "UNFORMATTED_VALUE"})
    r.raise_for_status()
    rows = r.json().get("values", [])
    omap = owner_map()
    out, unknown = [], {}
    for row in rows:
        row = list(row) + [""] * (9 - len(row))
        owner, first, last, email, _phone, _rating, _board, when, ad = row[:9]
        mgr = omap.get(_key(owner))
        if mgr is None:
            if str(owner).strip():
                unknown[str(owner)] = unknown.get(str(owner), 0) + 1
            continue
        d = _serial_date(when)
        if d is None:
            continue
        out.append((mgr, d, str(first).strip(), str(last).strip(),
                    str(email).strip().lower(), str(ad)))
    if unknown and verbose:
        print("  [names] call-list owners not on the roster (rows skipped): %s"
              % ", ".join("%s x%d" % kv for kv in sorted(unknown.items())), flush=True)
    return out


def in_window(call_rows, manager, start, end):
    """Deduped (first, last, ad, date) for one manager inside one ad-week."""
    seen, out = set(), []
    for mgr, d, first, last, email, ad in call_rows:
        if mgr != manager or not (start <= d <= end):
            continue
        k = (first.lower(), last.lower(), email)
        if k in seen:
            continue
        seen.add(k)
        out.append((first, last, ad, d))
    return out


def _ad_key(ad_string):
    """(base role, city) for a Call List Ad string, through the SAME pipeline
    the report subjects go through, so both sides land on identical keys."""
    title, city = parse.split_city(parse.clean(strip_wrapper(ad_string)))
    return parse.base_role(title).lower(), city.lower()


def attach(ads, name_rows, city_agnostic, week_start):
    """Hang each name on the merged ad row it answered, day-bucketed.

    Match by (base role, city) first; a name whose city doesn't pin a row (the
    ", N locations" postings arrive city-less) falls back to base role alone,
    taken by the row with the larger Pull when two accounts run the same role.
    City-agnostic managers (Carlos, Jamis — their rows merge cities already)
    match on base role directly. Anything still unmatched is returned rather
    than dropped: a name must never silently disappear from the board.

    Returns (names_for, days_for, unmatched_names, unmatched_days): names_for
    maps id(ad row) -> list of "First Last"; days_for maps the same key to a
    7-slot count list, day 0 = week_start (Wednesday) — the board's day cells.
    """
    by_base = {}
    for g in ads:
        by_base.setdefault(g["base"].lower(), []).append(g)
    names_for, days_for = {}, {}
    unmatched, unmatched_days = [], [0] * 7
    for first, last, ad, d in name_rows:
        base, city = _ad_key(ad)
        cands = by_base.get(base, [])
        target = None
        if cands:
            if city_agnostic or len(cands) == 1:
                target = max(cands, key=lambda g: g["rec"]["apps"])
            else:
                exact = [g for g in cands if g["city"].lower() == city]
                target = (exact[0] if len(exact) == 1
                          else max(cands, key=lambda g: g["rec"]["apps"]))
        slot = (d - week_start).days
        if target is None:
            unmatched.append("%s %s" % (first, last))
            if 0 <= slot < 7:
                unmatched_days[slot] += 1
        else:
            names_for.setdefault(id(target), []).append("%s %s" % (first, last))
            if 0 <= slot < 7:
                days_for.setdefault(id(target), [0] * 7)[slot] += 1
    return names_for, days_for, unmatched, unmatched_days
