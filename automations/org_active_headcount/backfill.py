"""Seed the history columns (F..L) from the focus reports' own weekly rows.

WHY THIS EXISTS. The tab was born with seven empty history columns, and Tableau
cannot give them back: the NDS and BOX trackers have no date control at all, and
the ATT/B2B pagers only reach one week back through their `(LW)` sheets. So the
past is simply not in the source any more.

But it IS in the focus reports. Every focus tab is a grid of WEEK COLUMNS, and
one of its rows is `Active Headcount on Tableau` (`Active Selling Heads` on the
NDS/BOX tabs) — the same number this report writes, recorded every week for
months. Eve, 2026-09-07: "si para NDS y box ayuda, podés mirar los focus reports
de semanas anteriores de dueños que hagan esas campañas". It does: NDS came back
with all seven weeks (41, 42, 39, 31, 36, 36, 36 for Colten Wright), and so did
Fiber, B2B and BOX.

NOTHING IS RECOMPUTED. A cell is copied across exactly as the focus report wrote
it, into the column whose `WE mm.dd` header names the same week. A week the focus
tab left blank stays blank here — a gap in the record is a fact about the record.

TWO WORKBOOKS, TWO NAMING SCHEMES, and the join has to survive both:
  • ATT Fiber lives on Raf's `ATT Program - Focus Report`, one tab per ICD named
    with the bare name ('Jacob Dover').
  • Everything else lives on `Alphalete Org 1on1s - Focus Reports`, where a tab
    is '<name> - <CAMPAIGN>' with the campaign in the title — which is what makes
    Carlos Hidalgo's two rows separable: 'Carlos Hidalgo -B2B' (no space, as
    typed) is a different tab from his BOX one.
  • A tab whose name starts 'x ' or 'x-' is RETIRED and is never read. That is
    how Carlos's old BOX tab is excluded rather than silently supplying numbers
    for a campaign he is still on under a different arrangement.

    python -m automations.org_active_headcount.backfill            # dry-run
    python -m automations.org_active_headcount.backfill --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Tuple

from automations.recruiting_report import fill as rfill
from automations.org_active_headcount import sources as src
from automations.org_active_headcount import structure as st

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                  # noqa: BLE001
    pass

ORG_FOCUS_SHEET = "1C6BLttOSZhs_dREySac19XkxnMl-Ab_sYacNSl2l6AQ"   # Alphalete Org 1on1s

# The row that carries the number, under either of its two names. Matched on
# col B, lowercased — `opt_nds.ROW_LABEL_ALIASES` treats these as the same row
# and so must we, or every NDS and BOX tab reads as having no headcount at all.
HEADCOUNT_LABELS = ("active headcount on tableau", "active selling heads")

# Campaign box -> (workbook, tab-name campaign suffix). None = Raf's workbook,
# where tabs are named with the bare ICD name and no campaign suffix.
BOX_TO_FOCUS: Dict[str, Tuple[Optional[str], Optional[str]]] = {
    "ATT Fiber Team":   (None, None),
    "ATT NDS Team":     (ORG_FOCUS_SHEET, "NDS"),
    "B2B":              (ORG_FOCUS_SHEET, "B2B"),
    "BOX":              (ORG_FOCUS_SHEET, "BOX"),
    "Retail NL":        (ORG_FOCUS_SHEET, "Retail"),
    "Retail Internet":  (ORG_FOCUS_SHEET, "Retail"),
    "Retail JE":        (ORG_FOCUS_SHEET, "JE"),
}

# BOARD name -> the name its FOCUS TAB uses. Separate from `sources.ALIASES`,
# which maps to what TABLEAU calls people: the two disagree often enough that
# sharing one map would be wrong. 'Roshan Amin Ahmad' is the clearest case —
# Tableau drops the middle name, his focus tab keeps it.
FOCUS_TAB_ALIASES: Dict[str, str] = {
    "rafaelhidalgo":   "Raf Hidalgo",
    "muhammadhaque":   "Hammad Haque",
    "josephdelgado":   "Joe Delgado",
    "maxamadaden":     "Maxamed Aden",
    "atefchoudhury":   "Atef Choudhry",
    "akibchowdhury":   "Boaktear Chowdhury",
}


def _focus_name(board_name: str) -> str:
    return FOCUS_TAB_ALIASES.get(src.norm(board_name), board_name)


def _is_retired(tab: str) -> bool:
    """'x - Carlos Hidalgo - BOX' / 'x- Carl Foss - NDS' are retired tabs."""
    return bool(re.match(r"^\s*x\s*-", tab, re.I))


def find_tab(titles: List[str], icd: str, suffix: Optional[str]) -> Optional[str]:
    """The focus tab for this ICD on this campaign, or None.

    Matches on the NORMALISED name being contained in the normalised tab title,
    so 'Boaktear Chowdhury (Akib/MJ) - Retail' is found by 'Boaktear Chowdhury'.
    When a campaign suffix is given the title must carry it too — otherwise
    Carlos Hidalgo's B2B and BOX tabs are indistinguishable and one of his two
    board rows gets the other's numbers.
    """
    want = src.norm(_focus_name(icd))
    suf = src.norm(suffix) if suffix else None
    hits = []
    for t in titles:
        if _is_retired(t):
            continue
        nt = src.norm(t)
        if want not in nt:
            continue
        if suf and suf not in nt:
            continue
        hits.append(t)
    if not hits:
        return None
    # Prefer the shortest title: 'Ryan Mcspadden - BOX' over a longer variant.
    return sorted(hits, key=len)[0]


def _parse_date(s) -> Optional[dt.date]:
    s = str(s or "").strip()
    for f in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%y"):
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def read_history(grid: List[List], weeks: List[dt.date]) -> Dict[dt.date, str]:
    """{week ending: value} off a focus tab, for the weeks asked for.

    Finds the headcount row by its label, then the nearest DATE HEADER row above
    it — the tabs stack several date-headed blocks (recruiting funnel on top,
    the OPT block below), and only the block the row belongs to has the right
    columns. 'Nearest above' is what ties them together without hardcoding a row.
    """
    out: Dict[dt.date, str] = {}
    for i, row in enumerate(grid):
        label = str(row[1]).strip().lower() if len(row) > 1 else ""
        if label not in HEADCOUNT_LABELS:
            continue
        for j in range(i - 1, max(i - 30, -1), -1):
            cols = {d: k for k, c in enumerate(grid[j]) if (d := _parse_date(c))}
            if len(cols) < 5:                 # a real week-header row, not a stray date
                continue
            for w in weeks:
                k = cols.get(w)
                if k is not None and k < len(row) and str(row[k]).strip():
                    out.setdefault(w, str(row[k]).strip())
            break
    return out


def plan(board_grid: List[List], history: Dict[str, Dict[str, Dict[dt.date, str]]]
         ) -> Tuple[List[Tuple[str, object]], Dict[str, List[str]]]:
    """([(A1, value)], {box: [ICDs with nothing to seed]}). Pure, no I/O.

    `history` is {box: {ICD: {week ending: value}}}. Only EMPTY history cells are
    written: a column that already carries a number was put there by a real run
    of this report and outranks a copy of somebody else's sheet.
    """
    updates: List[Tuple[str, object]] = []
    gaps: Dict[str, List[str]] = {}
    for box in st.find_boxes(board_grid):
        per_icd = history.get(box["campaign"], {})
        cols = [(c, st.parse_we(lbl, _year_for(lbl))) for c, lbl in box["week_cols"]]
        missing = []
        for row, icd in box["rows"]:
            got = per_icd.get(icd)
            if not got:
                missing.append(icd)
                continue
            usable = False
            for c, week in cols:
                if week is None or week not in got:
                    continue
                usable = True
                if st.cell(board_grid, row, c):
                    continue                   # already filled — leave it alone
                updates.append((f"{st.a1col(c)}{row}", _num(got[week])))
            if not usable:
                # NOT the same as "wrote nothing": a row whose history is
                # already complete has nothing to write and is fine. Only a row
                # for which no source carried ANY of these weeks is a gap.
                missing.append(icd)
        if missing:
            gaps[box["campaign"]] = missing
    return updates, gaps


def _weeks_of(board_grid: List[List]) -> List[dt.date]:
    """Every week the board's history columns name, newest first."""
    weeks: List[dt.date] = []
    for box in st.find_boxes(board_grid):
        for _c, lbl in box["week_cols"]:
            w = st.parse_we(lbl, _year_for(lbl))
            if w and w not in weeks:
                weeks.append(w)
    return weeks


