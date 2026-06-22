"""First Sale / Last Sale upload report — parses the emailed B2B.D2D
.xlsx and fills the FK/LK section across every ICD tab on the ATT Program
- Focus Report.

Workflow: user uploads the .xlsx file as a preflight, then runs this. The
filename carries the week (e.g. 'B2B.D2D First Last Sale WE 5.10.2026.xlsx'
-> WE 5/10 column on every tab).

Usage:
  .venv/bin/python -m automations.first_last_sale.run --dry-run
  .venv/bin/python -m automations.first_last_sale.run --dir ~/Downloads
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from automations.recruiting_report import fill as rfill
from automations.focus_office_att import aliases as _aliases
from . import fill as fsfill
from .parse import parse_filename_week, parse_all


WORKSPACE = Path(__file__).resolve().parent.parent.parent
# Where the Hub drops the uploaded B2B.D2D file
UPLOAD_DIR = WORKSPACE / "automations" / "uploaded" / "first_last_sale"
# Source of formatting (Megan-formatted)
FORMAT_SOURCE_TAB = "Marcellus Butler"

# Non-ICD tabs to never touch
NON_ICD_TAB_TITLES = {
    "1on1's", "ATT owners list", "Copy of Country Sales Board ",
    "Copy of Country Stats", "Country Metrics", "Country Metrics pilot",
    "Country Sales Board", "Country Sales Board (backup copy)",
    "Country Stats", "Focus Office - Sales", "Hub Activity",
    "OLD-Daily Focus Report", "Rafs", "Recruiting", "Template 1",
    "Template Fiber",
}


def gather_files(directory: Path) -> List[Path]:
    """Uploaded .xlsx files in the directory matching the FK/LK naming
    pattern. Excludes Excel lock files."""
    return sorted(p for p in directory.glob("*.xlsx")
                  if not p.name.startswith("~$")
                  and "first" in p.name.lower() and "last" in p.name.lower())


def run_first_last_sale(file_paths: List[Path], dry_run: bool = False,
                        logfn=print) -> dict:
    """Parse the uploaded file(s) and fill every ICD tab. Returns a summary."""
    if not file_paths:
        logfn("FSLS: no files to process")
        return {"filled": 0, "absent": 0, "no_section": 0}

    # Use the latest file by filename WE date
    file_paths = sorted(file_paths, key=parse_filename_week)
    upload = file_paths[-1]
    week = parse_filename_week(upload)
    logfn(f"FSLS: using {upload.name} -> week ending {week}")
    if len(file_paths) > 1:
        logfn(f"FSLS: (ignoring older uploads: "
              f"{[p.name for p in file_paths[:-1]]})")

    parsed = parse_all(upload)
    multi = {k: e for k, e in parsed.items() if len(e["_sheets"]) > 1}
    if multi:
        logfn("FSLS: WARN — owners in multiple channel sheets (should be 1):")
        for k, e in multi.items():
            logfn(f"   {e['raw_name']}: {sorted(e['_sheets'])}")

    aliases_map = _aliases.load_aliases()
    sh = rfill.open_sheet()

    # Format source — Marcellus Butler's section bounds
    src_ws = rfill._retry(sh.worksheet, FORMAT_SOURCE_TAB)
    src_grid = rfill._retry(src_ws.get_all_values)
    src_sec = fsfill.find_section(src_grid)
    if not src_sec:
        raise RuntimeError(
            f"FSLS: can't find FK/LK section on the format source "
            f"'{FORMAT_SOURCE_TAB}' — fix that tab before running")
    src_bounds = fsfill.section_bounds(src_sec)
    src_sid = src_ws._properties["sheetId"]

    tabs = [w.title for w in sh.worksheets()
            if w.title not in NON_ICD_TAB_TITLES and not w.title.startswith("_")]

    filled, absent, no_section, errored = [], [], [], []
    inserted_log = {}

    for tab in tabs:
        try:
            ws = rfill._retry(sh.worksheet, tab)
            res = fsfill.fill_for_tab(sh, ws, week, parsed, aliases_map,
                                       src_bounds, src_sid, dry_run=dry_run)
            if res.get("inserted"):
                inserted_log[tab] = res["inserted"]
            if res["status"] == "OK":
                filled.append(tab)
                ch = res.get("channel") or "?"
                ins = (f"  (+inserted: {','.join(res['inserted'])})"
                       if res["inserted"] else "")
                logfn(f"  [OK]   {tab}: {ch}, {res['cells']} cells, "
                      f"format {res['fmt']}{ins}")
            elif res["status"] == "ABSENT":
                absent.append(tab)
                logfn(f"  [N/A]  {tab}: '{fsfill.NOT_ON_UPLOAD}', "
                      f"cleared {res['cells']-1} body cells, format {res['fmt']}")
            elif res["status"] == "EXPECTED_NO_SECTION":
                logfn(f"  [EXPECTED] {tab}: no FK/LK section (Megan-confirmed)")
            else:
                no_section.append(tab)
                logfn(f"  [NO SEC] {tab}: no FK/LK section found")
        except Exception as e:
            errored.append((tab, type(e).__name__, str(e)))
            logfn(f"  [ERR] {tab}: {type(e).__name__}: {e}")

    logfn("")
    logfn(f"FSLS summary: {len(filled)} filled, {len(absent)} 'Not On Emailed Report', "
          f"{len(no_section)} no-section, {len(errored)} errored")
    if inserted_log:
        logfn(f"FSLS: rows inserted on {len(inserted_log)} tabs:")
        for t, ds in inserted_log.items():
            logfn(f"   {t}: +{','.join(ds)}")
    return {"filled": len(filled), "absent": len(absent),
            "no_section": len(no_section), "errored": len(errored)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help=f"Folder of uploaded .xlsx (default: {UPLOAD_DIR})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print actions without writing")
    args = ap.parse_args()

    directory = Path(args.dir).expanduser() if args.dir else UPLOAD_DIR
    files = gather_files(directory)
    if not files:
        print(f"no FK/LK .xlsx files found in {directory}")
        return 1
    print(f"FSLS: {len(files)} candidate file(s) in {directory}, "
          f"dry_run={args.dry_run}")
    run_first_last_sale(files, dry_run=args.dry_run)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
