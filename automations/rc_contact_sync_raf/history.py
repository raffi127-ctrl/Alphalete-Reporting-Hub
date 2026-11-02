"""Per-rep flag history for the wrap-up reports — how many report days in a row
a rep has been on the list, and how many times this week.

Keyed by Slack channel so each report/office is independent, and stored per
machine under ~/.config/recruiting-report/ (outside the repo, so `lucy update`
never touches it). Shape:

    { "<channel_id>": {
        "_runs": ["2026-11-01", ...],          # days this channel POSTED
        "reps":  { "willie henderson": ["2026-11-01", ...] } } }

STREAK is consecutive REPORT-RUN days (not calendar days) the rep was flagged,
walking back from the reported day: a Sunday / no-sales day isn't a run so it
doesn't break a streak, but a day the report ran and the rep was NOT flagged
(they texted everyone) does. WEEK COUNT is the rep's flagged days in the Mon–Sun
week of the reported day.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Tuple

STORE = Path.home() / ".config" / "recruiting-report" / "wrap_up_flag_history.json"
KEEP_DAYS = 60


def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:                                      # noqa: BLE001
        return {}


def _save(data: dict) -> None:
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
        tmp.replace(STORE)
    except Exception:                                      # noqa: BLE001
        pass


def _dates(xs: List[str]) -> List[dt.date]:
    out = []
    for x in xs or []:
        try:
            out.append(dt.date.fromisoformat(x))
        except (ValueError, TypeError):
            pass
    return out


def _streak(run_days: List[dt.date], flagged: set, day: dt.date) -> int:
    """Consecutive run days ending at `day` on which the rep was flagged."""
    runs_desc = sorted({d for d in run_days if d <= day}, reverse=True)
    streak = 0
    for d in runs_desc:
        if d in flagged:
            streak += 1
        else:
            break
    return streak


def _week_count(flagged: set, day: dt.date) -> int:
    monday = day - dt.timedelta(days=day.weekday())
    sunday = monday + dt.timedelta(days=6)
    return len({d for d in flagged if monday <= d <= sunday})


def update_and_stats(channel: str, flagged_reps: List[str], day: dt.date,
                     *, persist: bool = True) -> Dict[str, Tuple[int, int]]:
    """Record that `channel` posted on `day` and that `flagged_reps` were on the
    list, then return {rep: (streak, week_count)}. Always call it when the report
    POSTS (even with an empty flagged_reps on an all-messaged day) so the run is
    recorded and streaks break correctly. `persist=False` for a dry run —
    `day` is still included in the returned stats, just not written."""
    di = day.isoformat()
    data = _load()
    chan = data.setdefault(channel, {})
    runs = chan.setdefault("_runs", [])
    reps = chan.setdefault("reps", {})
    if di not in runs:
        runs.append(di)
    for rep in flagged_reps:
        lst = reps.setdefault(_norm(rep), [])
        if di not in lst:
            lst.append(di)

    run_days = _dates(runs)
    out: Dict[str, Tuple[int, int]] = {}
    for rep in flagged_reps:
        flagged = set(_dates(reps.get(_norm(rep), [])))
        out[rep] = (_streak(run_days, flagged, day), _week_count(flagged, day))

    # prune anything older than KEEP_DAYS so the file stays small
    cutoff = (day - dt.timedelta(days=KEEP_DAYS)).isoformat()
    chan["_runs"] = sorted({x for x in runs if x >= cutoff})
    for k in list(reps.keys()):
        reps[k] = sorted({x for x in reps[k] if x >= cutoff})
        if not reps[k]:
            del reps[k]
    if persist:
        _save(data)
    return out
