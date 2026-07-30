"""Each rep's FIRST DAY OF SALES, derived from the full Tableau order history.

Fills the "Start Date or First Day of sales" column of the DD block, which Eve
used to type by hand. Raf's spec (2026-07-30):

  * Tableau retains order history forever -> one backfill covers everyone.
  * ANY logged sale counts -> NO Product Type filter and NO Status filter.
    A cancelled or inactive order still marks the day the rep first sold.
  * Rep names are consistent in Tableau -> key on _norm(rep), no alias layer.

Source is the org-wide ORDERLOG / ALLREPS 'A.Order Log' crosstab (per-order row
grain, already maintained for 8 office-metrics reports). The DD product view
can't do this: it has no date field, only weekday COLUMNS inside a
week-filtered pull, so reaching back years would need one pull per week.

Two phases, because a rep's first sale date never changes once known:
  1. backfill()      — walk all history in monthly chunks, min-per-rep, resumable.
  2. update_recent() — the 3am harvest pulls a rolling 30-day window and adds
                       ONLY reps missing from the map (add-only, immutable).

The map lives on a '_first_sale' tab in the DD workbook rather than a local
JSON, so it works from any machine and survives a mini rebuild.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from . import config as C

SHEET_TAB = "_first_sale"
STATE_PATH = C.OUTPUT_DIR / "first_sale_backfill.json"

# A month org-wide measured ~47k rows / ~32MB (2026-05 sample). A chunk anywhere
# near this alarm is either an anomalous month or a truncated export, so we
# re-pull it as weekly sub-chunks instead of trusting it. Never truncate
# silently — that is exactly how the week-filter bug hid for two days.
CHUNK_ROW_ALARM = 150_000
BACKFILL_FLOOR = dt.date(2015, 1, 1)     # probe walks forward from here


# --------------------------------------------------------------------------
def _norm(s) -> str:
    from .pull import _norm as n
    return n(s)


def _parse_date(s) -> Optional[dt.date]:
    """Tableau order-log dates are M/D/YYYY; tolerate ISO too."""
    s = (s or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return dt.date(*(int(x) for x in m.groups()))
        except ValueError:
            return None
    return None


def _sale_date(order, install, activ) -> Optional[dt.date]:
    """First-sale date for a row: order date, else install, else activation.

    NOTE the priority is deliberately the REVERSE of order_log._eff_date, which
    resolves (activation, install, order) because it decides a PAY week.
    Activation and install always land AFTER the sale, so using that order here
    would report a start date later than the rep's real first day. Order date is
    the sale; the other two are only a fallback for a blank order date.
    """
    for v in (order, install, activ):
        d = _parse_date(v)
        if d:
            return d
    return None


def _cols(hdr: List[str]) -> Tuple[int, int, int, int]:
    """(rep, order, install, activation) column indexes, found by header label —
    never by position. 'Rep' is matched exactly so 'icd.Lead Rep ID' and
    'rep.Rep Number' can't win. The activation header is misspelled
    'Activatoin Date (order log)' in the view, so match loosely on 'ctivat'."""
    def find(pred, label):
        i = next((i for i, h in enumerate(hdr) if pred((h or "").strip())), None)
        if i is None:
            raise KeyError(f"order log crosstab has no {label} column: {hdr[:8]}")
        return i
    rep = find(lambda h: h == "Rep", "'Rep'")
    order = find(lambda h: "Order Date" in h, "'Order Date'")
    install = next((i for i, h in enumerate(hdr) if "Install Date" in (h or "")), -1)
    activ = next((i for i, h in enumerate(hdr) if "ctivat" in (h or "")), -1)
    return rep, order, install, activ


# --------------------------------------------------------------------------
def _chunk_url(start: dt.date, end: dt.date) -> str:
    from automations.uploaded.order_log import ALLREPS_VIEW_URL_TMPL
    return ALLREPS_VIEW_URL_TMPL.format(start=start.isoformat(), end=end.isoformat())


def _download(start: dt.date, end: dt.date, out: Path, page, verbose: bool) -> Path:
    from automations.uploaded.order_log import CROSSTAB_SHEET
    from automations.shared.tableau_patchright import download_crosstab_patchright
    download_crosstab_patchright(_chunk_url(start, end), CROSSTAB_SHEET, out,
                                 verbose=verbose, page=page)
    return out


def scan_file(path: Path) -> Tuple[Dict[str, Tuple[str, dt.date]], int, Optional[dt.date], Optional[dt.date]]:
    """min sale-date per rep in one crosstab.

    Returns ({norm rep: (display, date)}, row_count, min_date, max_date).
    NO product-type and NO status filter — any logged sale counts."""
    from .pull import _read_utf16_tsv
    rows = _read_utf16_tsv(path)
    if not rows:
        return {}, 0, None, None
    ri, oi, ii, ai = _cols(rows[0])
    out: Dict[str, Tuple[str, dt.date]] = {}
    lo = hi = None
    n = 0
    for r in rows[1:]:
        if len(r) <= ri:
            continue
        rep = (r[ri] or "").strip()
        if not rep or rep.lower() in ("total", "grand total"):
            continue
        d = _sale_date(r[oi] if oi < len(r) else "",
                       r[ii] if 0 <= ii < len(r) else "",
                       r[ai] if 0 <= ai < len(r) else "")
        if not d:
            continue
        n += 1
        lo = d if lo is None or d < lo else lo
        hi = d if hi is None or d > hi else hi
        k = _norm(rep)
        if k not in out or d < out[k][1]:
            out[k] = (rep, d)
    return out, n, lo, hi


def _merge(dst: Dict[str, Tuple[str, dt.date]], src: Dict[str, Tuple[str, dt.date]]) -> None:
    for k, (disp, d) in src.items():
        if k not in dst or d < dst[k][1]:
            dst[k] = (disp, d)


# --------------------------------------------------------------------------
def month_ranges(start: dt.date, end: dt.date) -> Iterator[Tuple[dt.date, dt.date]]:
    cur = dt.date(start.year, start.month, 1)
    while cur <= end:
        nxt = dt.date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)
        yield max(cur, start), min(nxt - dt.timedelta(days=1), end)
        cur = nxt


def week_ranges(start: dt.date, end: dt.date) -> Iterator[Tuple[dt.date, dt.date]]:
    cur = start
    while cur <= end:
        yield cur, min(cur + dt.timedelta(days=6), end)
        cur += dt.timedelta(days=7)


# --------------------------------------------------------------------------
def _load_state() -> dict:
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        raw["map"] = {k: (v[0], dt.date.fromisoformat(v[1])) for k, v in raw.get("map", {}).items()}
        return raw
    except Exception:
        return {"done": [], "map": {}}


def _save_state(st: dict) -> None:
    C.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({
        "done": st["done"],
        "map": {k: [v[0], v[1].isoformat()] for k, v in st["map"].items()},
    }), encoding="utf-8")


def _pull_chunk(a: dt.date, b: dt.date, page, verbose: bool, log) -> Dict[str, Tuple[str, dt.date]]:
    """One range -> min-per-rep. Splits to weekly if the export looks truncated."""
    tmp = C.OUTPUT_DIR / "first_sale_chunk.csv"
    _download(a, b, tmp, page, verbose)
    got, n, lo, hi = scan_file(tmp)
    log(f"  {a}..{b}: {n:,} rows, {len(got):,} reps, dates {lo}..{hi}")
    if n >= CHUNK_ROW_ALARM:
        log(f"  ! {a}..{b} hit the {CHUNK_ROW_ALARM:,}-row alarm — re-pulling weekly "
            f"rather than trusting a possibly-truncated export")
        got = {}
        for wa, wb in week_ranges(a, b):
            _download(wa, wb, tmp, page, verbose)
            sub, sn, slo, shi = scan_file(tmp)
            log(f"    {wa}..{wb}: {sn:,} rows, {len(sub):,} reps")
            _merge(got, sub)
    return got


def backfill(*, start: dt.date = None, end: dt.date = None, page=None,
             verbose: bool = False, log=print) -> dict:
    """Walk all history in monthly chunks; resumable. Returns the merged map."""
    end = end or (dt.date.today() - dt.timedelta(days=1))
    start = start or BACKFILL_FLOOR
    st = _load_state()
    chunks = [(a, b) for a, b in month_ranges(start, end)
              if f"{a}:{b}" not in set(st["done"])]
    log(f"backfill {start}..{end} — {len(chunks)} chunk(s) to go "
        f"({len(st['done'])} already done, {len(st['map']):,} reps so far)")

    def _work(pg):
        for a, b in chunks:
            got = _pull_chunk(a, b, pg, verbose, log)
            _merge(st["map"], got)
            st["done"].append(f"{a}:{b}")
            _save_state(st)                      # resumable after every chunk

    if page is None:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(headless=True, verbose=verbose) as pg:
            _work(pg)
    else:
        _work(page)
    log(f"backfill done — {len(st['map']):,} reps with a first-sale date")
    return st["map"]


def update_recent(*, days: int = 30, page=None, verbose: bool = False,
                  log=print) -> dict:
    """3am harvest step: pull a rolling window and ADD only reps missing from
    the stored map. A first-sale date is immutable once set, and any rep whose
    first sale is older than the window is already in the map from the backfill,
    so add-only is correct (and keeps this to one crosstab a day)."""
    end = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=days)
    stored = load_map()
    tmp = C.OUTPUT_DIR / "first_sale_recent.csv"

    def _work(pg):
        _download(start, end, tmp, pg, verbose)
        return scan_file(tmp)

    if page is None:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(headless=True, verbose=verbose) as pg:
            got, n, lo, hi = _work(pg)
    else:
        got, n, lo, hi = _work(page)
    added = {k: v for k, v in got.items() if k not in stored}
    log(f"first-sale window {start}..{end}: {n:,} rows, {len(got):,} reps seen, "
        f"{len(added):,} new")
    if added:
        stored.update(added)
        save_map(stored)
    return {"seen": len(got), "added": len(added), "total": len(stored)}


# --------------------------------------------------------------------------
def _ws(create: bool = False):
    """The '_first_sale' tab in the DD workbook.

    create=False (reads) returns None when the tab doesn't exist yet rather than
    making one — a /dd should never leave an empty tab behind as a side effect
    of looking something up. Only save_map() creates it.
    """
    import gspread
    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(C.DD_SHEET_ID)
    try:
        return sh.worksheet(SHEET_TAB)
    except gspread.WorksheetNotFound:
        if not create:
            return None
        ws = _retry(sh.add_worksheet, title=SHEET_TAB, rows=20000, cols=4)
        _retry(ws.update, "A1:C1", [["Rep", "First Sale", "Updated"]])
        return ws


def load_map() -> Dict[str, Tuple[str, dt.date]]:
    from automations.recruiting_report.fill import _retry
    out: Dict[str, Tuple[str, dt.date]] = {}
    try:
        ws = _ws()
        if ws is None:
            return out
        rows = _retry(ws.get_all_values)
    except Exception:
        return out
    for r in rows[1:]:
        if len(r) < 2 or not (r[0] or "").strip():
            continue
        d = _parse_date(r[1])
        if d:
            out[_norm(r[0])] = (r[0].strip(), d)
    return out


def save_map(m: Dict[str, Tuple[str, dt.date]]) -> int:
    """Overwrite the tab with the full map (sorted by rep). This tab is derived
    data the report owns end-to-end — no human types into it — so a rewrite is
    safe; every other DD tab stays append-only."""
    from automations.recruiting_report.fill import _retry
    ws = _ws(create=True)
    today = dt.date.today().isoformat()
    body = [[disp, d.isoformat(), today] for _, (disp, d) in sorted(m.items())]
    _retry(ws.clear)
    _retry(ws.update, "A1:C1", [["Rep", "First Sale", "Updated"]])
    if body:
        _retry(ws.update, f"A2:C{len(body) + 1}", body)
    return len(body)


def start_date_for(rep_key: str, m: Dict[str, Tuple[str, dt.date]]) -> str:
    """Rendered value for the 'Start Date or First Day of sales' cell."""
    hit = m.get(rep_key)
    if not hit:
        return ""
    d = hit[1]
    return f"{d.month}/{d.day}/{d.year}"      # not %-m/%-d — that is Mac-only


# --------------------------------------------------------------------------
def probe(*, page=None, verbose: bool = False, log=print, empty_stop: int = 2) -> dict:
    """How far back does the ALLREPS Start Date param actually reach?

    Sampling one month per year and walking FORWARD from 2015 would burn a pull
    per empty year before reaching real data. Walk BACKWARD from this year
    instead and stop after `empty_stop` consecutive empty years — that costs
    roughly (years-of-history + 2) pulls instead of a fixed twelve.
    """
    tmp = C.OUTPUT_DIR / "first_sale_probe.csv"
    found, empties = {}, 0

    def _work(pg):
        nonlocal empties
        for yr in range(dt.date.today().year, BACKFILL_FLOOR.year - 1, -1):
            a, b = dt.date(yr, 6, 1), dt.date(yr, 6, 30)
            try:
                _download(a, b, tmp, pg, verbose)
                _, n, lo, hi = scan_file(tmp)
            except Exception as e:                # noqa: BLE001
                log(f"  {yr}-06: pull failed ({type(e).__name__}: {str(e)[:80]})")
                found[yr] = {"rows": None, "min": None}
                continue
            log(f"  {yr}-06: {n:,} rows, dates {lo}..{hi}")
            found[yr] = {"rows": n, "min": lo.isoformat() if lo else None}
            empties = empties + 1 if n == 0 else 0
            if empties >= empty_stop:
                log(f"  {empty_stop} empty years in a row — history starts after "
                    f"{yr}; stopping the probe here")
                return

    if page is None:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(headless=True, verbose=verbose) as pg:
            _work(pg)
    else:
        _work(page)
    live = sorted(y for y, v in found.items() if v.get("rows"))
    return {"years": found,
            "earliest_year_with_rows": live[0] if live else None,
            "suggested_backfill_start": dt.date(live[0], 1, 1).isoformat() if live else None}