def _year_for(label: str) -> int:
    """The year a 'WE mm.dd' header belongs to. The headers carry none, and the
    seven columns are always within a few months of today, so anchor on today
    and step back a year for a label that would otherwise land in the future."""
    today = dt.date.today()
    d = st.parse_we(label, today.year)
    if d is None:
        return today.year
    return today.year - 1 if d > today + dt.timedelta(days=180) else today.year


def _num(s: str):
    t = str(s).replace(",", "").strip()
    try:
        return int(float(t))
    except ValueError:
        return s


def collect(board_grid: List[List], logfn=print, skip=()
            ) -> Dict[str, Dict[str, Dict[dt.date, str]]]:
    """Read every focus tab this board needs, once each.

    `skip` names boxes whose focus tabs must NOT be read because a better source
    is going to supply them. That is not a preference, it is a correction: the
    focus tabs are second-hand copies and at least one of them has drifted off
    its own source. On 2026-09-07 the tab 'Boaktear Chowdhury (Akib/MJ) -
    Retail' carried 7 6 7 7 7 7 8 across the seven weeks — which is AMJAD
    MALHAS's SARA series exactly, not Boaktear's own (4 5 5 5 5 6 6). Copying it
    put one ICD's headcount under another ICD's name, and every total that
    included it was wrong by the difference. SARA is what opt_retail reads to
    write those tabs in the first place, so for Retail the source wins over the
    copy. (Ronald Dawson's tab, checked the same way, agrees with SARA — so this
    is one bad tab, not a broken convention.)"""
    weeks = []
    for box in st.find_boxes(board_grid):
        for _c, lbl in box["week_cols"]:
            w = st.parse_we(lbl, _year_for(lbl))
            if w and w not in weeks:
                weeks.append(w)
    books: Dict[Optional[str], tuple] = {}
    out: Dict[str, Dict[str, Dict[dt.date, str]]] = {}
    for box in st.find_boxes(board_grid):
        if skip and box["campaign"] in skip:
            continue
        # Match the box LABEL loosely: Eve's renames ("ATT NDS Team" ->
        # "ATT NDS Team Headcount") made the exact lookup fall through to
        # (None, None), which silently sent B2B looking in Raf's workbook and
        # found nobody. [[structure.match_box]]
        sheet_id, suffix = next(
            (v for k, v in BOX_TO_FOCUS.items()
             if st.match_box(k, box["campaign"])), (None, None))
        key = sheet_id or "raf"
        if key not in books:
            sh = rfill.open_by_key(sheet_id or rfill.SPREADSHEET_ID)
            books[key] = (sh, [w.title for w in sh.worksheets()])
        sh, titles = books[key]
        per_icd: Dict[str, Dict[dt.date, str]] = {}
        for _row, icd in box["rows"]:
            tab = find_tab(titles, icd, suffix)
            if not tab:
                logfn(f"  {box['campaign']:18s} {icd:22s} no focus tab")
                continue
            hist = read_history(sh.worksheet(tab).get_all_values(), weeks)
            logfn(f"  {box['campaign']:18s} {icd:22s} <- {tab!r}: "
                  f"{len(hist)}/{len(weeks)} week(s)")
            if hist:
                per_icd[icd] = hist
        out[box["campaign"]] = per_icd
    return out


