"""The live ICD sales board site.

Two views off one pipeline:
  • Org     — every office, for Megan / Eve / Raf
  • Office  — one owner's board and their recruiting funnel

ONE ROW PER PERSON. Production and who they are live in the same row — there is
no separate roster section, because listing a rep twice is how two versions of
the truth start (Megan 2026-08-17). Raf's board already carries Team, Leadership
Status, Field Status, Start Date and a per-day Roll Call out at columns 80-100,
so those are read from the board rather than stored again anywhere else.

1st DAY OF SALES is DERIVED, never typed: due_diligence.first_sale keeps a map
built from the full Tableau order history and refreshed by the 3am harvest. Any
logged sale counts, cancelled or not, since it still marks the day they first
sold. Reps at the edge of Tableau's retention window render "<date> or earlier"
— we must not assert a day we cannot see.

Run:
  OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES .venv/bin/streamlit run \
    automations/icd_sales_board/site.py --server.fileWatcherType=none
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Streamlit puts the SCRIPT's directory on sys.path, not the working directory,
# so `automations…` is unimportable without this. Resolved from __file__ so it
# works on the mini and on Windows too — no hardcoded venv or absolute path.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from automations.icd_sales_board import campaigns as C  # noqa: E402
from automations.icd_sales_board import funnel as F  # noqa: E402
from automations.icd_sales_board import profiles as P  # noqa: E402
from automations.icd_sales_board import roster as R  # noqa: E402
from automations.icd_sales_board import board_read as B  # noqa: E402
from automations.icd_sales_board import attendance as A  # noqa: E402
from automations.icd_sales_board import goals as G  # noqa: E402

# Raf's board — the template, and the only office with real data wired so far.
RAF_SHEET = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"
RAF_ICD = "Rafael Hidalgo"

# An office's brand, which is not its owner's name. Only Raf's is known today;
# office_metrics.Office already carries a `business_name` field for onboarded
# offices, so this map is the stopgap until every ICD has one there.
BUSINESS_NAMES = {"Rafael Hidalgo": "Alphalete Marketing"}

st.set_page_config(page_title="Sales Boards", page_icon="📊", layout="wide")


# --------------------------------------------------------------- data access
@st.cache_data(ttl=300, show_spinner=False)
def load_profiles() -> dict:
    return {n: p for n, p in P.load().items()}


@st.cache_data(ttl=300, show_spinner="Reading the board…")
def load_raf_board(tab: str = "") -> dict:
    """Read Raf's board read-only. Cached so edits don't re-pull every rerun."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(RAF_SHEET)
    tabs = B.week_tabs([w.title for w in sh.worksheets()])
    if not tabs:
        return {}
    use = tab if tab in tabs else tabs[0]
    wk = B.parse_week(sh.worksheet(use).get_all_values(), use)
    return {"tabs": tabs, "week": wk}


def _num(s) -> float:
    try:
        return float(str(s).replace(",", "").replace("%", "").strip() or 0)
    except ValueError:
        return 0.0


# ------------------------------------------------------------------ fragments
# Marks that mean the rep was never in the field, so they belong in neither the
# numerator nor the denominator. Same exclusions the board's own COUNTIFS uses.
_NOT_NUMERIC = {"X", "T", "CR", "RT", "STF", "L"}


def _day_date(week, day: str):
    """The calendar date of one day column, or None."""
    start = _week_start(week.week_label)
    if not start or day not in week.day_names:
        return None
    return start + dt.timedelta(days=week.day_names.index(day))


ALL_TEAMS = "All teams"


def rep_team(r: dict, overrides: dict) -> str:
    """A rep's team — the owner's saved value if they set one, else the board's."""
    ov = overrides.get((r.get("name") or "").strip().lower())
    if ov and ov.team:
        return ov.team
    return (r.get("attrs", {}).get("team") or "").strip()


def _calc_vitals(week, scope: str, overrides: dict, team: str = "",
                 campaign: str = "") -> dict:
    """The four numbers for a period, for any slice of the board.

    Mirrors the board's own summary formulas rather than inventing a rule:
    skip rows whose value is a marker (X/T/RT/…), skip first-week reps and
    roadtrips, then count above-zero against the rest. The per-campaign split
    matches the board's `COUNTIFS(CH…,"Fiber*")` — a prefix match, because the
    column holds values like 'Fiber' and 'Fiber/Energy'."""
    in_field = on_board = zero = 0
    for r in week.reps:
        attrs = r.get("attrs", {})
        tenure = (attrs.get("field status") or "").strip().lower()
        if tenure in {"1st week", "rt", "roadtrip"}:
            continue
        if campaign:
            rep_camp = (attrs.get("campaign") or "").strip().lower()
            if not rep_camp.startswith(campaign.strip().lower()):
                continue
        if team and team != ALL_TEAMS and rep_team(r, overrides) != team:
            continue

        if scope == "Week":
            cell = (r.get("values", {}).get("Total Apps", "") or "").strip()
        else:
            cell = ((r.get("daily") or {}).get(scope, {})
                    .get("values", {}).get("Apps", "") or "").strip()
        if not cell or cell.upper() in _NOT_NUMERIC:
            continue
        try:
            v = float(cell.replace(",", ""))
        except ValueError:
            continue
        in_field += 1
        if v > 0:
            on_board += 1
        else:
            zero += 1
    pct = f"{round(100 * on_board / in_field)}%" if in_field else "—"
    return {"in_field": in_field, "on_board": on_board, "zero": zero,
            "pct": pct}


@st.cache_data(ttl=900, show_spinner=False)
def prev_week_board(tabs: tuple, current_tab: str):
    """Last week's whole board, for like-for-like comparisons."""
    order = list(tabs)
    try:
        nxt = order.index(current_tab) + 1
    except ValueError:
        return None
    if nxt >= len(order):
        return None
    try:
        from automations.recruiting_report.fill import open_by_key
        sh = open_by_key(RAF_SHEET)
        tab = order[nxt]
        return B.parse_week(sh.worksheet(tab).get_all_values(), tab)
    except Exception:
        return None


