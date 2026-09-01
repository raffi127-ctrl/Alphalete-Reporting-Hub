"""Which job ads the call-list applies came from — and what they turned into.

The point is a keep-or-kill decision, so volume alone is not enough: an ad can
send hundreds of applies and hire nobody. This pairs applies per ad against
hires per ad so the two are read together.

SOURCE: the Alphalete Org Applicant Tracker's "Call List" tab, which already
records the Ad per applicant (col I) alongside owner, job board and date. No
new scrape — the applicant tracker fills this every morning.

The Ad cell is an email subject, not a title:
    "[Action required] New application for AT&T Agent, Lawrence, IN"
so the title has to be lifted out of it before anything can be grouped.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict

SHEET_ID = "1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo"
TAB = "Call List"

COL_OWNER, COL_FIRST, COL_LAST = 0, 1, 2
COL_EMAIL, COL_PHONE, COL_RATING = 3, 4, 5
COL_BOARD, COL_WHEN, COL_AD = 6, 7, 8

# The Ad cell is an email subject, and there are three wrappers plus a bare
# title. Counted over all 74,961 filled cells rather than guessed from one
# example: [Action required] 37,887 · bare title 35,664 · "You have a new
# applicant…" 920 · "New application:" 490.
_WRAPPERS = [
    re.compile(r"^\s*\[[^\]]*\]\s*New application for\s*", re.I),
    re.compile(r"^\s*You have a new applicant ready for review for\s*", re.I),
    re.compile(r"^\s*New application[:]?\s*", re.I),
]
# "New application: Entry Level Marketing from Karrington Henderson" — the
# applicant's own name is appended to some subjects and is not part of the ad.
_TRAILING_FROM = re.compile(r"\s+from\s+[A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*){0,3}\s*$")


def ad_title(raw: str) -> str:
    """The ad's name, with the notification fluff removed.

    Location STAYS attached ("AT&T Agent, Lawrence, IN"): the same title in two
    markets is two different ads with two different costs, and collapsing them
    would hide the very difference this is meant to expose."""
    t = str(raw or "").strip()
    for w in _WRAPPERS:
        t2 = w.sub("", t)
        if t2 != t:
            t = t2.strip()
            break
    t = _TRAILING_FROM.sub("", t).strip()
    return t or "(no ad recorded)"


def _parse_when(raw: str):
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(str(raw or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def breakdown(rows: list, owner: str = "", since: dt.date | None = None,
              until: dt.date | None = None,
              hired_keys: set | None = None) -> list:
    """Per ad: applies sent to the call list, and how many were hired.

    `hired_keys` is a set of applicant identities known to have been hired; a
    row counts as a hire when its identity is in that set. Left as None, hires
    read 0 and the column says 'unknown' rather than implying nobody was hired
    — an ad with no hire DATA is not an ad with no hires."""
    per = defaultdict(lambda: {"applies": 0, "hired": 0, "boards": set(),
                               "first": None, "last": None})
    for r in rows:
        if len(r) <= COL_AD:
            continue
        if owner and (r[COL_OWNER] or "").strip().lower() != owner.lower():
            continue
        when = _parse_when(r[COL_WHEN])
        if since and (when is None or when < since):
            continue
        # An UNDATED row is dropped from a bounded window rather than kept:
        # it belongs to no window, and keeping it would pad whichever one is
        # on screen while the counts still claim to cover only that span.
        if until and (when is None or when > until):
            continue

        title = ad_title(r[COL_AD])
        rec = per[title]
        rec["applies"] += 1
        board = (r[COL_BOARD] or "").strip()
        if board:
            rec["boards"].add(board)
        if when:
            rec["first"] = when if rec["first"] is None else min(rec["first"], when)
            rec["last"] = when if rec["last"] is None else max(rec["last"], when)
        if hired_keys and identity(r) in hired_keys:
            rec["hired"] += 1

    out = []
    for title, rec in per.items():
        applies = rec["applies"]
        out.append({
            "Ad": title,
            "Board": ", ".join(sorted(rec["boards"])) or "",
            "Applies": applies,
            "Hired": rec["hired"] if hired_keys is not None else None,
            "Hire rate": (f"{rec['hired'] / applies:.1%}"
                          if hired_keys is not None and applies else ""),
            "First seen": rec["first"].isoformat() if rec["first"] else "",
            "Last seen": rec["last"].isoformat() if rec["last"] else "",
        })
    out.sort(key=lambda d: -d["Applies"])
    return out


def identity(row: list) -> tuple:
    """How one applicant is recognised across tabs.

    Email plus name, lowercased. Rating is deliberately excluded — recruiters
    change it after the fact, so it identifies a moment, not a person."""
    def cell(i):
        return (row[i] or "").strip().lower() if i < len(row) else ""
    return (cell(COL_EMAIL), cell(COL_FIRST), cell(COL_LAST))


def load_rows(sheet_id: str = SHEET_ID) -> list:
    from automations.recruiting_report.fill import open_by_key, _retry
    ws = open_by_key(sheet_id).worksheet(TAB)
    return _retry(ws.get_all_values)[1:]


# ---------------------------------------------------------------------------
# BOB — Brought On Board — by ad and by location.
#
# One tab has everything: the tracker's '2R' is wide and carries BOTH the
# person's journey (Offered col 7, Start Date col 9) AND where they came from
# (Ad col 55, City col 57). So no join and no name-matching is needed, which
# also means no chance of pairing the wrong two people.
#
# BOB = a filled Start Date. 'Offered' is the offer; the start date is the
# person actually coming on board, which is what BOB means.
# ---------------------------------------------------------------------------
R2_TAB = "2R"
R2_OWNER, R2_OFFERED, R2_START = 45, 7, 9
R2_AD, R2_CITY = 55, 57


def load_2r(sheet_id: str = SHEET_ID) -> list:
    from automations.recruiting_report.fill import open_by_key, _retry
    ws = open_by_key(sheet_id).worksheet(R2_TAB)
    return [r for r in _retry(ws.get_all_values)[1:] if any(c.strip() for c in r)]


def _cell(row: list, i: int) -> str:
    return str(row[i]).strip() if i < len(row) and row[i] is not None else ""


def bob_by(rows: list, key: str = "ad", owner: str = "") -> list:
    """BOB per ad, or per location. `key` is 'ad' or 'city'.

    Reports interviewed / offered / BOB together so a winner can't be declared
    on BOB alone: an ad that sent two people and got one BOB is not beating one
    that sent two hundred and got twelve, and only the rate shows that."""
    from collections import defaultdict
    per = defaultdict(lambda: {"interviewed": 0, "offered": 0, "bob": 0})
    for r in rows:
        if owner and _cell(r, R2_OWNER).lower() != owner.lower():
            continue
        label = (ad_title(_cell(r, R2_AD)) if key == "ad"
                 else (_cell(r, R2_CITY) or "(no city recorded)"))
        if not label:
            continue
        rec = per[label]
        rec["interviewed"] += 1
        if _cell(r, R2_OFFERED):
            rec["offered"] += 1
        if _cell(r, R2_START):
            rec["bob"] += 1

    out = []
    for label, rec in per.items():
        n = rec["interviewed"]
        out.append({("Ad" if key == "ad" else "Location"): label,
                    "Interviewed": n,
                    "Offered": rec["offered"],
                    "BOB": rec["bob"],
                    "BOB rate": f"{rec['bob'] / n:.0%}" if n else ""})
    out.sort(key=lambda d: (-d["BOB"], -d["Interviewed"]))
    return out


def parse_start(raw: str, today: dt.date | None = None):
    """A Start Date cell as a real date. None when it can't be read.

    The cells carry no year ('7/27'), so the current year is assumed and
    rolled back when that would put the date in the future — the same rule the
    week tabs use. None rather than a guess: a start date invented a year out
    would land in the wrong week and quietly move a BOB."""
    today = today or dt.date.today()
    v = str(raw or "").strip()
    if not v:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    m = re.match(r"^(\d{1,2})/(\d{1,2})$", v)
    if not m:
        return None
    mo, day = int(m.group(1)), int(m.group(2))
    try:
        d = dt.date(today.year, mo, day)
    except ValueError:
        return None
    if d > today + dt.timedelta(days=10):
        try:
            d = dt.date(today.year - 1, mo, day)
        except ValueError:
            return None
    return d


def week_ending(d: dt.date) -> dt.date:
    """The Sunday that closes d's week — the same week boundary the sales
    board uses, so a BOB week lines up with a production week."""
    return d + dt.timedelta(days=(6 - d.weekday()) % 7)


def bob_weekly(rows: list, key: str = "ad", owner: str = "",
               weeks: int = 8, today: dt.date | None = None) -> tuple:
    """(week_endings, [{label, <week>: n, …, 'Total': n}]) — BOB week over week.

    Bucketed on the START date, because that is when somebody actually came on
    board. Rows whose start date can't be read are skipped rather than dropped
    into the nearest week."""
    from collections import defaultdict
    today = today or dt.date.today()
    per = defaultdict(lambda: defaultdict(int))
    seen_weeks = set()

    for r in rows:
        if owner and _cell(r, R2_OWNER).lower() != owner.lower():
            continue
        d = parse_start(_cell(r, R2_START), today)
        if d is None:
            continue
        we = week_ending(d)
        label = (ad_title(_cell(r, R2_AD)) if key == "ad"
                 else (_cell(r, R2_CITY) or "(no city recorded)"))
        if not label:
            continue
        per[label][we] += 1
        seen_weeks.add(we)

    ordered = sorted(seen_weeks)[-weeks:]
    out = []
    for label, by_week in per.items():
        total = sum(by_week.get(w, 0) for w in ordered)
        if not total:
            continue
        row = {("Ad" if key == "ad" else "Location"): label, "Total": total}
        for w in ordered:
            row[w.strftime("%m/%d")] = by_week.get(w, 0)
        out.append(row)
    out.sort(key=lambda d: -d["Total"])
    return ordered, out


# ---------------------------------------------------------------------------
# AD QUALITY — not just how many an ad brings on board, but whether they last.
#
# The tracker's own tenure columns (Days worked, Retired?, First Sale Date) are
# ALL EMPTY — headers with nothing under them — so quality has to come from
# elsewhere. Two independent signals, neither needing a new pull:
#
#   EVER SOLD    due_diligence.first_sale, the map the 3am harvest already
#                keeps from the full Tableau order history. Org-wide, so it
#                does not care whose board someone is on this week.
#   LASTED 3 WK  the rep appears on a sales board for a week ending at least
#                21 days after their start date. Appearing there is proof they
#                were still around; the board is the roster.
#
# Both are matched on name, which is the weak link — so `matched` is reported
# alongside every rate. A rate over a handful of matched people is not a
# finding, and hiding the denominator would make it look like one.
# ---------------------------------------------------------------------------
R2_FIRST_NAME, R2_LAST_NAME = 46, 47

# "Lasted three weeks" is what the BOARD says, not something computed from
# dates (Megan 2026-08-31): a rep marked 4th Wk or 5th wk+ has visibly gone
# past three weeks. Counted off the board's own Field Status, so it needs no
# 21-day arithmetic and no "not yet eligible" carve-out — somebody either
# reached that tenure or has not reached it yet.
# Live values on Raf's board: 5th wk+ 200 · 2nd Wk 65 · 1st Wk 48 · RT 42 ·
# 3rd Wk 39 · 4th Wk 26. 'RT' is a roadtrip, not a tenure, so it says nothing
# either way and is left out.
PAST_3_WEEKS = {"4th wk", "5th wk+"}


def lasted_names(board_weeks_reps: dict) -> set:
    """Lowered names ever marked past three weeks on any board week.

    `board_weeks_reps` is {week_ending: [rep dicts]} — the parsed rows, not
    just names, because the tenure lives on the rep. Names go through
    board_read.clean_name first: the board writes 'Kelvinton ( BO ) Scarbough
    (Wk 3)' where the ad only ever knew 'Kelvinton Scarbough'."""
    from automations.icd_sales_board import board_read
    out = set()
    for reps in board_weeks_reps.values():
        for r in reps:
            t = (r.get("attrs", {}).get("field status") or "").strip().lower()
            if t in PAST_3_WEEKS:
                clean, _ = board_read.clean_name(r.get("name") or "")
                if clean:
                    out.add(clean.strip().lower())
    return out


