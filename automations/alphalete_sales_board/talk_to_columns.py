"""Add the three Talk-To columns to every day block of a Sales Board tab.

WHAT EVE BUILT BY HAND. On 'Sales Board WE 9.6 Eve Edits' she widened THU's
day block from the usual eight columns

    Apps | Int | Int Up | DTV | NL | TK | Cx | Roll Call

to eleven, by slipping three new sub-headers in AFTER `TK` and BEFORE `Cx`:

    ... | TK | Total Talk-To's | % of TT's per knock | AVG app per TT | Cx | ...

plus a nested (depth-2) column group over just those three, so they fold away
inside the day's own group. This script copies that shape onto the other six
days of the same tab.

WHY A SCRIPT AND NOT SIX COPY-PASTES. Doing it by hand means picking the right
insert point in six collapsed blocks; one mis-click puts the trio inside `Cx`
and the daily fill starts writing knocks into a cancel column. The insert point
is found the way every fill on this board finds one -- weekday label in row 1,
sub-header in row 3 UNDER it, never an index. [[feedback_no_hardcoded_columns]]

WHAT IT COPIES. The template columns from the sub-header row down to their last
non-empty row -- the row-3 header with its green fill, the empty rep rows, and
the TOTALS-row `SUMIF`. The per-rep cells are empty on THU, so they land empty
everywhere: nothing is invented.

NOT THE WHOLE COLUMN, on purpose. Row 1-2 and the second section's header row
are MERGED across each day block, and Sheets refuses a paste that partially
intersects a merge. Those merged headers do not need copying anyway -- an
insert INSIDE a merge widens it by itself.

WHAT IT DOES NOT TOUCH. The day's `Apps` ARRAYFORMULA does not mention the trio
on THU either, so it is left exactly as it is. No rep row is written.

CAREFUL -- THIS CHANGES THE BLOCK WIDTH from 8 columns to 11 on every day.
Anything that walks a day block by OFFSET instead of by header will read the
wrong column the moment this ships to a live tab; that exact bug has already
bitten three readers on this board.
[[project_sales-board-en-to-tk-broke-a-third-reader]]

    python -m automations.alphalete_sales_board.talk_to_columns              # preview
    python -m automations.alphalete_sales_board.talk_to_columns --apply
    python -m automations.alphalete_sales_board.talk_to_columns --tab "Sales Board WE 9.13"
"""
from __future__ import annotations

import argparse
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

# The workbook, the three header rows and the weekday labels are the Energy /
# TK fill's geometry. Same board, one definition.
from automations.energy_slack_fill.run import DAY_LABELS, DAY_ROW, SUB_ROW, PROD_SHEET_ID

SANDBOX_TAB = "Sales Board WE 9.6 Eve Edits"

# The three columns, in order, exactly as row 3 spells them on THU.
TRIO = ("Total Talk-To's", "% of TT's per knock", "AVG app per TT")

# Where they go: straight after this sub-header, still inside the day's group.
ANCHOR = "TK"


def _col_letter(c: int) -> str:
    s = ""
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(grid, row: int, col: int) -> str:
    try:
        return str(grid[row - 1][col - 1]).strip()
    except Exception:  # noqa: BLE001 -- short rows are blanks
        return ""


def day_blocks(grid) -> dict:
    """{'MON': (first_col, last_col)} -- 1-based, by the row-1 weekday labels."""
    width = max((len(r) for r in grid), default=0)
    starts = []
    for c in range(1, width + 1):
        lab = _cell(grid, DAY_ROW, c).upper()
        if lab in DAY_LABELS:
            starts.append((lab, c))
    out = {}
    for i, (lab, c) in enumerate(starts):
        end = starts[i + 1][1] - 1 if i + 1 < len(starts) else width
        out[lab] = (c, end)
    return out


def sub_col(grid, block, header: str):
    """The column of a row-3 sub-header inside one day block, or None."""
    lo, hi = block
    want = header.strip().lower()
    for c in range(lo, hi + 1):
        if _cell(grid, SUB_ROW, c).lower() == want:
            return c
    return None


