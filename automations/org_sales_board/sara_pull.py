"""Retail NL / Retail Internet pull for the Alphalete ORG Sales Board.

ONE SARA PLUS pass feeds BOTH the Retail NL section (Wireless Lines = new
lines) and the Retail Internet section (Internet). Source is the
purpose-built view:

  DropshipV_2 / SARAPLUSSALESSUMMARYBYDAY / RetailNLOrgSalesBoard
  .../2eaaea0a-8456-44d9-8852-edd8034e4ee7/RetailNLOrgSalesBoard

RetailNLOrgSalesBoard is a Tableau CUSTOM (saved) view — the .csv export
endpoint can't address a custom view by name (it 404s; it only serves the
base worksheet, which would drop the view's exclude-upgrade / Phone
scoping). So we navigate patchright to the FULL custom-view URL and scrape
its "Download → Data → View Data" grid (the path the recipe anticipated
for SARA). The view is relative to the current week, so there's no date to
set — the scrape returns this week's days.

Confirmed live 2026-05-31 — the View-Data grid columns are:
  Owner & Office | ICD Owner Name | Measure Names | Order Date | Measure
  Values   (tab-delimited, UTF-8; metrics: Wireless Lines, AIA, Internet,
  DTV, ATV). 'Download → Data' is disabled until a worksheet is active, so
  the scrape clicks into the viz first (activate_xy).

The existing `tableau_http.parse_sara_plus_byday` SUMS across days to a
week-to-date total. The ORG board fills each weekday column separately, so
`parse_sara_byday_perday` keeps the Order Date dimension:
{owner_norm: {metric: {date: value}}}.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from pathlib import Path
from typing import Dict, List, Optional

from automations.alphalete_org_report import tableau_http

# Full custom-view URL + the click point that activates the worksheet so
# Download → Data enables (multi-worksheet dashboard).
RETAIL_NL_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/DropshipV_2/"
    "SARAPLUSSALESSUMMARYBYDAY/2eaaea0a-8456-44d9-8852-edd8034e4ee7/"
    "RetailNLOrgSalesBoard")
ACTIVATE_XY = (0.5, 0.5)

# Measure Names → which ORG-board section the metric feeds.
METRIC_WIRELESS_LINES = "Wireless Lines"   # → Retail NL
METRIC_INTERNET = "Internet"               # → Retail Internet


def _read_rows(path: Path) -> List[List[str]]:
    """Read a scraped View-Data file (tab-delimited UTF-8) OR a comma CSV
    (offline test fixtures). Sniffs the delimiter off the header line."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "utf-16", "iso-8859-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    first = text.splitlines()[0] if text.splitlines() else ""
    delim = "\t" if "\t" in first else ","
    return list(csv.reader(io.StringIO(text), delimiter=delim))


def _parse_order_date(raw: str) -> Optional[dt.date]:
    """Tolerant parse of Tableau's Order Date cell. Tableau exports dates
    in a few shapes depending on the view's formatting; try the common
    ones and return None if none match (caller skips the row)."""
    s = (raw or "").strip()
    if not s:
        return None
    # ISO first (cheap + unambiguous).
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y",
                "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_sara_byday_perday(
    path: Path,
    metrics: Optional[list[str]] = None,
) -> Dict[str, Dict[str, Dict[dt.date, int]]]:
    """Parse SARAPLUSSALESSUMMARYBYDAY keeping the per-day breakdown.

    Returns {normalized owner: {Measure Name: {date: summed value}}}.
    Unlike `tableau_http.parse_sara_plus_byday` (which collapses days to a
    week total), this preserves the Order Date so each weekday column on
    the board can be filled individually.

    `metrics` (case-insensitive) filters Measure Names; None keeps all.
    Columns are found by header label, never by position
    ([[feedback_no_hardcoded_columns]]).
    """
    rows = _read_rows(path)
    if not rows:
        return {}
    header = rows[0]
    owner_i = tableau_http.col_idx(header, "ICD Owner Name")
    measure_i = tableau_http.col_idx(header, "Measure Names")
    value_i = tableau_http.col_idx(header, "Measure Values")
    date_i = tableau_http.col_idx(header, "Order Date")
    if None in (owner_i, measure_i, value_i, date_i):
        missing = [lbl for lbl, i in (
            ("ICD Owner Name", owner_i), ("Measure Names", measure_i),
            ("Measure Values", value_i), ("Order Date", date_i)) if i is None]
        raise ValueError(
            f"SARA by-day CSV missing expected column(s): {missing}. "
            f"Header was: {header}")
    wanted = {m.strip().lower() for m in metrics} if metrics else None

    out: Dict[str, Dict[str, Dict[dt.date, int]]] = {}
    for r in rows[1:]:
        if len(r) <= max(owner_i, measure_i, value_i, date_i):
            continue
        owner = tableau_http._norm_owner(r[owner_i])
        metric = (r[measure_i] or "").strip()
        day = _parse_order_date(r[date_i])
        if not owner or not metric or day is None:
            continue
        if wanted is not None and metric.lower() not in wanted:
            continue
        try:
            val = int(float((r[value_i] or "0").replace(",", "")))
        except ValueError:
            continue
        out.setdefault(owner, {}).setdefault(metric, {})
        out[owner][metric][day] = out[owner][metric].get(day, 0) + val
    return out


