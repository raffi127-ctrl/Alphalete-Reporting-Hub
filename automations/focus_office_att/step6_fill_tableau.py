"""Fill per-day sale-type metrics (New INT, Upgrades, DTV, New Lines) from
the Tableau 'Sales By ICD (Weekly View).xlsx' export.

Tableau dashboards are painful to scrape directly (canvas/SVG render). Tableau
Online provides a built-in 'Download as Excel' option that gives us a clean
per-rep per-day per-product crosstab. This script parses that file and writes
to the matching cells on every owner tab.

Excel format (verified 2026-05-14):
  Row 1: ['Owner Name', 'Rep', 'Product Type (Broken Out)', 'Monday', 'Tuesday', ...]
  Row 2: 'Sales Total' summary row (skip)
  Per-owner blocks:
    First row: <Owner Name> | 'Total' | None | <day totals>      (skip — totals)
    Body rows: None | <Rep Name> | <PRODUCT TYPE> | <day counts>
      - Rep cell can be None on continuation rows (same rep, different product)

Product type → Sheet canonical metric (Raf-confirmed):
  NEW INTERNET     → New INT
  UPGRADE INTERNET → Upgrades
  VIDEO            → DTV
  WIRELESS         → New Lines

Run:
    .venv/bin/python -m automations.focus_office_att.step6_fill_tableau \\
        --file ~/Downloads/'Sales By ICD (Weekly View).xlsx'
    # Cody-only test:
    .venv/bin/python -m automations.focus_office_att.step6_fill_tableau \\
        --file <path> --only "Cody Cannon"
    # Dry-run (no writes):
    .venv/bin/python -m automations.focus_office_att.step6_fill_tableau \\
        --file <path> --dry-run
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

from automations.recruiting_report import fill as _fill
from automations.focus_office_att.aliases import load_aliases, alias_to_canonical
from automations.focus_office_att.columns import resolve_layout, _normalize
from automations.focus_office_att.step5_fill_one_owner import (
    _col_letter, write_weekly_formulas, write_office_totals_row,
    apply_empty_cell_defaults, reset_conditional_formatting,
    TT_FIELD_TO_CANONICAL, DISP_FIELD_TO_CANONICAL,
)

DEST_SPREADSHEET_ID = "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY"

PRODUCT_TO_METRIC = {
    "NEW INTERNET":     "New INT",
    "UPGRADE INTERNET": "Upgrades",
    "VIDEO":            "DTV",
    "WIRELESS":         "New Lines",
}

# Day name in Tableau → weekday index used by columns.py.
DAY_TO_WEEKDAY = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}


def parse_tableau_xlsx(path: Path) -> dict:
    """Returns {owner_name: {rep_name: {weekday_idx: {metric: count}}}}.

    Skips Sales Total row + per-owner Total rows. Handles continuation rows
    (rep cell is None on second/third product line for the same rep).
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active

    # Find day cols.
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    day_cols: dict[int, int] = {}  # weekday_idx → 1-based col
    for col_idx, h in enumerate(headers, start=1):
        if h in DAY_TO_WEEKDAY:
            day_cols[DAY_TO_WEEKDAY[h]] = col_idx

    out: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(int))))

    current_owner: str | None = None
    current_rep: str | None = None

    for r in range(2, ws.max_row + 1):
        owner_cell = ws.cell(r, 1).value
        rep_cell   = ws.cell(r, 2).value
        prod_cell  = ws.cell(r, 3).value

        if owner_cell == "Sales Total":
            continue
        if owner_cell:
            current_owner = owner_cell
            current_rep = None
            # The owner's first row is the "Total" row — body data starts next row.
            continue

        if rep_cell == "Total":
            continue
        if rep_cell:
            current_rep = rep_cell
        # rep_cell == None → continuation: same rep as previous body row.

        if not current_owner or not current_rep or not prod_cell:
            continue

        metric = PRODUCT_TO_METRIC.get(str(prod_cell).strip().upper())
        if not metric:
            continue

        for wd, col in day_cols.items():
            val = ws.cell(r, col).value
            if isinstance(val, (int, float)) and val:
                out[current_owner][current_rep][wd][metric] += int(val)

    # Convert nested defaultdicts to regular dicts for cleaner downstream code.
    return {
        owner: {
            rep: {wd: dict(metrics) for wd, metrics in days.items()}
            for rep, days in reps.items()
        }
        for owner, reps in out.items()
    }


