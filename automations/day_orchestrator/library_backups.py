"""Per-report last-known-good backups for every shared-library report, in a
'Library Backups' tab of the shared library Sheet. So no user edit can ever
permanently lose or break a report: the guard (library_self_heal) restores from
here when a report's code stops compiling or loses a registered critical marker.

Backups only ever hold a GOOD version — the guard refuses to overwrite a backup
with code that doesn't compile or that shrank suspiciously (a possible wipe), so
the safety copy can't be poisoned by the very thing it protects against.
"""
from __future__ import annotations

import datetime

from automations.recruiting_report import fill as _fill

SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"   # shared library Sheet
TAB = "Library Backups"
HEADERS = ["ID", "Script", "Chars", "Updated At"]
_LAST_COL = chr(ord("A") + len(HEADERS) - 1)   # 'D'


def _ws():
    import gspread as _gs
    sh = _fill.open_by_key(SHEET_ID)
    try:
        return sh.worksheet(TAB)
    except _gs.WorksheetNotFound:
        ws = sh.add_worksheet(title=TAB, rows=200, cols=len(HEADERS))
        ws.update([HEADERS], f"A1:{_LAST_COL}1")
        return ws


def get(lib_id: str) -> str | None:
    """The stored good script for a report, or None if there's no backup yet."""
    try:
        for r in _ws().get_all_records():
            if str(r.get("ID", "")).strip() == lib_id:
                s = str(r.get("Script", "") or "")
                return s or None
    except Exception:
        return None
    return None


def save(lib_id: str, script: str) -> bool:
    """Upsert a report's backup. Caller guarantees the script is good."""
    try:
        ws = _ws()
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        vals = [lib_id, script, len(script), stamp]
        target = None
        for i, r in enumerate(ws.get_all_records(), start=2):
            if str(r.get("ID", "")).strip() == lib_id:
                target = i
                break
        if target:
            ws.update([vals], f"A{target}:{_LAST_COL}{target}", value_input_option="RAW")
        else:
            ws.append_row(vals, value_input_option="RAW")
        return True
    except Exception:
        return False
