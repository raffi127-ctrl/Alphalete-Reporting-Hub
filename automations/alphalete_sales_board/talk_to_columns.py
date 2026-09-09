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
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

# The workbook, the three header rows and the weekday labels are the Energy /
# TK fill's geometry. Same board, one definition.
from automations.energy_slack_fill.run import DAY_LABELS, DAY_ROW, SUB_ROW, PROD_SHEET_ID

# THE sandbox, and the tab `--seed` copies its row-3 headers from. It was
# 'Sales Board WE 9.6 Eve Edits' -- the tab Eve built THU on by hand -- until
# 2026-09-09, when she moved to the live week and had the old one deleted.
# Keep this pointing at whichever sandbox is current: a tab that no longer
# exists makes every default here raise WorksheetNotFound.
SANDBOX_TAB = "Sales Board WE 9.13 SANDBOX"

# The three columns, in order, exactly as row 3 spells them on THU.
TRIO = ("Total Talk-To's", "% of TT's per knock", "AVG app per TT")

# Where they go: straight after this sub-header, still inside the day's group.
ANCHOR = "TK"

# The last column of a day block. Used as the "did this day happen yet" test:
# it is filled in the morning, and blank on a day still ahead in the week.
ROLL_CALL = "Roll Call"


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


# What a cell says when the ratio CANNOT BE MEASURED -- the denominator is zero.
# Eve, 2026-09-08, in three steps: blank first ("si queda vacio entiendo que es
# una falla"), then 0, then this. The reason 0 was not the end of it: a rep with
# 116 talk-to's and no sale, and a rep who sold without talking to anybody, both
# read 0.0 in 'AVG TTs per app', and only ONE of those is a real zero. So the
# three cases stay apart:
#
#   no denominator to divide by  ->  "-"   (nothing to measure)
#   a real zero on top           ->  0     (measured, and it is zero)
#   no rep in the row            ->  blank (not a data cell at all)
CANT_MEASURE = '"-"'