def fill_tableau_for_owner(ws, owner_data: dict, layout, dry_run: bool = False) -> dict:
    """owner_data is {rep_name: {weekday_idx: {metric: count}}}.

    Returns stats with: written_cells, skipped_cells, unmatched_reps (in
    Tableau but not in this owner's Sheet tab).
    """
    rep_col_vals = ws.col_values(layout.rep_name_col)
    # Build {lowercase_rep_name: row}
    sheet_reps: dict[str, int] = {}
    for i, name in enumerate(rep_col_vals, start=1):
        if i >= 3 and name and name.strip():
            sheet_reps[name.lower().strip()] = i

    cells_to_write: list[tuple[str, int]] = []
    written = 0
    skipped = 0
    unmatched_reps: list[str] = []

    for tableau_rep, days in owner_data.items():
        key = tableau_rep.lower().strip()
        row = sheet_reps.get(key)
        if row is None:
            unmatched_reps.append(tableau_rep)
            continue
        for wd, metric_counts in days.items():
            if wd not in layout.day_cols:
                continue
            wd_cols = layout.day_cols[wd]
            for metric, count in metric_counts.items():
                col = wd_cols.get(metric)
                if col is None:
                    continue
                a1 = f"{_col_letter(col)}{row}"
                cells_to_write.append((a1, int(count)))
                written += 1

    if cells_to_write and not dry_run:
        data = [{"range": f"'{ws.title}'!{a1}", "values": [[v]]} for a1, v in cells_to_write]
        ws.spreadsheet.values_batch_update({"valueInputOption": "USER_ENTERED", "data": data})

    return {"written": written, "unmatched_reps": unmatched_reps}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="Path to the Tableau xlsx download.")
    ap.add_argument("--only", default="",
                    help="Comma-separated owner tab names to fill (rest skipped).")
    ap.add_argument("--dry-run", action="store_true", help="Parse + report; no Sheet writes.")
    args = ap.parse_args()

    path = Path(args.file).expanduser()
    if not path.exists():
        print(f"❌ File not found: {path}")
        return 1
    print(f"Parsing {path.name}…")
    tableau = parse_tableau_xlsx(path)
    print(f"  ✓ {len(tableau)} owner(s) in file.")

    sh = _fill._client().open_by_key(DEST_SPREADSHEET_ID)
    all_tabs = {t.title: t for t in sh.worksheets()}
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    # Tableau-name → Sheet-tab-name alias (e.g. "Tony Chavez" → "Jose Antonio Chavez").
    # Load owner aliases from the shared 'ICD Aliases' Sheet tab. Returns
    # {canonical: [aliases]} — we use alias_to_canonical() for the reverse
    # lookup (Tableau name → Sheet tab name).
    aliases_raw = load_aliases()
    if aliases_raw:
        total = sum(len(v) for v in aliases_raw.values())
        print(f"  Loaded {total} alias(es) for {len(aliases_raw)} ICD(s) from shared Sheet")

    summary: dict[str, dict] = {}
    metrics_for_layout = (
        list(TT_FIELD_TO_CANONICAL.values())
        + list(DISP_FIELD_TO_CANONICAL.values())
        + ["Total Apps", "New INT", "Upgrades", "DTV", "New Lines"]
    )
    for owner, owner_data in tableau.items():
        # Apply alias: Tableau name → Sheet tab name (via the shared ICD Aliases Sheet).
        sheet_tab_name = alias_to_canonical(owner, aliases_raw)
        if only and sheet_tab_name not in only:
            continue
        if sheet_tab_name not in all_tabs:
            summary[owner] = {"status": "no Sheet tab — skipped"}
            continue
        ws = all_tabs[sheet_tab_name]
        label = f"{owner}" + (f" → tab {sheet_tab_name!r}" if sheet_tab_name != owner else "")
        print(f"  → {label}…")
        layout = resolve_layout(ws, metrics=metrics_for_layout, interactive=False)
        stats = fill_tableau_for_owner(ws, owner_data, layout, dry_run=args.dry_run)
        # Refresh Weekly formulas so newly-filled per-day data rolls up,
        # apply Raf's empty-cell defaults (0 for production / x for activity),
        # strip the green/red conditional formatting, and refresh the
        # OFFICE TOTALS row. All wrapped — cosmetic API hiccups shouldn't
        # invalidate the actual data write.
        if not args.dry_run and stats["written"] > 0:
            for label, fn in [
                ("write_weekly_formulas",        lambda: write_weekly_formulas(ws, layout)),
                ("apply_empty_cell_defaults",    lambda: apply_empty_cell_defaults(ws, layout)),
                ("reset_conditional_formatting", lambda: reset_conditional_formatting(ws)),
                ("write_office_totals_row",     lambda: write_office_totals_row(ws, layout)),
            ]:
                try:
                    fn()
                except Exception as e:
                    print(f"    ⚠ {label} failed (ignoring): {type(e).__name__}: {e}")
        summary[owner] = {
            "status": "ok",
            "written": stats["written"],
            "unmatched_reps": stats["unmatched_reps"],
        }
        verb = "would write" if args.dry_run else "wrote"
        print(f"    ✓ {verb} {stats['written']} cell(s)" + (
            f"; {len(stats['unmatched_reps'])} unmatched rep(s)" if stats["unmatched_reps"] else ""))

    print()
    print("=== SUMMARY ===")
    for owner, s in summary.items():
        if s["status"] != "ok":
            print(f"  • {owner}: {s['status']}")
            continue
        print(f"  ✓ {owner}: {s['written']} cell(s) written" + (
            f"; unmatched reps: {s['unmatched_reps']}" if s["unmatched_reps"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
