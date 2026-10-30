"""What the fixer looks for on a 'Lanes' tab -- pure functions.

Rafael, 2026-10-10 (Slack): owners will be pushed to use the main spreadsheets
more, so they will break them; Lanes is #2 of his list. Eve, 2026-10-19:
"primero arrancá con lanes" -- and "deben ser todos": our board AND every
owner's board that has one.

THE TAB. Two blocks, 'Current Week' and 'Last week', one lane per column
(Super Saiyan / Fast / Cruise / Grandma / Exit), each lane ONE formula in the
row under the lane headers with the names spilling below it. Every office
builds it its own way, so nothing here assumes a shape:
  * ours (Sales Board): each block reads its own 'Sales Board WE m.d' tab and
    lanes.py re-points them every 10 min -- `targets` says where;
  * Drew / Jairo: both blocks read ONE board tab, current vs last-week total
    column (C vs G);
  * Frank: 'Last week' is TYPED by hand every week -- not formulas, never
    "healed";
  * Cyrus: one LET/INDIRECT formula per block that finds its week by itself.

WHICH CELLS ARE LANES. A cell is a lane when it holds a formula now, or held
one in the last healthy copy Lucy saved of that tab (lanes_good.json, keyed by
sheet + tab). A hand-typed block (Frank) never had one, so it is never touched.

WHAT GETS FIXED
  lane_formula_lost   formula deleted / typed over / #REF! -> put back from
                      the healthy copy, or (ours only, where each block reads
                      its own week) from the same lane in the other block.
  lane_col_moved      a column of the board tab moved (inserted / deleted
                      column) -> the letter goes where that header is now.
  lane_range          wrong week tab (ours) or the range stops before the
                      board's TOTALS row -- a rep added above TOTALS falls
                      outside it and vanishes from every lane.
  lane_extra_lost     another formula on the lane row (col M '2wks in a Row').
WHAT IS ONLY REPORTED -- someone may have done it on purpose
  lane_spill_blocked  something typed under a lane: when the list reaches it
                      the whole lane goes BLANK (iferror hides the error).
  lane_threshold      the cut-off doesn't match the header ('8+' filtering >=7).
  lane_twin_differs   (ours) the two weeks filter the same lane differently.

Nothing here reads or writes a sheet; run.py does the I/O.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from automations.alphalete_sales_board import lanes as L
from automations.sales_board_fixer.checks import Finding, col_index, col_letter

TAB = L.TAB
# A range on another tab: 'Sales Board WE 10.18'!DQ4:DQ72 or JAIRO!B4:B113
RANGE_RE = re.compile(r"(?:'([^']+)'|(?<![\w'])([A-Za-z_][\w.]*))!"
                      r"\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)")
# a range compared with a number: ...!C4:C53>=10
NUMBER_TAIL_RE = re.compile(r"\s*(>=|<)\s*(\d+)")
TOTALS = "totals"
REPAIRS = ("lane_formula_lost", "lane_col_moved", "lane_range", "lane_extra_lost")


def ranges(f: str):
    """[(tab, col1, row1, col2, row2, match)] for every other-tab range."""
    return [(m.group(1) or m.group(2), m.group(3), int(m.group(4)), m.group(5),
             int(m.group(6)), m) for m in RANGE_RE.finditer(str(f or ""))]


def _ref(tab: str, c1: str, r1: int, c2: str, r2: int) -> str:
    t = tab if re.fullmatch(r"[A-Za-z_][\w.]*", tab) else "'%s'" % tab
    return "%s!%s%d:%s%d" % (t, c1, r1, c2, r2)


def _healthy(f) -> bool:
    f = str(f or "")
    return f.startswith("=") and "#REF!" not in f


def _cell(grid, r0: int, c0: int) -> str:
    return str(grid[r0][c0]) if r0 < len(grid) and c0 < len(grid[r0]) else ""


def board_header(grid, c0: int) -> str:
    """'field status|' -- a board's row 1 + row 3 over column c0. Row 2 holds
    the day's date on ours and changes weekly, so it is left out."""
    return "|".join(_cell(grid, r, c0).strip().lower() for r in (0, 2))


def _stable(h: str) -> bool:
    """A header worth tracking: something there and no date in it."""
    return h.strip("|") != "" and not re.search(r"\d", h)


