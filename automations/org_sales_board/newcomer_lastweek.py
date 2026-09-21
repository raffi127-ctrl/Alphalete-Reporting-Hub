"""Last week for somebody NEW on a sales board — in every table that shows it,
on all three boards.

THE RULE (Eve). A person added to a board after Tuesday's freeze has no LAST
week anywhere: the freeze only copied the rows that existed that morning.
  2026-08-31  "siempre que agregues a alguien ... hay que backfillear el
              desglose diario de la semana pasada" (delta boxes)
  2026-09-01  a brand-new person gets LAST WEEK ONLY, and in every place that
              shows it, or the board contradicts itself (Ja Mosley)
  2026-09-07  "si no tienen ventas = 0"
  2026-09-15  "hay una regla que incorporamos para la org sales board y no estás
              aplicando a 'all campaigns sales board' y 'country sales board' ...
              falta la info de samuel acay" / "tampoco estan sus numeros de la
              semana pasada en org sales board, y si no tiene ventas, va 0"

`delta_lastweek_backfill` only ever did the ORG board's DELTA boxes. Samuel Acay
(ATT NDS, first sale 9/14) showed what it left out: his WE 09.13 leaderboard
cell and his LAST WEEK'S TOTALS were blank on the ORG board, and on All
Campaigns the same two plus all seven 'Last week' cells of his delta row.

WHAT "NEW" MEANS HERE. A row whose last-week cell is EMPTY in a table where at
least MIN_FILLED other rows already carry a frozen value. Empty, not 0: a
literal 0 is a freeze that came out zero. A formula is never touched.

THE PLACES (Eve's list, 2026-09-01), per board:
  1. the leaderboard's most recent CLOSED week column (col D, checked against
     the 'WE mm.dd' header) — and its TOTALS row, plus ALL TOTALS on the ORG board
  2. LAST WEEK'S TOTALS (col K) of the daily table — and its Totals row
  3. the per-day 'Last week' cells of the person's delta row (All Campaigns and
     Country; the ORG board's delta boxes stay with delta_lastweek_backfill)
  4. the week's row in the history stack under the daily table: 'Last Week' on
     the ORG board's campaign sections, the top 'WE m.d' row on the other two
  5. PREVIOUS WEEK'S TOTALS (col L) stays blank — the next roll fills it.
The totals only move when the person actually sold; a 0 changes nothing.

WHERE THE NUMBERS COME FROM.
  * ORG board: the section's own Tableau view (section_pull.SPECS), pinned to
    LAST week — the same view, product filter and parser the daily fill uses.
    The Retail sections (SARA / JE) have no such view, so a newcomer there is
    left blank and NAMED.
  * All Campaigns: the SUM of the same pulls over every ORG campaign section the
    person has a row in — that is literally how that board's All Units is built
    (all_campaigns_board.aggregate). A person with one unsourced section is
    left blank rather than under-counted.
  * Country: its own view's last-week worksheet ('(LW2)').
Absent from a view that DID render = 0: these crosstabs omit zero rows.

IT CHECKS BEFORE IT TRUSTS. Every row that already has last week frozen is a
known answer; the pull has to agree with them (<= 10% disagreeing, >= 5 rows
checked) or its numbers are not used. A totals cell that is not a number
refuses the board's writes.

NO READABLE LAST WEEK = NO SALES = 0 (Eve 2026-09-15). The NDS view cannot be
pinned to an old week and has no '(LW2)' worksheet, so Samuel Acay's last week
could not be read at all. Eve: "cargale 0, debe ser que no tiene ventas, ponelo
como regla". So a section with no view, a view that failed, or one that does not
match the frozen rows gives the newcomer a literal 0 — never a blank — and the
log says why. A 0 moves no total. Idempotent: only empty cells are filled, so a
second run finds nothing and opens no browser.

    python -m automations.org_sales_board.newcomer_lastweek            # dry-run
    python -m automations.org_sales_board.newcomer_lastweek --apply
    python -m automations.org_sales_board.newcomer_lastweek --board country
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ORG_SHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
COUNTRY_SHEET_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"
ALLCAMP_TAB = "All Campaigns Org Sales Board"      # live title has a trailing space
ALLCAMP_SECTION = "All Units"
CENTRAL = ZoneInfo("America/Chicago")

# ORG campaign section -> section_pull.SPECS key (the views that can be pinned
# to an old week). Retail NL / Retail Internet (SARA) and Retail JE are not here.
SECTION_SPECS = {"ATT Fiber Team": "fiber", "ATT NDS Team": "nds",
                 "B2B": "b2b", "BOX": "box"}

MIN_FILLED = 3                  # frozen rows a table needs before a blank reads "new"
MIN_CALIBRATION_ROWS = 5
MAX_DISAGREE_SHARE = 0.10
OUT_DIR = Path("output") / "_newcomer_lastweek"
# The worksheet a relative-week view keeps LAST week on, under its this-week one
# ('Sales By ICD (Weekly View)' -> 'Sales By ICD (Weekly View) (LW2)').
LAST_WEEK_SUFFIX = " (LW2)"
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday")
_WE_RE = re.compile(r"^\s*WE\s+(\d{1,2})\.(\d{1,2})\s*$", re.I)


# ------------------------------------------------------------------ helpers

def _cell(g, r: int, c: int) -> str:
    if not 0 < r <= len(g):
        return ""
    row = g[r - 1]
    return str(row[c - 1]).strip() if 0 < c <= len(row) else ""


def _num(s) -> Optional[float]:
    t = str(s or "").replace(",", "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _fmt(n: float):
    return int(n) if float(n).is_integer() else n


def _a1(c: int) -> str:
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def _is_formula(fg, r: int, c: int) -> bool:
    return _cell(fg, r, c).startswith("=")


def _we_md(label: str) -> Optional[Tuple[int, int]]:
    m = _WE_RE.match(label or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def last_week_ending(today: dt.date) -> dt.date:
    """The Sunday of the week the board calls LAST week (the board rolls
    Tuesday, so `today - 7` goes through the same Monday lag)."""
    from automations.org_sales_board import week as wk
    return wk.reporting_sunday(today - dt.timedelta(days=7))


@dataclasses.dataclass
class Blank:
    row: int
    col: int
    name: str
    day: str = ""               # weekday of a delta cell; "" = a weekly total


class Refuse(Exception):
    """A totals cell this run would have to grow is not a number."""


# ------------------------------------------------------------------ finders

def daily_blanks(grid, fgrid, label: str):
    """(blank LAST WEEK'S TOTALS cells, [(name, frozen value)], anchor)."""
    from automations.org_sales_board import fill_section as fs
    try:
        a = fs.find_daily_section(grid, label)
    except ValueError:
        return [], [], None
    kc = a.running_total_col + 1
    if _cell(grid, a.header_row, kc).lower() != "last week's totals":
        return [], [], a
    blanks, filled = [], []
    for name, r in a.icd_rows.items():
        v = _cell(grid, r, kc)
        if v == "":
            if not _is_formula(fgrid, r, kc):
                blanks.append(Blank(r, kc, name))
        elif _num(v) is not None:
            filled.append((name, _num(v)))
    if len(filled) < MIN_FILLED:
        return [], filled, a
    return blanks, filled, a


def leaderboard_blanks(grid, fgrid, header_row: int, data_rows: List[int],
                       today: dt.date, col: int = 4):
    """Blank cells in the leaderboard's last CLOSED week column — only when
    that column's header really is last week."""
    lw = last_week_ending(today)
    if _we_md(_cell(grid, header_row, col)) != (lw.month, lw.day):
        return [], []
    blanks, filled = [], []
    for r in data_rows:
        name = _cell(grid, r, 2)
        if not name:
            continue
        v = _cell(grid, r, col)
        if v == "":
            if not _is_formula(fgrid, r, col):
                blanks.append(Blank(r, col, name))
        elif _num(v) is not None:
            filled.append((name, _num(v)))
    if len(filled) < MIN_FILLED:
        return [], filled
    return blanks, filled


def delta_blanks(grid, fgrid) -> List[Blank]:
    """Empty per-day 'Last week' cells of every delta box on the tab."""
    from automations.org_sales_board import rollover as ro
    out: List[Blank] = []
    for t in ro.find_delta_tables(grid):
        days = {}
        for c in t["this_cols"]:
            d = _cell(grid, t["header_row"] - 1, c).capitalize()
            if d in WEEKDAYS:
                days[c] = d
        if not days:
            continue
        cells, complete = [], 0
        for r in t["data_rows"]:
            name = _cell(grid, r, 2)
            if not name:
                continue
            miss = [Blank(r, c + 1, name, d) for c, d in days.items()
                    if _cell(grid, r, c + 1) == ""
                    and not _is_formula(fgrid, r, c + 1)]
            if miss:
                cells += miss
            else:
                complete += 1
        if complete >= MIN_FILLED:
            out += cells
    return out


def stack_row(grid, totals_row: int, today: dt.date) -> Optional[int]:
    """The 'WE m.d' row for last week, at the top of the stack under a daily
    Totals row (All Campaigns / Country). None when it is not there or is not
    last week."""
    lw = last_week_ending(today)
    for r in range(totals_row + 1, min(totals_row + 4, len(grid)) + 1):
        md = _we_md(_cell(grid, r, 1))
        if md:
            return r if md == (lw.month, lw.day) else None
    return None


# ------------------------------------------------------------------ sources

def person_days(parsed, metric: str, name: str, aliases) -> Dict[str, int]:
    """{weekday: units} for `name` in one parsed pull (0 when absent)."""
    from automations.org_sales_board import fill_section as fs
    cands = fs._candidates_for(name, aliases)
    out = {d: 0 for d in WEEKDAYS}
    for key, metrics in (parsed or {}).items():
        if key in cands:
            for day, v in (metrics.get(metric) or {}).items():
                out[day.strftime("%A")] += int(v or 0)
    return out


def calibrate(filled, days_of: Callable[[str], Optional[Dict[str, int]]]
              ) -> Tuple[int, List[str]]:
    checked, bad = 0, []
    for name, frozen in filled:
        got = days_of(name)
        if got is None:
            continue
        checked += 1
        if abs(sum(got.values()) - frozen) > 0.5:
            bad.append(f"{name}: board {_fmt(frozen)} vs view {sum(got.values())}")
    return checked, bad


def _no_sales(_name: str = "") -> Dict[str, int]:
    return {d: 0 for d in WEEKDAYS}


def trusted(checked: int, bad: List[str]) -> bool:
    return (checked >= MIN_CALIBRATION_ROWS
            and len(bad) / checked <= MAX_DISAGREE_SHARE)


def pull_sections(keys, today: dt.date, page, logfn=print):
    """({spec key: (metric, parsed)}, [failed keys]) for LAST week."""
    from automations.org_sales_board import section_pull as sp
    from automations.org_sales_board import week as wk
    ref = today - dt.timedelta(days=7)
    want = set(wk.reporting_week(ref))
    pulls, failed = {}, []
    for key in sorted(set(keys)):
        spec = dataclasses.replace(sp.SPECS[key],
                                   out_name=f"newcomer_lastweek_{key}.csv")
        try:
            path = sp.pull_section_byday(spec, OUT_DIR, page, logfn=logfn,
                                         today=ref)
            parsed = sp.parse_byday(spec, path, ref)
        except Exception as e:                                # noqa: BLE001
            # THE PIN DOES NOT REACH AN OLD WEEK ON EVERY VIEW (2026-09-15, NDS:
            # "Couldn't find 'Sales By ICD (Weekly View)' … saw 1 thumb"). These
            # views are pinned to RELATIVE weeks: a filter for another week
            # renders the worksheet empty and Tableau drops it from the Crosstab
            # dialog. The view carries last week as its own worksheet, named
            # with ' (LW2)' — the same way out delta_lastweek_backfill found on
            # 2026-09-07. Calibration below still decides whether it is used.
            logfn(f"  [!] {key}: pinned view failed ({type(e).__name__}: "
                  f"{str(e)[:90]}) — trying its last-week worksheet")
            parsed = None
            if spec.crosstab_sheet:
                lw2 = dataclasses.replace(
                    spec, week_pin=False,
                    crosstab_sheet=spec.crosstab_sheet + LAST_WEEK_SUFFIX,
                    out_name=f"newcomer_lastweek_{key}_lw2.csv")
                try:
                    path = sp.pull_section_byday(lw2, OUT_DIR, page,
                                                 logfn=logfn, today=ref)
                    parsed = sp.parse_byday(lw2, path, ref)
                    logfn(f"  {key}: using {lw2.crosstab_sheet!r} "
                          f"({len(parsed)} owners)")
                except Exception as e2:                       # noqa: BLE001
                    logfn(f"  [!] {key}: {lw2.crosstab_sheet!r} could not be "
                          f"pulled either ({type(e2).__name__}: {str(e2)[:90]})")
            if parsed is None:
                failed.append(key)
                continue
        got = {d for m in parsed.values() for v in m.values() for d in v}
        if got and not got <= want:
            logfn(f"  [!] {key}: the view came back on {min(got)}..{max(got)}, "
                  f"not {min(want)}..{max(want)} — not used")
            failed.append(key)
            continue
        pulls[key] = (spec.metric, parsed)
    return pulls, failed


# ------------------------------------------------------------------ planning

def _growth_writes(grid, fgrid, adds: Dict[Tuple[int, int], float]) -> List[dict]:
    out = []
    for (r, c), add in sorted(adds.items()):
        if not add or _is_formula(fgrid, r, c):
            continue            # a formula total recomputes on its own
        cur = _num(_cell(grid, r, c))
        if cur is None:
            raise Refuse(f"{_a1(c)}{r} holds {_cell(grid, r, c)!r}, not a number")
        out.append({"range": f"{_a1(c)}{r}", "values": [[_fmt(cur + add)]]})
    return out


def org_line_rows(grid, all_totals: Optional[int]) -> Dict[str, int]:
    """The per-org lines right under ALL TOTALS ('Raf Org', 'Carlos Org',
    'Colten Org' — Eve 2026-09-21), as {'raf': row, ...}. ALL TOTALS is their
    =SUM, so a newcomer's closed week has to land on one of them too, or the
    frozen history stops adding up."""
    out: Dict[str, int] = {}
    if not all_totals:
        return out
    for r in range(all_totals + 1, all_totals + 6):
        lab = _cell(grid, r, 1).lower()
        if not lab.endswith(" org"):
            break
        out[lab.split()[0]] = r
    return out


def org_head_of(grid, anchor, name: str) -> str:
    """The person's 'Org Head' tag (col headed 'Org Head' on the daily table),
    lowercased — the same tag the board's CARLOS/COLTEN ORG blocks =SUMIF on."""
    if anchor is None or name not in anchor.icd_rows:
        return ""
    hdr = anchor.header_row
    col = next((c for c in range(1, len(grid[hdr - 1]) + 1)
                if _cell(grid, hdr, c).lower() == "org head"), None)
    return _cell(grid, anchor.icd_rows[name], col).lower() if col else ""


def plan_org(grid, fgrid, pulls, failed, aliases, today: dt.date):
    """(updates, notes) for the ORG board's campaign sections."""
    from automations.new_owners import board_add as ba
    from automations.org_sales_board import rollover as ro
    updates: List[dict] = []
    notes: List[str] = []
    adds: Dict[Tuple[int, int], float] = defaultdict(float)
    try:
        org = ro.find_org_block(grid)
    except StopIteration:
        org = None
    all_totals = None
    if org:
        all_totals = next((r for r in range(org.header_row + 1, org.header_row + 4)
                           if _cell(grid, r, 1).lower() == "all totals"), None)
    org_lines = org_line_rows(grid, all_totals)
    hist = {t["this"]: t for t in ro.find_campaign_history_tables(grid)}

    for label in ba.campaign_labels(grid):
        dblank, dfilled, anchor = daily_blanks(grid, fgrid, label)
        lb, lblank = None, []
        if org:
            try:
                lb = ba.find_campaign_leaderboard(grid, label)
            except ValueError:
                lb = None
            if lb:
                lblank, _ = leaderboard_blanks(grid, fgrid, org.header_row,
                                               lb["data_rows"], today)
        if not dblank and not lblank:
            continue
        who = ", ".join(dict.fromkeys(b.name for b in dblank + lblank))
        key = SECTION_SPECS.get(label)
        reason = None
        if key is None:
            reason = "this section has no last-week view"
        elif key not in pulls:
            reason = (f"the {key} view "
                      f"{'failed' if key in failed else 'was not pulled'}")
        else:
            metric, parsed = pulls[key]
            days_of = lambda n, p=parsed, m=metric: person_days(p, m, n, aliases)
            checked, bad = calibrate(dfilled, days_of)
            if not trusted(checked, bad):
                reason = (f"last week's view does not match the rows already "
                          f"frozen ({len(bad)} of {checked}: {'; '.join(bad[:3])})")
        if reason:
            # NO SOURCE = NO SALES (Eve 2026-09-15, Samuel Acay: "cargale 0,
            # debe ser que no tiene ventas, ponelo como regla"). Somebody new
            # whose last week cannot be read is written as a literal 0 rather
            # than left blank — and said so, loudly, in the log.
            days_of = _no_sales
            notes.append(f"{label}: {who} — {reason}; no sales assumed: 0")
        sec_adds: Dict[Tuple[int, int], float] = defaultdict(float)
        for b in dblank:
            days = days_of(b.name)
            tot = sum(days.values())
            updates.append({"range": f"{_a1(b.col)}{b.row}", "values": [[tot]]})
            notes.append(f"{label} / {b.name}: LAST WEEK'S TOTALS {b.col and _a1(b.col)}{b.row} = {tot}"
                         + ("" if tot else " (not in the view: 0)"))
            if tot:
                sec_adds[(anchor.totals_row, b.col)] += tot
                h = hist.get(anchor.totals_row)
                if h is None:
                    notes.append(f"{label}: no 'Last Week' history row under "
                                 f"Totals — {b.name}'s days not added there")
                else:
                    for col in sorted(anchor.day_col_by_daynum.values()):
                        wd = _cell(grid, anchor.header_row, col).capitalize()
                        if days.get(wd):
                            sec_adds[(h["lw"], col)] += days[wd]
                    sec_adds[(h["lw"], anchor.running_total_col)] += tot
        for b in lblank:
            tot = sum(days_of(b.name).values())
            updates.append({"range": f"{_a1(b.col)}{b.row}", "values": [[tot]]})
            notes.append(f"{label} / {b.name}: leaderboard "
                         f"{_cell(grid, org.header_row, b.col)} {_a1(b.col)}{b.row}"
                         f" = {tot}" + ("" if tot else " (not in the view: 0)"))
            if tot:
                if lb.get("totals_row"):
                    sec_adds[(lb["totals_row"], b.col)] += tot
                if all_totals:
                    sec_adds[(all_totals, b.col)] += tot
                if org_lines:
                    # ALL TOTALS = Raf + Carlos + Colten: the person's own line
                    # grows too. Untagged → Raf (his line is the org minus
                    # Carlos and Colten).
                    line = org_lines.get(org_head_of(grid, anchor, b.name),
                                         org_lines.get("raf"))
                    if line:
                        sec_adds[(line, b.col)] += tot
        for k, v in sec_adds.items():
            adds[k] += v
    updates += _growth_writes(grid, fgrid, adds)
    return updates, notes


def plan_block(grid, fgrid, *, section: str, leaderboard: Optional[dict],
               days_of: Callable[[str], Tuple[Optional[Dict[str, int]], str]],
               today: dt.date, board: str):
    """(updates, notes) for a board with ONE daily table, one leaderboard and
    delta boxes over the same people — All Campaigns and Country."""
    updates: List[dict] = []
    notes: List[str] = []
    dblank, dfilled, anchor = daily_blanks(grid, fgrid, section)
    lblank = []
    if leaderboard:
        lblank, _ = leaderboard_blanks(grid, fgrid, leaderboard["header_row"],
                                       leaderboard["data_rows"], today)
    dcells = delta_blanks(grid, fgrid)
    names = list(dict.fromkeys(b.name for b in dblank + lblank + dcells))
    if not names:
        return updates, notes

    # Only rows whose number is FULLY sourced can vouch for the source.
    checked, bad = calibrate(
        dfilled, lambda n: (lambda d, why: None if why else d)(*days_of(n)))
    if checked >= MIN_CALIBRATION_ROWS and not trusted(checked, bad):
        notes.append(f"{board}: last week's numbers do not match the rows already "
                     f"frozen ({len(bad)} of {checked}: {'; '.join(bad[:3])}); "
                     f"no sales assumed: 0 for {', '.join(names)}")
        days_of = lambda n: (_no_sales(), "")

    stack = stack_row(grid, anchor.totals_row, today) if anchor else None
    adds: Dict[Tuple[int, int], float] = defaultdict(float)
    for name in names:
        days, why = days_of(name)
        if days is None:
            days = _no_sales()
        if why:
            notes.append(f"{board} / {name}: {why}; counted as no sales (0)")
        tot = sum(days.values())
        mine = [b for b in dblank if b.name == name]
        for b in mine:
            updates.append({"range": f"{_a1(b.col)}{b.row}", "values": [[tot]]})
            if tot:
                adds[(anchor.totals_row, b.col)] += tot
                if stack is None:
                    notes.append(f"{board}: no last-week 'WE' row under Totals — "
                                 f"{name}'s days not added to the stack")
                else:
                    for col in sorted(anchor.day_col_by_daynum.values()):
                        wd = _cell(grid, anchor.header_row, col).capitalize()
                        if days.get(wd):
                            adds[(stack, col)] += days[wd]
                    adds[(stack, anchor.running_total_col)] += tot
        for b in (b for b in lblank if b.name == name):
            updates.append({"range": f"{_a1(b.col)}{b.row}", "values": [[tot]]})
            if tot and leaderboard.get("totals_row"):
                adds[(leaderboard["totals_row"], b.col)] += tot
        for b in (b for b in dcells if b.name == name):
            updates.append({"range": f"{_a1(b.col)}{b.row}",
                            "values": [[days.get(b.day, 0)]]})
        where = [w for w, got in (("LAST WEEK", mine),
                                  ("leaderboard", [b for b in lblank if b.name == name]),
                                  ("delta", [b for b in dcells if b.name == name])) if got]
        notes.append(f"{board} / {name}: last week = {tot} "
                     f"({' '.join(f'{d[:3]} {days[d]}' for d in WEEKDAYS)}) -> "
                     f"{', '.join(where)}" + ("" if tot else " (no sales: 0)"))
    updates += _growth_writes(grid, fgrid, adds)
    return updates, notes


def plan_allcamp(grid, fgrid, org_grid, pulls, failed, aliases, today: dt.date):
    from automations.all_campaigns_board import aggregate as agg
    from automations.all_campaigns_board import rollover as rj
    from automations.org_sales_board import fill_section as fs
    members: Dict[str, List[set]] = {}
    for label in agg.CAMPAIGN_SECTIONS:
        try:
            a = fs.find_daily_section(org_grid, label)
        except ValueError:
            continue
        members[label] = [fs._candidates_for(n, aliases) for n in a.icd_rows]

    def days_of(name):
        cands = fs._candidates_for(name, aliases)
        secs = [l for l, forms in members.items() if any(f & cands for f in forms)]
        if not secs:
            return _no_sales(), "not on any ORG campaign section"
        # A section with no readable last week counts as no sales there (Eve
        # 2026-09-15) — the sourced ones still add their real numbers.
        unsourced = [l for l in secs if SECTION_SPECS.get(l) not in pulls]
        out = {d: 0 for d in WEEKDAYS}
        for l in secs:
            if l in unsourced:
                continue
            metric, parsed = pulls[SECTION_SPECS[l]]
            for d, v in person_days(parsed, metric, name, aliases).items():
                out[d] += v
        return out, (f"no last-week view for {', '.join(unsourced)}"
                     if unsourced else "")

    try:
        lb = rj.find_leaderboard_block(grid)
    except ValueError:
        lb = None
    return plan_block(grid, fgrid, section=ALLCAMP_SECTION, leaderboard=lb,
                      days_of=days_of, today=today, board="All Campaigns")


def sections_needed(org_grid, org_fgrid, allcamp_grid, allcamp_fgrid,
                    aliases, today: dt.date) -> List[str]:
    """The spec keys a run has to pull — [] on a normal day (no browser)."""
    from automations.all_campaigns_board import aggregate as agg
    from automations.all_campaigns_board import rollover as rj
    from automations.new_owners import board_add as ba
    from automations.org_sales_board import fill_section as fs
    from automations.org_sales_board import rollover as ro
    keys = set()
    if org_grid is not None:
        try:
            org = ro.find_org_block(org_grid)
        except StopIteration:
            org = None
        for label in ba.campaign_labels(org_grid):
            if label not in SECTION_SPECS:
                continue
            new = daily_blanks(org_grid, org_fgrid, label)[0]
            if not new and org:
                try:
                    lb = ba.find_campaign_leaderboard(org_grid, label)
                    new = leaderboard_blanks(org_grid, org_fgrid, org.header_row,
                                             lb["data_rows"], today)[0]
                except ValueError:
                    new = []
            if new:
                keys.add(SECTION_SPECS[label])
    if allcamp_grid is not None:
        names = {b.name for b in daily_blanks(allcamp_grid, allcamp_fgrid,
                                              ALLCAMP_SECTION)[0]}
        try:
            lb = rj.find_leaderboard_block(allcamp_grid)
            names |= {b.name for b in leaderboard_blanks(
                allcamp_grid, allcamp_fgrid, lb["header_row"], lb["data_rows"],
                today)[0]}
        except ValueError:
            pass
        names |= {b.name for b in delta_blanks(allcamp_grid, allcamp_fgrid)}
        if names and org_grid is not None:
            for label in agg.CAMPAIGN_SECTIONS:
                if label not in SECTION_SPECS:
                    continue
                try:
                    a = fs.find_daily_section(org_grid, label)
                except ValueError:
                    continue
                forms = set()
                for n in a.icd_rows:
                    forms |= fs._candidates_for(n, aliases)
                if any(fs._candidates_for(n, aliases) & forms for n in names):
                    keys.add(SECTION_SPECS[label])
    return sorted(keys)


# ------------------------------------------------------------------ apply

def _find_ws(sh, title: str):
    want = title.strip().lower()
    for w in sh.worksheets():
        if w.title.strip().lower() == want:
            return w
    raise ValueError(f"tab {title!r} not found")


def _grids(ws):
    from automations.recruiting_report.fill import _retry
    return (_retry(ws.get_all_values),
            _retry(lambda: ws.get_all_values(value_render_option="FORMULA")))


def _write(ws, updates, notes, dry_run, logfn, board):
    for n in notes:
        logfn(f"    {n}")
    for u in updates:
        logfn(f"    {board} {u['range']} <- {u['values'][0][0]}")
    if updates and not dry_run:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    logfn(f"  {board}: {len(updates)} cell(s)"
          + (" (dry-run)" if dry_run else " written" if updates else ""))


def _session(page, fn):
    if page is not None:
        return fn(page)
    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=False) as pg:
        return fn(pg)


