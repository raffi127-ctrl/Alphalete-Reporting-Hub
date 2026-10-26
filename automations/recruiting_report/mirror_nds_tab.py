"""Mirror an owner's NDS Program tab onto the ATT Program - Focus Report.

WHY THIS EXISTS (Eve 2026-10-26)
--------------------------------
Raf (mail "Applicant stream access - Jean (JC) Lopez", 10/25) wants JC Lopez's
numbers for his 1on1s. JC sells NDS, so his real tab is `JC Lopez - NDS` on the
NDS Program - Focus Report, filled every Monday by nds_program_focus_all
(AppStream recruiting + opt_nds). Raf lives in the ATT Program workbook, so Eve
asked for the tab THERE too, where he looks.

Filling it twice would mean a second 45-min NDS Tableau pull and two copies that
could disagree. So the NDS tab stays the only one that is filled, and this copies
its typed values onto the ATT copy:

  * `--create` makes the ATT tab once (copyTo of the NDS tab: same layout,
    formulas, formats) and leaves it at the end of the owner tabs.
  * a normal run walks the NDS tab cell by cell and writes every TYPED value
    that differs on the ATT copy. Formulas are left alone on both sides — the
    copy carries the same ones. It never clears a cell the NDS tab has blank,
    so anything typed by hand on the ATT copy survives.

Runs Mondays right after nds_program_focus_all (job `nds_mirror_to_att`).

Usage:
  python -m automations.recruiting_report.mirror_nds_tab --dry-run
  python -m automations.recruiting_report.mirror_nds_tab --create
  python -m automations.recruiting_report.mirror_nds_tab
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# (tab on the NDS Program workbook, tab on the ATT Program workbook)
MIRRORS = [
    ("JC Lopez - NDS", "JC Lopez (NDS)"),
]


def _a1(r: int, c: int) -> str:
    from gspread.utils import rowcol_to_a1
    return rowcol_to_a1(r, c)


def _create(src_book, dst_book, src_tab: str, dst_tab: str, dry_run: bool) -> None:
    from . import fill
    src = fill._retry(src_book.worksheet, src_tab)
    if dry_run:
        print(f"  DRY RUN — would copy {src_tab!r} into {dst_book.title!r} as {dst_tab!r}")
        return
    res = fill._retry(src.copy_to, dst_book.id)
    new_id = res["sheetId"]
    n_tabs = len(fill._retry(dst_book.worksheets))
    fill._retry(dst_book.batch_update, {"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": new_id, "title": dst_tab, "index": n_tabs - 1},
        "fields": "title,index"}}]})
    print(f"  created {dst_tab!r} (sheetId {new_id}) in {dst_book.title!r}")


def _sync(src_book, dst_book, src_tab: str, dst_tab: str, dry_run: bool) -> int:
    from . import fill
    src = fill._retry(src_book.worksheet, src_tab)
    dst = fill._retry(dst_book.worksheet, dst_tab)
    rng = f"A1:{_a1(src.row_count, src.col_count)}"
    s_grid = fill._retry(src.get, rng, value_render_option="FORMULA")
    d_grid = fill._retry(dst.get, rng, value_render_option="FORMULA")
    writes = []
    for r, row in enumerate(s_grid, start=1):
        d_row = d_grid[r - 1] if r - 1 < len(d_grid) else []
        for c, v in enumerate(row, start=1):
            if isinstance(v, str) and (v.startswith("=") or v.strip() == ""):
                continue
            d = d_row[c - 1] if c - 1 < len(d_row) else ""
            if str(d) == str(v):
                continue
            writes.append({"range": _a1(r, c), "values": [[v]]})
    print(f"  {src_tab!r} -> {dst_tab!r}: {len(writes)} cell(s) to update")
    for w in writes[:15]:
        print(f"    {w['range']} = {w['values'][0][0]!r}")
    if writes and not dry_run:
        fill._retry(dst.batch_update, writes, value_input_option="USER_ENTERED")
        print("  written")
    return len(writes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--create", action="store_true",
                    help="Make the ATT tab first if it does not exist yet.")
    ap.add_argument("--dry-run", action="store_true", help="Write nothing.")
    args = ap.parse_args()

    os.environ.setdefault("CAPTAINSHIP", "Raf")
    from . import fill
    src_book = fill.open_by_key(fill.captainship_sheet_id("NDS-Program"))
    dst_book = fill.open_by_key(fill.captainship_sheet_id("Raf"))
    have = {w.title for w in fill._retry(dst_book.worksheets)}

    rc = 0
    for src_tab, dst_tab in MIRRORS:
        print(f"=== {dst_tab} ({'DRY RUN' if args.dry_run else 'LIVE'}) ===")
        if dst_tab not in have:
            if not args.create:
                print(f"  ✗ {dst_tab!r} is not on {dst_book.title!r} — run with --create")
                rc = 1
                continue
            _create(src_book, dst_book, src_tab, dst_tab, args.dry_run)
            if args.dry_run:
                continue
            # copyTo already carried every value; the sync below confirms 0.
        _sync(src_book, dst_book, src_tab, dst_tab, args.dry_run)
    return rc


if __name__ == "__main__":
    sys.exit(main())