def rep_name(row: list) -> str:
    return " ".join(f"{_cell(row, R2_FIRST_NAME)} "
                    f"{_cell(row, R2_LAST_NAME)}".split()).strip()


def quality_by_ad(rows: list, owner: str = "", first_sale_map=None,
                  lasted: set | None = None,
                  today: dt.date | None = None) -> list:
    """Per ad: BOB, how many ever sold, and how many lasted three weeks.

    `lasted` is the set of names the board has marked past three weeks (see
    lasted_names). Left None, the three-week column reads unknown rather than
    zero: an ad whose people we cannot follow is not an ad whose people left."""
    from collections import defaultdict
    today = today or dt.date.today()
    per = defaultdict(lambda: {"bob": 0, "sold": 0, "lasted": 0, "known": 0,
                               "too_new": 0})

    for r in rows:
        if owner and _cell(r, R2_OWNER).lower() != owner.lower():
            continue
        start = parse_start(_cell(r, R2_START), today)
        if start is None:
            continue
        name = rep_name(r).lower()
        if not name:
            continue
        rec = per[ad_title(_cell(r, R2_AD))]
        rec["bob"] += 1

        if first_sale_map is not None:
            from automations.due_diligence.first_sale import _norm
            if _norm(name) in first_sale_map:
                rec["sold"] += 1

        if lasted is not None:
            # The board says who got past three weeks. Someone who has not is
            # either gone or not there yet — the board cannot tell those apart,
            # so this counts who DID rather than accusing anyone of leaving.
            rec["known"] += 1
            if name in lasted:
                rec["lasted"] += 1

    out = []
    for ad, rec in per.items():
        bob = rec["bob"]
        out.append({
            "Ad": ad,
            "BOB": bob,
            "Ever sold": rec["sold"] if first_sale_map is not None else None,
            "Sold %": (f"{rec['sold'] / bob:.0%}"
                       if first_sale_map is not None and bob else ""),
            # The rate is over people who have HAD three weeks, never over
            # everyone brought on board.
            "Past 3 wks": rec["lasted"] if lasted is not None else None,
            "Past 3 wks %": (f"{rec['lasted'] / bob:.0%}"
                             if lasted is not None and bob else ""),
        })
    out.sort(key=lambda d: (-(d["Ever sold"] or 0), -d["BOB"]))
    return out
