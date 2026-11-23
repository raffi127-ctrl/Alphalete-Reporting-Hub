"""'Teams — Current Week' screenshot off a board tab (Carlos 2026-11-19: "Send a
screenshot of the teams board on the NDS metrics thread and as text message to
the Aplayer and leaders chat").

The box sits under the '% on the Board' block: a header row whose first cell
starts with 'Teams' (labels in column B, the stats to its right), the campaign
total row, one row per team -- ranked by Apps by the sheet's own formulas --
and 'Unaccounted For'. Rows are found by label, never by index: the box moves
whenever the roster above it grows, and gets a row longer or shorter whenever
a team is added or emptied (the board's script, _refreshTeamsBoxOn).

Shot straight off the LIVE tab, like pct_block: the VA's basic filter only
covers the rep rows, and this box is below it, so no temp copy is needed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

_PROD_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
SHEET_ID = os.environ.get("SALES_BOARD_SHEET_ID", _PROD_SHEET_ID)

LABEL_COL = 2                      # column B holds the box's labels
HEADER_MARK = "total head count"   # the header row carries this column title
LAST_LABEL = "unaccounted for"     # the box's closing row
MAX_ROWS = 40                      # the script never lets the box run longer
READ_RANGE = "A1:T220"             # the reps and the box; never the whole tab


def _norm(v) -> str:
    return " ".join(str(v or "").split()).lower()


def _letter(c: int) -> str:
    out = ""
    while c:
        c, r = divmod(c - 1, 26)
        out = chr(65 + r) + out
    return out


def box_rows(g: List[List[str]]) -> Tuple[int, int, int]:
    """(header row, last row, last column), all 1-based, of the Teams box in
    grid `g`. The header is the row whose column-B cell starts with 'teams'
    and that names 'Total Head Count'; the box ends on its 'Unaccounted For'
    row (a team that just lost its last rep leaves a blank row above it until
    the script rebuilds, so look for the label, not for the first blank).
    Raises when the tab has no such box."""
    hdr = None
    for r, row in enumerate(g, start=1):
        cells = [_norm(c) for c in row]
        if len(cells) >= LABEL_COL and cells[LABEL_COL - 1].startswith("teams") \
                and HEADER_MARK in cells:
            hdr = r
            last_col = max(i for i, c in enumerate(cells, start=1) if c)
            break
    if hdr is None:
        raise RuntimeError("no 'Teams' box header (a row naming Total Head Count)")
    last = run_end = hdr
    in_run = True
    for r in range(hdr + 1, min(len(g), hdr + MAX_ROWS) + 1):
        row = g[r - 1]
        label = _norm(row[LABEL_COL - 1]) if len(row) >= LABEL_COL else ""
        if label == LAST_LABEL:
            last = r
            break
        if not label:
            in_run = False
        elif in_run:
            run_end = r
    if last == hdr:
        last = run_end
    if last == hdr:
        raise RuntimeError("the Teams box has no rows under its header")
    return hdr, last, last_col


def render_teams_box(tab_name: str, out_path, log=print) -> Path:
    """Export the tab's Teams box as a PNG at `out_path`."""
    from automations.pnl_office.run import _token
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.sales_boards import render as R

    sh = open_by_key(SHEET_ID)
    ws = sh.worksheet(tab_name)
    g = _retry(lambda: ws.get(READ_RANGE))
    try:
        hdr, last, last_col = box_rows(g)
    except RuntimeError as e:
        raise RuntimeError(f"{tab_name}: {e}") from None
    rng = f"{_letter(LABEL_COL)}{hdr}:{_letter(last_col)}{last}"
    img = R.export(SHEET_ID, ws.id, rng, _token())
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    log(f"[teams] {tab_name}: {rng} ({last - hdr - 1} row(s) under the header) "
        f"-> {out_path.name}")
    return out_path


# ------------------------------------------------------------ last week ----
# Carlos 2026-11-23 (Monday): "send a screenshot of the team totals for last
# week on there" -- the NDS Metrics thread. By Monday the board has rolled to
# the new week, so the live box reads 0 everywhere, and flipping the gold WE
# cell would rewrite the live board for everyone (and today's typed zeros
# would sit in the old week's Monday). Instead the box is rebuilt from the
# rep rows' own 'Last Wk' column with the box's own filters: campaign = the
# box's campaign, Term? = 0 (a terminated rep's apps are out of the box, as
# on the board), grouped by today's Team. Head counts are the live box's
# (today's roster); Sales Avg = Apps / Total Head Count, as the box does.
STAT_COLS = ("Apps", "Total Head Count", "Leaders", "Entry Level", "In Training",
             "Sales Avg by Rep")


