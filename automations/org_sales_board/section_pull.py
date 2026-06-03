"""Generic scrape + per-day parse for the ORG board's purpose-built views.

Retail NL has its own module (sara_pull) because ONE pull feeds two
sections via a Measure-Names column. The other scraped daily sections —
Fiber, NDS, B2B — are each a single-metric custom view, so they share one
config-driven adapter: give it a ScrapeSpec (view URL + which columns hold
owner / day / value) and it returns the engine's input shape
{owner_norm: {metric: {date: value}}}.

Two day shapes show up across these views:
  • DATE   — the view breaks rows out by an actual Order Date (m/d/Y).
             B2B's "sp.Order Date (copy)" is this. Parsed straight to a
             dt.date, like SARA.
  • WEEKDAY — the view breaks rows out by weekday NAME ("Monday"). Fiber
             and NDS are this. There's no year/month in the cell, so we
             map the weekday name onto the dt.date of that weekday in the
             week containing `today`. (These views are this-week-relative,
             so "Monday" always means this week's Monday.)

Every scrape uses the slow steady-scroll knobs — the default View-Data
scroll strategy SILENTLY DROPS rows on these grids (it pulled 4 of 21
owners on Retail NL 2026-05-31). See sara_pull for the same fix.

Columns are found by header LABEL, never position
([[feedback_no_hardcoded_columns]]). Rows are SUMMED per (owner, day):
Fiber sums across product-type rows, NDS across rep rows, B2B across the
day's orders.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from automations.alphalete_org_report import tableau_http
from automations.org_sales_board import sara_pull

# Slow steady-scroll — captures every row on these sparse/virtualized grids.
SPARSE_SCRAPE_KWARGS = {
    "jump_every": None, "scroll_step": 0.35,
    "scroll_wait_ms": 1800, "stale_max": 30,
}

DATE = "date"        # day_col holds an actual date (m/d/Y)
WEEKDAY = "weekday"  # day_col holds a weekday NAME ("Monday")

# Pull mechanisms.
VIEWDATA = "viewdata"   # scroll-scrape Download → Data (long format)
CROSSTAB = "crosstab"   # Download → Crosstab (pivoted, weekday columns) — RELIABLE

_WEEKDAY_INDEX = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thur": 3,
    "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


@dataclass(frozen=True)
class ScrapeSpec:
    """Where one ORG-board section's per-day numbers come from + how to read
    the scraped View-Data grid into the engine shape."""
    section_label: str          # matches Source.label / SectionSpec.label
    metric: str                 # the metric key emitted (matches Source.metric)
    view_url: str               # full custom-view URL (patchright navigates here)
    owner_col: str
    value_col: str
    day_col: str
    day_kind: str = DATE        # DATE | WEEKDAY (VIEWDATA only)
    strip_office: bool = False   # owner cell carries a "|company|" / "[city]" tail
    activate_xy: tuple = (0.5, 0.5)
    out_name: str = ""          # csv filename (defaults off the metric)
    # Pull mechanism. CROSSTAB is preferred — server-side, captures every row
    # (the scroll-scrape silently drops rows on big grids), and the worksheet
    # already totals per owner×weekday so there's nothing to sum.
    method: str = VIEWDATA
    crosstab_sheet: str = ""     # worksheet to export (CROSSTAB only)
    total_label: str = ""        # the product-type value naming a per-owner
    #   pre-summed total row (e.g. "Total"). Used to identify/skip it.
    exclude_products: tuple = ()  # product-type rows to DROP, then sum the
    #   rest (e.g. "VOICE" — the no-voice total = sum of every other product
    #   row). When set, the pre-summed total_label row is skipped to avoid
    #   double-counting. When empty + total_label set, keep only total_label.
    product_col: str = "Product Type (Broken Out)"  # the per-row product label
    skip_owners: tuple = ()      # crosstab grand-total rows to drop (e.g.
    #   "Sales Total"). Matched case-insensitively against the owner cell.
    week_pin: bool = False       # append the current "Sale Date Week Ending
    #   (mon-sun)" filter to view_url so the view shows THIS week, not whatever
    #   week the saved view defaults to. Fiber's AllproductsRafsteam view was
    #   stuck on last week (WE 5/31), writing last week's numbers into this
    #   week's columns (Megan 2026-06-02).


def _norm_section_owner(raw: str, strip_office: bool) -> str:
    """Normalize an owner cell to the engine key. _norm_owner already cuts a
    trailing '[city, ST]'; some views instead carry '|Company, Inc.|', which
    it leaves — cut that first when strip_office is set."""
    s = raw or ""
    if strip_office:
        s = re.split(r"[|\[]", s, maxsplit=1)[0]
    return tableau_http._norm_owner(s)


def _weekday_to_date(name: str, today: dt.date) -> Optional[dt.date]:
    """Map a weekday NAME to its date in the week containing `today`
    (Mon-anchored, matching the board's Mon-Sun columns)."""
    idx = _WEEKDAY_INDEX.get((name or "").strip().lower())
    if idx is None:
        return None
    monday = today - dt.timedelta(days=today.weekday())
    return monday + dt.timedelta(days=idx)


def parse_section_byday(
    spec: ScrapeSpec,
    path: Path,
    today: dt.date,
) -> Dict[str, Dict[str, Dict[dt.date, int]]]:
    """Parse a scraped single-metric View-Data grid to
    {owner_norm: {spec.metric: {date: summed value}}}. Columns by label."""
    rows = sara_pull._read_rows(path)
    if not rows:
        return {}
    header = rows[0]
    oi = tableau_http.col_idx(header, spec.owner_col)
    vi = tableau_http.col_idx(header, spec.value_col)
    di = tableau_http.col_idx(header, spec.day_col)
    if None in (oi, vi, di):
        missing = [lbl for lbl, i in (
            (spec.owner_col, oi), (spec.value_col, vi), (spec.day_col, di))
            if i is None]
        raise ValueError(
            f"{spec.section_label}: View-Data missing column(s) {missing}. "
            f"Header was: {header}")

    out: Dict[str, Dict[str, Dict[dt.date, int]]] = {}
    for r in rows[1:]:
        if len(r) <= max(oi, vi, di):
            continue
        owner = _norm_section_owner(r[oi], spec.strip_office)
        if not owner:
            continue
        if spec.day_kind == WEEKDAY:
            day = _weekday_to_date(r[di], today)
        else:
            day = sara_pull._parse_order_date(r[di])
        if day is None:
            continue
        try:
            val = int(float((r[vi] or "0").replace(",", "")))
        except ValueError:
            continue
        m = out.setdefault(owner, {}).setdefault(spec.metric, {})
        m[day] = m.get(day, 0) + val
    return out


def _day_for_header(h: str, monday: dt.date) -> Optional[dt.date]:
    """Map a crosstab day-column header to its date. Handles every shape seen
    across the board's views:
      • "Monday" / "Sunday"        (Fiber/NDS)  → exact weekday name
      • "5/25 Mon"                 (BOX)        → m/d date
      • "Mon (05-25)"              (B2B)        → m-d date
    An explicit date wins over the weekday token; falls back to the weekday."""
    hl = (h or "").strip().lower()
    if not hl:
        return None
    if hl in _WEEKDAY_INDEX:
        return monday + dt.timedelta(days=_WEEKDAY_INDEX[hl])
    m = re.search(r"(\d{1,2})[-/](\d{1,2})", hl)
    if m:
        try:
            return dt.date(monday.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    tok = re.split(r"[ (]", hl, 1)[0]
    if tok in _WEEKDAY_INDEX:
        return monday + dt.timedelta(days=_WEEKDAY_INDEX[tok])
    return None


def parse_crosstab_byday(
    spec: ScrapeSpec,
    path: Path,
    today: dt.date,
) -> Dict[str, Dict[str, Dict[dt.date, int]]]:
    """Parse a Download → Crosstab export (pivoted: weekday NAMES as columns)
    to {owner_norm: {spec.metric: {date: value}}}.

    Layout (Fiber/Raf's-team example):
      Owner Name | Product Type (Broken Out) | Monday | … | Sunday | Product Total
    Each owner has a 'Total' row (all products) plus per-product rows. We keep
    the `spec.total_label` row per owner (already summed incl. Voice) and map
    each weekday column onto that weekday's date in this week. Columns by
    header label; the grand-total row(s) in `spec.skip_owners` are dropped."""
    rows = sara_pull._read_rows(path)
    if not rows:
        return {}
    # Some crosstabs prepend a date-only chrome row above the real column
    # header (NDS: a row of the week-ending date repeated). The REAL header is
    # the row whose day columns map to the most DISTINCT dates (7 = Mon-Sun);
    # the chrome row repeats one date. Pick by distinct-day count.
    monday = today - dt.timedelta(days=today.weekday())
    def _distinct_days(r):
        return len({d for c in r if (d := _day_for_header(c, monday))})
    scan = min(6, len(rows))
    hdr_idx = max(range(scan), key=lambda i: _distinct_days(rows[i]))
    if _distinct_days(rows[hdr_idx]) == 0:
        hdr_idx = 0
    header = [h.strip() for h in rows[hdr_idx]]
    data_rows = rows[hdr_idx + 1:]
    oi = tableau_http.col_idx(header, spec.owner_col)
    if oi is None:
        raise ValueError(
            f"{spec.section_label}: crosstab missing {spec.owner_col!r}. "
            f"Header: {header}")
    # Day columns → that day's date this week (handles Monday / 5/25 Mon /
    # Mon (05-25)).
    day_cols = {i: d for i, h in enumerate(header)
                if (d := _day_for_header(h, monday))}
    if not day_cols:
        raise ValueError(
            f"{spec.section_label}: no day columns in crosstab header "
            f"{header}")
    # Per-row product-type column (for total-row selection / voice exclusion).
    ti = tableau_http.col_idx(header, spec.product_col)
    skip = {s.lower() for s in spec.skip_owners}
    exclude = {p.upper() for p in spec.exclude_products}
    # The owner cell only appears on the FIRST of an owner's product rows; the
    # rest are blank. Carry it forward so component rows attribute correctly.
    cur_owner = ""

    out: Dict[str, Dict[str, Dict[dt.date, int]]] = {}
    for r in data_rows:
        if len(r) <= oi:
            continue
        owner_raw = r[oi].strip()
        if owner_raw:
            cur_owner = owner_raw
        owner_raw = cur_owner
        if not owner_raw or owner_raw.lower() in skip:
            continue
        prod = r[ti].strip() if (ti is not None and len(r) > ti) else ""
        if exclude:
            # Sum component product rows; skip the pre-summed total + Voice.
            if (spec.total_label and prod == spec.total_label) \
                    or prod.upper() in exclude:
                continue
        elif spec.total_label and ti is not None:
            if prod != spec.total_label:
                continue
        owner = _norm_section_owner(owner_raw, spec.strip_office)
        if not owner:
            continue
        m = out.setdefault(owner, {}).setdefault(spec.metric, {})
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


def pull_section_byday(
    spec: ScrapeSpec,
    out_dir: Path,
    page,
    logfn=print,
    today: Optional[dt.date] = None,
) -> Path:
    """Pull `spec`'s view to a file and return its path (CROSSTAB or VIEWDATA).
    `page` is a live patchright tableau_session() Page."""
    out_dir.mkdir(parents=True, exist_ok=True)
    name = spec.out_name or f"org_sales_board_{spec.metric.lower()}_byday.csv"
    out_path = out_dir / name
    view_url = spec.view_url
    if spec.week_pin:
        # Pin to THIS week's ending Sunday so the view stops serving its saved
        # default week. ISO date — Tableau silently ignores MM/DD/YYYY.
        from urllib.parse import quote
        td = today or dt.date.today()
        we_sunday = td + dt.timedelta(days=6 - td.weekday())   # Mon-anchored
        sep = "&" if "?" in view_url else "?"
        view_url = (f"{view_url}{sep}"
                    f"{quote('Sale Date Week Ending (mon-sun)')}"
                    f"={quote(we_sunday.isoformat())}")
        logfn(f"  [{spec.section_label}] week-pinned to WE {we_sunday.isoformat()}")
    if spec.method == CROSSTAB:
        from automations.shared.tableau_patchright import download_crosstab_patchright
        logfn(f"  downloading {spec.section_label} crosstab "
              f"({spec.crosstab_sheet})…")
        download_crosstab_patchright(
            view_url, spec.crosstab_sheet, out_path, page=page,
            verbose=False)
    else:
        from automations.shared.tableau_patchright import scrape_view_data_patchright
        logfn(f"  scraping {spec.section_label} custom view (Download → Data)…")
        scrape_view_data_patchright(
            view_url, out_path, page=page, verbose=False,
            activate_xy=spec.activate_xy, scrape_kwargs=SPARSE_SCRAPE_KWARGS)
    logfn(f"  saved {out_path}")
    return out_path


def parse_byday(spec: ScrapeSpec, path: Path, today: dt.date):
    """Dispatch to the crosstab or view-data parser for `spec`."""
    if spec.method == CROSSTAB:
        return parse_crosstab_byday(spec, path, today)
    return parse_section_byday(spec, path, today)


# ----------------------------------------------------------- the specs

_BASE = ("https://us-east-1.online.tableau.com/#/site/sci/views/")

# Fiber daily section = Raf's Fiber team, ALL product types EXCEPT Voice
# (Megan 2026-05-31: "DO NOT INCLUDE VOICE SALES"). The narrow
# 'FiberTeamnovoice' view was wrong — it carries only WIRELESS + NEW INTERNET
# (drops AIR + VIDEO too), so Cyrus Sat read 18 instead of 21. The
# AllproductsRafsteam crosstab "Sales By ICD (Weekly View)" breaks every
# product out per owner×weekday; we SUM all of them EXCEPT VOICE (and skip the
# pre-summed 'Total' row, which can include Voice). Cyrus Sat = AIR 0 + NEW
# INTERNET 11 + VIDEO 3 + WIRELESS 7 = 21 ✓. NOTE: couples Fiber to Raf's
# captainship view (= the 9 Fiber ICDs); revisit if those lists diverge.
FIBER_SPEC = ScrapeSpec(
    section_label="ATT Fiber Team", metric="Total",
    view_url=_BASE + ("ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
                      "ab2eca72-395f-48d5-a254-9d99739b88d4/AllproductsRafsteam"),
    owner_col="Owner Name",
    value_col="",  # crosstab: value is per weekday column, not one column
    day_col="",
    method=CROSSTAB,
    crosstab_sheet="Sales By ICD (Weekly View)",
    total_label="Total",            # the pre-summed row to skip
    exclude_products=("VOICE",),    # ALL units except Voice = what the VAs key
    skip_owners=("Sales Total",),
    week_pin=True,                   # view defaults to LAST week — pin to current
    out_name="org_sales_board_fiber_byday.csv",
)

# NDS daily section — WIRELESSONLY view (Megan 2026-05-31: the recipe's
# 'Wirelessthisweek' view was mis-scoped to 4 owners). Crosstab "Sales By ICD
# (Weekly View)": 2-row header (date row above the real column header), owner
# cell carries an embedded newline + "[company]" suffix. Wireless-only, so
# each owner's 'Total' row == its WIRELESS row; keep 'Total' to avoid
# double-counting.
NDS_SPEC = ScrapeSpec(
    section_label="ATT NDS Team", metric="Wireless",
    view_url=_BASE + ("NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/"
                      "d9da84f9-9302-4249-96b5-f4d1df08774f/WIRELESSONLY"),
    owner_col="Owner & Office",
    value_col="",
    day_col="",
    method=CROSSTAB,
    crosstab_sheet="Sales By ICD (Weekly View)",
    total_label="Total",
    skip_owners=("Grand Total",),
    strip_office=True,
    out_name="org_sales_board_nds_byday.csv",
)

B2B_SPEC = ScrapeSpec(
    section_label="B2B", metric="count",
    view_url=_BASE + ("ATTTRACKER-B2B/D2D1-PAGERV3/"
                      "e52b4954-dc0b-4f2a-a588-d218942f23a0/LuissCaptainship"),
    owner_col="ICD Owner Name",
    value_col="Sales (All)",
    day_col="sp.Order Date (copy)",
    day_kind=DATE,
    out_name="org_sales_board_b2b_byday.csv",
)

# BOX daily section — B2BBOXEnergyDailyTracker, "BOX Daily Tracker" worksheet
# (Megan 2026-05-31). Crosstab columns: ICD Name | Column Max | "5/25 Mon" …
# "5/31 Sun". Already the current week (date-labeled headers, parsed directly).
# Each ICD spans two rows split by a 'Column Max' 0/1 flag with complementary
# day values — summing per (owner,date) reconstructs the daily totals, so no
# total/product filtering. ICD Name is clean here (no |company| suffix).
BOX_SPEC = ScrapeSpec(
    section_label="BOX", metric="count",
    view_url=_BASE + "B2BBOXEnergy/B2BBOXEnergyDailyTracker",
    owner_col="ICD Name",
    value_col="",
    day_col="",
    method=CROSSTAB,
    crosstab_sheet="BOX Daily Tracker",
    skip_owners=("Grand Total", "Total"),
    out_name="org_sales_board_box_byday.csv",
)

SPECS = {"fiber": FIBER_SPEC, "nds": NDS_SPEC, "b2b": B2B_SPEC, "box": BOX_SPEC}
