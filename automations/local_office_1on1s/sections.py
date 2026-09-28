"""Make a team tab hold exactly the sections its roster calls for.

A fresh team tab is a copy of `TEAM Template`, which arrives with TWO boxes:

    r1-41    the team box   — 'Owner 1on1's' roll-up + Team Structure
    r43-84   an individual box — the pattern every other leader repeats

So section 1 is the team head's and section 2 is the first leader's; every
leader after that needs a box appended.

BOXES ARE COPIED, NOT DRAWN. A section carries colour per block (orange sales,
cyan recruiting, yellow training, pink culture, green finances), merged label
cells in col A and its own week header. Rewriting that in code would drift from
the template the first time Raf restyles it. So a new section is a copyPaste of
`Individual Template` rows 1-42, which brings formatting, merges and headers
with it — restyle the template and the next appended section follows.

ADDITIVE ONLY. This appends and it renames; it never clears a section and never
removes one. A section whose person is gone is handled by `retire`, which MOVES
it to the TERMINATED tab and verifies the copy landed before anything is
cleared. [[feedback_dont_touch_user_data]]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from automations.local_office_1on1s import layout as LO

INDIVIDUAL_TEMPLATE = "Individual Template"
BOX_ROWS = 42            # 'Individual Template' r1-42
GAP_ROWS = 1             # blank row between boxes, as the template has it
WIDTH = 44               # cols A-AR


@dataclass
class Plan:
    rename: Dict[int, str]          # {section start row: name to write}
    append: List[str]               # names needing a new box, in order
    already: Dict[str, int]         # {name: start row} already present
    unexpected: List[str]           # sections on the tab whose person is not on the roster


def _fold(s: str) -> str:
    return LO.fold(s)


def plan(grid: List[List[str]], head: str, leaders: List[str]) -> Plan:
    """What this tab needs so it holds `head` then every name in `leaders`."""
    secs = LO.find_sections(grid)
    if not secs:
        raise RuntimeError("no 'Rep Name?' marker on this tab — is it a team tab?")

    want = [head] + list(leaders)
    have = {_fold(s.name): s.start for s in secs if s.name.strip()}

    rename: Dict[int, str] = {}
    append: List[str] = []
    already: Dict[str, int] = {}

    # Section 1 is always the head's, whatever it currently says.
    if _fold(secs[0].name) != _fold(head):
        rename[secs[0].start] = head
    else:
        already[head] = secs[0].start

    # Then fill the remaining EMPTY sections in order before appending new ones,
    # so the template's spare individual box is used rather than orphaned.
    spare = [s for s in secs[1:] if s.is_blank]
    for name in leaders:
        if _fold(name) in have:
            already[name] = have[_fold(name)]
        elif spare:
            rename[spare.pop(0).start] = name
        else:
            append.append(name)

    wanted = {_fold(w) for w in want}
    unexpected = [s.name for s in secs
                  if s.name.strip() and _fold(s.name) not in wanted]
    return Plan(rename=rename, append=append, already=already,
                unexpected=unexpected)


def apply(spreadsheet, tab: str, p: Plan, *, logfn=print) -> None:
    """Carry out a Plan: renames first, then appended boxes."""
    ws = spreadsheet.worksheet(tab)
    tmpl = spreadsheet.worksheet(INDIVIDUAL_TEMPLATE)

    if p.rename:
        ws.batch_update([{"range": f"B{row}", "values": [[name]]}
                         for row, name in sorted(p.rename.items())])
        for row, name in sorted(p.rename.items()):
            logfn(f"    r{row} <- {name}")

    if not p.append:
        return

    grid = ws.get_all_values()
    secs = LO.find_sections(grid)
    at = max(s.end for s in secs) + 1 + GAP_ROWS      # 1-indexed next free row

    requests = []
    for i, name in enumerate(p.append):
        start = at + i * (BOX_ROWS + GAP_ROWS)
        requests.append({"copyPaste": {
            "source": {"sheetId": tmpl.id, "startRowIndex": 0,
                       "endRowIndex": BOX_ROWS, "startColumnIndex": 0,
                       "endColumnIndex": WIDTH},
            "destination": {"sheetId": ws.id, "startRowIndex": start - 1,
                            "endRowIndex": start - 1 + BOX_ROWS,
                            "startColumnIndex": 0, "endColumnIndex": WIDTH},
            "pasteType": "PASTE_NORMAL"}})
    needed = at - 1 + len(p.append) * (BOX_ROWS + GAP_ROWS)
    if needed > ws.row_count:
        requests.insert(0, {"appendDimension": {
            "sheetId": ws.id, "dimension": "ROWS",
            "length": needed - ws.row_count + 10}})
    spreadsheet.batch_update({"requests": requests})

    # Name them only after the boxes exist.
    ws.batch_update([{"range": f"B{at + i * (BOX_ROWS + GAP_ROWS)}",
                      "values": [[name]]}
                     for i, name in enumerate(p.append)])
    for i, name in enumerate(p.append):
        logfn(f"    r{at + i * (BOX_ROWS + GAP_ROWS)} <- {name}  (new box)")