def _summary_vitals(wk) -> dict:
    """The four numbers as the board's OWN summary block states them."""
    allsum = (wk.summary.get("ALL") or {}) if wk else {}

    def pick(*keys):
        for k in allsum:
            if any(t in k.lower() for t in keys):
                return _num(allsum[k])
        return None

    return {"in_field": pick("total reps"), "on_board": pick("got on the board"),
            "zero": pick("rolled a zero"), "pct": pick("% of reps")}


def _delta(now, before):
    """A numeric delta, or None when either side is unknown.

    None means 'no pill' — better than a 0 that implies we compared and found
    no change."""
    if now is None or before is None:
        return None
    try:
        return round(float(now) - float(before), 1)
    except (TypeError, ValueError):
        return None


def vitals_row(week, reps, scope: str = "Week", overrides: dict | None = None,
               team: str = ALL_TEAMS, tabs=()) -> None:
    """The four numbers on top. Stupid simple: four numbers, one glance.

    They follow the day selector AND the team filter — pick Wednesday and
    Ceaseless and these describe Ceaseless on Wednesday. A day that hasn't
    happened yet shows nothing at all, because a future day full of zeros reads
    as 'everybody blanked' when nobody has gone out."""
    overrides = overrides or {}
    filtered = team and team != ALL_TEAMS
    day_view = week is not None and scope != "Week"
    note = (f"{scope if day_view else 'Week to date'}"
            + (f" · {team}" if filtered else ""))

    if day_view:
        d = _day_date(week, scope)
        if d and d > dt.date.today():
            # not %-d — that is Mac-only and dies on Windows
            st.info(f"{scope} hasn't happened yet — {d.strftime('%b')} "
                    f"{d.day}.", icon="🗓️")
            c1, c2, c3, c4 = st.columns(4)
            for col, label in zip(
                    (c1, c2, c3, c4),
                    ("Reps in the field", "Got on the board",
                     "% of reps selling", "Rolled a zero")):
                col.metric(label, "—")
            return

    # The board's own summary block is authoritative, but it only describes the
    # WHOLE office for the WHOLE week — so any narrower slice has to be counted
    # here, by the same rule the sheet uses.
    prev = prev_week_board(tuple(tabs), week.tab) if week is not None else None

    if week is not None and (day_view or filtered):
        v = _calc_vitals(week, scope, overrides, team=team)
        # Compare against the SAME slice last week — same day, same team — so
        # the pill answers "better or worse than last week?" and not "different
        # from some other cut of the data".
        pv = (_calc_vitals(prev, scope, overrides, team=team) if prev
              else {})
        pct_now = _num(v["pct"]) if v["pct"] != "—" else None
        pct_prev = _num(pv.get("pct")) if pv.get("pct", "—") != "—" else None
        _render_vitals(v["in_field"], v["on_board"], v["pct"], v["zero"],
                       _delta(v["in_field"], pv.get("in_field")),
                       _delta(v["on_board"], pv.get("on_board")),
                       _delta(pct_now, pct_prev),
                       _delta(v["zero"], pv.get("zero")), note)
        return

    all_sum = (week.summary.get("ALL") or {}) if week else {}
    in_field = [r for r in reps if r.in_field] if reps else []

    def pick(*keys):
        for k in all_sum:
            if any(t in k.lower() for t in keys):
                return all_sum[k]
        return None

    total = pick("total reps") or (len(in_field) if in_field else "—")
    on_board = pick("got on the board") or "—"
    pct = pick("% of reps") or "—"
    zero = pick("rolled a zero") or "—"

    # Both sides come from each week's OWN summary block, so the headline keeps
    # matching the sheet exactly and the comparison stays like-for-like.
    p = _summary_vitals(prev) if prev else {}
    n = _summary_vitals(week) if week else {}
    _render_vitals(total, on_board, pct, zero,
                   _delta(n.get("in_field"), p.get("in_field")),
                   _delta(n.get("on_board"), p.get("on_board")),
                   _delta(n.get("pct"), p.get("pct")),
                   _delta(n.get("zero"), p.get("zero")), "Week to date")


def _render_vitals(in_field, on_board, pct, zero,
                   d_field, d_board, d_pct, d_zero, note) -> None:
    """The four metrics with last-week pills.

    'Rolled a zero' is INVERTED: fewer zeros is the good direction, so a drop
    has to read green. Colouring it like the others would paint the best week
    of the month red."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reps in the field", in_field, delta=d_field, help=note)
    c2.metric("Got on the board", on_board, delta=d_board, help=note)
    c3.metric("% of reps selling", pct,
              delta=(f"{d_pct:+.0f}%" if d_pct is not None else None),
              help=note)
    c4.metric("Rolled a zero", zero, delta=d_zero, delta_color="inverse",
              help=note)


@st.cache_data(ttl=900, show_spinner=False)
def prev_week_teams(tabs: tuple, current_tab: str) -> dict:
    """The Teams block from the week BEFORE current_tab.

    Used for last week's averages, because each tab computes its own
    current-week average against its own headcount — which is the number the
    board's LW columns get wrong."""
    order = list(tabs)
    try:
        nxt = order.index(current_tab) + 1
    except ValueError:
        return {}
    if nxt >= len(order):
        return {}
    try:
        from automations.recruiting_report.fill import open_by_key
        sh = open_by_key(RAF_SHEET)
        return B.parse_teams(sh.worksheet(order[nxt]).get_all_values())
    except Exception:
        return {}