def sara_backfill(weeks: List[dt.date], logfn=print) -> Dict[str, Dict[dt.date, str]]:
    """{ICD: {week: active reps}} for the Retail boxes, straight from Tableau.

    The ONE source in this report that can be asked about a past week: SARA
    Plus takes Min/Max Date as URL params, so each of the seven weeks is its own
    pull. Everything else here is a current-week snapshot, which is why the rest
    of the history has to come from the focus reports.

    Costly on purpose — one browser download per week — so it only runs when
    asked for (`--sara`), and only the weeks still missing get pulled.
    """
    from automations.alphalete_org_report import opt_retail as orl
    from automations.shared.tableau_patchright import scrape_view_data_patchright
    out: Dict[str, Dict[dt.date, str]] = {}
    for w in weeks:
        target = CACHE = orl.OUTPUT_DIR / f"_hc_sara_{w:%Y%m%d}.csv"
        label = w.strftime("%m/%d/%y")
        logfn(f"  SARA {label} -> {target.name}")
        try:
            if not target.exists() or target.stat().st_size < 500:
                scrape_view_data_patchright(
                    orl._sara_view_data_url(label), target, verbose=False,
                    activate_xy=orl.RETAIL_SARA_ACTIVATE_XY,
                    scrape_kwargs=dict(jump_every=None, scroll_step=0.35,
                                       scroll_wait_ms=1800, stale_max=30))
            totals = orl.parse_sara_view_data(target)
        except Exception as e:                                    # noqa: BLE001
            logfn(f"    SKIPPED {label}: {type(e).__name__}: {e}")
            continue
        for name, rec in totals.items():
            # opt_retail keys its dict with ITS OWN normalisation ('amjad
            # malhas', spaces kept); the board side asks with src.norm
            # ('amjadmalhas'). Normalising here is what makes the two meet —
            # without it every SARA week silently matched nobody.
            out.setdefault(src.norm(name), {})[w] = str(rec.get("_active_reps", 0))
        logfn(f"    {len(totals)} ICD(s)")
        _ = CACHE
    return out