def apply_org_boards(*, today: Optional[dt.date] = None, dry_run: bool = True,
                     page=None, org_tab: Optional[str] = None,
                     allcamp_tab: str = ALLCAMP_TAB,
                     boards=("org", "allcamp"), logfn=print) -> List[dict]:
    """The ORG board and All Campaigns, off ONE set of last-week pulls."""
    from automations.focus_office_att.aliases import load_aliases
    from automations.org_sales_board.tabs import BOARD_TAB
    from automations.recruiting_report.fill import open_by_key
    today = today or dt.datetime.now(CENTRAL).date()
    sh = open_by_key(ORG_SHEET_ID)
    org_ws = _find_ws(sh, org_tab or BOARD_TAB)
    org_grid, org_fgrid = _grids(org_ws)
    ac_ws = ac_grid = ac_fgrid = None
    if "allcamp" in boards:
        ac_ws = _find_ws(sh, allcamp_tab)
        ac_grid, ac_fgrid = _grids(ac_ws)
    aliases = load_aliases()
    keys = sections_needed(org_grid if "org" in boards else None, org_fgrid,
                           ac_grid, ac_fgrid, aliases, today)
    if not keys:
        # A newcomer in a Retail section still has to be NAMED, and that needs
        # no browser: plan with no pulls.
        pulls, failed = {}, []
    else:
        logfn(f"  newcomers found — pulling last week's view(s): {', '.join(keys)}")
        pulls, failed = _session(page, lambda pg: pull_sections(
            keys, today, pg, logfn=logfn))
    written: List[dict] = []
    if "org" in boards:
        try:
            ups, notes = plan_org(org_grid, org_fgrid, pulls, failed, aliases, today)
        except Refuse as e:
            ups, notes = [], [f"ORG board: {e} — nothing written"]
        _write(org_ws, ups, notes, dry_run, logfn, "ORG board")
        written += ups
    if "allcamp" in boards:
        try:
            ups, notes = plan_allcamp(ac_grid, ac_fgrid, org_grid, pulls, failed,
                                      aliases, today)
        except Refuse as e:
            ups, notes = [], [f"All Campaigns: {e} — nothing written"]
        _write(ac_ws, ups, notes, dry_run, logfn, "All Campaigns")
        written += ups
    return written