def _col_of(row, name):
    n = _norm(name)
    return next((i for i, c in enumerate(row) if _norm(c) == n), None)


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def last_week_rows(g: List[List[str]]):
    """-> (week label e.g. 'WE 11.22', [(label, is_total, {stat: text})]):
    the campaign row first, the teams by last week's Apps (high first), then
    'Unaccounted For' -- the live box's shape, last week's Apps."""
    rh = next(i for i, row in enumerate(g)
              if len(row) > 1 and _norm(row[1]) == "rep"
              and any(_norm(c) == "last wk" for c in row))
    H = g[rh]
    i_last, i_camp = _col_of(H, "Last Wk"), _col_of(H, "Campaign")
    i_team, i_term = _col_of(H, "Team"), _col_of(H, "Term?")
    if None in (i_last, i_camp, i_team):
        raise RuntimeError("the rep header has no Last Wk / Campaign / Team column")
    hdr, last, _last_col = box_rows(g)
    bh = g[hdr - 1]
    stat_i = {s: _col_of(bh, s) for s in STAT_COLS}
    box = []
    for r in range(hdr + 1, last + 1):
        row = list(g[r - 1]) + [""] * 60
        label = row[LABEL_COL - 1].strip()
        if label:
            box.append((label, row))
    camp_label = box[0][0]
    width = max(i_last, i_camp, i_team, i_term or 0) + 1
    reps, camp_code = [], ""
    for row in g[rh + 1:]:
        row = list(row) + [""] * width
        if _norm(row[1]) == _norm(camp_label):
            camp_code = row[i_camp].strip()          # the total row's own campaign cell
            break
        if row[1].strip():
            reps.append(row)
    if not camp_code:
        camp_code = max({r[i_camp].strip() for r in reps if r[i_camp].strip()} or {""},
                        key=lambda c: sum(1 for r in reps if r[i_camp].strip() == c))

    def counted(r):
        term = r[i_term].strip() if i_term is not None else ""
        return r[i_camp].strip() == camp_code and term in ("", "0")

    def apps(team):
        return sum(_num(r[i_last]) for r in reps if counted(r)
                   and (team is None or r[i_team].strip() == team))

    out = []
    for label, row in box:
        if _norm(label) == _norm(camp_label):
            a = apps(None)
        elif _norm(label) == LAST_LABEL:
            a = apps("")
        else:
            a = apps(label)
        stats = {}
        for s in STAT_COLS[1:5]:
            i = stat_i.get(s)
            stats[s] = row[i].strip() if i is not None else ""
        hc = _num(stats.get("Total Head Count"))
        stats["Apps"] = "%d" % a
        stats["Sales Avg by Rep"] = ("%.1f" % (a / hc)) if hc else ""
        out.append((label, _norm(label) == _norm(camp_label), stats))
    first, teams, unacc = out[:1], out[1:], []
    if teams and _norm(teams[-1][0]) == LAST_LABEL:
        teams, unacc = teams[:-1], teams[-1:]
    teams.sort(key=lambda t: (-_num(t[2]["Apps"]), t[0].lower()))
    week = ""
    for row in g:
        if len(row) > 3 and _norm(row[1]) == "last week" and str(row[3]).strip():
            week = str(row[3]).strip()
            break
    return week, first + teams + unacc


def render_last_week(tab_name: str, out_path, log=print) -> Path:
    """Last week's Teams box (see last_week_rows) as a PNG at `out_path`."""
    from automations.b2b_metrics.rep_boards import render_table_png
    from automations.recruiting_report.fill import open_by_key, _retry
    ws = open_by_key(SHEET_ID).worksheet(tab_name)
    g = _retry(lambda: ws.get("A1:AT220"))
    week, rows = last_week_rows(g)
    table = [(label, "", is_total, {s: {"rate": v, "color": ""} for s, v in stats.items()})
             for label, is_total, stats in rows]
    sub = ("%s — Apps = each rep's Last Wk on the %s, grouped by today's Team "
           "(terminated reps left out, like the board's Teams box); head counts are "
           "today's roster" % (week or "last week", tab_name))
    out = render_table_png("TEAMS — LAST WEEK%s" % ((" (%s)" % week) if week else ""),
                           sub, list(STAT_COLS), table, Path(out_path))
    log("[teams] %s last week %s: %s" % (tab_name, week,
                                        ", ".join("%s %s" % (l, s["Apps"]) for l, _t, s in rows)))
    return out
