"""Creating and removing rep tabs.

NEW TABS are duplicates of a real, current rep tab rather than of 'Template'.
The Template hasn't kept up: it has six week columns and an older row list
(no '2nd rds Conducted', no 'Personal New starts this week'), so a rep started
from it would get a tab that doesn't match the fifty next to it. The prototype
is picked automatically as the rep tab whose week run reaches furthest — i.e.
the newest one made — and the copy is then blanked across its week block so
none of the prototype's numbers ride along.

DELETING a tab is the one irreversible thing this report does, so it never
happens without a snapshot: every deleted tab is written to
output/reps_gross_paycheck/deleted/ as a CSV of its full contents first. If a
termination turns out to be wrong, the tab is rebuildable from that file.
[[don't touch user data without confirming]]
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

from automations.reps_gross_paycheck import records
from automations.reps_gross_paycheck.records import TabModel

SNAPSHOT_DIR = Path("output") / "reps_gross_paycheck" / "deleted"


def pick_prototype(tabs: List[TabModel]) -> Optional[TabModel]:
    """The rep tab to clone for new reps: newest week run, then widest."""
    usable = [t for t in tabs if t.weeks]
    if not usable:
        return None
    return max(usable, key=lambda t: (t.last_week, len(t.weeks), t.title))


def duplicate_requests(prototype: TabModel, new_names: List[str],
                       start_index: int) -> List[dict]:
    """batch_update requests cloning `prototype` once per new rep."""
    return [
        {"duplicateSheet": {
            "sourceSheetId": prototype.sheet_id,
            "insertSheetIndex": start_index + i,
            "newSheetName": name}}
        for i, name in enumerate(new_names)
    ]


def seed_values(prototype: TabModel, name: str,
                first_week: dt.date) -> List[dict]:
    """values_batch_update entries that turn a fresh clone into `name`'s tab.

    Writes the name, anchors the week run at `first_week` (every later header
    is already '=<prev>+7' and follows on its own), and blanks the week block
    so the prototype's own numbers don't come along. Only the week columns are
    cleared — the household-expenses block to the right is the same starting
    budget on every tab and is meant to be inherited.
    """
    first_col = min(prototype.weeks.values())
    last_col = max(prototype.weeks.values())
    left, right = records.a1_col(first_col), records.a1_col(last_col)
    blank_rows = max(prototype.gp_row, prototype.last_label_row)
    width = last_col - first_col + 1
    return [
        {"range": f"'{name}'!A1", "values": [[name]]},
        # Clear first, anchor second: the clear covers B1 too.
        {"range": f"'{name}'!{left}1:{right}{blank_rows}",
         "values": [[""] * width for _ in range(blank_rows)]},
        {"range": f"'{name}'!{left}1",
         "values": [[first_week.strftime("%m/%d/%Y")]]},
        *[{"range": f"'{name}'!{records.a1_col(c)}1",
           "values": [[f"={records.a1_col(c - 1)}1+7"]]}
          for c in range(first_col + 1, last_col + 1)],
    ]


def snapshot(spreadsheet, deletes, stamp: str = "") -> Dict[int, Path]:
    """Write each tab's full contents to a CSV before it is deleted.

    Keyed by sheet id, not title: 'Mustafa Alzaidy' and 'Mustafa Alzaidy '
    (trailing space) are two real tabs whose filenames would otherwise collide
    and leave only one of the two snapshots on disk.
    """
    from automations.recruiting_report.fill import _retry
    if not deletes:
        return {}
    stamp = stamp or dt.date.today().isoformat()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    res = _retry(spreadsheet.values_batch_get,
                 [f"'{d.tab}'!A1:BZ200" for d in deletes])
    out = {}
    for d, vr in zip(deletes, res["valueRanges"]):
        safe = "".join(c if c.isalnum() or c in " -_()" else "_" for c in d.tab)
        path = SNAPSHOT_DIR / f"{stamp}--{safe.strip()}-{d.sheet_id}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(vr.get("values", []))
        out[d.sheet_id] = path
    return out


def delete_requests(sheet_ids: List[int]) -> List[dict]:
    return [{"deleteSheet": {"sheetId": sid}} for sid in sheet_ids]
