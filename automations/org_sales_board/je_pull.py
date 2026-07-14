"""Just Energy (JE) retail production pull for the Alphalete ORG Sales Board.

Source: the JE 'Weekly Metrics by ICD' Tableau view, worksheet
'Daily Sales by ICD' — per-ICD daily sale counts (the LEFT table on the
dashboard), measure 'Total Sales'. We read each ICD's per-day values + the
weekly Total ("overall production per ICD", per Megan 2026-06-07).

WEEK SELECTION (resolved 2026-06-07): the view's week control can NOT be
driven by a URL param (ISO blanks the sheet, M/D is ignored) and the viz is
canvas (no DOM dropdown). The reliable path is the SAVED CUSTOM VIEW:
  .../WeeklyMetricsbyICD/4d55c69f-.../Thisweek
That custom view filters on the calculated field 'Sales Weekending Selected'
with limit "Top 1 by MAX(...)" — i.e. it auto-selects the MOST RECENT week
ending (confirmed in Tableau's bootstrap). So it AUTO-ROLLS to the current
week on every pull — no weekly re-save needed.

Staleness guard (belt + suspenders, also handles JE's 1-day lag): parse()
returns the week-ending it actually shows + whether that's the current
week. At a week's start, the latest posted week can still be last week
(JE runs a day behind) — when shown week != current week, the caller
(orchestrate) SKIPS the fill and flags rather than writing last week's
numbers into this week. Blank day cells mean "not posted yet" — leave
empty, never write 0.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import tempfile
from pathlib import Path
from typing import Optional

from automations.shared.tableau_patchright import download_crosstab_patchright

# Saved custom view "ThisWeek". WEEK SELECTION IS NOW DRIVEN EXPLICITLY (2026-07-09):
# the view was ASSUMED to auto-roll ("Top 1 by MAX(Sales Weekending Selected)"),
# but a re-save baked in a FIXED 'Sales Week Ending' filter, so it silently stuck
# on a stale week (found 2026-07-09: pinned to 7/5 while the board was on the 7/12
# week → JE section blank all week). Rather than depend on the saved view's pinned
# week, fetch() now drives the 'Sales Week Ending' multi-select dropdown to the
# CURRENT reporting week every run (see _drive_week_selection). The custom view is
# still used only for its stable layout/GUID; its saved week no longer matters.
# When JE has NOT yet posted the current week, the dropdown simply lacks that date
# and the selection is a no-op — parse() then reports is_current_week=False and the
# caller skips (unchanged staleness behaviour).
#
# The view PERIODICALLY corrupts / stops rendering (Download button never appears →
# 120s timeout) and gets rebuilt with a NEW GUID: 4d55c69f → 828a12c2 → 41cac48e
# (last re-saved by Megan 2026-06-30). When it breaks again, re-save + update the
# GUID below. NOTE: this view puts the per-day labels ('6/08 Mon' …) on the row
# ABOVE the 'ICD Office Name' row and repeats the week-ending date ('6/14/2026') on
# it — parse() handles both layouts.
CV_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "JustEnergyRTL-SalesStaffingProductivityWorkbook/WeeklyMetricsbyICD/"
    "41cac48e-7b4d-4b27-b595-8b01b1e80948/ThisWeek?:iid=1"
)
WORKSHEET = "Daily Sales by ICD"

_DAY_RE = re.compile(r"(\d{1,2})/(\d{1,2})\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)")
_WE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")   # week-ending M/D/YYYY
# weekday name -> Python weekday() index (Mon=0 .. Sun=6)
_WD = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

# JE board section metric key (matches sources.py Source(label="Retail JE")).
METRIC = "Closed Won"


def _infer_date(mo: int, da: int, today: dt.date) -> Optional[dt.date]:
    """A m/d (no year) header -> dt.date, inferring the year from `today`
    (handles a Dec/Jan rollover so a late-December week read in January
    doesn't land a year off)."""
    for yr in (today.year, today.year - 1, today.year + 1):
        try:
            d = dt.date(yr, mo, da)
        except ValueError:
            continue
        if abs((d - today).days) <= 200:
            return d
    return None


def _week_label(today: dt.date) -> str:
    """The 'Sales Week Ending' dropdown label for the board's current
    reporting week (M/D/YYYY, no zero-pad — matches Tableau's rendering)."""
    from automations.org_sales_board import week as _wk
    s = _wk.reporting_sunday(today)
    return f"{s.month}/{s.day}/{s.year}"


def _drive_week_selection(label: str, verbose: bool = False):
    """Build a pre_export hook that drives the JE 'Sales Week Ending'
    multi-select dropdown to exactly `label` (the current reporting week).

    The saved custom view's pinned week is unreliable (it silently sticks on
    a stale week), so we set the week ourselves every run. The dropdown is a
    Tableau categorical (multi-value) quick filter: each option is a
    `div.FIItem[role=checkbox]` toggled by clicking its `.FICheckRadio` glyph
    (clicking the label anchor does NOT toggle); filters apply immediately (no
    Apply button). We check the target week, uncheck every other still-checked
    week, then collapse the dropdown so it can't overlay the Download button.

    Idempotent: if the box already shows the target, it's a no-op. If JE
    hasn't posted the target week yet, that date is absent from the list — we
    leave the selection as-is and let parse()'s staleness guard handle it."""
    import re as _re

    def _close_dropdown(page, viz):
        """Collapse the open quick-filter dropdown — WITHOUT clicking the combobox.

        While the menu is open Tableau lays a `div.tab-glass` outside-click catcher
        over the whole viz, so clicking the combobox a second time to collapse it is
        intercepted ("tab-glass intercepts pointer events") and Locator.click burns
        its full 30s actionability timeout, then raises. That turned the benign
        "JE hasn't posted this week yet" bail-out into a hard pull FAILURE — the
        section got marked missing, the fill manifest went INCOMPLETE and the Sales
        Board email was gated off (2026-07-14, first Tuesday of a new week).

        Escape closes the menu without touching the glass; clicking the glass itself
        is the fallback. Best-effort by design: a dropdown left open is cosmetic, but
        a raised timeout kills the whole JE pull."""
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
        except Exception:  # noqa: BLE001
            pass
        try:
            glass = viz.locator("div.tab-glass").first
            if glass.count():
                glass.click(timeout=3000)      # bounded — never the 30s default
                page.wait_for_timeout(400)
        except Exception:  # noqa: BLE001
            pass

    def pre_export(page, viz):
        boxes = viz.locator('span.tabComboBox[role="combobox"]')
        tbox = cur = None
        for _ in range(20):   # poll ~20s for the filter control to hydrate
            for i in range(boxes.count()):
                t = (boxes.nth(i).inner_text() or "").strip()
                if _re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", t):
                    tbox, cur = boxes.nth(i), t
                    break
            if tbox is not None:
                break
            page.wait_for_timeout(1000)
        if tbox is None:
            if verbose:
                print("  [je] ⚠ 'Sales Week Ending' dropdown not found — "
                      "leaving whatever week the view shows")
            return
        if cur == label:
            return   # already on the target week

        def _toggle(week):
            item = viz.locator('div.FIItem[role="checkbox"]').filter(
                has_text=_re.compile(rf"^{_re.escape(week)}$")).first
            glyph = item.locator(".FICheckRadio").first
            glyph.scroll_into_view_if_needed()
            glyph.click(timeout=10000)   # bounded: 3 retries x 30s default = a 90s
                                         # hang on a glass-intercept regression

        def _checked():
            c = viz.locator('div.FIItem[role="checkbox"][aria-checked="true"]')
            return [(c.nth(j).inner_text() or "").strip() for j in range(c.count())]

        tbox.click()               # open the dropdown
        page.wait_for_timeout(1200)
        if viz.locator('div.FIItem[role="checkbox"]').filter(
                has_text=_re.compile(rf"^{_re.escape(label)}$")).count() == 0:
            # JE hasn't posted this week yet — nothing to select. Close + bail;
            # parse() will report is_current_week=False and the caller skips.
            if verbose:
                print(f"  [je] week {label} not in the dropdown yet "
                      "(JE hasn't posted it) — leaving selection unchanged")
            _close_dropdown(page, viz)
            return
        _toggle(label)             # check the target week
        page.wait_for_timeout(1200)
        for _ in range(6):         # uncheck every other still-checked week
            others = [o for o in _checked() if o and o != label]
            if not others:
                break
            for o in others:
                _toggle(o)
                page.wait_for_timeout(800)
        _close_dropdown(page, viz)  # collapse (never via the combobox — see above)
        page.wait_for_timeout(2500)
        final = (tbox.inner_text() or "").strip()
        if verbose:
            print(f"  [je] Sales Week Ending set to {final}")
        if final != label:
            # raise so download_crosstab_patchright's retry re-navigates and
            # re-applies the selection on a fresh load
            raise RuntimeError(
                f"JE week select failed: box={final!r} expected {label!r}")

    return pre_export


def fetch(out_path: Optional[Path] = None, verbose: bool = False, page=None,
          today: Optional[dt.date] = None) -> Path:
    """Download the JE 'Daily Sales by ICD' crosstab, driving the
    'Sales Week Ending' filter to the current reporting week (the saved
    view's pinned week is unreliable — see module docstring)."""
    out_path = out_path or Path(tempfile.gettempdir()) / "je_daily_sales.csv"
    label = _week_label(today or dt.date.today())
    download_crosstab_patchright(CV_URL, WORKSHEET, out_path, verbose=verbose,
                                 page=page,
                                 pre_export=_drive_week_selection(label, verbose))
    return out_path


def _read_rows(csv_path: Path) -> list[list[str]]:
    for enc in ("utf-16-le", "utf-8-sig", "utf-8"):
        try:
            rows = list(csv.reader(open(csv_path, encoding=enc), delimiter="\t"))
            if rows and len(rows[0]) > 1:
                return rows
        except Exception:
            continue
    return []


def parse(csv_path: Path, today: Optional[dt.date] = None) -> dict:
    """Parse the JE crosstab.

    Returns:
      {
        "week_ending": date | None,   # the Sunday the view shows
        "is_current_week": bool,      # week_ending == this week's Sunday
        "reps": { "<office> | <name>": {
                    "office": str, "name": str,
                    "days": {weekday_idx: int},   # only days with data
                    "total": int | None } },
        "office_total": {"days": {...}, "total": int|None},
      }
    Blank day cells are omitted (not 0) — JE posts a day behind.
    """
    rows = _read_rows(csv_path)
    if not rows:
        return {"week_ending": None, "is_current_week": False,
                "reps": {}, "office_total": {}}

    # Find the header row (has 'ICD Office Name'). The per-day labels
    # ('6/08 Mon' …) may sit ON this row OR on a row just above it — the
    # 'ThisWeek' view puts them one row up and repeats the week-ending date
    # ('6/14/2026') on the 'ICD Office Name' row.
    hdr_i = next((i for i, r in enumerate(rows)
                  if any(c.strip() == "ICD Office Name" for c in r)), None)
    if hdr_i is None:
        return {"week_ending": None, "is_current_week": False,
                "reps": {}, "office_total": {}}
    header = [c.strip() for c in rows[hdr_i]]
    office_i = header.index("ICD Office Name")
    name_i = header.index("ICD Name") if "ICD Name" in header else office_i + 1
    total_i = header.index("Total") if "Total" in header else None

    today = today or dt.date.today()
    # Day columns: take each column's 'm/d Mon' label from the header row OR
    # the rows just above it (whichever carries it).
    col_date: dict[int, dt.date] = {}   # column index -> actual date
    sun_date: Optional[dt.date] = None
    hdr_rows = [r for r in (hdr_i, hdr_i - 1, hdr_i - 2) if 0 <= r < len(rows)]
    ncols = max((len(rows[r]) for r in hdr_rows), default=0)
    for ci in range(ncols):
        for hr in hdr_rows:
            if ci >= len(rows[hr]):
                continue
            m = _DAY_RE.search((rows[hr][ci] or "").strip())
            if m:
                d = _infer_date(int(m.group(1)), int(m.group(2)), today)
                if d is not None:
                    col_date[ci] = d
                    if m.group(3) == "Sun":
                        sun_date = d
                break

    # Week-ending: prefer an explicit M/D/YYYY on the header row (the view
    # repeats the week-ending Sunday across the day columns, e.g. '6/14/2026');
    # else the Sunday column's date; else latest day rolled forward to Sunday.
    week_ending: Optional[dt.date] = None
    for cell in header:
        m = _WE_RE.search(cell)
        if m:
            try:
                week_ending = dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            except ValueError:
                week_ending = None
            if week_ending:
                break
    if week_ending is None:
        week_ending = sun_date
    if week_ending is None and col_date:
        latest = max(col_date.values())
        week_ending = latest + dt.timedelta(days=(6 - latest.weekday()))
    # The board's active reporting week-ending Sunday (rolls Tuesday — on
    # Monday this is last week's Sunday, so JE fills the just-finished week).
    from automations.org_sales_board import week as _wk
    cur_sunday = _wk.reporting_sunday(today)
    is_current = (week_ending == cur_sunday)

    def _num(s: str):
        s = (s or "").strip().replace(",", "")
        if not s:
            return None
        try:
            return int(float(s))
        except ValueError:
            return None

    reps: dict = {}
    office_total: dict = {"days": {}, "total": None}
    for r in rows[hdr_i + 1:]:
        if len(r) <= office_i:
            continue
        office = r[office_i].strip()
        name = r[name_i].strip() if name_i < len(r) else ""
        if not office and not name:
            continue
        is_grand = office == "Grand Total" or name == "Total"
        days = {}
        for ci, d in col_date.items():
            if ci < len(r):
                v = _num(r[ci])
                if v is not None:
                    days[d] = v
        total = _num(r[total_i]) if (total_i is not None and total_i < len(r)) else None
        if is_grand:
            office_total = {"days": days, "total": total}
        else:
            reps[f"{office} | {name}"] = {
                "office": office, "name": name, "days": days, "total": total,
            }

    return {
        "week_ending": week_ending,
        "is_current_week": is_current,
        "reps": reps,
        "office_total": office_total,
    }


def to_board_pull(parsed: dict, metric: str = METRIC) -> dict:
    """Convert parse() output to the board adapter shape the section-fill
    engine consumes: {owner_norm: {metric: {date: value}}}. Keyed by the
    ICD owner NAME (the JE 'ICD Name'), normalized the same way the board
    matches its rows."""
    from automations.alphalete_org_report.tableau_http import _norm_owner
    out: dict = {}
    for rec in parsed.get("reps", {}).values():
        name = rec.get("name") or ""
        days = rec.get("days") or {}
        if not name or not days:
            continue
        out.setdefault(_norm_owner(name), {})[metric] = dict(days)
    return out