def production_panel(week, scope: str, overrides: dict, team: str,
                     office_key: str, tabs=()) -> None:
    """What the selection has actually PUT UP, plus the team averages.

    The four vitals above say how many people sold; this says how much. Both
    follow the team filter, so picking Ceaseless gives Ceaseless's units and
    Ceaseless's averages against Ceaseless's goal."""
    filtered = bool(team) and team != ALL_TEAMS
    day_view = scope != "Week"
    if day_view:
        d = _day_date(week, scope)
        if d and d > dt.date.today():
            return

    # Sum the selection's own rows rather than reading the sheet's TOTALS row,
    # which only ever describes the whole office.
    measure_keys = ["Total Apps", "INT", "NL", "EN"] if not day_view else \
                   ["Apps", "Int", "NL", "EN"]
    sums = {k: 0.0 for k in measure_keys}
    for r in week.reps:
        if filtered and rep_team(r, overrides) != team:
            continue
        src = (r.get("values", {}) if not day_view
               else (r.get("daily") or {}).get(scope, {}).get("values", {}))
        for k in measure_keys:
            try:
                sums[k] += float(str(src.get(k, "") or "").replace(",", ""))
            except ValueError:
                pass

    # Compare with last week AT THE SAME POINT. A part-week against a whole
    # week is not a comparison — three days in, it would show a collapse every
    # single time. So sum last week over the SAME days that have happened this
    # week (or the same weekday, on a day view).
    prev_board = prev_week_board(tuple(tabs), week.tab)
    today = dt.date.today()
    if day_view:
        day_set = [scope]
    else:
        day_set = [d for d in week.day_names
                   if (_day_date(week, d) or today) <= today]
    # week totals are headed 'Total Apps'/'INT'; the day blocks use 'Apps'/'Int'
    daily_key = {"Total Apps": "Apps", "Apps": "Apps", "INT": "Int",
                 "Int": "Int", "NL": "NL", "EN": "EN"}
    prev_sums = {}
    if prev_board and day_set:
        for k in measure_keys:
            tot = 0.0
            for r in prev_board.reps:
                if filtered and rep_team(r, overrides) != team:
                    continue
                for d in day_set:
                    cell = ((r.get("daily") or {}).get(d, {})
                            .get("values", {}).get(daily_key.get(k, k), ""))
                    try:
                        tot += float(str(cell or "").replace(",", ""))
                    except ValueError:
                        pass
            prev_sums[k] = tot

    label = scope if day_view else "week to date"
    st.markdown(f"**Production · {label}"
                + (f" · {team}" if filtered else "") + "**")
    cols = st.columns(len(measure_keys))
    for col, k in zip(cols, measure_keys):
        shown = f"{sums[k]:.0f}" if sums[k] == int(sums[k]) else f"{sums[k]:.2f}"
        d = _delta(sums[k], prev_sums.get(k))
        # Name last week's number IN the pill. "-46 vs LW" reads as though we
        # did 46 last week; "-46 (LW 51)" cannot be misread.
        pill = (f"{d:+.0f} (LW {prev_sums.get(k, 0):.0f})"
                if d is not None else None)
        col.metric("Total Units" if k in ("Total Apps", "Apps") else k, shown,
                   delta=pill,
                   help=(f"Last week over the same "
                         f"{len(day_set)} day{'s' if len(day_set) != 1 else ''}"
                         f": {prev_sums.get(k, 0):.0f}")
                   if prev_sums else None)

    # Averages get their own row: side by side with the sums, "Total Units" and
    # "Total units avg" sat next to each other reading almost the same, and the
    # cramped column truncated the label to "Total units …".
    cols = st.columns(len(measure_keys))

    # Averages come from the board's own Teams block — its numbers, not a
    # recomputation that could quietly disagree with the sheet.
    who_row = team if filtered else B.TEAM_TOTALS_KEY
    row = (week.teams or {}).get(who_row, {})
    goal = row.get("goal", "")

    # Last week's averages come from LAST WEEK'S TAB, not this one. The board's
    # own LW columns are `=$K157/CI157` — last week's units over THIS week's
    # Active Reps — so early in a week they divide a full week's production by a
    # handful of reps and read absurdly high (144 new int / 5 reps = 28.80).
    # Each tab computes its own current-week average correctly, so we read that.
    prev = prev_week_teams(tuple(tabs), week.tab).get(who_row, {})

    def avg_metric(col, label, now_key, lw_key):
        """The average, with a REAL delta against last week.

        The delta must be a NUMBER: given a string, Streamlit can't tell which
        way it went and draws an up arrow regardless — which had this pointing
        up while the average had fallen."""
        now_txt = row.get(now_key, "")
        lw_txt = prev.get(now_key) or row.get(lw_key, "")
        try:
            delta = round(float(str(now_txt).replace(",", ""))
                          - float(str(lw_txt).replace(",", "")), 2)
        except ValueError:
            delta = None
        col.metric(label, now_txt or "—", delta=delta,
                   help=f"Last week {lw_txt}" if lw_txt else None)

    avg_metric(cols[0], "Average total units", "units_avg", "lw_units_avg")
    avg_metric(cols[1], "Average new int", "new_int_avg", "lw_new_int_avg")
    # The goal is the owner's to set, so it's an input, not a caption. Blank
    # clears the override and the board's own number shows again.
    who = team if filtered else "OFFICE"
    saved = G.get(office_key, who, goal)
    gc, pc = st.columns([1, 3])
    with gc:
        new_goal = st.text_input(
            "Weekly goal", value=saved, key=f"goal_{office_key}_{who}",
            help="Yours to change — blank uses the board's own goal. "
                 "Saved by the Save changes button below.")
    # Staged, not written on keystroke: one Save button for everything on the
    # page is less surprising than a goal that saves itself while the table
    # below still needs saving.
    st.session_state["pending_goal"] = (office_key, who, new_goal)
    st.session_state["goal_dirty"] = new_goal.strip() != str(saved).strip()

    done = sums[measure_keys[0]]
    try:
        target = float(str(new_goal or saved).replace(",", ""))
    except ValueError:
        target = 0.0
    with pc:
        if target <= 0:
            st.caption("No goal set for this selection.")
            return
        st.progress(min(1.0, done / target),
                    text=f"{done:.0f} of {target:.0f} ({done / target:.0%})")

        # PACE. A goal on its own doesn't say whether you're winning — half the
        # goal is great on Tuesday and dire on Saturday. So compare against
        # where the week should be by now, and say what the rest of it has to
        # look like.
        today = dt.date.today()
        dates = [_day_date(week, d) for d in week.day_names]
        dates = [d for d in dates if d]
        if not dates:
            return
        elapsed = sum(1 for d in dates if d < today)
        remaining = sum(1 for d in dates if d >= today)
        if elapsed == 0:
            st.caption(f"Week hasn't started. {target / max(1, len(dates)):.1f}"
                       f" a day hits {target:.0f}.")
            return

        expected = target * elapsed / len(dates)
        gap = done - expected
        if gap >= 0:
            st.success(f"On pace — {gap:+.0f} vs the {expected:.0f} you'd "
                       f"expect after {elapsed} of {len(dates)} days.",
                       icon="✅")
        else:
            st.warning(f"Behind pace — {gap:+.0f} vs the {expected:.0f} you'd "
                       f"expect after {elapsed} of {len(dates)} days.",
                       icon="⚠️")

        left = target - done
        if left <= 0:
            st.caption("Goal already met.")
        elif remaining > 0:
            st.caption(f"Needs {left / remaining:.1f} a day over the "
                       f"{remaining} day{'s' if remaining != 1 else ''} left "
                       f"({left:.0f} to go).")
        else:
            st.caption(f"Week is over — finished {left:.0f} short.")


