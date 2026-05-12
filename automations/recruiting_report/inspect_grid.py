"""Print the first N rows × first M columns of a tab as a grid for layout inspection."""
from __future__ import annotations
import sys
from . import fill


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: inspect_grid.py <tab name> [rows=20] [cols=15]")
        return 1
    name = sys.argv[1]
    rows_to_show = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    cols_to_show = int(sys.argv[3]) if len(sys.argv) > 3 else 15
    sh = fill.open_sheet()
    ws = sh.worksheet(name)
    values = ws.get_all_values()
    print(f"Tab: {name!r}  total rows: {len(values)}, total cols: {max(len(r) for r in values) if values else 0}")
    for i, row in enumerate(values[:rows_to_show], start=1):
        print(f"\nROW {i}:")
        for j, cell in enumerate(row[:cols_to_show], start=1):
            if cell:
                print(f"  col {j}: {cell!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