def merge_sara(history: Dict[str, Dict[str, Dict[dt.date, str]]],
               board_grid: List[List], sara: Dict[str, Dict[dt.date, str]],
               logfn=print) -> None:
    """Fold the SARA weeks into the Retail boxes, without overwriting a week the
    focus report already supplied (that one came from the report that owns the
    number)."""
    for box in st.find_boxes(board_grid):
        if not box["campaign"].lower().startswith("retail"):
            continue
        if box["campaign"] == "Retail JE":
            continue
        per_icd = history.setdefault(box["campaign"], {})
        for _row, icd in box["rows"]:
            key = src.norm(src.source_name(icd))
            got = sara.get(key)
            if not got:
                continue
            slot = per_icd.setdefault(icd, {})
            added = [w for w in got if w not in slot]
            for w in added:
                slot[w] = got[w]
            if added:
                logfn(f"  {box['campaign']:18s} {icd:22s} +{len(added)} week(s) from SARA")


NDS_LW_CACHE = "_hc_nds_lw.csv"


def nds_last_week(week_end: dt.date, logfn=print) -> Dict[str, Dict[dt.date, str]]:
    """{ICD: {week: rep count}} for the week that just closed, off NDS's own
    `TT-LineN/P Detail (LW)` crosstab.

    The NDS tracker looked like a dead end — no date control, so no past week —
    until the Crosstab dialog turned out to list a `(LW)` twin of every sheet.
    That twin is the closed week, and it carries the WHOLE roster, including the
    three ICDs whose focus tabs never had their headcount row filled in (Frank
    Matos, Joe Delgado, Jose Velasquez).

    Cross-checked before being trusted (2026-09-07): for the seven ICDs whose
    focus tabs DID carry the week, the two sources agree — Jairo Ruiz 40 and
    Colten Wright 41 in both. Two independent records of the same number is the
    only reason this is a source and not a guess.
    """
    from automations.alphalete_org_report.opt_nds import parse_tt_detail, OUTPUT_DIR
    path = OUTPUT_DIR / NDS_LW_CACHE
    if not path.exists():
        logfn(f"  NDS (LW): no crosstab at {path} - download it first")
        return {}
    detail = parse_tt_detail(path)
    out: Dict[str, Dict[dt.date, str]] = {}
    for name, rec in detail.items():
        rc = str(rec.get("rep_count", "")).strip()
        if rc:
            out[src.norm(name)] = {week_end: rc}
    logfn(f"  NDS (LW): {len(out)} ICD(s) for {week_end}")
    return out


def merge_by_norm(history: Dict[str, Dict[str, Dict[dt.date, str]]],
                  board_grid: List[List], box_name: str,
                  by_norm: Dict[str, Dict[dt.date, str]], logfn=print) -> None:
    """Fold a {normalised ICD: {week: value}} source into one box, without
    overwriting a week that already has a value."""
    for box in st.find_boxes(board_grid):
        if box["campaign"] != box_name:
            continue
        per_icd = history.setdefault(box_name, {})
        for _row, icd in box["rows"]:
            got = by_norm.get(src.norm(src.source_name(icd)))
            if not got:
                continue
            slot = per_icd.setdefault(icd, {})
            added = [w for w in got if w not in slot]
            for w in added:
                slot[w] = got[w]
            if added:
                logfn(f"  {box_name:18s} {icd:22s} +{len(added)} week(s)")