def plan(grid):
    """(template_day, template_first_col, [(day, anchor_col, needs_insert)]).

    `needs_insert` is False for a day whose block is ALREADY as wide as the
    template's but has no headers in the new columns -- an interrupted run.
    Re-running then finishes the paste instead of inserting three more columns.
    """
    blocks = day_blocks(grid)
    template = None
    for lab in DAY_LABELS:
        b = blocks.get(lab)
        if not b:
            continue
        cols = [sub_col(grid, b, h) for h in TRIO]
        if all(cols) and cols == list(range(cols[0], cols[0] + 3)):
            template = (lab, cols[0], b[1] - b[0] + 1)
            break
    todo = []
    for lab in sorted(blocks, key=lambda k: blocks[k][0]):
        if template and lab == template[0]:
            continue
        b = blocks[lab]
        if any(sub_col(grid, b, h) for h in TRIO):
            continue                      # already has some of it -- leave it alone
        anchor = sub_col(grid, b, ANCHOR)
        if anchor is None:
            print("  ! %s: no %r sub-header in %s..%s -- skipped"
                  % (lab, ANCHOR, _col_letter(b[0]), _col_letter(b[1])))
            continue
        width = b[1] - b[0] + 1
        todo.append((lab, anchor, not (template and width >= template[2])))
    return (template[0] if template else None,
            template[1] if template else None, todo)


def widths(ss, tab: str, first_col: int) -> list:
    meta = ss.fetch_sheet_metadata({
        "ranges": ["'%s'!%s1:%s1" % (tab, _col_letter(first_col),
                                     _col_letter(first_col + 2))],
        "fields": "sheets(data(columnMetadata(pixelSize)))",
    })
    cm = meta["sheets"][0]["data"][0].get("columnMetadata", [])
    return [c.get("pixelSize") for c in cm][:3]


def _no_rep(row: int, expr: str, name_col_letter: str) -> str:
    """`expr`, but blank on a row that holds no rep.

    Every one of these columns reads 0 when there is no data, because a blank
    cell reads as a broken report (Eve, 2026-09-08). A row with nobody in it is
    the exception: the board keeps filler rows between the last rep and TOTALS,
    and a strip of 0.0% down empty rows is noise, not information. The test is
    the NAME cell, so the formula lights up the moment somebody is typed in.
    """
    return '=IF($%s%d="","",%s)' % (name_col_letter, row, expr.lstrip("="))


def number_format(ws, col: int, first_row: int, last_row: int,
                  kind: str, pattern: str) -> dict:
    """A request that sets one column's number format over a row range.

    `updateCells` and NOT `repeatCell`, which is the whole reason this is a
    function. The board carries a live FILTER, and repeatCell silently skips
    every row the filter hides -- so the reps Eve has filtered out keep the raw
    `0.1443298969` while everyone else reads `14.4%`, and it only shows up the
    day somebody clears the filter. updateCells addresses rows by index and
    formats them all.
    """
    cell = {"userEnteredFormat": {
        "numberFormat": {"type": kind, "pattern": pattern}}}
    return {"updateCells": {
        "range": {"sheetId": ws.id, "startRowIndex": first_row - 1,
                  "endRowIndex": last_row,
                  "startColumnIndex": col - 1, "endColumnIndex": col},
        "rows": [{"values": [cell]} for _ in range(last_row - first_row + 1)],
        "fields": "userEnteredFormat.numberFormat",
    }}


def _has_group(ss, ws, start0: int, end0: int) -> bool:
    """Is there already a column group over exactly these columns?"""
    meta = ss.fetch_sheet_metadata({"fields": "sheets(properties(sheetId),columnGroups)"})
    for sh in meta.get("sheets", []):
        if sh.get("properties", {}).get("sheetId") != ws.id:
            continue
        for g in sh.get("columnGroups", []) or []:
            r = g.get("range", {})
            if r.get("startIndex") == start0 and r.get("endIndex") == end0:
                return True
    return False


def hidden_cols(ss, tab: str, last_col: int) -> list:
    """hiddenByUser per column, 1-based. A COLLAPSED day group hides its members
    this way, and a freshly inserted column does not inherit it -- without this
    the trio would stick out of six folded-up days."""
    meta = ss.fetch_sheet_metadata({
        "ranges": ["'%s'!A1:%s1" % (tab, _col_letter(last_col))],
        "fields": "sheets(data(columnMetadata(hiddenByUser)))",
    })
    cm = meta["sheets"][0]["data"][0].get("columnMetadata", [])
    return [False] + [bool(c.get("hiddenByUser")) for c in cm]


