"""Print the actual columnGroups on every owner tab of the Daily Rep
Breakdown sheet. Read-only — no edits. Helps build the right collapse
logic by showing what depth/range Sheets actually has.

Run:
    .venv/bin/python -m automations.focus_office_att._inspect_groups
"""
from __future__ import annotations

from automations.recruiting_report import fill as _fill
from automations.focus_office_att.daily import DEST_SPREADSHEET_ID, NON_OWNER_TABS


def main() -> None:
    client = _fill._client()
    sh = client.open_by_key(DEST_SPREADSHEET_ID)
    meta = sh.fetch_sheet_metadata(
        params={"fields": "sheets(properties(sheetId,title),columnGroups)"}
    )
    for s in meta.get("sheets", []):
        title = s["properties"]["title"]
        if title in NON_OWNER_TABS:
            continue
        groups = s.get("columnGroups", []) or []
        print(f"\n=== {title} ({len(groups)} columnGroup(s)) ===")
        if not groups:
            print("  (no column groups)")
            continue
        for g in groups:
            r = g.get("range", {})
            start = r.get("startIndex", "?")
            end   = r.get("endIndex",   "?")
            depth = g.get("depth", "?")
            collapsed = g.get("collapsed", False)
            print(f"  depth={depth}  cols[{start}:{end})  "
                  f"(A1 ~ {_col_letter(start+1)}:{_col_letter(end)})  "
                  f"collapsed={collapsed}")


def _col_letter(c: int) -> str:
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


if __name__ == "__main__":
    main()
