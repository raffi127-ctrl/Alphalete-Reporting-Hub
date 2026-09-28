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
import json
import os
import pathlib
from typing import Dict, List, Optional, Tuple

from automations.local_office_1on1s import people as PEO

OFFICE = "Rafael Hidalgo"          # wkd.offices.RAF — the rhidalgo login IS 11280

# A STORE OF OUR OWN, because shared.knock_week_cache is a 3-WEEK ROLLING
# CACHE. Its put() calls prune(keep_weeks=3) on every write — deliberately:
# "three weeks is enough that a late catch-up rerun of an older week still
# hits, and small enough that the directory stays a handful of files". That
# is right for what it is for (the Sunday board and the captainship build
# sharing one pull of the SAME week) and wrong for a nine-week backfill: the
# 2026-09-28 run pulled 9/9 weeks and each write deleted the oldest, so the
# fill found 3 and August read as if ownerville had no data.
#
# Widening the shared cache would change behaviour for reports that rely on it
# staying small. This report keeps its own history instead and still READS the
# shared cache first, so a week the Sunday board already paid for costs
# nothing. [[feedback_no_cross_report_data_reuse]]
STORE = pathlib.Path(__file__).resolve().parents[2] / "output" / "1on1s_knock_history"


def _store_path(saturday: dt.date) -> pathlib.Path:
    return STORE / f"{saturday.isoformat()}.json"


def store_get(saturday: dt.date) -> Optional[List[dict]]:
    try:
        raw = json.loads(_store_path(saturday).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a missing or broken file is just a miss
        return None
    rows = raw.get("rows")
    return rows if isinstance(rows, list) and rows else None


def store_put(saturday: dt.date, rows: List[dict], dispo_cols: List[str]) -> None:
    """Record a pull. An EMPTY result is never written — an empty week is
    almost always a failed pull, and freezing one in would hide the failure
    behind a week that looks legitimately quiet."""
    if not rows:
        return
    STORE.mkdir(parents=True, exist_ok=True)
    tmp = _store_path(saturday).with_suffix(".tmp")
    tmp.write_text(json.dumps({"saturday": saturday.isoformat(),
                               "office": OFFICE,
                               "rows": rows,
                               "dispo_cols": dispo_cols}, default=str),
                   encoding="utf-8")
    os.replace(tmp, _store_path(saturday))


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

    # A LIST OF ZEROS IS NOT DATA. `if mf_talk:` is true for [0,0,0,0,0], which
    # is what a week with no talk-to rows looks like, and that produced
    # 'Monday % Talk To's Per knocks = 0.0%' beside a BLANK talk-to count —
    # a rate stated for a week nothing was recorded. The board path
    # (sales.day_cells) had the same arithmetic and was fixed there; this copy
    # was not, which is why it came back. Both now require a real observation.
    # [[feedback_dont_explain_away_a_zero]]
    tk_sum = sum(mf_knocks) if mf_knocks else None
    tt_sum = sum(mf_talk) if mf_talk else None
    have_tt = bool(mf_talk) and tt_sum is not None and tt_sum > 0

    if tk_sum:
        add("Monday - Friday Total Knocks", num(tk_sum), "sum Mon-Fri knocks")
    if have_tt:
        add("Monday - Friday Total Talk Too's", num(tt_sum), "sum Mon-Fri talk-to's")
    # AVERAGES DIVIDE BY DAYS ACTUALLY KNOCKED, never by 5 — a rep who knocked
    # three days did not average their week over five.
    if mf_days and tk_sum:
        add("Monday - Friday AVG Doors knocked / Day",
            num(tk_sum / mf_days), f"Mon-Fri knocks / {mf_days} days knocked")
    if mf_days and have_tt:
        add("Mon - Friday avg Talk To's Day",
            num(tt_sum / mf_days), f"Mon-Fri talk-to's / {mf_days} days knocked")
    if tk_sum and have_tt:
        add("Monday % Talk To's Per knocks",
            f"{100 * tt_sum / tk_sum:.1f}%", "talk-to's / knocks, Mon-Fri")

    # Same rule on Saturday: a 0 here means "no talk-to rows that day", not
    # "spoke to nobody". Knocks of 0 are equally uninformative — the rep did
    # not work Saturday, which the blank says and a 0 misstates.
    if sat_knocks:
        add("Saturday Avg Doors / Day", num(sat_knocks), "Saturday knocks")
    if sat_talk:
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
    rows = store_get(saturday)
    if rows:
        logfn(f"    knocks WE {saturday:%-m/%-d}: history ({len(rows)} reps)")
        return by_person(rows)

    from automations.shared import knock_week_cache as KC
    hit = KC.get(OFFICE, saturday, aliases=aliases)
    if hit:
        logfn(f"    knocks WE {saturday:%-m/%-d}: shared cache ({len(hit[0])} reps)")
        store_put(saturday, hit[0], hit[1])       # keep it before prune eats it
        return by_person(hit[0])
    if page is None:
        return None
    from automations.weekly_knock_dispositions import offices as OFF, pull as P
    monday = saturday - dt.timedelta(days=5)
    logfn(f"    knocks WE {saturday:%-m/%-d}: pulling 6 days from ownerville")
    rows, cols = P.pull_office_week(page, cfg or OFF.RAF, aliases, monday,
                                    saturday, verbose=False)
    if rows:
        store_put(saturday, rows, cols)
        KC.put(OFFICE, saturday, rows, cols, aliases=aliases)
    return by_person(rows)
