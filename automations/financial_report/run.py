"""Financial report — parse the uploaded FINANCIAL SUMMARY workbooks and fill
the financial section across the focus-report spreadsheets.

Workflow: the user uploads the emailed FINANCIAL SUMMARY .xlsx files, then
runs this. It parses every file, merges them, and writes the financial rows
onto each ICD tab across the focus-report Google Sheets.

Usage:
  .venv/bin/python -m automations.financial_report.run --dry-run
  .venv/bin/python -m automations.financial_report.run --dir ~/Downloads
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from automations.recruiting_report import fill as rfill
from . import fill as ffill
from .parse import norm_name, parse_financial_files

# Worksheet titles that aren't ICD tabs — don't touch them even if they
# happen to have a 'Total Funds Available' label (templates, summary tabs).
_NON_ICD_TAB_TITLES = {
    "1on1's", "ATT owners list", "B2B Template", "Copy of Country Sales Board ",
    "Copy of Country Stats", "Country Metrics", "Country Metrics pilot",
    "Country Sales Board", "Country Sales Board (backup copy)",
    "Country Stats", "Focus Office - Sales", "Hub Activity",
    "OLD-Daily Focus Report", "Rafs", "Recruiting", "Template 1",
    "Template Fiber",
}


def _name_bridge() -> dict:
    """{normalized tab name: [alternate names]} — bridges a tab's nickname to
    the legal name the financial files use. Drawn from the recruiting
    mapping's AppStream owner AND the shared ICD alias list (the canonical
    place for name-spelling fixes)."""
    bridge: dict = {}
    try:
        for c in rfill.load_mapping()["confirmed"]:
            ao = c.get("as_owner")
            if ao:
                bridge.setdefault(norm_name(c["sheet_tab"]), []).append(ao)
    except Exception:
        pass
    try:
        from automations.focus_office_att import aliases as _aliases
        for canonical, alts in _aliases.load_aliases().items():
            bridge.setdefault(norm_name(canonical), []).extend(alts)
    except Exception:
        pass
    return bridge

WORKSPACE = Path(__file__).resolve().parent.parent.parent
# Where the Hub drops the uploaded FINANCIAL SUMMARY files.
UPLOAD_DIR = WORKSPACE / "automations" / "uploaded" / "financial"


def gather_files(directory: Path) -> List[Path]:
    """The uploaded .xlsx workbooks (Excel lock files excluded)."""
    return sorted(p for p in directory.glob("*.xlsx")
                  if not p.name.startswith("~$"))


def run_financial_report(file_paths, dry_run: bool = False,
                         only_sheet: Optional[str] = None, logfn=print) -> dict:
    """Parse the financial workbooks and fill every matching ICD tab across
    the focus-report spreadsheets. Returns a summary dict."""
    by_owner, weeks, problems = parse_financial_files(file_paths, logfn=logfn)
    logfn(f"financial: parsed {len(by_owner)} offices from "
          f"{len(list(file_paths))} file(s); week endings {weeks}")
    if not by_owner:
        logfn("financial: no office data parsed — nothing to fill")
        if problems:
            logfn("")
            logfn("===== ❌ UPLOAD PROBLEMS — Megan check these files =====")
            for name, reason in problems:
                logfn(f"  ❌ {name}: {reason}")
        return {"filled": 0, "matched": 0, "problems": problems}

    client = rfill._client()
    bridge = _name_bridge()
    total_filled = total_matched = 0
    for sheet_name, sid in ffill.OUTPUT_SHEETS.items():
        if only_sheet and only_sheet.lower() not in sheet_name.lower():
            continue
        try:
            sh = client.open_by_key(sid)
        except Exception as e:
            logfn(f"financial: can't open {sheet_name!r} ({e})")
            continue
        filled = matched = not_found = 0
        for ws in rfill._retry(sh.worksheets):
            # Skip system / template / summary tabs entirely
            if ws.title in _NON_ICD_TAB_TITLES or ws.title.startswith("_"):
                continue
            office = ffill._match_owner(ws.title, by_owner, bridge)
            if office:
                matched += 1
                lines = ffill.fill_financial_for_tab(ws, office, weeks, dry_run)
                for line in lines:
                    logfn(f"  {sheet_name}: {line}")
                if lines and lines[0].lstrip().startswith(("[OK]", "[DRY-RUN]")):
                    filled += 1
                continue
            # No financial-file match. Hard skip Raf (his financials live
            # elsewhere). For everyone else with a financial section on
            # their tab, mark each metric cell 'Not Found In Email' so the
            # gap is visible. write_not_found returns empty for tabs that
            # don't have the section anchor (templates, summary tabs).
            tab_n = ffill._norm(ffill._tab_to_name(ws.title))
            if tab_n in ffill._SKIP_TABS:
                continue
            lines = ffill.write_not_found_for_tab(ws, weeks, dry_run)
            for line in lines:
                logfn(f"  {sheet_name}: {line}")
            if lines and lines[0].lstrip().startswith(("[NOT-FOUND]",
                                                       "[DRY-RUN-NOT-FOUND]")):
                not_found += 1
        logfn(f"financial: {sheet_name} — {filled}/{matched} matched tabs filled, "
              f"{not_found} tabs marked 'Not Found In Email'")
        total_matched += matched
        total_filled += filled
    if problems:
        logfn("")
        logfn("===== ❌ UPLOAD PROBLEMS — Megan check these files =====")
        for name, reason in problems:
            logfn(f"  ❌ {name}: {reason}")
        logfn("(A '0 offices parsed' problem usually means the file's "
              "template is new — Claude needs to add a parser for that "
              "layout. Send the file to Claude.)")
    return {"filled": total_filled, "matched": total_matched,
            "problems": problems}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="Folder of uploaded FINANCIAL SUMMARY .xlsx "
                                  f"files (default: {UPLOAD_DIR}).")
    ap.add_argument("--only-sheet", help="Only this output spreadsheet (substring match).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write — just print what would change.")
    args = ap.parse_args()

    directory = Path(args.dir).expanduser() if args.dir else UPLOAD_DIR
    files = gather_files(directory)
    if not files:
        print(f"no .xlsx files found in {directory}")
        return 1
    print(f"financial report — {len(files)} file(s) from {directory}, "
          f"dry_run={args.dry_run}")
    run_financial_report(files, dry_run=args.dry_run,
                         only_sheet=args.only_sheet)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
