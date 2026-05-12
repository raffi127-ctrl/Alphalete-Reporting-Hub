"""Quick inspection of a Sheet tab's column A. Helps debug detection logic."""
from __future__ import annotations
import sys
from . import fill


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: inspect_tab.py <tab name>")
        return 1
    name = " ".join(sys.argv[1:])
    sh = fill.open_sheet()
    ws = sh.worksheet(name)
    col_a = ws.col_values(1)
    print(f"Tab: {name!r}  rows in col A: {len(col_a)}")
    for i, v in enumerate(col_a, start=1):
        print(f"  {i:3d}: {v!r}")
    print()
    print(f"is_office_tab_populated -> {fill.is_office_tab_populated(ws)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