def add_for_day(ss, ws, anchor_col: int, tmpl_first: int, px: list,
                last_row: int, insert: bool = True, hide: bool = False) -> None:
    """Make room after `anchor_col` and paste the template columns onto it.

    The insert goes in its own request so the paste that follows sees the
    widened sheet; `tmpl_first` is the template's column AFTER that insert,
    which the caller tracks (the template shifts right whenever a day to its
    LEFT is widened).
    """
    gid = ws.id
    new0 = anchor_col            # 0-based index of the first new column
    if insert:
        ss.batch_update({"requests": [{
            "insertDimension": {
                "range": {"sheetId": gid, "dimension": "COLUMNS",
                          "startIndex": new0, "endIndex": new0 + 3},
                "inheritFromBefore": True,
            }
        }]})

    src0 = tmpl_first - 1
    reqs = [
        {"copyPaste": {
            "source": {"sheetId": gid, "startRowIndex": SUB_ROW - 1,
                       "endRowIndex": last_row,
                       "startColumnIndex": src0, "endColumnIndex": src0 + 3},
            "destination": {"sheetId": gid, "startRowIndex": SUB_ROW - 1,
                            "endRowIndex": last_row,
                            "startColumnIndex": new0, "endColumnIndex": new0 + 3},
            "pasteType": "PASTE_NORMAL",
        }},
    ]
    # Only if the fold isn't there already -- asking twice nests a THIRD level.
    if not _has_group(ss, ws, new0, new0 + 3):
        reqs.append({"addDimensionGroup": {
            "range": {"sheetId": gid, "dimension": "COLUMNS",
                      "startIndex": new0, "endIndex": new0 + 3}
        }})
    for i, size in enumerate(px):
        if not size:
            continue
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS",
                      "startIndex": new0 + i, "endIndex": new0 + i + 1},
            "properties": {"pixelSize": size},
            "fields": "pixelSize",
        }})
    if hide:
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS",
                      "startIndex": new0, "endIndex": new0 + 3},
            "properties": {"hiddenByUser": True},
            "fields": "hiddenByUser",
        }})
    ss.batch_update({"requests": reqs})


def _headers(ws):
    return ws.get("A1:%s%d" % (_col_letter(ws.col_count), SUB_ROW),
                  value_render_option="FORMATTED_VALUE")


def template_last_row(ws, first_col: int) -> int:
    """Last row the template columns actually use -- the TOTALS row today.

    Copying only down to here keeps the paste clear of the merged section
    headers further down the tab, which is what Sheets rejects.
    """
    rng = "%s%d:%s%d" % (_col_letter(first_col), SUB_ROW,
                         _col_letter(first_col + 2), ws.row_count)
    got = ws.get(rng, value_render_option="FORMULA")
    last = SUB_ROW
    for i, row in enumerate(got, start=SUB_ROW):
        if any(str(x).strip() for x in row):
            last = i
    return last


