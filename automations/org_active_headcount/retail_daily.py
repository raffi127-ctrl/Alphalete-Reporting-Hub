"""Retail NL daily headcount — the Monday focus report's own count, day by day.

EVE, 2026-09-12: "vas a tener que hacer el recuento diario de reps igual que lo
haces los lunes para el focus report". The Monday count is `opt_retail`'s SARA
Plus View Data scrape for the week (Min Date = Monday, Max Date = Sunday) and
`parse_sara_view_data`'s `_active_reps`: DISTINCT reps that appear in the
office's data for the range, whether or not their measures are > 0 (Megan's
2026-05-23 spec).

DAY BY DAY = THE SAME PULL WITH A SHORTER RANGE. For day D the range is
Monday-of-D .. D, so the number is exactly what the Monday report would have
said had the week ended on D — the same running count the trackers give for
the other campaigns. SARA takes Min/Max Date as URL parameters, so past days
CAN be pulled (unlike JE or the tracker boards).

Writes nothing to the headcount board: one row per (day, board ICD) into the
'HC Retail Daily' tab of the Mini Control workbook, plus every SARA owner seen
so a name mismatch is visible instead of silently reading as 0. Each day's
scrape is cached (output/_hc_retail/), so a re-run only pulls missing days.

    python -m automations.org_active_headcount.retail_daily \
        --start 2026-08-31 --end 2026-09-11
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Dict, List

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "output" / "_hc_retail"
TAB = "HC Retail Daily"
BOARD_ICDS = ["Amjad Malhas", "Akib Chowdhury", "Ana Griffin"]


def range_url(day: dt.date) -> str:
    """opt_retail's SARA URL, with Min Date = Monday of `day`'s week and Max
    Date = `day` (its own builder only knows whole Mon-Sun weeks)."""
    from automations.alphalete_org_report import opt_retail as orl
    monday = day - dt.timedelta(days=day.weekday())
    return (f"{orl._RETAIL_SARA_BASE_URL}?:iid=1"
            f"&Min%20Date={monday.isoformat()}&Max%20Date={day.isoformat()}")


def _words(s: str) -> List[str]:
    return [t for t in re.split(r"[^a-z]+", (s or "").lower()) if t]


def owner_for(icd: str, owners: List[str]) -> List[str]:
    """SARA owner keys (already lowercased, [city] stripped) for a board ICD:
    every word of the ICD's source name is in the owner label."""
    from automations.org_active_headcount import sources as src
    want = _words(src.source_name(icd))
    return [o for o in owners if all(w in _words(o) for w in want)]


def day_counts(day: dt.date, logfn=print) -> Dict[str, int]:
    """{sara owner: active reps} for Monday..day, scraping only if not cached."""
    from automations.alphalete_org_report import opt_retail as orl
    from automations.shared.tableau_patchright import scrape_view_data_patchright
    path = CACHE / f"sara_{day.isoformat()}.csv"
    if not path.exists() or path.stat().st_size < 500:
        logfn(f"  SARA {day - dt.timedelta(days=day.weekday())} .. {day} -> {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same activate point and scroll tuning opt_retail uses on this grid —
        # without them 'Download -> Data' stays disabled or middle owners get
        # skipped (see pull._scrape_sara).
        scrape_view_data_patchright(
            range_url(day), path, verbose=False,
            activate_xy=orl.RETAIL_SARA_ACTIVATE_XY,
            scrape_kwargs=dict(jump_every=None, scroll_step=0.35,
                               scroll_wait_ms=1800, stale_max=30))
    totals = orl.parse_sara_view_data(path)
    return {owner: rec.get("_active_reps", 0) for owner, rec in totals.items()}


def run(start: dt.date, end: dt.date, logfn=print) -> None:
    rows: List[list] = [["day", "board ICD", "SARA owner", "active reps (Mon..day)"]]
    seen_owners = set()
    day = start
    while day <= end:
        try:
            got = day_counts(day, logfn=logfn)
        except Exception as e:                                     # noqa: BLE001
            logfn(f"  {day}: FAILED {type(e).__name__}: {e}")
            rows.append([day.isoformat(), "*", "FAILED", f"{type(e).__name__}: {e}"[:200]])
            day += dt.timedelta(days=1)
            continue
        seen_owners.update(got)
        for icd in BOARD_ICDS:
            hits = owner_for(icd, list(got))
            if not hits:
                rows.append([day.isoformat(), icd, "NOT IN SARA", ""])
            for o in hits:
                rows.append([day.isoformat(), icd, o, got[o]])
        logfn(f"  {day}: " + ", ".join(
            f"{icd}={[got[o] for o in owner_for(icd, list(got))]}" for icd in BOARD_ICDS))
        day += dt.timedelta(days=1)
    rows.append([])
    rows.append(["every SARA owner seen"] + sorted(seen_owners))
    from automations.org_active_headcount.tracker_readings import _to_sheet
    _to_sheet(TAB, rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", required=True, type=dt.date.fromisoformat)
    ap.add_argument("--end", required=True, type=dt.date.fromisoformat)
    a = ap.parse_args(argv)
    run(a.start, a.end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