def totals_end(grid, col: str) -> Optional[int]:
    """Last rep row of a board: the row above 'TOTALS' in the names column."""
    c0 = col_index(col) - 1
    for r in range(len(grid)):
        if _cell(grid, r, c0).strip().lower() == TOTALS:
            return r          # 0-based TOTALS row == 1-based row above it
    return None


def remember(lanes_formulas, lanes_values, boards: Dict[str, list]) -> dict:
    """The healthy copy saved to lanes_good.json: every formula on the lane
    row, and the header of every board column the lanes read."""
    row0, _ = L.find_blocks(lanes_values)
    frow = lanes_formulas[row0] if row0 < len(lanes_formulas) else []
    formulas = {col_letter(c + 1): f for c, f in enumerate(frow) if str(f).startswith("=")}
    headers = {}
    for f in formulas.values():
        for tab, c1, _r1, c2, _r2, _m in ranges(f):
            grid = boards.get(tab)
            if grid is not None and c1 == c2:
                h = board_header(grid, col_index(c1) - 1)
                if _stable(h):
                    headers["%s|%s" % (tab, c1) if not tab.startswith(L.fill.TAB_PREFIX)
                            else c1] = h
    return {"formulas": formulas, "headers": headers}


def _header_key(tab: str, col: str) -> str:
    """Ours rolls to a new tab every week: its headers are kept by letter."""
    return col if tab.startswith(L.fill.TAB_PREFIX) else "%s|%s" % (tab, col)


def _squash(f: str) -> str:
    """The formula minus its week and end row, spaces dropped."""
    f = RANGE_RE.sub(lambda m: "T!%s%s:%s" % (m.group(3), m.group(4), m.group(5)), f)
    return re.sub(r"\s+", "", f).lower()


def _fix_ranges(f: str, boards: Dict[str, list], headers: Dict[str, str]):
    """(formula, moved [(tab, old, new, header)], ends [(tab, old, new)],
    starts [(tab, col, old, new)]): columns moved back to their header, every
    range started on the row its first range (the names) starts on, and every
    range ended on the row above its board's TOTALS (when the board has one).

    Starts (Miami 2026-10-30): one range at BL5:BL113 next to B4:B113 made
    FILTER's ranges different sizes; iferror turned the error into "" and every
    lane went blank for two days with nothing looking broken."""
    moved, ends, starts = [], [], []
    widths = {}
    first = {}
    for t, _c1, a, _c2, _z, _m in ranges(f):
        first.setdefault(t, a)

    def sub(m):
        tab, c1, r1, c2, r2 = (m.group(1) or m.group(2), m.group(3), int(m.group(4)),
                               m.group(5), int(m.group(6)))
        if r1 != first[tab]:
            starts.append((tab, c1, r1, first[tab]))
            r1 = first[tab]
        grid = boards.get(tab)
        if grid is None:
            return _ref(tab, c1, r1, c2, r2) if r1 != int(m.group(4)) else m.group(0)
        if c1 == c2:
            want = headers.get(_header_key(tab, c1))
            if want and board_header(grid, col_index(c1) - 1) != want:
                w = widths.setdefault(tab, max((len(r) for r in grid[:3]), default=0))
                hits = [c for c in range(w) if board_header(grid, c) == want]
                if len(hits) == 1:
                    new = col_letter(hits[0] + 1)
                    moved.append((tab, c1, new, want))
                    c1 = c2 = new
        end = totals_end(grid, (ranges(f)[0][1] if ranges(f) else c1))
        if end and end >= r1 and end != r2:
            ends.append((tab, r2, end))
            r2 = end
        return (_ref(tab, c1, r1, c2, r2)
                if (c1, r1, r2) != (m.group(3), int(m.group(4)), int(m.group(6))) else m.group(0))
    out = RANGE_RE.sub(sub, f)
    return out, moved, ends, starts


