"""When each 1st round was SCHEDULED, off AppStream -- next to when it started.

Hyro's feedback (Rafael, 2026-09-30): interviews start too early and people
aren't let in. Fathom knows when the recording started; AppStream knows the
slot the applicant was booked for. Each reply shows both.

The booked slot is read off the Weekly Calendar (p=105), "First Interview
Date: <d>" band -- the same page and mechanics as sms_thread_dump
(--bookings-only: the day's table only, no chat dialogs, seconds per office).
READ-ONLY on AppStream. The applicant is matched by name (the grader reads
the names off the transcript, so a misheard spelling is expected: first +
last name, loosely). Times on the calendar are the office's own, Central.
"""
from __future__ import annotations

import datetime as dt
import re
import time
import unicodedata
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# Rafael's three 1st round funnels (1 = 11280, 2 = 23965, 3 = 24065; Eve
# 2026-09-29). Every one is read, so it doesn't matter which funnel a Zoom
# account interviews for.
OFFICES = ["11280", "23965", "24065"]
# Every other office's calendar too (Eve 2026-10-07: Carlos' office books in
# 11580, so his interviews read "not on AppStream"). Read only for the
# interviews the three funnels didn't place -- ~130 offices is minutes.
MAPPINGS = Path(__file__).resolve().parents[1] / "recruiting_report"
NAME_MATCH = 0.8               # 0-1 closeness of a transcript name to a booked one


def booked(day: dt.date, offices: Iterable[str] = OFFICES) -> List[Dict]:
    """[{office, time: 'H:MM AM', name}] for every 1st round booked that day."""
    from automations.shared.tableau_patchright import appstream_direct_session
    from automations.sms_thread_dump import run as dump
    ds = dump._fmt(day)
    out: List[Dict] = []
    with appstream_direct_session(verbose=False) as page:
        tok = dump._rqst(page)
        if not tok:
            raise RuntimeError("no rqst token on the AppStream console page")
        for office in offices:
            try:
                page.goto(f"https://www.applicantstream.com/index.cfm?p=104&rqst={tok}"
                          f"&newOfficeId={office}")
                page.wait_for_load_state("networkidle")
                time.sleep(1.0)
                dump._goto_week_containing(page, tok, day)
                if dump._expand_day(page, ds) < 0:
                    continue
                for r in dump._day_rows(page, ds):
                    out.append({"office": office, "time": r["time"], "name": r["name"]})
            except Exception as exc:  # noqa: BLE001 -- one office can't hold the rest
                print(f"AppStream office {office} not read ({type(exc).__name__}: {exc})")
    return out


def other_offices() -> List[str]:
    """Every confirmed office in the recruiting report's mappings, minus the
    three funnels, in file order, no repeats."""
    seen, out = set(OFFICES), []
    for f in sorted(MAPPINGS.glob("office-mapping*.json")):
        try:
            rows = json.loads(f.read_text(encoding="utf-8")).get("confirmed") or []
        except (OSError, ValueError, AttributeError):
            continue
        for r in rows:
            oid = str((r or {}).get("office_id") or "").strip()
            if oid and oid not in seen:
                seen.add(oid)
                out.append(oid)
    return out


def _norm(name: str) -> List[str]:
    plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return [w for w in re.split(r"[^a-z]+", plain.lower()) if w]


def _same_person(said: str, booked_name: str) -> bool:
    a, b = _norm(said), _norm(booked_name)
    if not a or not b:
        return False
    close = lambda x, y: SequenceMatcher(None, x, y).ratio() >= NAME_MATCH
    if len(a) == 1:                        # only a first name was said
        return close(a[0], b[0])
    return close(a[0], b[0]) and close(a[-1], b[-1])


def slot_time(clock: str) -> Optional[dt.time]:
    try:
        return dt.datetime.strptime(clock.strip().upper(), "%I:%M %p").time()
    except ValueError:
        return None


def scheduled_for(applicants: Iterable[str], bookings: List[Dict],
                  started: dt.datetime) -> Optional[dt.datetime]:
    """The slot these applicants were booked in (CT, same day as `started`),
    or None when none of them is on the calendar. Several matches (a name
    booked twice) -> the slot closest to when the interview started."""
    slots = []
    for said in applicants:
        for b in bookings:
            t = slot_time(b["time"])
            if t and _same_person(said, b["name"]):
                slots.append(started.replace(hour=t.hour, minute=t.minute,
                                             second=0, microsecond=0))
    if not slots:
        return None
    return min(slots, key=lambda s: abs((s - started).total_seconds()))


def early_by(m: Dict) -> int:
    """Minutes the recording started BEFORE the booked slot (0 = on time or
    later, or no slot known). What Hyro's feedback is about."""
    sched = m.get("scheduled_ct")
    if not isinstance(sched, dt.datetime):
        return 0
    from automations.first_round_scorecards import fathom
    return max(0, int((sched - fathom.start_ct(m)).total_seconds() // 60))


def scheduled_text(m: Dict) -> str:
    """'10:45 AM' / 'not on AppStream' / '' when AppStream wasn't read."""
    sched = m.get("scheduled_ct")
    if isinstance(sched, dt.datetime):
        return sched.strftime("%I:%M %p").lstrip("0")
    return "not on AppStream" if "scheduled_ct" in m else ""
