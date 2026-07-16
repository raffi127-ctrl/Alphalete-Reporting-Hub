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

# Light-blue highlight for rows added in the most recent run, so
# whoever opens the sheet can see what's new at a glance. Matches
# the canceled_orders fill highlight for consistency across tabs.
_HIGHLIGHT_BG = {"red": 213 / 255, "green": 232 / 255, "blue": 252 / 255}
_WHITE_BG = {"red": 1.0, "green": 1.0, "blue": 1.0}

# Sheet's canonical field order — the keys produced by pull.parse_and_filter
# (plus "Owner Name", injected from the pulled `_owner` at write time). Used
# as a fallback when a tab has no header yet.
SHEET_COLS = [
    "Owner Name", "Rep", "Order Date", "Customer Name", "SPM Number",
    "Account BAN", "Product Type", "Customer Phone", "Package", "Install Date",
    "DTR Status", "Status Date", "Eligibility Reason", "Auto Bill Pay",
    "Tech Install",
]

# The 3 tabs use slightly different header wording, and the two Captainship
# tabs carry an Owner column + manual columns the Local Office tab doesn't.
# We map each tab's literal header to one canonical field key by label — never
# by index — so the same writer fills every tab and stays correct when columns
# are added/renamed. Mirrors canceled_orders.fill.
#   canonical key  →  header strings seen in the wild
_HEADER_ALIASES = {
    "Owner Name":   ["Owner Name", "Owner Disconnects", "Owner"],
    "SPM Number":   ["SPM Number", "SPM Number "],
    "Install Date": ["Install Date", "spe.Install Date"],
    "Tech Install": ["Tech Install", "Tech Install?", "Tech Install "],
}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _canonical(label: str) -> str:
    """Map a sheet's literal header to our canonical field key.
    Unknown headers (Eve's manual cols like '(DYLAN ONLY)', 'FEEDBACK')
    pass through trimmed, so they resolve to no row value → left blank."""
    s = (label or "").strip()
    for canon, aliases in _HEADER_ALIASES.items():
        if s in aliases:
            return canon
    return s


def _find_col(header: list[str], name: str) -> int:
    """Find a column by name OR by any of its known aliases. Tolerates
    trailing/leading whitespace (e.g. 'SPM Number ' with a trailing space)."""
    aliases = _HEADER_ALIASES.get(name, [name])
    alias_set = {_norm(a) for a in aliases} | {_norm(name)}
    for i, h in enumerate(header):
        if _norm(h) in alias_set:
            return i
    raise ValueError(f"Column {name!r} (or aliases {aliases}) not found in {header}")


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
    grid_before = ws.get_all_values()
    rows_before = len(grid_before)
    header = grid_before[0] if grid_before else SHEET_COLS

    # Expose the pulled owner under its canonical key so the Owner column
    # (labeled 'Owner Disconnects' / 'Owner' on the Captainship tabs) gets
    # filled. Local Office has no Owner column, so this key is simply unused.
    for r in new:
        r.setdefault("Owner Name", r.get("_owner", ""))

    # Build each row against the tab's ACTUAL header, by label. Columns the
    # tab has but we don't produce (manual '(DYLAN ONLY)', 'FEEDBACK') resolve
    # to "" and are left for the team to fill. This keeps every field under
    # its correct header even though the 3 tabs differ in width/wording.
    matrix = [[r.get(_canonical(col), "") for col in header] for r in new]
    ws.insert_rows(matrix, row=2, value_input_option="USER_ENTERED")

    # Highlight the new rows light blue + reset every other data row to
    # white, so whoever opens the tab sees this run's additions at a glance.
    N = len(new)
    rows_after = rows_before + N
    ncols = max(len(header), len(SHEET_COLS))
    _paint_highlight(ws, rows_after=rows_after, new_count=N, ncols=ncols)

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
    # Batch all deletes into ONE Sheets API call. Iterating per-row hit
    # the 60-writes/minute quota on tabs with lots of legacy dupes.
    # Walk top-down (highest index first) so each deleteDimension range
    # is interpreted against the same baseline.
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


def _paint_highlight(ws, *, rows_after: int, new_count: int, ncols: int) -> None:
    """Clear backgrounds on all data rows (white), then highlight just
    the top `new_count` rows in light blue — one batched Sheets API call."""
    requests = [
        {"repeatCell": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": 1,
                "endRowIndex": rows_after,
                "startColumnIndex": 0,
                "endColumnIndex": ncols,
            },
            "cell": {"userEnteredFormat": {"backgroundColor": _WHITE_BG}},
            "fields": "userEnteredFormat.backgroundColor",
        }},
        {"repeatCell": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": 1,
                "endRowIndex": 1 + new_count,
                "startColumnIndex": 0,
                "endColumnIndex": ncols,
            },
            "cell": {"userEnteredFormat": {"backgroundColor": _HIGHLIGHT_BG}},
            "fields": "userEnteredFormat.backgroundColor",
        }},
    ]
    ws.spreadsheet.batch_update({"requests": requests})