@st.cache_data(ttl=900, show_spinner=False)
def first_sale_map() -> dict:
    """Each rep's 1st day of sales, from the map the 3am harvest maintains.

    Derived from the full Tableau order history rather than typed by anyone —
    any logged sale counts, cancelled or not, because it still marks the day
    they first sold. Reps at the edge of Tableau's retention window come back
    as '<date> or earlier'; we must not assert a day we cannot see."""
    try:
        from automations.due_diligence import first_sale as FS
        return {"map": FS.load_map(), "render": FS.start_date_for,
                "norm": FS._norm}
    except Exception:
        return {}


# Rough px per character at the table's font. Streamlit's default (width=None)
# squeezes columns once a table is wide enough to scroll, which truncates names.
_PX_PER_CHAR = 8
_MIN_W, _MAX_W = 60, 210


def _fit_len(col: str, rows: list) -> int:
    """How many characters a column really needs.

    Sizing to the LONGEST value makes one outlier — a single 28-character name
    — pad every other row with dead space. Size to the 90th percentile instead
    and let the rare long value wrap or clip; the column then matches the data
    people actually read."""
    lens = sorted(len(str(r.get(col, "") or "")) for r in rows)
    if not lens:
        return len(col)
    p90 = lens[min(len(lens) - 1, int(len(lens) * 0.9))]
    return max(len(str(col)), p90)


ROW_PX = 35          # one grid row
HEADER_PX = 40
TOTALS_LABEL = "TOTALS"


def _grid_height(n_rows: int) -> int:
    """Tall enough to show every rep, so the page scrolls instead of the grid.

    A grid with its own scrollbar hides how many people are below the fold and
    makes you scroll twice to read one board (Megan 2026-08-17)."""
    return HEADER_PX + ROW_PX * max(1, n_rows) + 4


def _totals_row(rows: list) -> list:
    """One totals row, summing every column that holds numbers.

    Replaces a run-on caption: totals belong under the column they total, where
    you read them against the rows, not in a sentence you have to parse."""
    out = {}
    for col in rows[0]:
        nums = []
        for r in rows:
            raw = str(r.get(col, "") or "").replace(",", "").strip()
            if not raw:
                continue
            try:
                nums.append(float(raw))
            except ValueError:
                nums = []
                break                     # a text column — nothing to total
        if nums:
            total = sum(nums)
            # keep the column's own look: 0.00 stays 0.00, 3 stays 3
            decimals = any("." in str(r.get(col, "")) for r in rows)
            out[col] = f"{total:.2f}" if decimals else f"{int(total)}"
        else:
            out[col] = ""
    out[list(rows[0])[0]] = TOTALS_LABEL
    return [out]


def _sort_rows(rows: list, col: str) -> list:
    """Sort the board by one column.

    Numbers descending — the board exists to show who is producing, so the top
    of the list should be the top of the board ([[feedback_scoring_log_sort_desc]]).
    Text sorts A-Z instead, since 'highest' means nothing for a team name.
    Non-numeric cells in a number column (X, T, blank) sink to the bottom rather
    than sorting as zero: not working is not the same as selling nothing."""
    def numeric(v):
        try:
            return float(str(v).replace(",", "").replace("%", "").strip())
        except (ValueError, AttributeError):
            return None

    vals = [numeric(r.get(col)) for r in rows]
    is_num = any(v is not None for v in vals)
    if is_num:
        return sorted(
            rows,
            key=lambda r: (numeric(r.get(col)) is None,
                           -(numeric(r.get(col)) or 0.0),
                           str(r.get("Rep", "")).lower()))
    return sorted(rows, key=lambda r: (str(r.get(col, "") or "").lower() == "",
                                       str(r.get(col, "") or "").lower()))


def _autofit(rows: list, base: dict | None = None) -> dict:
    """Size every column to its content, measured from the real data each run."""
    cfg = dict(base or {})
    for col in rows[0]:
        px = min(_MAX_W, max(_MIN_W, _fit_len(col, rows) * _PX_PER_CHAR + 22))
        existing = cfg.get(col)
        kwargs = {"width": px}
        if col == "Rep":
            # keep names on screen while scrolling the production columns
            kwargs["pinned"] = True
        if existing is None:
            cfg[col] = st.column_config.Column(**kwargs)
        else:
            # column_config entries are plain dicts, not objects — assigning
            # attributes on them raises. Update the keys so a configured
            # column keeps its type (e.g. the Roll Call dropdown).
            existing["width"] = px
            if col == "Rep":
                existing["pinned"] = True
            cfg[col] = existing
    return cfg


def _style_totals(df):
    """Tint the last row so TOTALS reads as a rule under the board.

    Streamlit applies Styler output to NON-EDITABLE columns only, so the
    numbers pick the tint up and the three dropdown columns (Team, Leadership,
    Roll Call) stay plain — those are empty on the totals line anyway. Colour is
    semi-transparent so it works on a light or dark theme instead of assuming
    one."""
    last = len(df) - 1

    def row_style(row):
        if row.name != last:
            return [""] * len(row)
        return ["background-color: rgba(255, 193, 7, 0.28); "
                "font-weight: 700"] * len(row)

    return df.style.apply(row_style, axis=1)