def pull_retail_nl_byday(
    out_dir: Path,
    page,
    today: Optional[dt.date] = None,
    logfn=print,
) -> Path:
    """Scrape the RetailNLOrgSalesBoard custom view's View-Data grid to a
    tab-delimited file and return its path. `page` is a live patchright
    tableau_session() Page (the view is relative to the current week — no
    date to set)."""
    from automations.shared.tableau_patchright import scrape_view_data_patchright
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "org_sales_board_retail_nl_byday.csv"
    logfn("  scraping Retail NL custom view (Download → Data)…")
    # This is a SPARSE grid (only 3-5 owners). The default alternating
    # incremental+jump scroll strategy SKIPS middle rows on sparse grids —
    # which dropped entire owners (Akib/Boaktear, Ronald) 2026-05-31. The
    # slow steady-scroll knobs capture every row ([[reference_tableau_*]]).
    scrape_view_data_patchright(
        RETAIL_NL_VIEW_URL, out_path, page=page, verbose=False,
        activate_xy=ACTIVATE_XY,
        scrape_kwargs={"jump_every": None, "scroll_step": 0.35,
                       "scroll_wait_ms": 1800, "stale_max": 30})
    logfn(f"  saved {out_path}")
    return out_path


# CROSSTAB path (Eve 2026-06-04): the View-Data scroll-scrape above intermittently
# can't activate the worksheet (so it silently dropped Wednesday). The Crosstab
# download reads the worksheet directly and is reliable — the same migration B2B /
# NDS / Fiber already got. The 'Sara Plus Sales ICD (by day)' worksheet pivots
# Order Date into weekday columns ('Mon (06-01)' …), one row per ICD × measure.
RETAIL_CROSSTAB_SHEET = "Sara Plus Sales ICD (by day)"


def pull_retail_crosstab(out_dir: Path, page, today: Optional[dt.date] = None,
                         logfn=print) -> Path:
    """Download the SARA 'Sara Plus Sales ICD (by day)' crosstab worksheet."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "org_sales_board_retail_crosstab.csv"
    logfn(f"  Retail: Download → Crosstab ('{RETAIL_CROSSTAB_SHEET}')…")
    download_crosstab_patchright(RETAIL_NL_VIEW_URL, RETAIL_CROSSTAB_SHEET,
                                 out_path, page=page, verbose=False)
    logfn(f"  saved {out_path}")
    return out_path


def parse_sara_crosstab_byday(path: Path, today: Optional[dt.date] = None
                              ) -> Dict[str, Dict[str, Dict[dt.date, int]]]:
    """Parse the SARA by-day CROSSTAB → {normalized owner: {measure: {date: n}}}
    (same shape as parse_sara_byday_perday). Layout: 'ICD Owner Name' col, then a
    blank-header MEASURE col (Wireless Lines / Internet / …) right after it, then
    weekday-date columns 'Mon (06-01)' …."""
    from automations.org_sales_board.section_pull import _day_for_header
    today = today or dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    rows = _read_rows(path)
    if not rows:
        return {}
    hdr_idx = next((i for i, r in enumerate(rows)
                    if any("ICD Owner Name" in (c or "") for c in r)), None)
    if hdr_idx is None:
        return {}
    header = rows[hdr_idx]
    owner_i = next(i for i, c in enumerate(header) if "ICD Owner Name" in (c or ""))
    measure_i = owner_i + 1     # blank-header measure column sits right after
    day_cols = {i: d for i, c in enumerate(header)
                if (d := _day_for_header(c, monday))}
    out: Dict[str, Dict[str, Dict[dt.date, int]]] = {}
    for r in rows[hdr_idx + 1:]:
        if len(r) <= measure_i:
            continue
        owner = tableau_http._norm_owner(r[owner_i])
        measure = (r[measure_i] or "").strip()
        if not owner or not measure:
            continue
        m = out.setdefault(owner, {}).setdefault(measure, {})
        for ci, day in day_cols.items():
            if ci >= len(r):
                continue
            cell = (r[ci] or "").strip().replace(",", "")
            if not cell:
                continue
            try:
                m[day] = m.get(day, 0) + int(float(cell))
            except ValueError:
                continue
    return out
