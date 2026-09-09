"""The two sheets the box is filled FROM.

1. TRAINERS -- the blue box on 'Line Up WE <m>.<d>', same workbook as the
   board. One row per trainer: 'Is Training' holds the trainer, and the
   columns to its right hold the one, two or three new starts they took. The
   header labels only the first of those columns ('New Start Name'), so the
   box's WIDTH is read from the blue fill on the header row -- that colour is
   literally what makes it a box, and it is what people extend when a fourth
   trainee column is needed.

   Junk lands in the box ('Fire', '1st Choices' were both in it on 9/09).
   Nothing filters them here on purpose: a name that is not in the board's box
   is never looked up, so it can never be written.

2. LOCATIONS -- 'D2D OBCL <m>.<d>' on the recruiting book, the classroom
   intake sheet for the week's MONDAY. First name and last name are two
   columns; the city is 'Location'. Rows with no city are skipped rather than
   written blank.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

from automations.new_starts_box import config as C
from automations.new_starts_box.box import cell, width
from automations.new_starts_box.names import norm


def open_tab(book, title: str, what: str):
    want = title.strip().lower()
    for ws in book.worksheets():
        if ws.title.strip().lower() == want:
            return ws
    raise RuntimeError(
        "no %r tab (%s) in %r -- it is usually rolled over at the start of the "
        "week. Nothing was written." % (title, what, book.title))


def _header(grid, labels: Tuple[str, ...], scan_rows: int = 12
            ) -> Tuple[int, Dict[str, int]]:
    """(row, {label: col}) for the first row carrying ALL of `labels`."""
    want = {norm(l) for l in labels}
    for r in range(1, min(len(grid), scan_rows) + 1):
        found = {norm(cell(grid, r, c)): c
                 for c in range(1, width(grid) + 1) if cell(grid, r, c).strip()}
        if want <= set(found):
            return r, {l: found[norm(l)] for l in labels}
    raise RuntimeError(
        "no header row carrying %s in the first %d rows -- the tab's shape "
        "changed. Nothing was written." % (", ".join(map(repr, labels)),
                                           scan_rows))


def _band_end(book, tab_title: str, header_row: int, start_col: int,
              grid) -> int:
    """The last column of the blue box, read off the header row's fill.

    Falls back to the tab's used width if the formatting can't be read -- on
    this tab the box is the right-most thing on the sheet, so that is the same
    answer, just less explicit about why.
    """
    try:
        end_a1 = "%s%d" % (_letters(width(grid) or start_col), header_row)
        meta = book.fetch_sheet_metadata({
            "includeGridData": True,
            "ranges": ["'%s'!A%d:%s" % (tab_title, header_row, end_a1)],
            "fields": "sheets(data(rowData(values(effectiveFormat("
                      "backgroundColor)))))"})
        vals = meta["sheets"][0]["data"][0]["rowData"][0].get("values", [])
        band = _hex(vals[start_col - 1])
        end = start_col
        while end < len(vals) and _hex(vals[end]) == band:
            end += 1
        if end > start_col:
            return end
    except Exception:  # noqa: BLE001 -- formatting is a nicety, never the run
        pass
    return max(start_col, width(grid))


def _hex(value: dict) -> str:
    bg = (value.get("effectiveFormat") or {}).get("backgroundColor") or {}
    return "%02x%02x%02x" % tuple(
        int(round(bg.get(k, 0) * 255)) for k in ("red", "green", "blue"))


def _letters(col: int) -> str:
    out, c = "", col
    while c > 0:
        c, rem = divmod(c - 1, 26)
        out = chr(65 + rem) + out
    return out


def collect_pairs(grid, header_row: int, trainer_col: int, first_name_col: int,
                  last_name_col: int) -> Tuple[List[Tuple[str, str]], List[str]]:
    """([(new start, trainer)], notes) read top-down out of the blue box."""
    pairs: List[Tuple[str, str]] = []
    seen: Dict[str, str] = {}
    notes: List[str] = []
    for r in range(header_row + 1, len(grid) + 1):
        trainer = cell(grid, r, trainer_col).strip()
        if not trainer:
            continue
        for c in range(first_name_col, last_name_col + 1):
            name = cell(grid, r, c).strip()
            if not name:
                continue
            key = norm(name)
            if key in seen:
                if seen[key] != trainer:
                    notes.append(
                        "%r is in the line up twice -- under %r (used) and %r "
                        "on row %d (ignored)" % (name, seen[key], trainer, r))
                continue
            seen[key] = trainer
            pairs.append((name, trainer))
    return pairs, notes


def trainers(book, day: dt.date) -> Tuple[List[Tuple[str, str]], List[str]]:
    """([(new start, trainer)], notes), in the order the line up lists them.

    FIRST MENTION WINS. On 9/09 Ashari Evans was in the box twice -- under
    Sydney Agnew on line 8 and under Lakeiah Gregory on line 25 -- and the
    board says Sydney Agnew. The rows are worked top-down and a second sighting
    is reported, not applied.
    """
    title = C.lineup_tab(day)
    ws = open_tab(book, title, "the week's line up")
    grid = ws.get_all_values()
    hrow, cols = _header(grid, (C.LINEUP_TRAINER_LABEL, C.LINEUP_NEWSTART_LABEL))
    tcol = cols[C.LINEUP_TRAINER_LABEL]
    ncol = cols[C.LINEUP_NEWSTART_LABEL]
    end = _band_end(book, ws.title, hrow, tcol, grid)

    pairs, notes = collect_pairs(grid, hrow, tcol, ncol, end)
    notes.insert(0, "line up %r: %d trainer/new-start pairs from cols %s-%s"
                 % (ws.title, len(pairs), _letters(ncol), _letters(end)))
    return pairs, notes


def locations(client, day: dt.date) -> Tuple[List[Tuple[str, str]], List[str]]:
    """([(full name, city)], notes) from the week's D2D OBCL tab."""
    title = C.obcl_tab(day)
    book = client.open_by_key(C.OBCL_BOOK_ID)
    ws = open_tab(book, title, "the week's classroom intake")
    grid = ws.get_all_values()
    hrow, cols = _header(grid, (C.OBCL_FIRST_LABEL, C.OBCL_LAST_LABEL,
                                C.OBCL_LOCATION_LABEL))
    out: List[Tuple[str, str]] = []
    for r in range(hrow + 1, len(grid) + 1):
        full = ("%s %s" % (cell(grid, r, cols[C.OBCL_FIRST_LABEL]),
                           cell(grid, r, cols[C.OBCL_LAST_LABEL]))).strip()
        city = cell(grid, r, cols[C.OBCL_LOCATION_LABEL]).strip()
        if full and city:
            out.append((full, city))
    return out, ["%r: %d people with a location" % (ws.title, len(out))]