def check(lanes_formulas, lanes_values, entered, boards: Dict[str, list],
          good: Optional[dict], targets: Optional[Dict[str, Tuple[str, int]]] = None,
          tab: str = TAB) -> List[Finding]:
    """Findings for one Lanes tab.

    entered[r][c] = True where a person typed the cell (userEnteredValue);
      False where it is blank or spilled from a formula.
    boards = {tab title: values grid} of the board tab(s) the lanes read.
    good = this tab's healthy copy from lanes_good.json, or None.
    targets = ours only: {'current': (tab, end_row), 'last': (...)} as
      lanes.py computes them; None on an owner's sheet (fixed tabs).
    """
    good = good or {"formulas": {}, "headers": {}}
    row0, blocks = L.find_blocks(lanes_values)
    r1 = row0 + 1                                    # the lane row, 1-based
    frow = list(lanes_formulas[row0]) if row0 < len(lanes_formulas) else []
    heads = lanes_values[row0 - 1] if row0 >= 1 else []
    out: List[Finding] = []
    weekly = targets is not None

    def at(c):
        return _cell([frow], 0, c)

    twin = {}
    for a, b in (("current", "last"), ("last", "current")):
        for i, c in enumerate(blocks.get(a, [])):
            if i < len(blocks.get(b, [])):
                twin[c] = blocks[b][i]

    def was_lane(c):
        # ours: both weeks are always formulas, so the other week vouches too
        return (at(c).startswith("=") or col_letter(c + 1) in good["formulas"]
                or (weekly and c in twin and at(twin[c]).startswith("=")))

    for key, cols in blocks.items():
        for c in cols:
            if not was_lane(c):
                continue                              # typed by hand (Frank)
            old = at(c)
            new, why, kind = old, [], None
            if not _healthy(old):
                src, origin = good["formulas"].get(col_letter(c + 1), ""), "Lucy's last healthy copy"
                if weekly and c in twin and _healthy(at(twin[c])):
                    src, origin = at(twin[c]), "the same lane in the other week"
                if not _healthy(src):
                    out.append(Finding("lane_formula_lost", tab, col_letter(c + 1) + str(r1),
                                       "lane formula gone and no healthy copy to put back",
                                       before=old, after="(a mano)"))
                    continue
                new, kind = src, "lane_formula_lost"
                why.append("formula was %s, put back from %s"
                           % ("deleted" if not old.strip() else "broken", origin))
            if weekly and L.REF_RE.search(new):
                new = L.repoint(new, *targets[key])
            new, moved, ends, starts = _fix_ranges(new, boards, good["headers"])
            if moved:
                kind = kind or "lane_col_moved"
                why += ["'%s' moved %s -> %s" % (h.replace("|", " ").strip(), o, n)
                        for _t, o, n, h in moved]
            if starts:
                kind = kind or "lane_range"
                why += ["%s started on row %d, not %d like the rest (lane showed blank)"
                        % (cl, a, b) for _t, cl, a, b in starts]
            if new != old:
                kind = kind or "lane_range"
                if kind == "lane_range" and (ends or not starts):
                    why.append("pointed at the wrong week or stopped short of TOTALS"
                               if weekly else "stopped short of TOTALS (rows %s)"
                               % ", ".join("%d->%d" % (a, b) for _t, a, b in ends[:1]))
                out.append(Finding(kind, tab, col_letter(c + 1) + str(r1), "; ".join(why),
                                   before=old, after=new, value=new))
            frow += [""] * (c + 1 - len(frow))
            frow[c] = new

    # -- other formulas on the lane row (col M) --
    lane_cols = {c for cols in blocks.values() for c in cols}
    for letter, f in good["formulas"].items():
        c = col_index(letter) - 1
        if c in lane_cols:
            continue
        old = at(c)
        if not old.startswith("=") or "#REF!" in old:
            out.append(Finding("lane_extra_lost", tab, letter + str(r1),
                               "formula %s, put back from Lucy's last healthy copy"
                               % ("deleted" if not old.strip() else "broken"),
                               before=old, after=f, value=f))

    # -- report only --
    for c in sorted(lane_cols):
        if not at(c).startswith("="):
            continue
        typed = [r for r in range(row0 + 1, len(entered))
                 if c < len(entered[r]) and entered[r][c]]
        if typed:
            cells = ", ".join(col_letter(c + 1) + str(r + 1) for r in typed[:5])
            more = " (+%d)" % (len(typed) - 5) if len(typed) > 5 else ""
            out.append(Finding("lane_spill_blocked", tab, cells + more,
                               "typed under the '%s' lane: when the list reaches it the lane "
                               "goes blank" % _cell([heads], 0, c).strip()[:30],
                               before=_cell(lanes_values, typed[0], c)))

    for c in sorted(lane_cols):
        h, f = _cell([heads], 0, c), at(c)
        nums = [int(n) for n in re.findall(r"\d+", h.lower().split("wk")[0])]
        if not nums or not _healthy(f):
            continue
        rs = ranges(f)
        apps = rs[1][1] if len(rs) > 1 else None     # 1st condition = the apps column
        got = []
        for t, c1, _a, _b, _z, m in rs:
            tail = NUMBER_TAIL_RE.match(f, m.end())
            if c1 == apps and tail:
                got.append("%s%s" % tail.groups())
        if not got:
            continue
        if "exit" in h.lower():
            want = "<%d" % ((nums[1] if len(nums) > 1 else nums[0]) + 1)
        else:
            want = ">=%d" % nums[0]
        if want not in got:
            out.append(Finding("lane_threshold", tab, col_letter(c + 1) + str(r1),
                               "header says %r, formula filters %s"
                               % (re.sub(r"\s+", " ", h).strip()[:30], " and ".join(got)),
                               before=f))

    if weekly:
        for c, t in twin.items():
            if c in blocks.get("current", []) and _healthy(at(c)) and _healthy(at(t)) \
                    and ranges(at(c)) and _squash(at(c)) != _squash(at(t)):
                out.append(Finding("lane_twin_differs", tab,
                                   "%s%d vs %s%d" % (col_letter(c + 1), r1, col_letter(t + 1), r1),
                                   "Current Week and Last week filter this lane differently",
                                   before=at(c), after=at(t)))
    return out


