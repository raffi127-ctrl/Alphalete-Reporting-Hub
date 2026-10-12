"""Who SOLD recently -- those reps are working, so no owner is asked about them.

Eve 2026-10-12: Kash's list was still 82 people after the Slack cross; "si
vende, sigue trabajando". Source: the org-wide Tableau order log (ALLREPS,
'A.Order Log') that the 3am due-diligence harvest on Lucy 1 already downloads
every day to output/due_diligence/first_sale_recent.csv (rolling 30 days,
every office). No extra Tableau pull.

The view's window has been filtered by activation date at times, so rows are
re-filtered here by their own sale date (order date, else install, else
activation -- first_sale._sale_date). Any status counts: a cancelled order
still means the rep was knocking that week.

A missing or stale file costs the filter, never the run: owners get the
longer list, which is the safe direction (nobody is skipped on a guess).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional, Set

from automations.owner_rep_audit import config as C

RECENT_CSV = C.REPO_ROOT / "output" / "due_diligence" / "first_sale_recent.csv"
DAYS = 30
MAX_AGE_DAYS = 3        # the harvest runs nightly; older = it has been failing


def recent_sellers(today: dt.date, path: Path = RECENT_CSV,
                   days: int = DAYS, logfn=print) -> Optional[Set[str]]:
    """Display names of reps with a sale in the last `days`, or None when the
    file can't be trusted (missing, stale, unreadable)."""
    from automations.due_diligence import first_sale as FS
    from automations.due_diligence.pull import _read_utf16_tsv
    try:
        age = (dt.datetime.now()
               - dt.datetime.fromtimestamp(path.stat().st_mtime)).days
    except OSError:
        logfn(f"  ⚠ no order log at {path} — sellers not filtered out")
        return None
    if age > MAX_AGE_DAYS:
        logfn(f"  ⚠ order log is {age} days old — sellers not filtered out")
        return None
    try:
        rows = _read_utf16_tsv(path)
        ri, oi, ii, ai = FS._cols(rows[0])
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ order log unreadable ({type(e).__name__}: {e}) — "
              "sellers not filtered out")
        return None
    floor = today - dt.timedelta(days=days)
    out: Set[str] = set()
    for r in rows[1:]:
        rep = (r[ri] if ri < len(r) else "").strip()
        if not rep or rep.lower() in ("total", "grand total"):
            continue
        d = FS._sale_date(r[oi] if oi < len(r) else "",
                          r[ii] if 0 <= ii < len(r) else "",
                          r[ai] if 0 <= ai < len(r) else "")
        if d and d >= floor:
            out.add(rep)
    return out


def drop_sellers(reps, sellers):
    """The reps NOT on the sellers list. Same name rule as the AO cleanup tab's
    'ACTIVE on Sales Board' note: full name, first + last (middle names
    differ), or both halves inside the rep's email handle (nicknames)."""
    if not sellers:
        return list(reps)
    from automations.ao_cleanup.fill_tab import active_index, is_active
    idx = active_index(sellers)
    return [r for r in reps
            if not is_active(r["name"], idx,
                             (r.get("email") or "").split("@")[0])]
