# -*- coding: utf-8 -*-
"""The numbers the card needs that no other module works out.

All of them come off ONE source: each booked applicant's Action History
(Applicant dialog -> Action History tab: Action | Source | At | By), as
saved by `sms_thread_dump --actions` into output/sms_thread_dump_<id>.json.

    Send to Call List   (Process Emails)  resume processed + pushed
    Send to AI          (Call List)       handed to the AI to text
    Assign First Interview                booked — "By" says AI or a person
    Reschedule First Interview            moved
    status on the record                  showed / no show

THE LIMIT (resources/recruiting-context/appstream-audit-findings.md §2):
that file is built by walking the CALENDAR, so everybody in it already
booked. It answers "of the people booked, who booked them and who showed",
never "of everyone pushed, how many booked". Every number here is said that
way on the card. The call list booking rate itself is AppStream's published
RTCL, which gradecard already reads.

AppStream does not log when a resume ARRIVES, only when it was processed
(Send to Call List). So "days to book" starts at processing.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import ast
import collections
import datetime as dt
import json
import math
import statistics

# Fewer than this in a group and a show rate is one bad morning.
MIN_N = 30
# The cliff that held up across 10 offices / 11,830 bookings: under 24h
# from push to booked shows 52.5%, 24h+ shows 40.2% (p=5e-25).
CLIFF_HOURS = 24

AI_BY = ("ai messaging", "a. messaging", "a messaging")


def _when(s):
    s = (s or "").strip()
    for fmt in ("%m-%d-%Y %I:%M %p", "%m/%d/%Y %I:%M %p", "%m-%d-%Y %H:%M"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def actions(rec):
    """[(action, source, datetime, by)] — oldest first, unreadable dropped.

    The dump stores the list as a Python repr string; literal_eval reads it
    without trusting it the way eval would."""
    raw = rec.get("actions") or []
    if isinstance(raw, str):
        try:
            raw = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = []
    out = []
    for a in raw:
        if not isinstance(a, (list, tuple)) or len(a) < 3:
            continue
        t = _when(a[2])
        if t is None:
            continue
        out.append((str(a[0]).strip(), str(a[1]).strip(), t,
                    str(a[3]).strip() if len(a) > 3 else ""))
    out.sort(key=lambda x: x[2])
    return out


def is_ai(by):
    b = (by or "").strip().lower()
    return any(b.startswith(x) for x in AI_BY)


def shown(rec):
    """True / False, or None when the interview has no outcome yet."""
    st = (rec.get("status") or "").strip()
    if not st:
        return None
    if "no show" in st.lower():
        return False
    if st.lower() in ("pending", "scheduled", "booked", "confirmed"):
        return None
    return True


def timeline(rec):
    """One applicant, flattened to what the card reads."""
    acts = actions(rec)

    def first(pred):
        for a in acts:
            if pred(a):
                return a
        return None

    push = first(lambda a: a[0].startswith("Send to Call List"))
    to_ai = first(lambda a: a[0] == "Send to AI")
    book = first(lambda a: a[0] == "Assign First Interview")
    slot = _when("{} {}".format(rec.get("date", ""), rec.get("time", "")))
    by = book[3] if book else (rec.get("booked_by") or "")
    return {
        "name": rec.get("name", ""),
        "board": (rec.get("board") or "").strip() or "(none)",
        "pushed": push[2] if push else None,
        "to_ai": to_ai[2] if to_ai else None,
        "booked": book[2] if book else None,
        "by": by,
        "ai": is_ai(by) or is_ai(rec.get("booked_by")),
        "slot": slot,
        "shown": shown(rec),
        "rescheduled": any(a[0] == "Reschedule First Interview" for a in acts),
    }


def timelines(recs, start=None, end=None):
    """Everyone whose interview slot falls inside [start, end] (dates)."""
    out = []
    for r in recs or []:
        t = timeline(r)
        d = t["slot"].date() if t["slot"] else None
        if start and (d is None or d < start):
            continue
        if end and (d is None or d > end):
            continue
        out.append(t)
    return out


def _rate(group):
    marks = [t["shown"] for t in group if t["shown"] is not None]
    if not marks:
        return None, 0
    return 100.0 * sum(marks) / len(marks), len(marks)


def _p_two(r1, n1, r2, n2):
    """Two-proportion z test, two sided. Rates in percent."""
    if not (n1 and n2):
        return None
    p1, p2 = r1 / 100.0, r2 / 100.0
    p = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1.0 / n1 + 1.0 / n2))
    if se == 0:
        return None
    z = abs(p1 - p2) / se
    return math.erfc(z / math.sqrt(2))


def _hours(a, b):
    if a is None or b is None or b < a:
        return None
    return (b - a).total_seconds() / 3600.0


# ------------------------------------------------------------- AI vs human

def ai_vs_human(tl):
    """Who books this office's interviews, and who shows up.

    Megan 2026-11-12 expects the AI to hold better. Across 10 offices it was
    52% vs 47% — but inside the same speed band the gap closed (24h+: 40.2%
    each). So the split is also given for people booked within a day of
    being pushed: if the AI still wins there, it is the AI; if it only wins
    overall, it is speed."""
    booked = [t for t in tl if t["by"] or t["booked"]]
    if not booked:
        return {"ok": False, "why": "no bookings in the window"}
    ai = [t for t in booked if t["ai"]]
    hu = [t for t in booked if not t["ai"]]
    ai_r, ai_n = _rate(ai)
    hu_r, hu_n = _rate(hu)

    def fast(g):
        return [t for t in g
                if (_hours(t["pushed"], t["booked"]) or 1e9) < CLIFF_HOURS]
    fa_r, fa_n = _rate(fast(ai))
    fh_r, fh_n = _rate(fast(hu))

    def med(g):
        hs = [h for h in (_hours(t["pushed"], t["booked"]) for t in g)
              if h is not None]
        return statistics.median(hs) if hs else None
    p = _p_two(ai_r, ai_n, hu_r, hu_n) if (ai_r is not None
                                          and hu_r is not None) else None
    return {
        "ok": True, "booked": len(booked),
        "ai_n": len(ai), "human_n": len(hu),
        "ai_share": 100.0 * len(ai) / len(booked),
        "ai_show": ai_r, "ai_marked": ai_n,
        "human_show": hu_r, "human_marked": hu_n,
        "ai_fast_show": fa_r, "ai_fast_n": fa_n,
        "human_fast_show": fh_r, "human_fast_n": fh_n,
        "ai_median_hours": med(ai), "human_median_hours": med(hu),
        "p": p,
        "humans": collections.Counter(
            t["by"] for t in hu if t["by"]).most_common(),
    }


# ------------------------------------------------------- push -> booked

def days_to_book(tl):
    """Processed -> handed to the AI -> booked, in hours and days."""
    p2b = [h for h in (_hours(t["pushed"], t["booked"]) for t in tl)
           if h is not None]
    p2ai = [h for h in (_hours(t["pushed"], t["to_ai"]) for t in tl)
            if h is not None]
    ai2b = [h for h in (_hours(t["to_ai"], t["booked"]) for t in tl)
            if h is not None]
    if not p2b:
        return {"ok": False,
                "why": "no applicant has both a Send to Call List and an "
                       "Assign First Interview in their Action History"}

    def summ(xs):
        if not xs:
            return None
        return {"n": len(xs), "avg_h": sum(xs) / len(xs),
                "median_h": statistics.median(xs),
                "avg_days": sum(xs) / len(xs) / 24.0}
    late = [t for t in tl
            if (_hours(t["pushed"], t["booked"]) or 0) >= CLIFF_HOURS]
    same_day = sum(1 for t in tl if t["pushed"] and t["booked"]
                   and t["pushed"].date() == t["booked"].date())
    on_r, on_n = _rate([t for t in tl
                        if _hours(t["pushed"], t["booked"]) is not None
                        and _hours(t["pushed"], t["booked"]) < CLIFF_HOURS])
    late_r, late_n = _rate(late)
    return {"ok": True,
            "push_to_book": summ(p2b), "push_to_ai": summ(p2ai),
            "ai_to_book": summ(ai2b),
            "late_share": 100.0 * len(late) / len(p2b),
            "same_day_share": 100.0 * same_day / len(p2b),
            "under_show": on_r, "under_n": on_n,
            "late_show": late_r, "late_n": late_n}


# ---------------------------------------------------------- booking times

def _hour_label(h):
    return "{}{}".format(h % 12 or 12, "am" if h < 12 else "pm")


DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def booking_times(tl):
    """When bookings happen, and which interview times people show up to."""
    hours = collections.Counter(t["booked"].hour for t in tl if t["booked"])
    days = collections.Counter(t["booked"].weekday() for t in tl if t["booked"])
    if not hours:
        return {"ok": False, "why": "no booking timestamps"}
    total = sum(hours.values())
    top = hours.most_common(3)
    slots = collections.defaultdict(list)
    for t in tl:
        if t["slot"]:
            slots[t["slot"].hour].append(t)
    slot_rates = []
    for h, g in slots.items():
        r, n = _rate(g)
        if r is not None and n >= MIN_N:
            slot_rates.append((h, r, n))
    slot_rates.sort(key=lambda x: -x[1])
    return {
        "ok": True, "total": total,
        "top_hours": [(_hour_label(h), n, 100.0 * n / total) for h, n in top],
        "by_hour": sorted(hours.items()),
        "top_day": (DAYS[days.most_common(1)[0][0]],
                    100.0 * days.most_common(1)[0][1] / total),
        "best_slot": ((_hour_label(slot_rates[0][0]),) + slot_rates[0][1:])
        if slot_rates else None,
        "worst_slot": ((_hour_label(slot_rates[-1][0]),) + slot_rates[-1][1:])
        if len(slot_rates) > 1 else None,
    }


# -------------------------------------------------- what moves retention

def _lead_bucket(t):
    if not (t["booked"] and t["slot"]):
        return None
    d = (t["slot"].date() - t["booked"].date()).days
    return "same day" if d <= 0 else "next day" if d == 1 else "2+ days out"


def _push_bucket(t):
    h = _hours(t["pushed"], t["booked"])
    if h is None:
        return None
    return "within a day" if h < CLIFF_HOURS else "after a day or more"


def _part_of_day(t):
    if not t["slot"]:
        return None
    h = t["slot"].hour
    return "morning" if h < 12 else "afternoon" if h < 16 else "evening"


# (what it is, plain question on the card, how to read one level)
FACTORS = (
    ("push", "How fast they were booked after their resume was pushed",
     _push_bucket),
    ("lead", "How far out the interview was set", _lead_bucket),
    ("booker", "Who booked them",
     lambda t: "the AI" if t["ai"] else "a recruiter"),
    ("resched", "Whether the interview was moved",
     lambda t: "moved" if t["rescheduled"] else "not moved"),
    ("part", "Time of day of the interview", _part_of_day),
    ("weekday", "Day of the interview",
     lambda t: DAYS[t["slot"].weekday()] if t["slot"] else None),
    ("board", "Job board they came from", lambda t: t["board"]),
)


def retention_drivers(tl, min_n=MIN_N):
    """Each factor's best and worst group, biggest gap first.

    Only groups with min_n marked outcomes count, and a gap that could be
    chance (p >= .05) is kept but marked, so the card never sells noise as
    the reason."""
    out = []
    for key, label, fn in FACTORS:
        groups = collections.defaultdict(list)
        for t in tl:
            v = fn(t)
            if v:
                groups[v].append(t)
        rated = []
        for v, g in groups.items():
            r, n = _rate(g)
            if r is not None and n >= min_n:
                rated.append((v, r, n))
        if len(rated) < 2:
            continue
        rated.sort(key=lambda x: -x[1])
        hi, lo = rated[0], rated[-1]
        p = _p_two(hi[1], hi[2], lo[1], lo[2])
        out.append({"key": key, "label": label,
                    "best": hi, "worst": lo, "gap": hi[1] - lo[1],
                    "p": p, "real": p is not None and p < 0.05,
                    "groups": rated})
    out.sort(key=lambda d: (not d["real"], -d["gap"]))
    return out


def summary(recs, start=None, end=None):
    tl = timelines(recs, start, end)
    slots = [t["slot"] for t in tl if t["slot"]]
    return {
        "n": len(tl),
        "span": (min(slots).date(), max(slots).date()) if slots else None,
        "who": ai_vs_human(tl),
        "days": days_to_book(tl),
        "times": booking_times(tl),
        "drivers": retention_drivers(tl),
    }
