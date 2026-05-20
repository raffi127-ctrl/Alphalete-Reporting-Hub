"""Deep inspect of Aya Al-Khafaji's tab — both column groups AND each
individual column's hiddenByUser flag. Helps diagnose why collapse isn't
visually applying.

Run:
    .venv/bin/python -m automations.focus_office_att._inspect_aya
"""
from __future__ import annotations

from automations.recruiting_report import fill as _fill
from automations.focus_office_att.daily import DEST_SPREADSHEET_ID

TARGET = "Aya Al-Khafaji"


def _col_letter(c: int) -> str:
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def main() -> None:
    client = _fill._client()
    sh = client.open_by_key(DEST_SPREADSHEET_ID)
    meta = sh.fetch_sheet_metadata(params={
        "fields": "sheets(properties(sheetId,title,gridProperties),"
                  "columnGroups,data(columnMetadata(hiddenByUser,pixelSize)))"
    })
    target = None
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == TARGET:
            target = s
            break
    if not target:
        print(f"Tab {TARGET!r} not found.")
        return

    grid = target["properties"]["gridProperties"]
    print(f"=== {TARGET} — gridCols={grid.get('columnCount')} ===\n")

    print("Column groups:")
    for g in target.get("columnGroups", []) or []:
        r = g.get("range", {})
        start, end = r.get("startIndex"), r.get("endIndex")
        print(f"  depth={g.get('depth')}  cols[{start}:{end})  "
              f"{_col_letter(start+1)}:{_col_letter(end)}  "
              f"collapsed={g.get('collapsed', False)}")

    print("\nHidden columns (hiddenByUser=True), if any:")
    data = (target.get("data", [{}])[0] or {})
    col_meta = data.get("columnMetadata", []) or []
    hidden = [(i, c.get("pixelSize", 0)) for i, c in enumerate(col_meta)
              if c.get("hiddenByUser")]
    if hidden:
        for i, px in hidden:
            print(f"  col {i} ({_col_letter(i+1)})  hiddenByUser=True  "
                  f"pixelSize={px}")
    else:
        print("  (none)")

    print("\nZero-width columns (pixelSize=0), if any:")
    zero = [(i, c) for i, c in enumerate(col_meta) if c.get("pixelSize") == 0]
    if zero:
        for i, c in zero:
            print(f"  col {i} ({_col_letter(i+1)})  pixelSize=0  "
                  f"hiddenByUser={c.get('hiddenByUser', False)}")
    else:
        print("  (none)")


if __name__ == "__main__":
    main()