def run(*, apply_changes: bool = False, live_tab: bool = True,
        sara: bool = False, nds_lw: bool = False, je_lw: bool = False,
        box: bool = False, je: bool = False, logfn=print) -> dict:
    tab = st.BOARD_TAB if live_tab else st.SANDBOX_TAB
    sh = rfill.open_by_key(st.SHEET_ID)
    ws = next((w for w in sh.worksheets() if w.title.strip() == tab), None)
    if ws is None:
        raise ValueError(f"tab {tab!r} not found in the workbook")
    logfn(f"tab: {ws.title!r}   {'APPLY' if apply_changes else 'DRY-RUN'}")
    grid = ws.get_all_values()
    logfn("\n== reading the focus reports ==")
    # Retail comes from SARA when it is available: the focus tab is a copy
    # and one of them is demonstrably wrong (see collect.__doc__).
    # Retail and BOX come from their own Tableau views when those are being
    # pulled: the focus tabs are copies, and both have been caught carrying
    # numbers that are not the ICD's own (see collect.__doc__ for Retail; for
    # BOX the tabs read a flat 14 and 13 for seven straight weeks while the
    # Daily Tracker shows them moving).
    skip = list(("Retail NL", "Retail Internet") if sara else ())
    if box:
        skip.append("BOX")
    history = collect(grid, logfn=logfn, skip=tuple(skip))
    if sara:
        logfn("\n== SARA, one pull per week ==")
        weeks = []
        for box in st.find_boxes(grid):
            for _c, lbl in box["week_cols"]:
                w = st.parse_we(lbl, _year_for(lbl))
                if w and w not in weeks:
                    weeks.append(w)
        merge_sara(history, grid, sara_backfill(weeks, logfn=logfn), logfn=logfn)
    if nds_lw:
        logfn("\n== NDS, last week off the (LW) crosstab ==")
        from automations.org_sales_board.week import reporting_sunday
        lw = reporting_sunday(dt.date.today()) - dt.timedelta(days=7)
        merge_by_norm(history, grid, "ATT NDS Team",
                      nds_last_week(lw, logfn=logfn), logfn=logfn)
    if je_lw:
        logfn("\n== JE, last week off 'Weekly Metrics by ICD' ==")
        from automations.org_active_headcount import pull as _pull
        from automations.org_sales_board.week import reporting_sunday as _rs
        lw = _rs(dt.date.today()) - dt.timedelta(days=7)
        merge_by_norm(history, grid, "Retail JE",
                      {k: {lw: str(v)} for k, v in
                       _pull.je_week(lw, skip_download=True,
                                     logfn=logfn).items()},
                      logfn=logfn)
    if box:
        logfn("\n== BOX, one pinned pull per week ==")
        from automations.org_active_headcount import pull as _p
        by_week: Dict[str, Dict[dt.date, str]] = {}
        for w in _weeks_of(grid):
            try:
                for k, v in _p.box_week(w, logfn=logfn).items():
                    by_week.setdefault(k, {})[w] = str(v)
            except Exception as e:                                # noqa: BLE001
                logfn(f"    SKIPPED {w}: {type(e).__name__}: {e}")
        merge_by_norm(history, grid, "BOX", by_week, logfn=logfn)
    if je:
        logfn("\n== JE, one pull per week ==")
        from automations.org_active_headcount import pull as _pj
        je_by_week: Dict[str, Dict[dt.date, str]] = {}
        for w in _weeks_of(grid):
            try:
                for k, v in _pj.je_week(w, logfn=logfn).items():
                    je_by_week.setdefault(k, {})[w] = str(v)
            except Exception as e:                                # noqa: BLE001
                logfn(f"    SKIPPED {w}: {type(e).__name__}: {e}")
        merge_by_norm(history, grid, "Retail JE", je_by_week, logfn=logfn)
    updates, gaps = plan(grid, history)
    logfn("\n== history cells ==")
    for a1, v in updates:
        logfn(f"  {a1:>6s} <- {v}")
    for campaign, names in gaps.items():
        logfn(f"  [no history] {campaign}: {', '.join(names)}")
    n = 0
    if apply_changes and updates:
        body = [{"range": a1, "values": [[v]]} for a1, v in updates]
        rfill._retry(ws.batch_update, body, value_input_option="USER_ENTERED")
        n = len(updates)
    logfn(f"\n{len(updates)} cell(s) planned, {n} written.")
    return {"planned": len(updates), "written": n, "gaps": gaps}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write the cells")
    ap.add_argument("--sandbox", action="store_true",
                    help="target the sandbox copy instead of the live tab")
    ap.add_argument("--sara", action="store_true",
                    help="also pull the Retail weeks from Tableau (slow: one "
                         "browser download per week)")
    ap.add_argument("--nds-lw", action="store_true",
                    help="also read NDS's (LW) crosstab for the closed week")
    ap.add_argument("--je-lw", action="store_true",
                    help="also read JE's 'Weekly Metrics by ICD' for the closed week")
    ap.add_argument("--box", action="store_true",
                    help="pull BOX's Daily Tracker once per week (slow)")
    ap.add_argument("--je", action="store_true",
                    help="pull JE's Weekly Metrics once per week (slow)")
    a = ap.parse_args()
    run(apply_changes=a.apply, live_tab=not a.sandbox, sara=a.sara,
        nds_lw=a.nds_lw, je_lw=a.je_lw, box=a.box, je=a.je)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
