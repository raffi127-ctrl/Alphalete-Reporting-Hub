"""Knock rows a LUCY pulled, shared for the owners' hourly board.

Most owners' knocks reach the board through their own Mac (Lucy ECO ->
'ICD Knocks'). A few offices are pulled by one of OUR Lucys instead -- Raf's
by gap_alerts on Lucy 1, Carlos's NDS crew by nds_oof on Lucy 2 -- and the
board runs on Lucy 1, which cannot see Lucy 2's disk. So whichever Lucy pulls
an office drops its rows here, in the relay workbook, one row per office:

    'Lucy Knocks' tab:  Key | Owner | Day | At | Rows JSON

Overwritten in place (one row per key), so the tab never grows. The rows are
in the renderer's own shape (SHEET_COLUMNS), the same as the ECO rows after
knocks_map.to_rows.

Never raises out of `share`: the pull's own board matters more than this copy.
Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Dict, List

TAB = "Lucy Knocks"
HEADER = ["Key", "Owner", "Day", "At", "Rows JSON"]
K_KEY, K_OWNER, K_DAY, K_AT, K_ROWS = range(5)


def _book():
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(P.RELAY_SPREADSHEET_ID)


def _tab(book, create: bool = False):
    try:
        return book.worksheet(TAB)
    except Exception:  # noqa: BLE001
        if not create:
            return None
        ws = book.add_worksheet(title=TAB, rows=20, cols=len(HEADER))
        ws.update(values=[HEADER], range_name="A1")
        return ws


def share(key: str, owner: str, day: dt.date, rows: List[Dict],
          log=print) -> None:
    """Put this office's rows for `day` on the tab (its own row, replaced)."""
    try:
        ws = _tab(_book(), create=True)
        values = ws.get_all_values()
        line = [key, owner, day.isoformat(),
                dt.datetime.now().isoformat(timespec="seconds"),
                json.dumps(rows, default=str)]
        at = next((i for i, r in enumerate(values[1:], start=2)
                   if r and r[K_KEY].strip() == key), None)
        if at is None:
            ws.append_row(line, value_input_option="RAW")
        else:
            ws.update(values=[line], range_name="A%d:E%d" % (at, at),
                      value_input_option="RAW")
    except Exception as e:  # noqa: BLE001
        log("  (owner-board copy of %s not shared: %s)" % (key, e))


def read(book, day: dt.date, *, stale_minutes: int = 0,
         log=print) -> Dict[str, List[Dict]]:
    """{owner: rows} for `day`. A row older than `stale_minutes` (0 = no
    limit) is left off: that Lucy's pull has stopped."""
    ws = _tab(book)
    if ws is None:
        return {}
    out: Dict[str, List[Dict]] = {}
    for r in ws.get_all_values()[1:]:
        r = list(r) + [""] * (len(HEADER) - len(r))
        if r[K_DAY].strip() != day.isoformat():
            continue
        if stale_minutes:
            try:
                age = dt.datetime.now() - dt.datetime.fromisoformat(r[K_AT])
            except ValueError:
                age = None
            if age is None or age > dt.timedelta(minutes=stale_minutes):
                log("%-14s Lucy pull from %s — too old, left off"
                    % (r[K_KEY], r[K_AT] or "?"))
                continue
        try:
            rows = json.loads(r[K_ROWS] or "[]")
        except ValueError:
            continue
        if rows:
            out.setdefault(r[K_OWNER] or r[K_KEY], []).extend(rows)
    return out