def sales_board(week, office_key: str, scope: str = "Week",
                team: str = ALL_TEAMS) -> None:
    """ONE row per person — production and who they are, together.

    Deliberately not a separate 'roster' section: the same rep listed twice is
    how two versions of the truth start (Megan 2026-08-17)."""
    st.subheader(f"Sales board · {week.week_label}"
                 + ("" if scope == "Week" else f" · {scope}"))

    day_view = scope != "Week"
    saved = A.get(office_key, week.tab, scope) if day_view else {}
    overrides = {r.name.strip().lower(): r for r in R.load(office_key)}

    # 1st Day of Sales is collapsed by default (Megan 2026-08-17) — Tenure
    # already answers "how new are they" at a glance, and the exact date is a
    # look-it-up-when-you-need-it fact. Kept behind a toggle rather than
    # deleted: it's derived, so showing it costs nothing but a lookup, which is
    # skipped entirely while hidden.
    show_first = st.toggle("Show 1st day of sales", value=False,
                           key=f"show_first_{office_key}")
    fs = first_sale_map() if show_first else {}

    rows = []
    for r in week.reps:
        a = r.get("attrs", {})
        name = r["name"]

        # PRODUCTION FIRST, rep info after — the order Raf's board already uses
        # (numbers in columns D-J, rep attributes way out at column 80+). The
        # board is read to see who sold, so the numbers sit next to the name;
        # tenure/team/level are context you glance at second.
        row = {
            # Just the name. The board writes tenure into the name cell
            # ("(Wk 2)", "(NC)"), but Tenure is its own column now, so showing
            # it twice is noise — and the clean name is what matches Tableau.
            # The tags are still parsed and available on the rep record.
            "Rep": name,
        }
        if not day_view:
            prod = dict(r["values"])
            roll = None
        else:
            d = (r.get("daily") or {}).get(scope, {})
            prod = dict(d.get("values", {}))
            # An owner's saved mark wins over the board's.
            roll = saved.get(name, d.get("roll_call", ""))

        # Last week's apps sits IMMEDIATELY right of this period's apps, so the
        # comparison is side by side: 0 reads very differently for someone who
        # did 16 last week than for someone who did 0. Anywhere else in the row
        # and you have to hunt for it.
        last_apps = (r.get("last_values") or {}).get("APPS", "")
        for i, (k, v) in enumerate(prod.items()):
            row[k] = v
            if i == 0 and last_apps != "":
                row["Last Wk"] = last_apps
        if roll is not None:
            # Roll Call closes the day block, same as the board.
            row["Roll Call"] = roll

        # Team and Leadership are the owner's to set, so a saved override wins
        # over whatever the board currently says.
        ov = overrides.get(name.strip().lower())
        row["Tenure"] = a.get("field status", "")
        row["Team"] = (ov.team if ov and ov.team else a.get("team", ""))
        row["Leadership"] = (ov.level if ov and ov.level
                             else a.get("leadership status", ""))
        if show_first:
            first_day = fs["render"](fs["norm"](name), fs["map"]) if fs else ""
            row["1st Day of Sales"] = first_day or a.get("start date", "")
        rows.append(row)

    if team and team != ALL_TEAMS:
        rows = [r for r in rows if (r.get("Team") or "").strip() == team]

    if not rows:
        st.info(f"No reps on {team}." if team and team != ALL_TEAMS
                else "No rep rows on this week's tab yet.")
        return

    # Sorting is the table's own — click a column header for the up/down arrow,
    # the way a spreadsheet does it. Both st.dataframe and st.data_editor keep
    # header sorting as long as num_rows is "fixed" (it is), so a separate
    # "Sort by" control would just be a second way to do the same thing.
    # This only sets the DEFAULT order: apps, highest first, since that is the
    # question the board exists to answer ([[feedback_scoring_log_sort_desc]]).
    cols = list(rows[0])
    apps_col = next((c for c in cols if c.lower() in ("total apps", "apps")),
                    cols[1] if len(cols) > 1 else cols[0])
    rows = _sort_rows(rows, apps_col)

    # EDITABLE: Team, Leadership, and (on a day) Roll Call. Everything else is
    # locked — a hand-edited sales number is exactly how a board starts
    # disagreeing with Tableau.
    editable = {"Team", "Leadership"} | ({"Roll Call"} if day_view else set())
    cfg = {c: st.column_config.Column(disabled=True)
           for c in rows[0] if c not in editable}

    # Options come from what the board already uses, so picking is choosing
    # from real teams rather than retyping one. Free text drifts: the board
    # already carries 'Hierachy' next to 'Hierarchy'-shaped names.
    teams = sorted({(r.get("Team") or "").strip() for r in rows
                    if (r.get("Team") or "").strip()}
                   | set(st.session_state.get(f"extra_teams_{office_key}", [])))
    levels = list(R.LEVELS)
    for r in rows:                      # keep any level the board uses already
        lv = (r.get("Leadership") or "").strip()
        if lv and lv not in levels:
            levels.append(lv)

    cfg["Team"] = st.column_config.SelectboxColumn(options=[""] + teams,
                                                   required=False)
    cfg["Leadership"] = st.column_config.SelectboxColumn(options=[""] + levels,
                                                         required=False)
    if day_view:
        cfg["Roll Call"] = st.column_config.SelectboxColumn(
            options=A.OPTIONS, required=False,
            help=" · ".join(f"{k} = {v}" for k, v in A.MEANINGS.items()))

    # TOTALS is the last row OF the grid, not a table beneath it — a separate
    # table has its own horizontal scroll, so the moment you scrolled the board
    # sideways the totals stopped lining up with their columns.
    n_reps = len(rows)
    grid_rows = rows + _totals_row(rows)

    edited = st.data_editor(
        _style_totals(pd.DataFrame(grid_rows)),
        use_container_width=True, hide_index=True,
        num_rows="fixed", column_config=_autofit(grid_rows, cfg),
        height=_grid_height(len(grid_rows)),
        key=f"board_{office_key}_{week.tab}_{scope}_{team}")
    # a Styler in means a DataFrame back
    edited = edited.to_dict("records")
    # never treat the totals line as a person on save
    edited = [r for r in edited if r.get("Rep") != TOTALS_LABEL]

    # Has anything actually been changed? Compare only the columns an owner can
    # touch — everything else is pulled and will differ for reasons that are
    # not edits. The flag is read on the NEXT run, which is exactly when the
    # nav controls need to know.
    def _editable_view(src):
        return [{k: (r.get(k) or "") for k in sorted(editable)}
                for r in src if r.get("Rep") != TOTALS_LABEL]

    st.session_state["board_dirty"] = (
        _editable_view(edited) != _editable_view(rows))

    day = next((d for d in week.days if d.day == scope), None)
    st.caption(f"{n_reps} reps"
               + ("" if not day_view else
                  f" · {scope}" + (f" {day.daynum}" if day and day.daynum
                                   else "")))

    if st.session_state.get("board_dirty") or st.session_state.get("goal_dirty"):
        st.warning("You have unsaved changes — save them, or discard, before "
                   "moving to another week, team or page.", icon="✏️")

    c_save, c_discard, c_add = st.columns([1, 1, 2])
    with c_discard:
        if st.button("Discard", key=f"discard_{office_key}_{scope}"):
            # Drop the grid's widget state so it reloads from the board.
            st.session_state.pop(
                f"board_{office_key}_{week.tab}_{scope}_{team}", None)
            st.session_state["board_dirty"] = False
            st.session_state["goal_dirty"] = False
            st.rerun()
    with c_save:
        if st.button("Save changes", type="primary",
                     key=f"save_{office_key}_{scope}"):
            R.set_attrs(office_key,
                        {r["Rep"]: {"team": r.get("Team") or "",
                                    "level": r.get("Leadership") or ""}
                         for r in edited})
            msg = "Saved team and leadership."
            if day_view:
                n = A.set_marks(office_key, week.tab, scope,
                                {r["Rep"]: r.get("Roll Call") for r in edited})
                msg = f"Saved team, leadership, and {n} {scope} roll-call marks."
            pend = st.session_state.get("pending_goal")
            if pend and st.session_state.get("goal_dirty"):
                G.set_goal(*pend)
                msg += " Weekly goal saved."
            st.session_state["board_dirty"] = False
            st.session_state["goal_dirty"] = False
            st.success(msg)
            st.rerun()
    with c_add:
        # Only on the all-teams view. Filtered to one crew, "Add a team" is
        # noise — you are looking at that team, not building the list.
        if team == ALL_TEAMS:
            new_team = st.text_input(
                "Add a team", key=f"newteam_{office_key}",
                placeholder="name a team that isn't listed")
            if new_team.strip():
                extra = st.session_state.setdefault(
                    f"extra_teams_{office_key}", [])
                if new_team.strip() not in extra:
                    extra.append(new_team.strip())
                    st.rerun()


    if show_first and not fs:
        st.caption("⚠️ 1st Day of Sales fell back to the board's own column — "
                   "the harvest map could not be read.")


