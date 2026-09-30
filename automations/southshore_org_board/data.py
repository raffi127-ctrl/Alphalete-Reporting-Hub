"""Pull + parse + the week history for the Southshore Org board."""
from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from automations.southshore_org_board import config as cfg

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday"]

OwnerDays = Dict[str, Dict[str, int]]     # {owner: {iso date: units}}

# The B2B download drops its page now and then (TargetClosedError on
# save_as, 2026-09-30) and a fresh session gets it the next time.
PULL_TRIES = 3


def week_of(monday: dt.date) -> List[dt.date]:
    return [monday + dt.timedelta(days=i) for i in range(7)]


# ------------------------------------------------------------------ parse
def parse_twl(path: Path, products=cfg.NDS_PRODUCTS) -> OwnerDays:
    """The 'Thisweekandlast' crosstab → {owner: {date: units}}.

    Two header rows: the week-ending date over each weekday column, then the
    weekday names — together they date every column exactly, whichever week
    'This Week' is. Columns by label, never by position. Rep rows are summed
    per owner; 'Total' rows are skipped so nothing is counted twice."""
    from automations.org_sales_board import sara_pull
    from automations.alphalete_org_report.opt_nds import _norm_owner
    rows = sara_pull._read_rows(path)
    if len(rows) < 3:
        return {}
    we_row, day_row = rows[0], rows[1]
    head = [c.strip().lower() for c in day_row]
    try:
        owner_i = next(i for i, c in enumerate(head) if c.startswith("owner"))
        rep_i = next(i for i, c in enumerate(head) if c.startswith("rep"))
        prod_i = next(i for i, c in enumerate(head) if c.startswith("product"))
    except StopIteration:
        raise ValueError(f"unexpected crosstab header: {day_row}")
    cols = []
    for i, (we, day) in enumerate(zip(we_row, day_row)):
        if day.strip() in DAYS and we.strip():
            m, d, y = (int(x) for x in we.strip().split("/"))
            sunday = dt.date(y, m, d)
            cols.append((i, sunday - dt.timedelta(days=6 - DAYS.index(day.strip()))))
    if not cols:
        raise ValueError(f"no dated weekday columns in {path.name}")
    keep = {p.upper() for p in products}
    out: OwnerDays = {}
    for r in rows[2:]:
        if len(r) <= max(owner_i, rep_i, prod_i):
            continue
        if r[rep_i].strip() == "Total" or r[prod_i].strip().upper() not in keep:
            continue
        owner = _norm_owner(r[owner_i])
        for i, day in cols:
            v = (r[i] if i < len(r) else "").replace(",", "").strip()
            if v:
                days = out.setdefault(owner, {})
                days[day.isoformat()] = days.get(day.isoformat(), 0) + int(float(v))
    # every dated column is a day the view covers: an owner with a blank there
    # sold 0 that day (the crosstab lists every owner with any sale in either week)
    for owner in out:
        for _i, day in cols:
            out[owner].setdefault(day.isoformat(), 0)
    return out


def twl_dates(path: Path) -> List[dt.date]:
    from automations.org_sales_board import sara_pull
    rows = sara_pull._read_rows(path)
    out = []
    for we, day in zip(rows[0], rows[1]):
        if day.strip() in DAYS and we.strip():
            m, d, y = (int(x) for x in we.strip().split("/"))
            out.append(dt.date(y, m, d) - dt.timedelta(days=6 - DAYS.index(day.strip())))
    return out