def formulas(ss, ws, apply: bool = False) -> int:
    """Lay the two DERIVED Talk-To columns in as formulas, every day, every row.

    Only `Total Talk-To's` is data -- ownerville's calculated 'Total Talk to',
    written by `alphalete_production.tk_fill` alongside TK. The other two are
    ratios of cells already on the row, so they are formulas and not writes:
    TK climbs all day and Apps is itself a formula, and a number computed at
    9:40 would be wrong by 9:55 with nothing to say so.

      % of TT's per knock = Talk-To's / TK
      AVG app per TT      = Apps      / Talk-To's

    NO DATA READS 0, NOT BLANK (Eve, 2026-09-08: *"si queda vacio entiendo que
    es una falla"*). A zero denominator lands on 0, `N()` turns a roll-call
    letter into 0, and IFERROR catches the Apps cell on a day it holds a letter
    rather than a count -- so a cell is never #DIV/0! and never empty. The one
    blank left is a row with NO REP in it: `IF($C="", ...)` keeps the filler rows
    above TOTALS clean, and the formula lights up by itself the moment somebody
    is typed into one.

    The TOTALS row gets the same two ratios over the column totals, NOT a sum of
    the per-rep percentages -- that would be an average of averages, and it is
    what a straight copy of the neighbouring SUMIF leaves behind.
    """
    from automations.energy_slack_fill.run import last_rep_row, name_col

    grid = ws.get_all_values()
    last = last_rep_row(grid)
    totals = last + 1
    names = _col_letter(name_col(grid))
    data, said = [], []
    for lab, b in sorted(day_blocks(grid).items(), key=lambda kv: kv[1][0]):
        apps = b[0]                                   # Apps is the block's first
        tk = sub_col(grid, b, ANCHOR)
        tt, pct, avg = (sub_col(grid, b, h) for h in TRIO)
        if not all((tk, tt, pct, avg)):
            said.append("  %-5s no Talk-To columns -- skipped" % lab)
            continue
        A, T_, K, P, V = (_col_letter(c) for c in (apps, tt, tk, pct, avg))
        rows = list(range(SUB_ROW + 1, totals + 1))
        data.append({
            "range": "%s%d:%s%d" % (P, rows[0], P, rows[-1]),
            "values": [[_no_rep(r, '=IFERROR(IF(N(%s%d)=0,0,%s%d/%s%d),0)'
                                % (K, r, T_, r, K, r), names)] for r in rows],
        })
        data.append({
            "range": "%s%d:%s%d" % (V, rows[0], V, rows[-1]),
            "values": [[_no_rep(r, '=IFERROR(IF(N(%s%d)=0,0,%s%d/%s%d),0)'
                                % (T_, r, A, r, T_, r), names)] for r in rows],
        })
        said.append("  %-5s %s = %s/%s   %s = %s/%s   rows %d-%d"
                    % (lab, P, T_, K, V, A, T_, rows[0], rows[-1]))
    print("\n".join(said))
    if not data:
        return 1
    if not apply:
        print("\npreview only -- re-run with --apply to write.")
        return 0
    ws.batch_update(data, value_input_option="USER_ENTERED")
    # Percent as a percent, the average to two places -- a bare 0.0384 in a
    # column headed '%' is the kind of thing nobody reports and everybody
    # misreads.
    fmt = []
    for lab, b in day_blocks(grid).items():
        _tt, pct, avg = (sub_col(grid, b, h) for h in TRIO)
        if not (pct and avg):
            continue
        for c, pattern, kind in ((pct, "0.0%", "PERCENT"), (avg, "0.00", "NUMBER")):
            fmt.append(number_format(ws, c, SUB_ROW + 1, totals, kind, pattern))
    if fmt:
        ss.batch_update({"requests": fmt})
    print("\nwrote the two derived columns on %d day block(s)." % (len(data) // 2))
    return 0


# The five Talk-To columns Eve added to the RUNNING WEEK TOTALS block, exactly as
# row 3 spells them. Two of these names ALSO exist inside every day block, so
# they are only ever looked up INSIDE the running-week block.
WEEK_BLOCK = "RUNNING WEEK TOTALS"
WEEK_AVG_TK = "AVG Total Knocks per day"
WEEK_TT = "Total Talk-To's"
WEEK_AVG_TT = "AVG TT's per day"
WEEK_PCT = "% of TT's per knock"
WEEK_TT_APP = "AVG TTs per app"


def running_block(grid):
    """(first_col, last_col) of the RUNNING WEEK TOTALS block: its row-1 label,
    out to the column before the next row-1 label."""
    width = max((len(r) for r in grid), default=0)
    start = None
    for c in range(1, width + 1):
        lab = _cell(grid, DAY_ROW, c)
        if start is None:
            if lab.upper() == WEEK_BLOCK:
                start = c
        elif lab:
            return start, c - 1
    return (start, width) if start else (None, None)


def week_formulas(ss, ws, apply: bool = False) -> int:
    """The five weekly Talk-To columns, as formulas over the day blocks.

    WHAT A "DAY WORKED" IS (Eve, 2026-09-08): a day the rep was actually out in
    the field. Her rule is the roll-call letter — a day marked `X` is a day he
    was not there and must not be averaged over — plus SUNDAY, which is a
    non-working day every week and so is left out of the day list entirely.

    ONLY `X` AND `T` ARE OFF. Eve, 2026-09-08: *"1 solo la x o T debe NO contar,
    el resto de las letras si"*. So this counts a day when the Apps cell is
    anything other than `X`, `T` or empty — a number (0.00 included: out in the
    field, sold nothing) and every other roll-call letter alike. `NOT_WORKED`
    below is the whole rule; a first pass used COUNT(), which reads "numbers
    only" and quietly dropped the letters she wants kept.

      AVG Total Knocks per day = week TK       / days worked
      Total Talk-To's          = the 7 daily Talk-To's, summed
      AVG TT's per day         = week Talk-To's / days worked
      % of TT's per knock      = week Talk-To's / week TK
      AVG TTs per app          = week Talk-To's / week Apps

    NO DATA READS 0, NOT BLANK — no days worked, no knocks, no apps all land on
    0, because an empty cell reads as a broken report. Only a row with NO REP in
    it stays blank; see `_no_rep`.

    In the TOTALS row the same formulas hold, with one thing worth knowing: the
    denominator there is the SIX working days of the office (each day's total is
    a number), so its 'per day' cells read office knocks/talk-to's per day. It
    is not the sum of everybody's days worked.
    """
    from automations.energy_slack_fill.run import last_rep_row, name_col

    grid = ws.get_all_values()
    totals = last_rep_row(grid) + 1
    lo, hi = running_block(grid)
    if not lo:
        print("no %r block in row 1 -- nothing to write." % WEEK_BLOCK)
        return 1
    wk = (lo, hi)
    wanted = {h: sub_col(grid, wk, h) for h in
              (WEEK_AVG_TK, WEEK_TT, WEEK_AVG_TT, WEEK_PCT, WEEK_TT_APP,
               "APPS", "TK")}
    missing = [h for h, c in wanted.items() if not c]
    if missing:
        print("%s is missing %s -- nothing written."
              % (WEEK_BLOCK, ", ".join(repr(m) for m in missing)))
        return 1

    blocks = day_blocks(grid)
    work = [b for lab, b in sorted(blocks.items(), key=lambda kv: kv[1][0])
            if lab.upper() != "SUN"]                  # Sunday is never a work day
    day_apps = [b[0] for b in work]
    all_tt = [sub_col(grid, b, TRIO[0])
              for _lab, b in sorted(blocks.items(), key=lambda kv: kv[1][0])]
    if not all(all_tt):
        print("some day block has no %r column -- run without --week-formulas "
              "first." % TRIO[0])
        return 1

    A, K = (_col_letter(wanted["APPS"]), _col_letter(wanted["TK"]))
    print("%s  %s..%s   dias habiles: %s   Apps=%s TK=%s"
          % (WEEK_BLOCK, _col_letter(lo), _col_letter(hi),
             ", ".join(_col_letter(c) for c in day_apps), A, K))

    rows = list(range(SUB_ROW + 1, totals + 1))
    names = _col_letter(name_col(grid))
    data = []

    def put(header, make):
        col = _col_letter(wanted[header])
        data.append({
            "range": "%s%d:%s%d" % (col, rows[0], col, rows[-1]),
            "values": [[_no_rep(r, make(r), names)] for r in rows],
        })
        print("  %-26s %s" % (header, col))

    def days(r):
        """Days the rep was out: every day whose Apps cell is not X, T or empty."""
        return "(%s)" % "+".join(
            'IF(OR(%s%d="X",%s%d="T",%s%d=""),0,1)'
            % (_col_letter(c), r, _col_letter(c), r, _col_letter(c), r)
            for c in day_apps)

    def tts(r):
        return ",".join("%s%d" % (_col_letter(c), r) for c in all_tt)

    TT = _col_letter(wanted[WEEK_TT])
    put(WEEK_AVG_TK, lambda r: '=IFERROR(IF(%s=0,0,%s%d/%s),0)'
        % (days(r), K, r, days(r)))
    put(WEEK_TT, lambda r: '=SUM(%s)' % tts(r))
    put(WEEK_AVG_TT, lambda r: '=IFERROR(IF(%s=0,0,%s%d/%s),0)'
        % (days(r), TT, r, days(r)))
    put(WEEK_PCT, lambda r: '=IFERROR(IF(N(%s%d)=0,0,%s%d/%s%d),0)'
        % (K, r, TT, r, K, r))
    put(WEEK_TT_APP, lambda r: '=IFERROR(IF(N(%s%d)=0,0,%s%d/%s%d),0)'
        % (A, r, TT, r, A, r))

    if not apply:
        print("\npreview only -- re-run with --apply to write.")
        return 0
    ws.batch_update(data, value_input_option="USER_ENTERED")
    fmt = []
    for header, kind, pattern in (
            (WEEK_AVG_TK, "NUMBER", "0.0"), (WEEK_TT, "NUMBER", "0"),
            (WEEK_AVG_TT, "NUMBER", "0.0"), (WEEK_PCT, "PERCENT", "0.0%"),
            (WEEK_TT_APP, "NUMBER", "0.0")):
        fmt.append(number_format(ws, wanted[header], rows[0], rows[-1],
                                 kind, pattern))
    ss.batch_update({"requests": fmt})
    print("\nwrote the five weekly columns, rows %d-%d." % (rows[0], rows[-1]))
    return 0


def refold(ss, ws, tab: str, apply: bool = False) -> int:
    """Hide any trio whose day block is folded up, leave the open day alone."""
    grid = _headers(ws)
    folded = hidden_cols(ss, tab, ws.col_count)
    reqs, said = [], []
    for lab, b in sorted(day_blocks(grid).items(), key=lambda kv: kv[1][0]):
        anchor = sub_col(grid, b, ANCHOR)
        first = sub_col(grid, b, TRIO[0])
        if not anchor or not first:
            continue
        want = folded[anchor]
        have = [folded[first + i] for i in range(3)]
        if all(h == want for h in have):
            continue
        said.append("  %-5s %s..%s -> %s"
                    % (lab, _col_letter(first), _col_letter(first + 2),
                       "hidden" if want else "shown"))
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": first - 1, "endIndex": first + 2},
            "properties": {"hiddenByUser": want},
            "fields": "hiddenByUser",
        }})
    if not reqs:
        print("every trio already matches its day block -- nothing to refold.")
        return 0
    print("\n".join(said))
    if not apply:
        print("\npreview only -- re-run with --apply to write.")
        return 0
    ss.batch_update({"requests": reqs})
    print("refolded.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tab", default=SANDBOX_TAB, help="board tab to widen")
    ap.add_argument("--sheet-id", default=PROD_SHEET_ID, help="override the workbook")
    ap.add_argument("--apply", action="store_true",
                    help="write to the Sheet (default is a preview)")
    ap.add_argument("--refold", action="store_true",
                    help="only re-hide trios that sit in a collapsed day group")
    ap.add_argument("--formulas", action="store_true",
                    help="(re)write the two derived columns, every day, every row")
    ap.add_argument("--week-formulas", action="store_true",
                    help="(re)write the five Talk-To columns of RUNNING WEEK TOTALS")
    a = ap.parse_args(argv)

    from automations.recruiting_report.fill import open_by_key
    ss = open_by_key(a.sheet_id)
    ws = ss.worksheet(a.tab)

    if a.refold:
        return refold(ss, ws, a.tab, apply=a.apply)
    if a.formulas:
        return formulas(ss, ws, apply=a.apply)
    if a.week_formulas:
        return week_formulas(ss, ws, apply=a.apply)

    tmpl_day, tmpl_col, todo = plan(_headers(ws))
    if not tmpl_day:
        print("No day block on %r has %r -- nothing to copy FROM." % (a.tab, TRIO[0]))
        return 1
    print("tab      : %s" % a.tab)
    print("template : %s at %s..%s"
          % (tmpl_day, _col_letter(tmpl_col), _col_letter(tmpl_col + 2)))
    if not todo:
        print("every other day already has the three columns -- nothing to do.")
        return 0
    for lab, anchor, ins in todo:
        print("  %-5s %s after %s (%s) -> %s..%s"
              % (lab, "insert 3 cols" if ins else "fill the 3 blank cols",
                 ANCHOR, _col_letter(anchor),
                 _col_letter(anchor + 1), _col_letter(anchor + 3)))
    if not a.apply:
        print("\npreview only -- re-run with --apply to write.")
        return 0

    px = widths(ss, a.tab, tmpl_col)
    last_row = template_last_row(ws, tmpl_col)
    folded = hidden_cols(ss, a.tab, ws.col_count)
    print("copying rows %d-%d of the template columns" % (SUB_ROW, last_row))

    # Right to left: widening a day never moves one still to be done, so every
    # anchor from the plan above stays valid. The TEMPLATE does move -- three
    # columns each time a day to its LEFT is widened -- and it moves during the
    # very insert that precedes the paste, so count the shift BEFORE copying.
    shift = 0
    for lab, anchor, ins in reversed(todo):
        if ins and anchor < tmpl_col:
            shift += 3
        add_for_day(ss, ws, anchor, tmpl_col + shift, px, last_row,
                    insert=ins, hide=folded[anchor])
        print("  %-5s done -> %s..%s"
              % (lab, _col_letter(anchor + 1), _col_letter(anchor + 3)))
    print("\nwrote the three Talk-To columns into every day block.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