def campaign_breakdown(week, scope: str = "Week",
                       overrides: dict | None = None,
                       team: str = ALL_TEAMS) -> None:
    """FIBER / ENERGY are CAMPAIGNS, not teams — the board splits this
    block by its Campaign column, while Team means Ceaseless, Se7en Sins,
    Hashiras. Calling it 'team' collided with the Team column two sections
    up and made the same word mean two things on one page."""
    groups = {g: d for g, d in week.summary.items() if g != "ALL"}
    if not groups:
        return

    # Follows the day selector, same as the vitals. On Week it reads the
    # board's own summary block, which counts column D — the RUNNING WEEK
    # total — so it is week-to-date, not today:
    #   =COUNTIFS(D4:D79,">0", CG…,"<>1st Week", CG…,"<>RT")
    filtered = bool(team) and team != ALL_TEAMS
    suffix = f" · {team}" if filtered else ""

    if scope == "Week" and not filtered:
        st.subheader("By Campaign · week to date")
        st.caption("Counts reps whose week total is above zero. First-week "
                   "reps and roadtrips are left out.")
        cols = st.columns(len(groups))
        for col, (name, d) in zip(cols, groups.items()):
            with col:
                st.markdown(f"**{name}**")
                for k, v in d.items():
                    st.write(f"{k.split('/')[0].strip()}: **{v}**")
        return

    st.subheader(f"By Campaign · "
                 f"{scope if scope != 'Week' else 'week to date'}"
                 f"{suffix}")
    d = _day_date(week, scope) if scope != "Week" else None
    if d and d > dt.date.today():
        st.caption(f"{scope} hasn't happened yet.")
        return
    st.caption(f"{scope} only. First-week reps and roadtrips left out.")
    cols = st.columns(len(groups))
    for col, name in zip(cols, groups):
        v = _calc_vitals(week, scope, overrides or {}, team=team,
                         campaign=name)
        with col:
            st.markdown(f"**{name}**")
            st.write(f"Total Reps in the Field: **{v['in_field']}**")
            st.write(f"Reps that got on the Board: **{v['on_board']}**")
            st.write(f"Reps that rolled a Zero: **{v['zero']}**")
            st.write(f"% of Reps on the Board: **{v['pct']}**")


def _week_start(label: str):
    """The Monday a 'WE 8/17- 8/23' header starts on.

    The label carries no year, so assume the current one and step back a year if
    that would land in the future (a January board reading a December week)."""
    m = re.search(r"(\d{1,2})/(\d{1,2})", label or "")
    if not m:
        return None
    today = dt.date.today()
    try:
        d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None
    if d > today + dt.timedelta(days=14):
        d = d.replace(year=today.year - 1)
    return d


def week_lines(df, dates: list, metrics: list):
    """A weekly multi-line chart, one colour per metric.

    x ticks are pinned to the real week endings — left alone the chart spaces
    them evenly and labels whatever weekday it lands on ('Mon 13', 'Tue 21'),
    which is meaningless on a weekly chart. Format is %m/%d, never %-m/%-d,
    which is Mac-only."""
    import altair as alt
    long = df.reset_index().melt("Week", value_vars=metrics,
                                 var_name="Metric", value_name="Value")
    return (
        alt.Chart(long)
        .mark_line(point=True)
        .encode(
            x=alt.X("Week:T", title=None,
                    axis=alt.Axis(values=dates, format="%m/%d", labelAngle=0)),
            y=alt.Y("Value:Q", title=None),
            color=alt.Color("Metric:N", title=None,
                            legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("Week:T", format="%m/%d/%y"), "Metric:N",
                     "Value:Q"])
        .properties(height=280))


