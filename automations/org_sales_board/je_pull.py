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
# A dropdown OPTION that is a week — 'M/D/YYYY' and nothing else. Everything
# that is not this shape ('(All)', '(Multiple values)', 'Null', and every
# option belonging to some OTHER filter card on the dashboard) is never
# clicked: see _drive_week_selection.
_WEEK_TXT = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
# What the combobox reads when the filter is NOT on a single week.
_MULTI_TXT = re.compile(r"^\((All|Multiple values|None)\)$", re.I)
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

    ONLY WEEK-SHAPED OPTIONS ARE EVER CLICKED (2026-08-16). The uncheck pass
    used to walk EVERY checked `div.FIItem` in the viz and untick anything that
    wasn't the target — which is not the same set as "the other weeks". It also
    picks up the dropdown's own '(All)' tri-state row (unticking that re-selects
    the whole list) and the options of any other filter card rendered on the
    dashboard. The loop then fought itself for six passes, gave up SILENTLY, and
    the run died on the final check with box='(Multiple values)'. Retail JE was
    dropped from the board that day (Sunday board-catchup, 14:30). Every click
    below is now gated on `_WEEK_TXT`, so nothing outside this filter's week
    list can be touched.

    Clicks are STATE-AWARE, not blind toggles: `_set(week, want)` reads
    aria-checked and clicks only when the state has to change. A blind toggle
    unticks a target that was already ticked — which is how a run that started
    with several weeks selected could end with the target OFF.

    Convergence is measured against the COMBOBOX, not against our own idea of
    the state, and a run that can't get there raises with the full option dump
    in the message (the old failure said only what the box read, so diagnosing
    it needed a second trip to the mini).

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

    _ROW = 'div.FIItem[role="checkbox"]'

    def _rows(viz):
        """The dropdown's option rows, preferring the VISIBLE ones: Tableau
        keeps hidden copies of menu markup in the DOM, and a click that lands
        on one of those changes nothing while reading as a success. Falls back
        to the unfiltered set so a Playwright without `:visible` still works."""
        try:
            vis = viz.locator(_ROW + ":visible")
            if vis.count():
                return vis
        except Exception:  # noqa: BLE001
            pass
        return viz.locator(_ROW)

    def _item(viz, week):
        """The dropdown row for one week. Weeks are unique, so text is a safe key."""
        return _rows(viz).filter(
            has_text=_re.compile(rf"^{_re.escape(week)}$")).first

    def _weeks(viz):
        """[(week, checked)] for the WEEK-SHAPED options only — '(All)' and
        anything belonging to another filter card are deliberately invisible
        here, so no later step can click them."""
        items = _rows(viz)
        out = []
        try:
            n = items.count()
        except Exception:  # noqa: BLE001 — menu closed under us
            return out
        for j in range(n):
            it = items.nth(j)
            try:
                txt = (it.inner_text() or "").strip()
                if not _WEEK_TXT.match(txt):
                    continue
                out.append((txt, (it.get_attribute("aria-checked") or "") == "true"))
            except Exception:  # noqa: BLE001 — a row re-rendered mid-read
                continue
        return out

    def _set(viz, page, week, want):
        """Tick/untick ONE week — only if it isn't already in that state."""
        item = _item(viz, week)
        try:
            now = (item.get_attribute("aria-checked") or "") == "true"
        except Exception:  # noqa: BLE001
            now = not want          # unreadable → attempt the click
        if now == want:
            return False
        glyph = item.locator(".FICheckRadio").first
        glyph.scroll_into_view_if_needed()
        glyph.click(timeout=10000)   # bounded: 3 retries x 30s default = a 90s
                                     # hang on a glass-intercept regression
        page.wait_for_timeout(900)
        return True

    def _only(page, viz, week):
        """Tableau's per-row 'Only' link — one click selects just this week,
        with none of the untick dance. Revealed on hover and not present in
        every Tableau version, so this is best-effort: False falls through to
        the tick/untick loop, which is checked against the combobox anyway."""
        try:
            item = _item(viz, week)
            item.scroll_into_view_if_needed()
            item.hover(timeout=5000)
            page.wait_for_timeout(400)
            link = item.locator("a, button, span").filter(
                has_text=_re.compile(r"^\s*Only\s*$", _re.I)).first
            if link.count() == 0:
                return False
            link.click(timeout=5000)
            page.wait_for_timeout(1500)
            return True
        except Exception:  # noqa: BLE001 — never let the fast path fail the pull
            return False

    def _box_text(tbox):
        try:
            return (tbox.inner_text() or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    def _find_box(page, viz):
        """The 'Sales Week Ending' combobox + what it currently reads.

        Normally it reads a single week ('8/9/2026'). It can also read
        '(Multiple values)' / '(All)' — the state a re-saved view or an
        interrupted run leaves behind, and the exact state the old code could
        not recover from: it matched a DATE only, so it declared the dropdown
        'not found' and pulled whatever weeks happened to be ticked."""
        boxes = viz.locator('span.tabComboBox[role="combobox"]')
        for _ in range(20):   # poll ~20s for the filter control to hydrate
            dated = multi = None
            try:
                n = boxes.count()
            except Exception:  # noqa: BLE001
                n = 0
            for i in range(n):
                t = _box_text(boxes.nth(i))
                if _WEEK_TXT.match(t) and dated is None:
                    dated = (boxes.nth(i), t)
                elif _MULTI_TXT.match(t) and multi is None:
                    multi = (boxes.nth(i), t)
            if dated is not None:
                return dated
            if multi is not None:
                return multi      # week list is confirmed once we open it
            page.wait_for_timeout(1000)
        return None, None

    def pre_export(page, viz):
        tbox, cur = _find_box(page, viz)
        if tbox is None:
            if verbose:
                print("  [je] ⚠ 'Sales Week Ending' dropdown not found — "
                      "leaving whatever week the view shows")
            return
        if cur == label:
            return   # already on the target week

        tbox.click()               # open the dropdown
        page.wait_for_timeout(1200)
        weeks = _weeks(viz)
        if not weeks:
            # The combobox we opened has no week-shaped options — it belongs to
            # some other filter, so leave the view alone rather than click
            # blindly in it.
            if verbose:
                print(f"  [je] ⚠ the {cur!r} dropdown holds no week options — "
                      "not touching it; leaving the view's own week")
            _close_dropdown(page, viz)
            return
        if label not in [w for w, _ in weeks]:
            # JE hasn't posted this week yet — nothing to select. Close + bail;
            # parse() will report is_current_week=False and the caller skips.
            if verbose:
                print(f"  [je] week {label} not in the dropdown yet "
                      "(JE hasn't posted it) — leaving selection unchanged")
            _close_dropdown(page, viz)
            return

        _only(page, viz, label)    # fast path; the loop below verifies it
        for _ in range(4):
            weeks = _weeks(viz)
            wrong = [w for w, ch in weeks if ch and w != label]
            on = any(w == label and ch for w, ch in weeks)
            if on and not wrong:
                break
            # Tick the target FIRST: Tableau re-selects everything when a
            # categorical filter would be left with nothing selected, so the
            # target has to be on before the others come off.
            if not on:
                _set(viz, page, label, True)
                continue
            for w in wrong:
                _set(viz, page, w, False)

        weeks = _weeks(viz)        # last look while the menu is still open
        _close_dropdown(page, viz)  # collapse (never via the combobox — see above)
        page.wait_for_timeout(2500)
        final = _box_text(tbox)
        if final != label:         # the box lags the clicks on a slow viz
            page.wait_for_timeout(2500)
            final = _box_text(tbox)
        if verbose:
            print(f"  [je] Sales Week Ending set to {final}")
        if final != label:
            # raise so download_crosstab_patchright's retry re-navigates and
            # re-applies the selection on a fresh load. The option dump rides
            # along: a box reading '(Multiple values)' says nothing about WHICH
            # weeks are stuck on, and the menu is gone by the time anyone looks.
            ticked = [w for w, ch in weeks if ch] or ["(none)"]
            raise RuntimeError(
                f"JE week select failed: box={final!r} expected {label!r}; "
                f"ticked weeks: {', '.join(ticked)} "
                f"(of {len(weeks)} week option(s))")

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
