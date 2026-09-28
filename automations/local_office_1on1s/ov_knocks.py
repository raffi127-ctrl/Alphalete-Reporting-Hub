"""The knocking block, from OwnerVille — the only source that has all of it.

WHY THIS EXISTS WHEN THE SALES BOARD ALREADY CARRIES KNOCKS.

The board answers 11 of the 13 knock rows for recent weeks and is nearly free
(one read per week). Two things it cannot do, both found 2026-09-28:

  * IT HAS NO HISTORY. 'Sales Board WE 8.2' / '8.16' / '8.30' head their
    columns `Total Apps · INT · INT UP · DTV · NL · EN · Cx` — no TK and no
    Talk-To's at all. Per-day knock tracking starts around WE 9.6, so the five
    August weeks are simply not on the board.
  * IT HAS NO TIMES. 'Mon-Fri AVG First/Last Knock' and 'Saturday First/Last
    Knock' are clock times; the board records counts only.

OwnerVille has both, per rep per day. Megan, 2026-09-28: "yes, do the ov pulls
to get 100% correct data."

COST, AND WHY THE CACHE MATTERS. `pull_office_week` is SIX single-day
Disposition pulls plus six Time Tracker calls — ~12 round trips per week, per
office — because the ranged view's First/Last Knock are the window's first and
most recent timestamps, NOT averages (observed 2026-08-22: Last Knock tracked
the afternoon clock across three same-day pulls). Only the per-day loop can
produce a true average. `shared.knock_week_cache` already holds weeks the
Sunday board and the captainship build paid for, so a week that is cached costs
nothing here. A completed week is frozen, so a cache hit is always as good as a
re-pull. [[feedback_report_runtime]]

EVERY NUMBER IS PER REP AND ALREADY AGGREGATED by pull_office_week: counts sum
across the six days, and First/Last Knock come back as each rep's AVERAGE daily
time over the days they actually knocked.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

from automations.local_office_1on1s import people as PEO

OFFICE = "Rafael Hidalgo"          # wkd.offices.RAF — the rhidalgo login IS 11280


def _keys():
    from automations.weekly_knock_dispositions import pull as P
    from automations.total_knocks.pull import (COL_FIRST_KNOCK, COL_LAST_KNOCK,
                                               COL_REP)
    return P, COL_FIRST_KNOCK, COL_LAST_KNOCK, COL_REP


def cells_for(rec: Dict, tab_note: str) -> List[Tuple[str, str, str]]:
    """[(1on1 row label, value, source)] for one rep's OwnerVille week."""
    P, C_FIRST, C_LAST, _ = _keys()

    knocks = rec.get(P.K_TOTAL_KNOCKS)
    leads = rec.get(P.K_TOTAL_LEADS)
    talk = rec.get(P.K_TALK_TO)
    daily_knocks = rec.get(P.K_DAILY_KNOCKS) or []
    daily_talk = rec.get(P.K_DAILY_TALK_TO) or []

    # Mon-Fri is the first FIVE of the six daily entries; Saturday is the last.
    mf_knocks = [v for v in daily_knocks[:5] if isinstance(v, (int, float))]
    mf_talk = [v for v in daily_talk[:5] if isinstance(v, (int, float))]
    sat_knocks = daily_knocks[5] if len(daily_knocks) > 5 else None
    sat_talk = daily_talk[5] if len(daily_talk) > 5 else None
    mf_days = sum(1 for v in mf_knocks if v)

    out: List[Tuple[str, str, str]] = []

    def add(label, value, how):
        if value is None or value == "":
            return
        out.append((label, str(value), f"OwnerVille {tab_note} — {how}"))

    def num(v):
        return None if v is None else (str(int(v)) if float(v) == int(v) else f"{v:.1f}")

    if mf_knocks:
        add("Monday - Friday Total Knocks", num(sum(mf_knocks)), "sum Mon-Fri knocks")
    if mf_talk:
        add("Monday - Friday Total Talk Too's", num(sum(mf_talk)), "sum Mon-Fri talk-to's")
    # AVERAGES DIVIDE BY DAYS ACTUALLY KNOCKED, never by 5 — a rep who knocked
    # three days did not average their week over five.
    if mf_days and mf_knocks:
        add("Monday - Friday AVG Doors knocked / Day",
            num(sum(mf_knocks) / mf_days), f"Mon-Fri knocks / {mf_days} days knocked")
    if mf_days and mf_talk:
        add("Mon - Friday avg Talk To's Day",
            num(sum(mf_talk) / mf_days), f"Mon-Fri talk-to's / {mf_days} days knocked")
    if mf_knocks and sum(mf_knocks) and mf_talk:
        add("Monday % Talk To's Per knocks",
            f"{100 * sum(mf_talk) / sum(mf_knocks):.1f}%", "talk-to's / knocks, Mon-Fri")

    add("Saturday Avg Doors / Day", num(sat_knocks), "Saturday knocks")
    add("Saturday avg Talk To's Day", num(sat_talk), "Saturday talk-to's")

    # The four the sales board can never answer.
    add("Mon - Friday AVG First Knock", rec.get(C_FIRST), "avg daily first knock")
    add("Mon - Friday AVG Last Knock", rec.get(C_LAST), "avg daily last knock")
    add("Saturday First knock", rec.get(P.K_SAT_FIRST), "Saturday first knock")
    add("Saturday Last Knock", rec.get(P.K_SAT_LAST), "Saturday last knock")
    return out


def by_person(rows: List[dict]) -> Dict[str, dict]:
    _P, _f, _l, COL_REP = _keys()
    return {PEO.key(r.get(COL_REP, "")): r for r in rows if r.get(COL_REP)}


def week(saturday: dt.date, *, page=None, cfg=None, aliases=None,
         logfn=print) -> Optional[Dict[str, dict]]:
    """{person key: record} for the Mon-Sat week ending `saturday`.

    Cache first. A live pull needs an open ownerville `page`; without one this
    returns None rather than opening a browser as a side effect of a fill.
    """
    from automations.shared import knock_week_cache as KC
    hit = KC.get(OFFICE, saturday, aliases=aliases)
    if hit:
        logfn(f"    knocks WE {saturday:%-m/%-d}: cache hit ({len(hit[0])} reps)")
        return by_person(hit[0])
    if page is None:
        return None
    from automations.weekly_knock_dispositions import offices as OFF, pull as P
    monday = saturday - dt.timedelta(days=5)
    logfn(f"    knocks WE {saturday:%-m/%-d}: pulling 6 days from ownerville")
    rows, cols = P.pull_office_week(page, cfg or OFF.RAF, aliases, monday,
                                    saturday, verbose=False)
    if rows:
        KC.put(OFFICE, saturday, rows, cols, aliases=aliases)
    return by_person(rows)