def week_line(df, ycol: str, dates: list):
    """A weekly line whose x-axis ticks are THE WEEKS, not Vega's own picks.

    Left to itself the chart spaces ticks evenly and labels them by whatever
    day they land on — 'Mon 13', 'Tue 21', 'Wed 29' — which are not week
    endings and read as nonsense on a weekly chart. Pinning `values` to the
    real dates puts one tick per point. Format is %m/%d, never %-m/%-d, which
    is Mac-only."""
    import altair as alt
    return (
        alt.Chart(df.reset_index())
        .mark_line(point=True)
        .encode(
            x=alt.X("Week:T", title=None,
                    axis=alt.Axis(values=dates, format="%m/%d", labelAngle=0)),
            y=alt.Y(f"{ycol}:Q", title=ycol),
            tooltip=[alt.Tooltip("Week:T", format="%m/%d/%y"),
                     alt.Tooltip(f"{ycol}:Q")])
        .properties(height=260))


@st.cache_data(ttl=900, show_spinner="Reading each week for this team…")
def team_history(tabs: tuple, team: str, n: int) -> list:
    """[(date, units)] for ONE team, newest first.

    The board's history rows at the bottom are office-wide only, so a team's
    line has to come from each week tab's own Teams block. That costs one sheet
    read per week — cached, and capped by the slider — which is why the default
    span is shorter here than for the office."""
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(RAF_SHEET)
    dated = dict(B.week_tab_dates(list(tabs)))
    out = []
    for tab in list(tabs)[:n]:
        try:
            row = B.parse_teams(sh.worksheet(tab).get_all_values()).get(team)
        except Exception:
            continue
        if not row or not row.get("units"):
            continue
        try:
            out.append((dated.get(tab), float(str(row["units"]).replace(",", ""))))
        except ValueError:
            continue
    return [(d, v) for d, v in out if d]


def trend(week, tabs=(), team: str = ALL_TEAMS) -> None:
    filtered = bool(team) and team != ALL_TEAMS

    if filtered:
        st.subheader(f"Week over week · {team}")
        n = st.slider("Weeks to show", 4, min(16, max(4, len(tabs))), 8,
                      key="trend_n_team")
        pts = team_history(tuple(tabs), team, n)
        if not pts:
            st.caption(f"No weekly history found for {team}.")
            return
        pts = sorted(pts, key=lambda x: x[0])
        names = [m for m in pts[0][1] if m] or ["Total Units"]
        picked = st.multiselect("Metrics", names,
                                default=[n for n in names[:1]],
                                key="trend_m_team")
        if not picked:
            st.caption("Pick at least one metric.")
            return
        df = pd.DataFrame([dict({"Week": d},
                                **{m: _num(vals.get(m)) for m in picked})
                           for d, vals in pts]).set_index("Week")
        st.altair_chart(week_lines(df, [d for d, _ in pts], picked),
                        use_container_width=True)
        st.caption("Per week, from each week's Teams block.")
        return

    if not week.history:
        return
    st.subheader("Week over week")
    n = st.slider("Weeks to show", 4, min(52, len(week.history)), 12,
                  key="trend_n")
    picked = st.multiselect("Metrics", week.measures,
                            default=week.measures[:1], key="trend_m")
    if not picked:
        st.caption("Pick at least one metric.")
        return

    # Index by a real DATE, not the week label. The labels carry no year, and a
    # categorical axis is sorted alphabetically by the chart — which puts 6/15
    # before 6/8 and makes the line jump around. The history rows are contiguous
    # weeks newest-first, so walking back 7 days per row from the board's own
    # week gives exact dates without guessing a year.
    anchor = _week_start(week.week_label) or dt.date.today()
    rows = []
    for i, (lbl, vals) in enumerate(week.history[:n]):
        row = {"Week": anchor - dt.timedelta(weeks=i + 1), "label": lbl}
        for m in picked:
            j = week.measures.index(m)
            row[m] = _num(vals[j]) if j < len(vals) else 0.0
        rows.append(row)
    rows.reverse()
    df = pd.DataFrame(rows).set_index("Week")
    st.altair_chart(week_lines(df, [r["Week"] for r in rows], picked),
                    use_container_width=True)
    st.caption(f"{rows[0]['label']} → {rows[-1]['label']}")


def _rep_streak(r: dict, days: list, anchor_idx: int) -> int:
    """How many days in a row this rep has rolled a literal zero.

    A ZERO is a numeric 0. 'X' (didn't work), 'T' (terminated) and blank are NOT
    zeros — you cannot roll a zero on a day you were never out there — so those
    days are stepped over without counting and without ending the run. Any
    positive number ends it. Same rule sales_boards/zeros.py uses for Carlos."""
    streak = 0
    for i in range(anchor_idx, -1, -1):
        cell = ((r.get("daily") or {}).get(days[i], {})
                .get("values", {}).get("Apps", "") or "").strip()
        if not cell or cell.upper() in _NOT_NUMERIC:
            continue
        try:
            v = float(cell.replace(",", ""))
        except ValueError:
            continue
        if v > 0:
            break
        streak += 1
    return streak


