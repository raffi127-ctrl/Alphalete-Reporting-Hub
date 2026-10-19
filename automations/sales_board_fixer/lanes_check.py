"""What the fixer looks for on the Sales Board's 'Lanes' tab -- pure functions.

Rafael, 2026-10-10 (Slack): owners will be pushed to use the main spreadsheets
more, so they will break them; Lanes is #2 of his list. Eve, 2026-10-19:
"primero arrancá con lanes".

THE TAB (see automations/alphalete_sales_board/lanes.py). Two blocks, 'Current
Week' and 'Last week', five lanes each. Each lane is ONE FILTER formula in the
row under the lane headers and the names spill below it. lanes.py re-points
those formulas at the right week every 10 min; it does NOT notice when one
breaks, and it refuses to run at all when one was deleted.

WHAT GETS FIXED
  lane_formula_lost   a lane's formula was deleted, typed over or carries
                      #REF! -> put back from its TWIN (the same lane in the
                      other block, re-pointed at this block's week), or from
                      the last healthy copy Lucy remembers (lanes_good.json).
  lane_col_moved      the Sales Board tab a block reads had a column inserted
                      or deleted, so a lane reads e.g. 'Field Status' from the
                      wrong letter -> the letter is moved to where that header
                      is now (headers remembered from the last healthy run).
  lane_range          wrong week tab or end row (the lanes.py job does this
                      too; the fixer covers the hours that job is off).
  lane_extra_lost     another formula on the lane row (col M '2wks in a Row')
                      deleted or #REF! -> put back from the healthy copy.

WHAT IS ONLY REPORTED -- someone may have done it on purpose
  lane_spill_blocked  something typed under a lane: when the list grows into
                      it the whole lane goes BLANK (iferror hides the error).
  lane_dead_cond      a condition that can never drop anyone, e.g. <>"T" on a
                      column that only holds numbers.
  lane_threshold      the formula's cut-off doesn't match the lane's header
                      ('Fast Lane 8+' filtering >=7).
  lane_twin_differs   the two blocks filter the same lane differently.

Nothing here reads or writes a sheet; run.py does the I/O.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from automations.alphalete_sales_board import lanes as L
from automations.sales_board_fixer.checks import Finding, col_index, col_letter

TAB = L.TAB
# A whole-column range on a Sales Board tab: 'Sales Board WE 10.18'!DQ4:DQ72
RANGE_RE = re.compile(r"'(%s [^']*)'!\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)"
                      % re.escape(L.fill.TAB_PREFIX))
# 'tab'!XX4:XX72<>"T" -- a range compared with a text literal
LITERAL_COND_RE = re.compile(RANGE_RE.pattern + r'\s*(<>|=)\s*"([^"]*)"')
NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?%?$")


def _healthy(f) -> bool:
    f = str(f or "")
    return f.startswith("=") and "#REF!" not in f and bool(RANGE_RE.search(f))


def _cell(grid, r0: int, c0: int) -> str:
    return str(grid[r0][c0]) if r0 < len(grid) and c0 < len(grid[r0]) else ""


def board_header(grid, c0: int) -> str:
    """'field status|' -- the Sales Board's day banner (row 1) + sub-header
    (row 3) over column c0. Row 2 carries the day's date and changes weekly,
    so it is left out."""
    return "|".join(_cell(grid, r, c0).strip().lower() for r in (0, 2))


def _stable(h: str) -> bool:
    """A header worth tracking: something there, and no date in it (col C's
    'WE 10/11 - 10/18' changes every week)."""
    return h.strip("|") != "" and not re.search(r"\d", h)


def remember(lanes_formulas, lanes_values, boards: Dict[str, list]) -> dict:
    """The healthy copy saved to lanes_good.json: every formula on the lane
    row, and the header of every Sales Board column the lanes read."""
    row0, blocks = L.find_blocks(lanes_values)
    frow = lanes_formulas[row0] if row0 < len(lanes_formulas) else []
    formulas = {col_letter(c + 1): f for c, f in enumerate(frow) if str(f).startswith("=")}
    headers = {}
    for f in formulas.values():
        for m in RANGE_RE.finditer(f):
            grid = boards.get(m.group(1))
            if grid is not None:
                h = board_header(grid, col_index(m.group(2)) - 1)
                if _stable(h):
                    headers[m.group(2)] = h
    return {"formulas": formulas, "headers": headers}


def _squash(f: str) -> str:
    """The formula with its week and end row taken out and spaces dropped --
    what two twin lanes should share."""
    f = RANGE_RE.sub(lambda m: "'TAB'!%s%s:%s" % (m.group(2), m.group(3), m.group(4)), f)
    return re.sub(r"\s+", "", f).lower()


def _move_columns(f: str, tab: str, grid, good_headers: Dict[str, str]):
    """(formula, [(old, new, header)]) with every column of `tab` whose header
    is no longer where the healthy copy had it moved to where it is now. A
    header found nowhere, or in two places, is left alone."""
    if grid is None or not good_headers:
        return f, []
    width = max((len(r) for r in grid[:3]), default=0)
    moves = {}
    for m in RANGE_RE.finditer(f):
        if m.group(1) != tab or m.group(2) != m.group(4):
            continue
        letter = m.group(2)
        want = good_headers.get(letter)
        if not want or board_header(grid, col_index(letter) - 1) == want:
            continue
        hits = [c for c in range(width) if board_header(grid, c) == want]
        if len(hits) == 1:
            moves[letter] = col_letter(hits[0] + 1)
    if not moves:
        return f, []

    def sub(m):
        if m.group(1) != tab or m.group(2) not in moves:
            return m.group(0)
        new = moves[m.group(2)]
        return "'%s'!%s%s:%s%s" % (tab, new, m.group(3), new, m.group(5))
    return RANGE_RE.sub(sub, f), [(o, n, good_headers[o]) for o, n in moves.items()]


def check(lanes_formulas, lanes_values, entered, boards: Dict[str, list],
          targets: Dict[str, Tuple[str, int]], good: Optional[dict]) -> List[Finding]:
    """Findings for the Lanes tab.

    entered[r][c] = True where a person typed the cell (userEnteredValue),
      False where it is blank or spilled from a formula; same shape as values.
    boards = {tab title: values grid} for the Sales Board tabs the lanes read.
    targets = {'current': (tab, end_row), 'last': (tab, end_row)} as lanes.py
      computes them.
    good = lanes_good.json ({'formulas': {letter: f}, 'headers': {letter: h}}).
    """
    good = good or {"formulas": {}, "headers": {}}
    row0, blocks = L.find_blocks(lanes_values)
    r1 = row0 + 1                                    # the lane row, 1-based
    frow = list(lanes_formulas[row0]) if row0 < len(lanes_formulas) else []
    heads = lanes_values[row0 - 1] if row0 >= 1 else []
    out: List[Finding] = []

    # -- the lane formulas: lost ones back, columns moved back, week/end row --
    twin = {}
    for a, b in (("current", "last"), ("last", "current")):
        for i, c in enumerate(blocks.get(a, [])):
            if i < len(blocks.get(b, [])):
                twin[c] = blocks[b][i]
    for key, cols in blocks.items():
        tab, end = targets[key]
        for c in cols:
            old = _cell([frow], 0, c)
            new, why, kind = old, [], None
            if not _healthy(old):
                src = _cell([frow], 0, twin[c]) if c in twin else ""
                origin = "the same lane in the other block"
                if not _healthy(src):
                    src, origin = good["formulas"].get(col_letter(c + 1), ""), "Lucy's last healthy copy"
                if not _healthy(src):
                    out.append(Finding("lane_formula_lost", TAB, col_letter(c + 1) + str(r1),
                                       "lane formula gone and no healthy copy to put back",
                                       before=old, after="(a mano)"))
                    continue
                new, kind = src, "lane_formula_lost"
                why.append("formula was %s, put back from %s"
                           % ("deleted" if not old.strip() else "broken", origin))
            new = L.repoint(new, tab, end)
            new, moved = _move_columns(new, tab, boards.get(tab), good["headers"])
            if moved:
                kind = kind or "lane_col_moved"
                why += ["'%s' moved %s -> %s" % (h.replace("|", " ").strip(), o, n)
                        for o, n, h in moved]
            if new != old:
                kind = kind or "lane_range"
                if kind == "lane_range":
                    why.append("pointed at the wrong week or stopped short of TOTALS")
                out.append(Finding(kind, TAB, col_letter(c + 1) + str(r1), "; ".join(why),
                                   before=old, after=new, value=new))
            frow += [""] * (c + 1 - len(frow))
            frow[c] = new

    # -- other formulas on the lane row (col M) --
    lane_cols = {c for cols in blocks.values() for c in cols}
    for letter, f in good["formulas"].items():
        c = col_index(letter) - 1
        if c in lane_cols:
            continue
        old = _cell([frow], 0, c)
        if not old.startswith("=") or "#REF!" in old:
            out.append(Finding("lane_extra_lost", TAB, letter + str(r1),
                               "formula %s, put back from Lucy's last healthy copy"
                               % ("deleted" if not old.strip() else "broken"),
                               before=old, after=f, value=f))

    # -- report only --
    for c in sorted(lane_cols):
        typed = [r for r in range(row0 + 1, len(entered))
                 if c < len(entered[r]) and entered[r][c]]
        if typed:
            cells = ", ".join(col_letter(c + 1) + str(r + 1) for r in typed[:5])
            more = " (+%d)" % (len(typed) - 5) if len(typed) > 5 else ""
            out.append(Finding("lane_spill_blocked", TAB, cells + more,
                               "typed under the '%s' lane: when the list reaches it the lane "
                               "goes blank" % _cell([heads], 0, c).strip()[:30],
                               before=_cell(lanes_values, typed[0], c)))

    seen = set()
    for key, cols in blocks.items():
        for c in cols:
            for m in LITERAL_COND_RE.finditer(frow[c] if c < len(frow) else ""):
                tab, letter, first, last, op, lit = (m.group(1), m.group(2), int(m.group(3)),
                                                     int(m.group(5)), m.group(6), m.group(7))
                grid = boards.get(tab)
                if grid is None or (key, letter, op, lit) in seen:
                    continue
                seen.add((key, letter, op, lit))
                vals = [_cell(grid, r, col_index(letter) - 1).strip()
                        for r in range(first - 1, last)]
                filled = [v for v in vals if v]
                if lit in vals or not filled:
                    continue
                if sum(1 for v in filled if NUMBER_RE.match(v)) >= 0.8 * len(filled):
                    out.append(Finding("lane_dead_cond", TAB, "%s block" % key,
                                       "%s%s\"%s\" reads '%s' (col %s), which only holds "
                                       "numbers: it never drops anyone"
                                       % (letter, op, lit, board_header(grid, col_index(letter) - 1)
                                          .replace("|", " ").strip(), letter),
                                       before="%s%s\"%s\"" % (letter, op, lit)))

    for key, cols in blocks.items():
        for c in cols:
            h = _cell([heads], 0, c)
            f = frow[c] if c < len(frow) else ""
            nums = [int(n) for n in re.findall(r"\d+", h.split("wk")[0])]
            if not nums or not _healthy(f):
                continue
            if "exit" in h.lower():
                want = "<%d" % ((nums[1] if len(nums) > 1 else nums[0]) + 1)
            else:
                want = ">=%d" % nums[0]
            got = re.findall(r"!\$?D\$?\d+:\$?D\$?\d+\s*(>=|<)\s*(\d+)", f)
            if got and want not in ["%s%s" % g for g in got]:
                out.append(Finding("lane_threshold", TAB, col_letter(c + 1) + str(r1),
                                   "header says %r, formula filters %s"
                                   % (h.strip()[:30], " and ".join("%s%s" % g for g in got)),
                                   before=f))

    for c, t in twin.items():
        if c in blocks.get("current", []) and c < len(frow) and t < len(frow):
            if _healthy(frow[c]) and _healthy(frow[t]) and _squash(frow[c]) != _squash(frow[t]):
                out.append(Finding("lane_twin_differs", TAB,
                                   "%s%d vs %s%d" % (col_letter(c + 1), r1, col_letter(t + 1), r1),
                                   "Current Week and Last week filter this lane differently",
                                   before=frow[c], after=frow[t]))
    return out


def restore_lost(lanes_formulas, lanes_values, good: Optional[dict]) -> Dict[int, str]:
    """{col0: formula} for lane cells with no healthy formula, borrowed from
    the twin lane or the healthy copy -- still pointing at the twin's week;
    lanes.py re-points it. Used by the 10-minute lanes job so a deleted lane
    no longer stops the whole job."""
    good = good or {"formulas": {}}
    row0, blocks = L.find_blocks(lanes_values)
    frow = lanes_formulas[row0] if row0 < len(lanes_formulas) else []
    cur, last = blocks.get("current", []), blocks.get("last", [])
    out = {}
    for mine, other in ((cur, last), (last, cur)):
        for i, c in enumerate(mine):
            if _healthy(_cell([frow], 0, c)):
                continue
            src = _cell([frow], 0, other[i]) if i < len(other) else ""
            if not _healthy(src):
                src = good["formulas"].get(col_letter(c + 1), "")
            if _healthy(src):
                out[c] = src
    return out
