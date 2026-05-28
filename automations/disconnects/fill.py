"""Write new disconnect rows to a target tab on the Disconnects sheet.
New rows go at the TOP (row 2, just below header). Dedup by SPM Number —
only inserts rows whose SPM isn't already in the tab.

The target tab is parameterized so the same code path fills both
'Local Office - New Internet Disconnects' (Raf's own office)
and 'Raf's Captainship - New Internet Disconnects' (rest of CB team).
"""
from __future__ import annotations

from typing import List, Dict

SHEET_ID = "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8"
TAB_LOCAL_OFFICE = "Local Office - New Internet Disconnects"
TAB_RAF_CAPTAINSHIP = "Raf's Captainship - New Internet Disconnects"
TAB_STARR_SAHIL = "Starr Capi + Sahil - New Internet Disconnects"

# Sheet's column order — must match the keys produced by pull.parse_and_filter
SHEET_COLS = [
    "Rep", "Order Date", "Customer Name", "SPM Number", "Account BAN",
    "Product Type", "Customer Phone", "Package", "Install Date",
    "DTR Status", "Status Date", "Eligibility Reason", "Auto Bill Pay",
    "Tech Install",
]


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _find_col(header: list[str], name: str) -> int:
    """Header lookup that tolerates trailing/leading whitespace
    (the Disconnects sheet's 'SPM Number ' has a trailing space)."""
    target = _norm(name)
    for i, h in enumerate(header):
        if _norm(h) == target:
            return i
    raise ValueError(f"Column {name!r} not found in {header}")


def find_new_rows(sh, tab_name: str,
                  rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Return the subset of `rows` whose (Customer Name, Account BAN)
    is NOT already in `tab_name`. Used by run.py to filter the Slack
    image to truly-new rows when the pull window overlaps prior runs
    (3-day window catches missed days but Slack should only show what's
    actually being added)."""
    ws = sh.worksheet(tab_name)
    grid = ws.get_all_values()
    header = grid[0] if grid else SHEET_COLS
    cust_col = _find_col(header, "Customer Name")
    ban_col = _find_col(header, "Account BAN")

    def _key(r: list[str]) -> tuple[str, str]:
        return (r[cust_col].strip() if len(r) > cust_col else "",
                r[ban_col].strip() if len(r) > ban_col else "")

    existing_keys = {_key(r) for r in grid[1:] if _key(r) != ("", "")}
    return [r for r in rows
            if (r.get("Customer Name", "").strip(),
                r.get("Account BAN", "").strip()) not in existing_keys]


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
    matrix = [[r.get(col, "") for col in SHEET_COLS] for r in new]
    ws.insert_rows(matrix, row=2, value_input_option="USER_ENTERED")

    # Post-insert dedup safety pass: if (Customer Name, Account BAN) appears
    # twice in the tab, delete the row CLOSEST TO THE TOP (= newer, since new
    # rows are always inserted at row 2). Keep the older row at the bottom.
    deleted = _dedup_pass(ws)

    return {"tab": tab_name, "new_count": len(new),
            "skipped_already_in_sheet": len(rows) - len(new),
            "wrote_rows": len(new),
            "post_insert_dedup_deleted": deleted}


def _dedup_pass(ws) -> int:
    """Scan the tab. For each (Customer Name, Account BAN) appearing > once,
    delete the row(s) closer to the TOP (newer). Keep the bottom-most row.
    Returns the number of rows deleted."""
    grid = ws.get_all_values()
    if len(grid) <= 2:
        return 0
    header = grid[0]
    cust_col = _find_col(header, "Customer Name")
    ban_col = _find_col(header, "Account BAN")

    # Walk bottom→top; track the first (= bottom-most) occurrence of each key.
    # All subsequent occurrences (= higher rows, closer to top) get deleted.
    seen: dict[tuple, int] = {}   # key → row index (0-based)
    rows_to_delete: list[int] = []
    for i in range(len(grid) - 1, 0, -1):    # skip row 0 (header)
        r = grid[i]
        cust = r[cust_col].strip() if len(r) > cust_col else ""
        ban = r[ban_col].strip() if len(r) > ban_col else ""
        if not cust and not ban:
            continue
        key = (cust, ban)
        if key in seen:
            rows_to_delete.append(i)
        else:
            seen[key] = i

    if not rows_to_delete:
        return 0
    # Delete top-down (highest index first) so earlier row indexes stay valid.
    for row_0 in sorted(rows_to_delete, reverse=True):
        ws.delete_rows(row_0 + 1)   # gspread uses 1-indexed
    return len(rows_to_delete)