# ------------------------------------------------------------------- pull
def pull(today: dt.date, out_dir: Path, verbose: bool = False):
    """Download both sources. Returns (nds_path, b2b_path). Separate browser
    sessions: a second download in the same session was dropping its page
    (2026-09-29, every pull after the first)."""
    from automations.org_sales_board import section_pull as sp
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright, tableau_session)
    out_dir.mkdir(parents=True, exist_ok=True)
    nds_path = out_dir / "nds_thisweekandlast.csv"
    spec = dataclasses.replace(sp.B2B_SPEC, out_name="b2b_byday.csv")
    b2b_path = out_dir / spec.out_name

    def _nds(page):
        download_crosstab_patchright(cfg.NDS_TWL_URL, cfg.NDS_SHEET, nds_path,
                                     page=page, verbose=verbose)

    def _b2b(page):
        sp.pull_section_byday(spec, out_dir, page, today=today)

    for label, path, fetch in (("NDS", nds_path, _nds), ("B2B", b2b_path, _b2b)):
        if path.exists():
            path.unlink()            # never parse a stale file from an earlier run
        err = None
        for attempt in range(1, PULL_TRIES + 1):
            try:
                with tableau_session(verbose=verbose) as page:
                    fetch(page)
                if path.exists() and path.stat().st_size:
                    break
                err = "download produced no file"
            except Exception as e:  # noqa: BLE001 — retried; the last one raises
                err = f"{type(e).__name__}: {str(e)[:160]}"
            print(f"  [{label}] try {attempt}/{PULL_TRIES} failed ({err})", flush=True)
            time.sleep(10)
        else:
            raise RuntimeError(f"{label} pull failed after {PULL_TRIES} tries: {err}")
    return nds_path, b2b_path


def parse_b2b(path: Path, today: dt.date) -> OwnerDays:
    from automations.org_sales_board import section_pull as sp
    parsed = sp.parse_byday(sp.B2B_SPEC, path, today)
    out: OwnerDays = {}
    for owner, metrics in parsed.items():
        for days in metrics.values():
            for d, v in days.items():
                out.setdefault(owner, {})[d.isoformat()] = int(v or 0)
    return out


# ---------------------------------------------------------------- history
def load_history() -> dict:
    """{week-ending iso: {"owner_days": {...}, "org_by_day": [...],
    "owner_totals": {...}}}. Starts from the seed; saved weeks layer on top."""
    hist = copy.deepcopy(cfg.SEED)
    if cfg.HISTORY_PATH.exists():
        saved = json.loads(cfg.HISTORY_PATH.read_text(encoding="utf-8"))
        for we, wk in saved.items():
            hist.setdefault(we, {}).update(
                {"owner_days": wk.get("owner_days", {})})
    return hist


def record(hist: dict, owner_days: OwnerDays, weeks: List[dt.date]) -> dict:
    """Write each owner's days for `weeks` (Mondays) into the history. A later
    pull of the same week overwrites it — Sunday's late posts land on Monday."""
    for monday in weeks:
        we = (monday + dt.timedelta(days=6)).isoformat()
        wk = hist.setdefault(we, {}).setdefault("owner_days", {})
        span = {d.isoformat() for d in week_of(monday)}
        for owner, days in owner_days.items():
            mine = {d: v for d, v in days.items() if d in span}
            if mine:
                wk.setdefault(owner, {}).update(mine)
    return hist


def save_history(hist: dict) -> None:
    cfg.HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    slim = {we: {"owner_days": wk["owner_days"]}
            for we, wk in hist.items() if wk.get("owner_days")}
    cfg.HISTORY_PATH.write_text(json.dumps(slim, indent=1, sort_keys=True),
                                encoding="utf-8")


def _complete(wk: dict, monday: dt.date) -> bool:
    """Every roster owner has all 7 days of this week captured."""
    od = wk.get("owner_days", {})
    days = {d.isoformat() for d in week_of(monday)}
    return all(days <= set(od.get(o, {})) for o, _src in cfg.ROSTER)


def org_by_day(hist: dict, monday: dt.date) -> Optional[List[int]]:
    """The org's 7 daily totals for a closed week: captured if complete, else
    the seeded row, else None (not known — never a guessed zero)."""
    wk = hist.get((monday + dt.timedelta(days=6)).isoformat(), {})
    if _complete(wk, monday):
        od = wk["owner_days"]
        return [sum(od[o].get(d.isoformat(), 0) for o, _s in cfg.ROSTER)
                for d in week_of(monday)]
    return wk.get("org_by_day")


def owner_total(hist: dict, monday: dt.date, owner: str) -> Optional[int]:
    wk = hist.get((monday + dt.timedelta(days=6)).isoformat(), {})
    days = wk.get("owner_days", {}).get(owner, {})
    span = [d.isoformat() for d in week_of(monday)]
    if all(d in days for d in span):
        return sum(days[d] for d in span)
    return (wk.get("owner_totals") or {}).get(owner)