def zero_streaks(week, overrides: dict, team: str = ALL_TEAMS) -> None:
    """Escalating 'zeros in a row' levels, like the Slack post.

    Each level is CUMULATIVE — the 2-day list is everyone on 2 or more — which
    is what makes it escalate: the list gets shorter and the problem gets more
    serious as you go down."""
    filtered = bool(team) and team != ALL_TEAMS
    days = week.day_names
    if not days:
        return

    # Anchor on the most recent COMPLETED day; today is still in progress and a
    # zero at 9am means nothing.
    today = dt.date.today()
    anchor_idx = -1
    for i, d in enumerate(days):
        dd = _day_date(week, d)
        if dd and dd < today:
            anchor_idx = i
    if anchor_idx < 0:
        st.subheader("Zero streaks")
        st.caption("No completed day on this week yet.")
        return

    rows = []
    for r in week.reps:
        if filtered and rep_team(r, overrides) != team:
            continue
        n = _rep_streak(r, days, anchor_idx)
        if n <= 0:
            continue
        rows.append({
            "Rep": r["name"],
            "Days": n,
            "Current Week": r.get("values", {}).get("Total Apps", ""),
            "Last Wk": (r.get("last_values") or {}).get("APPS", ""),
            "Team": rep_team(r, overrides),
            "Campaign": r.get("attrs", {}).get("campaign", ""),
        })

    st.subheader("Zero streaks" + (f" · {team}" if filtered else ""))
    if not rows:
        st.success("Nobody is on a zero streak.")
        return
    st.caption(f"Through {days[anchor_idx]}. A zero is a literal 0 — a day "
               "marked X, T or left blank is not counted against anyone.")

    longest = max(r["Days"] for r in rows)
    for lvl in range(1, longest + 1):
        at_or_above = sorted((r for r in rows if r["Days"] >= lvl),
                             key=lambda r: (-r["Days"], r["Rep"]))
        label = f"{lvl} Day" if lvl == 1 else f"{lvl} Days"
        with st.expander(f"{label} — {len(at_or_above)} reps",
                         expanded=(lvl == longest)):
            st.dataframe(at_or_above, use_container_width=True,
                         hide_index=True,
                         height=_grid_height(len(at_or_above)))


def recruiting(profile) -> None:
    st.subheader("Recruiting")
    st.caption("From Raf's funnel. Only the earliest stage that misses its goal "
               "is the constraint — the rest are downstream of it.")
    for s in F.STAGES:
        goal = F.GOALS.get(s.key)
        cols = st.columns([4, 2, 2])
        cols[0].write(f"**{s.order}. {s.label}**  \n{s.ratio}")
        cols[1].write("✅ pulled today" if s.is_wired else "⚠️ not wired")
        cols[2].write(f"goal {goal:.0%}" if goal is not None else "no goal set")


# ----------------------------------------------------------------------- app
def main() -> None:
    profs = load_profiles()

    st.sidebar.title("Sales Boards")
    # Streamlit can't intercept a click, so instead of trying to catch someone
    # leaving with unsaved work, the controls that would lose it are disabled
    # until they save or discard. Same effect, no surprise.
    locked = bool(st.session_state.get("board_dirty")
                  or st.session_state.get("goal_dirty"))
    if locked:
        st.sidebar.warning("Unsaved changes", icon="✏️")
    view = st.sidebar.radio("View", ["Office", "Org"], key="view",
                            disabled=locked)

    if view == "Org":
        st.title("Every office")
        st.caption(f"{len(profs)} ICDs on the ORG Sales Board.")
        st.dataframe(
            [{"ICD": n,
              "Campaigns": ", ".join(C.CAMPAIGNS[k].label for k in p.campaigns),
              "Sells": ", ".join(p.families),
              "Metrics": f"{len(p.metrics)}/{len(C.METRICS)}",
              "Feed today": p.channel_name or "—"}
             for n, p in profs.items()],
            use_container_width=True, hide_index=True)
        st.info("Per-rep org roll-up lands once the per-office boards exist — "
                "today only Raf's board carries real rep rows.")
        return

    names = sorted(profs)
    icd = st.sidebar.selectbox(
        "Office", names, index=names.index(RAF_ICD) if RAF_ICD in names else 0,
        disabled=locked)
    prof = profs[icd]
    key = (prof.office_key or icd.lower().replace(" ", "_"))

    # Production and Recruiting are separate PAGES, not two halves of one long
    # scroll (Megan 2026-08-17). They answer different questions and get read by
    # different people at different times; stacking them buries whichever is
    # second.
    page = st.sidebar.radio("Page", ["Production", "Recruiting"], key="page",
                            disabled=locked)

    # The BUSINESS name headlines — this is the office's board, and the branded
    # name is what an owner recognises as theirs. The owner's own name sits
    # under it as context, not as the title.
    st.title(BUSINESS_NAMES.get(icd, icd))
    st.caption(icd + " · "
               + " · ".join(C.CAMPAIGNS[k].label for k in prof.campaigns))

    if page == "Recruiting":
        recruiting(prof)
        return

    if icd != RAF_ICD:
        st.warning(
            f"{icd} has no board wired yet — Raf's is the only one with real "
            "data so far. This office shows its campaign profile only.",
            icon="🚧")
        vitals_row(None, R.load(key))
        return

    data = load_raf_board(st.session_state.get("tab", ""))
    if not data:
        st.error("Could not read the board.")
        return
    week = data["week"]
    labels = B.week_tab_labels(data["tabs"])
    st.sidebar.selectbox("Week Ending", data["tabs"], key="tab",
                         format_func=lambda t: labels.get(t, t),
                         disabled=locked)

    # The day selector sits ABOVE everything it changes: pick Wednesday and the
    # vitals, the board and the team split all become Wednesday. Otherwise the
    # numbers on top keep describing the week while the table below shows a day.
    scope = st.radio("Show", ["Week"] + week.day_names, horizontal=True,
                     key="scope", disabled=locked)

    # Team filter sits with the day selector because it narrows the SAME things
    # — pick Ceaseless and every number on the page is Ceaseless's.
    overrides = {r.name.strip().lower(): r for r in R.load(key)}
    team_names = sorted({rep_team(r, overrides) for r in week.reps
                         if rep_team(r, overrides)})
    team = st.selectbox("Team", [ALL_TEAMS] + team_names, key="team",
                        disabled=locked)

    vitals_row(week, R.load(key), scope, overrides, team,
               data['tabs'])
    production_panel(week, scope, overrides, team, key,
                     data['tabs'])
    st.divider()
    sales_board(week, key, scope, team)
    st.divider()
    campaign_breakdown(week, scope, overrides, team)
    st.divider()
    zero_streaks(week, overrides, team)
    st.divider()
    trend(week, data['tabs'], team)


main()