def apply_country(ws=None, *, today: Optional[dt.date] = None,
                  dry_run: bool = True, page=None, logfn=print) -> List[dict]:
    from automations.country_sales_board import fill as cf
    from automations.country_sales_board import pull as cp
    from automations.country_sales_board import rollover as cr
    from automations.focus_office_att.aliases import load_aliases
    today = today or dt.datetime.now(CENTRAL).date()
    if ws is None:
        from automations.country_sales_board.run import PROD_TAB
        from automations.recruiting_report.fill import open_by_key
        ws = open_by_key(COUNTRY_SHEET_ID).worksheet(PROD_TAB)
    grid, fgrid = _grids(ws)
    try:
        lb = cr.find_leaderboard(grid)
    except ValueError:
        lb = None
    new = (daily_blanks(grid, fgrid, cf.BLOCK_LABEL)[0]
           or (lb and leaderboard_blanks(grid, fgrid, lb["header_row"],
                                         lb["data_rows"], today)[0])
           or delta_blanks(grid, fgrid))
    if not new:
        logfn("  Country: nobody new without last week — nothing to do")
        return []
    aliases = load_aliases()
    reason = ""
    try:
        parsed = _session(page, lambda pg: cp.pull_icd_days(
            pg, OUT_DIR, last_week=True, today=today, logfn=logfn))
    except Exception as e:                                    # noqa: BLE001
        parsed = None
        reason = (f"last week's worksheet could not be pulled "
                  f"({type(e).__name__}: {str(e)[:90]})")
    if parsed is not None:
        # The Country view is NOT pinned (week_pin=False): its '(LW2)' sheet is
        # Tableau's previous calendar week. Only trust it when the frozen rows
        # can actually vouch for it — plan_block skips calibration below
        # MIN_CALIBRATION_ROWS, which is fine for All Campaigns (its sections are
        # calibrated on the ORG board) but not here.
        dfilled = daily_blanks(grid, fgrid, cf.BLOCK_LABEL)[1]
        checked, bad = calibrate(
            dfilled, lambda n: person_days(parsed, cp.SPEC.metric, n, aliases))
        if not trusted(checked, bad):
            reason = (f"'(LW2)' does not match the rows already frozen "
                      f"({len(bad)} of {checked})")
    if reason:
        logfn(f"  [!] Country: {reason} — no sales assumed: 0 (Eve 2026-09-15)")
        days_of = lambda n: (_no_sales(), "")
    else:
        days_of = lambda n: (person_days(parsed, cp.SPEC.metric, n, aliases), "")
    ups, notes = [], []
    try:
        ups, notes = plan_block(grid, fgrid, section=cf.BLOCK_LABEL, leaderboard=lb,
                                days_of=days_of, today=today, board="Country")
    except Refuse as e:
        ups, notes = [], [f"Country: {e} — nothing written"]
    _write(ws, ups, notes, dry_run, logfn, "Country")
    return ups


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="write to the Sheet (default: dry-run preview)")
    ap.add_argument("--board", choices=("all", "org", "allcamp", "country"),
                    default="all")
    ap.add_argument("--today", help="YYYY-MM-DD (testing)")
    ap.add_argument("--org-tab", default=None)
    ap.add_argument("--allcamp-tab", default=ALLCAMP_TAB)
    ap.add_argument("--country-tab", default=None,
                    help="default: the live Country Sales Board tab")
    a = ap.parse_args(argv)
    today = (dt.date.fromisoformat(a.today) if a.today
             else dt.datetime.now(CENTRAL).date())
    print(f"=== newcomer last week — {a.board} — "
          f"{'LIVE' if a.apply else 'DRY-RUN'} — today={today} "
          f"(last week = WE {last_week_ending(today)}) ===")
    boards = {"all": ("org", "allcamp"), "org": ("org",),
              "allcamp": ("org", "allcamp")}.get(a.board, ())
    if a.board == "allcamp":
        boards = ("allcamp",)
    if boards:
        apply_org_boards(today=today, dry_run=not a.apply, org_tab=a.org_tab,
                         allcamp_tab=a.allcamp_tab, boards=boards)
    if a.board in ("all", "country"):
        ws = None
        if a.country_tab:
            from automations.recruiting_report.fill import open_by_key
            ws = open_by_key(COUNTRY_SHEET_ID).worksheet(a.country_tab)
        apply_country(ws, today=today, dry_run=not a.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