def _no_rep(row: int, expr: str, name_col_letter: str) -> str:
    """`expr`, but blank on a row that holds no rep.

    The board keeps filler rows between the last rep and TOTALS, and a strip of
    dashes down empty rows is noise, not information. The test is the NAME cell,
    so the formula lights up the moment somebody is typed into one.
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


def day_worked_expr(apps_col: int, tk_col: int, rc_col: int, row: int) -> str:
    """`1` if the rep worked that day, `0` otherwise — as a Sheets expression.

    TWO TESTS, and the second is what makes the denominator grow one day at a
    time as the week runs (Eve, 2026-09-09: *"cada dia dividan por un dia
    mas"*). Nobody advances a counter; the week does.

    1. THE ROLL-CALL LETTER. `X` and `T` are out, every other letter is in
       (Eve, 2026-09-08). The day's Apps cell carries it, because the Apps
       formula returns the letter itself when there is one.
    2. THE DAY LEFT A TRACE. A day still ahead in the week reads Apps `0.00` --
       a NUMBER, so test 1 alone counts it, and mid-week every average divides
       by six. On the WE 9.13 sandbox that had Andres Mejia at 49 knocks/day
       when he had done 294 over two days. So a day also needs a roll call, or
       knocks, or a non-zero Apps.

    `N(TK)>0` and not `TK<>""`: the same formula runs on the TOTALS row, where
    an untouched day's TK is a `SUMIF` reading 0 rather than a blank, and
    "not empty" would count Thursday as a working day all week.
    """
    return ('IF(OR({a}{r}="X",{a}{r}="T",{a}{r}=""),0,'
            'IF(OR({c}{r}<>"",N({k}{r})>0,{a}{r}<>0),1,0))').format(
        a=_col_letter(apps_col), k=_col_letter(tk_col),
        c=_col_letter(rc_col), r=row)


def insert_order(jobs):
    """The jobs sorted RIGHT TO LEFT BY COLUMN, so no insert moves a later one.

    Not the same as reversing the list, and that is the whole point. The jobs
    come out in the order they were collected -- the seven day blocks, then
    RUNNING WEEK TOTALS -- but RUNNING WEEK sits LEFTMOST on the tab. Reversing
    ran it first, its five columns pushed every day anchor five to the right,
    and all seven trios landed beside `Apps` instead of `TK`
    (WE 9.13 SANDBOX, 2026-09-09). Sort by the anchor, never by arrival.
    """
    return sorted(jobs, key=lambda j: -j[1])


def _totals_like(grid, totals_row: int, model_col: int, want_col: int):
    """The TOTALS-row formula of `model_col`, pointed at `want_col` instead.

    Copied rather than written, exactly like `tk_fill.ensure_tk_total`: whatever
    row range and `Field Status <> RT` exclusion the column beside it uses, this
    one uses too, and a template that changes either carries us along. Returns
    None when the model cell is not a formula.
    """
    f = _cell(grid, totals_row, model_col)
    if not f.startswith("="):
        return None
    a, b = _col_letter(model_col), _col_letter(want_col)
    out = re.sub(r"(?<![A-Z0-9$])%s(\d+)" % a, lambda m: b + m.group(1), f)
    return out if out != f else None


def seed(ss, ws, src_ws, apply: bool = False) -> int:
    """Create the Talk-To columns on a tab that has NONE of them yet.

    `--tab` alone can only copy a day that already carries the trio, which is
    how the WE 9.6 sandbox was finished -- Eve had built THU by hand. A fresh
    week's tab has nothing to copy from, so this seeds it: three columns in
    every day block and five in RUNNING WEEK TOTALS.

    THE HEADERS COME FROM THE OTHER TAB, THE REST FROM THIS ONE. Only row 3 is
    pasted across (same row on both tabs, so nothing can land off by a row),
    which brings the wording, the green and the small font exactly as Eve made
    them. Everything else is local: the body formatting is inherited from the
    `TK` column the new ones sit beside, and the TOTALS-row sum is this tab's
    own TK total with the column letter swapped -- so a tab with a different
    roster length gets a total over ITS rows, not over WE 9.6's.
    """
    from automations.energy_slack_fill.run import last_rep_row

    src = _headers(src_ws)
    s_day = None
    for lab, b in day_blocks(src).items():
        cols = [sub_col(src, b, h) for h in TRIO]
        if all(cols) and cols == list(range(cols[0], cols[0] + 3)):
            s_day = (lab, cols[0])
            break
    s_lo, s_hi = running_block(src)
    s_week = [sub_col(src, (s_lo, s_hi), h) for h in WEEK_HEADERS] if s_lo else []
    if not s_day or not all(s_week):
        print("%r does not carry the columns -- nothing to copy headers FROM."
              % src_ws.title)
        return 1
    print("headers <- %r  (%s %s..%s, semanal %s..%s)"
          % (src_ws.title, s_day[0], _col_letter(s_day[1]),
             _col_letter(s_day[1] + 2), _col_letter(s_week[0]),
             _col_letter(s_week[-1])))

    grid = ws.get("A1:%s%d" % (_col_letter(ws.col_count), ws.row_count),
                  value_render_option="FORMULA")
    totals = last_rep_row(grid) + 1
    lo, hi = running_block(grid)
    jobs = []                      # (label, anchor_col, how_many, src_first)
    for lab, b in sorted(day_blocks(grid).items(), key=lambda kv: kv[1][0]):
        if any(sub_col(grid, b, h) for h in TRIO):
            print("  %-5s ya las tiene -- salteado" % lab)
            continue
        anchor = sub_col(grid, b, ANCHOR)
        if anchor is None:
            print("  ! %s sin %r -- salteado" % (lab, ANCHOR))
            continue
        jobs.append((lab, anchor, 3, s_day[1]))
    if lo and not any(sub_col(grid, (lo, hi), h) for h in WEEK_HEADERS):
        anchor = sub_col(grid, (lo, hi), ANCHOR)
        if anchor:
            jobs.append((WEEK_BLOCK, anchor, 5, s_week[0]))
    if not jobs:
        print("nada que sembrar -- la pestaña ya tiene las columnas.")
        return 0
    for lab, anchor, n, _s in jobs:
        print("  %-20s %d columnas después de %s (%s)"
              % (lab, n, ANCHOR, _col_letter(anchor)))
    if not apply:
        print("\npreview only -- re-run with --apply to write.")
        return 0

    folded = hidden_cols(ss, ws.title, ws.col_count)
    px_day = widths(ss, src_ws.title, s_day[1])
    px_week = widths(ss, src_ws.title, s_week[0]) + widths(
        ss, src_ws.title, s_week[0] + 3)
    for lab, anchor, n, s_first in insert_order(jobs):
        px = (px_day if n == 3 else px_week)[:n]
        ss.batch_update({"requests": [{"insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": anchor, "endIndex": anchor + n},
            "inheritFromBefore": True}}]})
        reqs = [{"copyPaste": {                       # ROW 3 ONLY, across tabs
            "source": {"sheetId": src_ws.id,
                       "startRowIndex": SUB_ROW - 1, "endRowIndex": SUB_ROW,
                       "startColumnIndex": s_first - 1,
                       "endColumnIndex": s_first - 1 + n},
            "destination": {"sheetId": ws.id,
                            "startRowIndex": SUB_ROW - 1, "endRowIndex": SUB_ROW,
                            "startColumnIndex": anchor, "endColumnIndex": anchor + n},
            "pasteType": "PASTE_NORMAL"}}]
        if n == 3:                                    # the day trio folds away
            reqs.append({"addDimensionGroup": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                          "startIndex": anchor, "endIndex": anchor + n}}})
        for i, size in enumerate(px):
            if size:
                reqs.append({"updateDimensionProperties": {
                    "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                              "startIndex": anchor + i, "endIndex": anchor + i + 1},
                    "properties": {"pixelSize": size}, "fields": "pixelSize"}})
        if folded[anchor]:
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                          "startIndex": anchor, "endIndex": anchor + n},
                "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
        ss.batch_update({"requests": reqs})
        print("  %-20s -> %s..%s" % (lab, _col_letter(anchor + 1),
                                     _col_letter(anchor + n)))

    # The TOTALS row: give every new column the sum its TK neighbour already
    # has. `--formulas` / `--week-formulas` then overwrite the ratio ones.
    grid = ws.get("A1:%s%d" % (_col_letter(ws.col_count), totals),
                  value_render_option="FORMULA")
    data = []
    todo = [(b, TRIO) for b in day_blocks(grid).values()]
    if lo:
        todo.append((running_block(grid), WEEK_HEADERS))
    for b, headers in todo:
        tk = sub_col(grid, b, ANCHOR)
        for h in headers:
            c = sub_col(grid, b, h)
            if not (tk and c):
                continue
            f = _totals_like(grid, totals, tk, c)
            if f:
                data.append({"range": "%s%d" % (_col_letter(c), totals),
                             "values": [[f]]})
    if data:
        ws.batch_update(data, value_input_option="USER_ENTERED")
    print("\nsembrada: %d bloque(s), %d total(es) en la fila %d."
          % (len(jobs), len(data), totals))
    return 0


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

    A zero denominator is not a zero, it is a ratio that cannot be measured, and
    the cell says `-`. `N()` turns a roll-call letter into that same case, and
    IFERROR catches the Apps cell on a day it holds a letter rather than a
    count, so no cell is ever #DIV/0!.

    A DAY WITH NO NUMBERS AT ALL STAYS EMPTY, though -- see `_day` below. That
    is the one place the day blocks and the weekly block differ on purpose.

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
        def _day(r, expr):
            """Blank the cell on a day that has NO numbers at all.

            Eve, 2026-09-08: in the DAY blocks a dash is only noise. A day the
            rep was not out has neither TK nor Talk-To's, and a grid of dashes
            down six blocks buries the days that do have numbers. The dash is
            kept for the WEEKLY block, where every row is a rep who was there
            some day of the week and the reader needs to know why a cell is not
            a number. Empty here means empty THERE -- both source cells blank.
            """
            return _no_rep(r, '=IF(AND(%s%d="",%s%d=""),"",%s)'
                           % (K, r, T_, r, expr.lstrip("=")), names)

        data.append({
            "range": "%s%d:%s%d" % (P, rows[0], P, rows[-1]),
            "values": [[_day(r, '=IF(N(%s%d)=0,%s,IFERROR(%s%d/%s%d,%s))'
                             % (K, r, CANT_MEASURE, T_, r, K, r,
                                CANT_MEASURE))] for r in rows],
        })
        data.append({
            "range": "%s%d:%s%d" % (V, rows[0], V, rows[-1]),
            "values": [[_day(r, '=IF(N(%s%d)=0,%s,IFERROR(%s%d/%s%d,%s))'
                             % (T_, r, CANT_MEASURE, A, r, T_, r,
                                CANT_MEASURE))] for r in rows],
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
        # BOTH as percentages. `AVG app per TT` is apps/talk-to's, which reads
        # `0.07` as a number and `7.3%` as a rate -- the same cell, and only one
        # of the two says "seven of every hundred conversations ended in a sale"
        # without the reader doing arithmetic (Eve, 2026-09-09). The formula and
        # the direction Rafael asked for are untouched; this is the display.
        for c, pattern, kind in ((pct, "0.0%", "PERCENT"),
                                 (avg, "0.0%", "PERCENT")):
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
# In the order Eve put them, which is also the order `seed` inserts them.
WEEK_HEADERS = (WEEK_AVG_TK, WEEK_TT, WEEK_AVG_TT, WEEK_PCT, WEEK_TT_APP)


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

    NOTHING READS BLANK. No days worked, no knocks or no apps means the ratio
    cannot be measured, and the cell says `-`; a genuine zero says 0. Only a row
    with NO REP in it stays empty. See `CANT_MEASURE` and `_no_rep`.

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
    day_cells = [(b[0], sub_col(grid, b, ANCHOR), sub_col(grid, b, ROLL_CALL))
                 for b in work]
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
        """Mon-Sat the rep was out, on days that have HAPPENED — see
        `day_worked_expr`."""
        return "(%s)" % "+".join(
            day_worked_expr(ap, tk, rc, r) for ap, tk, rc in day_cells)

    def tts(r):
        return ",".join("%s%d" % (_col_letter(c), r) for c in all_tt)

    TT = _col_letter(wanted[WEEK_TT])
    D = CANT_MEASURE
    put(WEEK_AVG_TK, lambda r: '=IF(%s=0,%s,IFERROR(%s%d/%s,%s))'
        % (days(r), D, K, r, days(r), D))
    put(WEEK_TT, lambda r: '=SUM(%s)' % tts(r))       # a sum: 0 is a real 0
    put(WEEK_AVG_TT, lambda r: '=IF(%s=0,%s,IFERROR(%s%d/%s,%s))'
        % (days(r), D, TT, r, days(r), D))
    put(WEEK_PCT, lambda r: '=IF(N(%s%d)=0,%s,IFERROR(%s%d/%s%d,%s))'
        % (K, r, D, TT, r, K, r, D))
    put(WEEK_TT_APP, lambda r: '=IF(N(%s%d)=0,%s,IFERROR(%s%d/%s%d,%s))'
        % (A, r, D, TT, r, A, r, D))

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


_SUMIFS = re.compile(
    r"^=SUMIFS\(.+?,\s*\$?([A-Z]{1,3})\s*:\s*\$?([A-Z]{1,3})\s*,\s*(.+)\)\s*$",
    re.I)


def _team_test(formula: str, first: int, last: int):
    """`(range=criterion)`, taken from the row's own SUMIFS, for SUMPRODUCT.

    Returns None when the row does not filter (the TOTALS row is a plain SUM
    over the team rows) or filters with a WILDCARD -- SUMPRODUCT compares
    literally, so `"*Andrew*"` would silently match nothing and the average
    would come out of a zero denominator looking like a real answer.
    """
    m = _SUMIFS.match(formula.strip())
    if not m:
        return None
    a, b, crit = m.group(1), m.group(2), m.group(3).strip()
    if a != b or "*" in crit or "?" in crit:
        return None
    return "($%s$%d:$%s$%d=%s)" % (a, first, a, last, crit)


def team_totals(ss, ws, apply: bool = False) -> int:
    """The five weekly Talk-To columns for the Teams block under the roster.

    THE SUM COLUMN IS NOT WRITTEN FROM SCRATCH -- it is the row's OWN `INT`
    formula with the column letter swapped, the same trick `tk_fill`'s
    `ensure_tk_total` uses. That is what makes this work across three different
    row shapes without knowing about any of them: a team row
    (`SUMIFS($E:$E,$DI:$DI,$C166)`), the TOTALS row (`SUM($E$166:$E$180)`) and
    the two sub-crews that match their people with a wildcard
    (`SUMIFS(E:E,$DI:$DI,"*Andr…")`). Whatever population that row counts, the
    Talk-To's column counts the same one.

    THE RATIOS ARE PER REP-DAY, NOT PER TEAM-DAY. 'AVG Total Knocks per day' on
    a team row divides by the rep-days its people actually worked, so it reads
    on the same scale as the rep rows above it -- a team averaging 150 sits next
    to a rep averaging 178. Dividing by 6 instead would give the team's daily
    VOLUME, which is a different number that cannot be compared with anything
    else in its own column. The day count is the SUMPRODUCT of the same
    not-X-not-T-not-blank test the per-rep column uses.

    A row that has no TK of its own (the two sub-crews carry Int..NL only) gets
    the Talk-To's sum and nothing else -- the same shape it already had.
    """
    from automations.energy_slack_fill.run import last_rep_row, name_col

    # FORMULAS, not values: this pass finds the team rows BY the formula in
    # their INT cell and then rewrites that formula for Talk-To's.
    # `get_all_values()` would hand back the rendered numbers instead.
    grid = ws.get("A1:%s%d" % (_col_letter(ws.col_count), ws.row_count),
                  value_render_option="FORMULA")
    last = last_rep_row(grid)
    first = SUB_ROW + 1
    lo, hi = running_block(grid)
    if not lo:
        print("no %r block in row 1 -- nothing to write." % WEEK_BLOCK)
        return 1
    wk = (lo, hi)
    col = {h: sub_col(grid, wk, h) for h in
           (WEEK_AVG_TK, WEEK_TT, WEEK_AVG_TT, WEEK_PCT, WEEK_TT_APP,
            "APPS", "INT", "TK")}
    if not all(col.values()):
        print("%s is missing %s -- nothing written."
              % (WEEK_BLOCK, [h for h, c in col.items() if not c]))
        return 1
    INT, TT = _col_letter(col["INT"]), _col_letter(col[WEEK_TT])
    A, K = _col_letter(col["APPS"]), _col_letter(col["TK"])

    blocks = day_blocks(grid)
    work = [b for lab, b in sorted(blocks.items(), key=lambda kv: kv[1][0])
            if lab.upper() != "SUN"]

    def _rng(c):
        return "$%s$%d:$%s$%d" % (_col_letter(c), first, _col_letter(c), last)

    # The array form of `week_formulas.days`: out that day, AND the day happened.
    span = "+".join(
        '({a}<>"X")*({a}<>"T")*({a}<>"")*(({c}<>"")+({k}<>"")*({k}<>0)+({a}<>0)>0)'
        .format(a=_rng(b[0]), k=_rng(sub_col(grid, b, ANCHOR)),
                c=_rng(sub_col(grid, b, ROLL_CALL)))
        for b in work)

    # The Teams block: every row BELOW the roster whose INT cell is a formula.
    rows = [r for r in range(last + 2, len(grid) + 1)
            if _cell(grid, r, col["INT"]).startswith("=")]
    if not rows:
        print("no team rows under the roster -- nothing to write.")
        return 1

    names = _col_letter(name_col(grid))
    data, said = [], []
    for r in rows:
        base = _cell(grid, r, col["INT"])
        tt = base.replace("$%s$" % INT, "$%s$" % TT).replace(
            "$%s:$%s" % (INT, INT), "$%s:$%s" % (TT, TT)).replace(
            "%s:%s" % (INT, INT), "%s:%s" % (TT, TT))
        if tt == base:
            said.append("  r%-4d %-22s no supe reescribir %r -- salteada"
                        % (r, _cell(grid, r, 3)[:22], base[:40]))
            continue
        cells = {WEEK_TT: tt}
        # Only rows that count a TK of their own get the ratios.
        test = _team_test(base, first, last)
        if _cell(grid, r, col["TK"]).startswith("=") and (
                test or "SUMIFS" not in base.upper()):
            days = ("SUMPRODUCT(%s*(%s))" % (test, span) if test
                    else "SUMPRODUCT(%s)" % span)
            cells[WEEK_AVG_TK] = ('=IFERROR(IF(%s=0,%s,$%s%d/%s),%s)'
                                  % (days, CANT_MEASURE, K, r, days,
                                     CANT_MEASURE))
            cells[WEEK_AVG_TT] = ('=IFERROR(IF(%s=0,%s,$%s%d/%s),%s)'
                                  % (days, CANT_MEASURE, TT, r, days,
                                     CANT_MEASURE))
            cells[WEEK_PCT] = ('=IF(N($%s%d)=0,%s,IFERROR($%s%d/$%s%d,%s))'
                               % (K, r, CANT_MEASURE, TT, r, K, r,
                                  CANT_MEASURE))
            cells[WEEK_TT_APP] = ('=IF(N($%s%d)=0,%s,IFERROR($%s%d/$%s%d,%s))'
                                  % (A, r, CANT_MEASURE, TT, r, A, r,
                                     CANT_MEASURE))
        for header, formula in cells.items():
            c = _col_letter(col[header])
            data.append({"range": "%s%d" % (c, r), "values": [[formula]]})
        said.append("  r%-4d %-24s %s" % (r, _cell(grid, r, 3)[:24],
                                          "5 columnas" if len(cells) == 5
                                          else "solo Talk-To's (la fila no "
                                               "lleva TK)"))
    print("Teams: filas %d..%d   dias habiles: %s"
          % (rows[0], rows[-1], ", ".join(_col_letter(b[0]) for b in work)))
    print("\n".join(said))
    if not apply:
        print("\npreview only -- re-run with --apply to write.")
        return 0
    ws.batch_update(data, value_input_option="USER_ENTERED")
    fmt = []
    for header, kind, pattern in (
            (WEEK_AVG_TK, "NUMBER", "0.0"), (WEEK_TT, "NUMBER", "0"),
            (WEEK_AVG_TT, "NUMBER", "0.0"), (WEEK_PCT, "PERCENT", "0.0%"),
            (WEEK_TT_APP, "NUMBER", "0.0")):
        fmt.append(number_format(ws, col[header], rows[0], rows[-1],
                                 kind, pattern))
    ss.batch_update({"requests": fmt})
    print("\nwrote %d cell(s) across %d team row(s)." % (len(data), len(rows)))
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
    ap.add_argument("--team-totals", action="store_true",
                    help="(re)write those five for the Teams block under the roster")
    ap.add_argument("--seed", action="store_true",
                    help="create all the columns on a tab that has NONE, "
                         "taking the row-3 headers from --from-tab")
    ap.add_argument("--from-tab", default=SANDBOX_TAB,
                    help="tab to copy the headers from when seeding")
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
    if a.team_totals:
        return team_totals(ss, ws, apply=a.apply)
    if a.seed:
        return seed(ss, ws, ss.worksheet(a.from_tab), apply=a.apply)

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
