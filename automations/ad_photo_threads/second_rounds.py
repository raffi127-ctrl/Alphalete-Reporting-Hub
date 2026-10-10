"""2nd rounds per ad (Raf 2026-10-09, Loom on the Funnel 1 channel):
"Can we add second round scheduled and second round showed, and then second
round retention for the ad? ... just cross-referencing the name with
applicant stream."

WHERE IT COMES FROM -- no new ApplicantStream scraping. applicant_tracker
already copies AppStream into the old org tracker's "2R" tab every day
(Applicant Tracker Sync, Lucy 1):
  * EVENING phase (8 PM): that day's "Total Second Interviews" -- one row per
    2nd round, right-hand block: Owner Name / First Name / Last Name / ... /
    Date and Time / Ad;
  * next MORNING phase (6:45 AM): the left-hand block's "Follow up" gets
    "no show" for everyone on that roster who is NOT on "Second Interviews
    Showed Up" ("BOB" if they were brought on board).
So: scheduled = on a 2nd-round roster; showed = a 2nd round whose Follow up
isn't "no show". A 2nd round with no left-hand row yet is "pending" (not
counted in the retention %). Today's 2nd rounds only land at 8 PM, so the
4:30 PM post counts 2nd rounds through YESTERDAY.

Matching is by NAME (the interviewers' sheet has no email): same first and
last word, or one side's last name inside the other's (two surnames). Only
2nd rounds on/after the 1st round and within WINDOW_DAYS count, so an old
namesake can't sneak in. Columns are found by their header, never by letter.

Python 3.9-safe (runs on the mini).
"""
from __future__ import annotations

import datetime as dt
import difflib
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from automations.ad_photo_threads import collect

WINDOW_DAYS = 21

# Header labels in the 2R tab, both blocks on row 1; data from row 3 down.
L_NAME, L_DATE, L_FOLLOW = "Full Name", "Date", "Follow up"
R_OWNER, R_FIRST, R_LAST, R_WHEN = "Owner Name", "First Name", "Last Name", "Date and Time"


@dataclass
class Second:
    name: str
    day: dt.date
    status: str          # "showed" | "no show" | "pending"


def _toks(s: str) -> List[str]:
    return collect._fold(s).replace("&", " ").split()


def _close(a: str, b: str) -> bool:
    """One surname typed a little off: Gonzales/Gonzalez, Olatunj/Olatunji."""
    if a == b:
        return True
    if min(len(a), len(b)) < 5:
        return False
    return a.startswith(b) or b.startswith(a) or         difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def same_person(a: str, b: str) -> bool:
    """Same first name and a matching surname (either side may carry two),
    a surname typed slightly off, or an initial for the first name when the
    surname is exact ("M ... Qureshi")."""
    ta, tb = _toks(a), _toks(b)
    if len(ta) < 2 or len(tb) < 2:
        return ta == tb and bool(ta)
    la, lb = ta[-1], tb[-1]
    if ta[0] != tb[0]:
        initial = ta[0].startswith(tb[0]) or tb[0].startswith(ta[0])
        return initial and la == lb
    return la in tb[1:] or lb in ta[1:] or _close(la, lb)


def _col(head: List[str], label: str) -> int:
    h = [x.strip().lower() for x in head]
    if label.lower() not in h:
        raise RuntimeError(f"2R tab has no {label!r} header -- did the tracker change?")
    return h.index(label.lower())


def _letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _when(s: str) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime((s or "").strip()[:10], "%m/%d/%Y").date()
    except ValueError:
        return None


def parse(left: List[List[str]], right: List[List[str]], owner: str,
          today: dt.date) -> List[Second]:
    """`left` = [Full Name, Date (m/d), Follow up] rows, `right` = [Owner,
    First, Last, Date and Time] rows, both from row 3 down."""
    follow: Dict[Tuple[str, str], str] = {}
    for r in left:
        r = list(r) + [""] * 3
        if r[0].strip():
            follow[(collect._fold(r[0]), r[1].strip())] = r[2].strip().lower()
    out = []
    for r in right:
        r = list(r) + [""] * 4
        if r[0].strip().lower() != owner.lower():
            continue
        day = _when(r[3])
        name = f"{r[1].strip()} {r[2].strip()}".strip()
        if not day or not name:
            continue
        f = follow.get((collect._fold(name), f"{day.month}/{day.day}"))
        if f is None or day >= today:
            status = "pending"
        else:
            status = "no show" if f == "no show" else "showed"
        out.append(Second(name=name, day=day, status=status))
    return out


_CACHE: Dict[str, List[Second]] = {}


def load(owner: str, today: Optional[dt.date] = None, sh=None) -> List[Second]:
    """Every 2nd round the tracker has for `owner` (AppStream's owner name,
    e.g. "Rafael Hidalgo" = 11280). Read once per run."""
    if owner in _CACHE:
        return _CACHE[owner]
    from automations.applicant_tracker.config import SPREADSHEET_KEY, TAB_2R
    from automations.recruiting_report.fill import _retry, open_by_key
    today = today or collect.central_today()
    ws = (sh or open_by_key(SPREADSHEET_KEY)).worksheet(TAB_2R)
    top = (_retry(lambda: ws.get("A1:CZ1")) or [[]])[0]
    lc = [_col(top, x) for x in (L_NAME, L_DATE, L_FOLLOW)]
    rc = [_col(top, x) for x in (R_OWNER, R_FIRST, R_LAST, R_WHEN)]
    cols = _retry(lambda: ws.batch_get([f"{_letter(c)}3:{_letter(c)}" for c in lc + rc],
                                       major_dimension="COLUMNS"))
    cols = [(c[0] if c else []) for c in cols]
    n = max(len(c) for c in cols)
    cols = [list(c) + [""] * (n - len(c)) for c in cols]
    rows = list(zip(*cols))
    got = parse([r[:3] for r in rows], [r[3:] for r in rows], owner, today)
    _CACHE[owner] = got
    return got


def counts(pairs: Iterable[tuple], seconds: List[Second]) -> dict:
    """`pairs` = [(1st-round day, Candidate)]. Per person: scheduled if any
    2nd round in the window; showed if any of them showed; pending if none
    showed yet and one isn't marked."""
    seconds = sorted(seconds, key=lambda s: s.day)
    sched = showed = pending = 0
    seen = set()
    for day, c in pairs:
        key = (collect._fold(c.name), day)
        if key in seen:
            continue
        seen.add(key)
        last = day + dt.timedelta(days=WINDOW_DAYS)
        hits = [s for s in seconds if day <= s.day <= last and same_person(c.name, s.name)]
        if not hits:
            continue
        sched += 1
        if any(s.status == "showed" for s in hits):
            showed += 1
        elif any(s.status == "pending" for s in hits):
            pending += 1
    return {"scheduled": sched, "showed": showed, "pending": pending}


def retention(k: dict) -> Optional[float]:
    done = k["scheduled"] - k["pending"]
    return 100.0 * k["showed"] / done if done else None


def lines(k: dict) -> List[str]:
    """The three lines under ⭐ Avg rating in the ad threads."""
    r = retention(k)
    out = [f"📅 2nd round scheduled: *{k['scheduled']}*",
           f"🙋 2nd round showed: *{k['showed']}*"]
    if r is not None:
        wait = f" _({k['pending']} not marked yet)_" if k["pending"] else ""
        out.append(f"📈 2nd round retention: *{r:.0f}%*{wait}")
    return out