def restore_lost(lanes_formulas, lanes_values, good: Optional[dict]) -> Dict[int, str]:
    """{col0: formula} for OUR lane cells with no healthy formula, borrowed
    from the other week's lane or the healthy copy -- still pointing at the
    source's week; lanes.py re-points it. Used by the 10-minute lanes job so a
    deleted lane no longer stops the whole job."""
    good = good or {"formulas": {}}
    row0, blocks = L.find_blocks(lanes_values)
    frow = lanes_formulas[row0] if row0 < len(lanes_formulas) else []
    cur, last = blocks.get("current", []), blocks.get("last", [])
    out = {}
    for mine, other in ((cur, last), (last, cur)):
        for i, c in enumerate(mine):
            if _healthy(_cell([frow], 0, c)):
                continue
            src = "" if i >= len(other) else (out.get(other[i]) or _cell([frow], 0, other[i]))
            if not _healthy(src):
                src = good["formulas"].get(col_letter(c + 1), "")
            if _healthy(src):
                out[c] = src
    return out


def roll(lanes_formulas, lanes_values, boards: Dict[str, list],
         targets: Dict[str, str], tab: str = TAB) -> List[Finding]:
    """An owner whose board is one dated tab per week ('10/25') and whose
    Lanes read those tabs (owners.json "lanes_roll", Omar 2026-10-25): each
    block onto its week's tab -- targets = {'current': title, 'last': title}
    -- every range ending on the row above that tab's TOTALS. Only the tab
    name and the end row change; the owner's conditions stay as they are."""
    row0, blocks = L.find_blocks(lanes_values)
    frow = lanes_formulas[row0] if row0 < len(lanes_formulas) else []
    out: List[Finding] = []
    for key, cols in blocks.items():
        want = targets.get(key)
        grid = boards.get(want)
        if grid is None:
            continue
        for c in cols:
            old = _cell([frow], 0, c)
            rs = ranges(old)
            if not _healthy(old) or not rs:
                continue                      # lost formulas are check()'s job
            end = totals_end(grid, rs[0][1])
            if not end:
                continue
            new = RANGE_RE.sub(lambda m: _ref(want, m.group(3), int(m.group(4)),
                                              m.group(5), end), old)
            if new != old:
                out.append(Finding("lane_week", tab, col_letter(c + 1) + str(row0 + 1),
                                   "%s now reads '%s' (rows %d-%d)"
                                   % (key, want, rs[0][2], end),
                                   before=old, after=new, value=new))
    return out
