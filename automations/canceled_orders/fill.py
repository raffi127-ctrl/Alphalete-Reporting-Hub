"""Write new canceled-order rows to a target tab on the Disconnects sheet.
New rows go at the TOP (row 2, just below header). Dedup by
(Customer Name, SPM #) — only inserts rows whose key isn't already
in the tab.

The 3 tabs have different column sets (Local Office = 10 cols, the two
Captainship tabs = 12 cols), so we map our row dict onto each tab's
HEADER row at runtime by label — never by index. A field that doesn't
exist in a particular tab's header is simply skipped for that write.
"""
from __future__ import annotations

from typing import List, Dict

SHEET_ID = "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8"
TAB_LOCAL_OFFICE = "Local Office - Daily Cancels"
TAB_RAF_CAPTAINSHIP = "Raf's Captainship - Cancels Ongoing"
TAB_STARR_SAHIL = "Starr Capi + Sahil- Cancels Ongoing"


def _norm(s: str) -> str:
    return (s or "").strip().lower()


# Some columns are spelled slightly differently across the 3 destination
# tabs (Eve / past VAs typed them by hand): "SPM #" vs "SPM Number" vs
# "SPM Number " (trailing space); "DTR Status" vs "DTR " (trailing space).
# We canonicalize headers to a single internal name so pull.py + render.py
# can use one stable key.
_HEADER_ALIASES = {
    # canonical key  →  list of header strings seen in the wild
    "SPM #":      ["SPM #", "SPM Number", "SPM Number "],
    "DTR Status": ["DTR Status", "DTR ", "DTR"],
    "Owner Name": ["Owner Name", "Owner Cancels"],
}


def _canonical(label: str) -> str:
    """Map a sheet's literal header to our canonical field key.
    Unknown headers pass through (trimmed)."""
    s = (label or "").strip()
    for canon, aliases in _HEADER_ALIASES.items():
        if s in aliases:
            return canon
    return s


def _find_col(header: list[str], name: str) -> int:
    """Find a column by name OR by any of its known aliases."""
    target = _norm(name)
    aliases = _HEADER_ALIASES.get(name, [name])
    alias_set = {_norm(a) for a in aliases} | {target}
    for i, h in enumerate(header):
        if _norm(h) in alias_set:
            return i
    raise ValueError(f"Column {name!r} (or aliases {aliases}) not found in {header}")


def find_new_rows(sh, tab_name: str,
                  rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Return the subset of `rows` whose (Customer Name, SPM #) is
    NOT already in `tab_name`. Used by run.py to filter the Slack image
    to truly-new rows when the 3-day window overlaps prior runs."""
    ws = sh.worksheet(tab_name)
    grid = ws.get_all_values()
    header = grid[0] if grid else []
    cust_col = _find_col(header, "Customer Name")
    spm_col = _find_col(header, "SPM #")

    def _key(r: list[str]) -> tuple[str, str]:
        return (r[cust_col].strip() if len(r) > cust_col else "",
                r[spm_col].strip() if len(r) > spm_col else "")

    existing_keys = {_key(r) for r in grid[1:] if _key(r) != ("", "")}
    return [r for r in rows
            if (r.get("Customer Name", "").strip(),
                r.get("SPM #", "").strip()) not in existing_keys]


def insert_new_rows_at_top(sh, tab_name: str, rows: List[Dict[str, str]],
                            dry_run: bool = False) -> dict:
    new = find_new_rows(sh, tab_name, rows)
    if not new:
        return {"tab": tab_name, "new_count": 0,
                "skipped_already_in_sheet": len(rows)}
    if dry_run:
        return {"tab": tab_name, "new_count": len(new),
                "skipped_already_in_sheet": len(rows) - len(new),
                "dry_run": True}

    ws = sh.worksheet(tab_name)
    header = ws.row_values(1)
    # Header-label mapping: build a matrix that matches THIS tab's columns.
    # Sheet headers may be aliased ("SPM Number " ↔ "SPM #") so we look up
    # row values by canonical key. Unknown columns get empty strings (Eve's
    # manual cols like SENT?, Cancels Feedback, Reason — left blank for her).
    matrix = [[r.get(_canonical(col), "") for col in header] for r in new]
    ws.insert_rows(matrix, row=2, value_input_option="USER_ENTERED")

    deleted = _dedup_pass(ws)

    return {"tab": tab_name, "new_count": len(new),
            "skipped_already_in_sheet": len(rows) - len(new),
            "wrote_rows": len(new),
            "post_insert_dedup_deleted": deleted}


def _dedup_pass(ws) -> int:
    """Scan the tab. For each (Customer Name, SPM #) appearing > once,
    delete the rows closer to the TOP (newer). Keep the bottom-most row.
    Returns the number of rows deleted."""
    grid = ws.get_all_values()
    if len(grid) <= 2:
        return 0
    header = grid[0]
    cust_col = _find_col(header, "Customer Name")
    spm_col = _find_col(header, "SPM #")

    seen: dict[tuple, int] = {}
    rows_to_delete: list[int] = []
    for i in range(len(grid) - 1, 0, -1):
        r = grid[i]
        cust = r[cust_col].strip() if len(r) > cust_col else ""
        spm = r[spm_col].strip() if len(r) > spm_col else ""
        if not cust and not spm:
            continue
        key = (cust, spm)
        if key in seen:
            rows_to_delete.append(i)
        else:
            seen[key] = i

    if not rows_to_delete:
        return 0
    # Batch all deletes into ONE Sheets API call. Iterating per-row hit
    # the 60-writes/minute quota on tabs with lots of legacy dupes
    # (Megan's first real run 2026-05-28: 429 quota error on Raf's
    # Captainship). Walk top-down (highest index first) so each
    # deleteDimension range is interpreted against the same baseline.
    requests = [
        {"deleteDimension": {
            "range": {
                "sheetId": ws.id,
                "dimension": "ROWS",
                "startIndex": row_0,
                "endIndex": row_0 + 1,
            },
        }}
        for row_0 in sorted(rows_to_delete, reverse=True)
    ]
    ws.spreadsheet.batch_update({"requests": requests})
    return len(rows_to_delete)
