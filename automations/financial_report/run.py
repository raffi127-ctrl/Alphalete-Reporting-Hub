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

# Run-manifest id — MUST equal schedule_config financial_report.verify.report_id
# AND the Hub card id (so the orchestrator's verify + the Hub's retry button
# both read the same file). Seeded failed at run start, mark_clean'd on a clean
# fill; a run with parse PROBLEMS leaves ok=false with the bad files named.
MANIFEST_ID = "financial-pull"


def _hidden_tab_titles(sh) -> set:
    """Tabs Megan has hidden in the Sheet — same retired/inactive convention
    the recruiting runner uses. One Sheets API call per spreadsheet."""
    try:
        resp = sh.client.request(
            "get",
            f"https://sheets.googleapis.com/v4/spreadsheets/{sh.id}",
            params={"fields": "sheets(properties(title,hidden))"},
        )
        return {s["properties"]["title"] for s in resp.json().get("sheets", [])
                if s["properties"].get("hidden")}
    except Exception:
        return set()   # fail open — better to attempt all than skip all


def gather_files(directory: Path) -> List[Path]:
    """The uploaded .xlsx workbooks (Excel lock files excluded)."""
    return sorted(p for p in directory.glob("*.xlsx")
                  if not p.name.startswith("~$"))


def run_financial_report(file_paths, dry_run: bool = False,
                         only_sheet: Optional[str] = None, logfn=print) -> dict:
    """Parse the financial workbooks and fill every matching ICD tab across
    the focus-report spreadsheets. Returns a summary dict."""
    by_owner, weeks, problems = parse_financial_files(file_paths, logfn=logfn)
    n_offices = sum(len(v) for v in by_owner.values())
    logfn(f"financial: parsed {n_offices} office(s) for {len(by_owner)} owner(s) "
          f"from {len(list(file_paths))} file(s); week endings {weeks}")
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
    # ICD tabs that got NO financials this week (their data wasn't in any email).
    # Now that financials auto-ingest from email (was manual upload), a missing
    # ICD means someone's numbers didn't come through — SURFACE it as a note so
    # Megan can chase that sender. Still NOT a failure: the run stays complete +
    # never wipes a tab (incremental). [[feedback_financial_incremental]]
    not_pulled: set = set()
    matched_titles: set = set()   # a tab matched in ANY sheet isn't "missing"
    for sheet_name, sid in ffill.OUTPUT_SHEETS.items():
        if only_sheet and only_sheet.lower() not in sheet_name.lower():
            continue
        # Per-sheet opening log so the runner doesn't go silent for minutes
        # while gspread auth + initial tab walk happens. Eve 2026-05-22
        # killed a run thinking it had hung — the script was actually still
        # working but the previous version stayed quiet through this phase.
        logfn(f"financial: opening {sheet_name}...")
        try:
            sh = rfill.open_by_key(sid, client)
        except Exception as e:
            logfn(f"financial: can't open {sheet_name!r} ({e})")
            continue
        # Tabs Megan has HIDDEN are retired/inactive — skip them, same
        # convention the recruiting runner uses. One API call per sheet.
        hidden = _hidden_tab_titles(sh)
        all_tabs = rfill._retry(sh.worksheets)
        candidate_tabs = [w for w in all_tabs
                          if w.title not in _NON_ICD_TAB_TITLES
                          and not w.title.startswith("_")
                          and w.title not in hidden]
        logfn(f"financial: {sheet_name} — {len(candidate_tabs)} ICD tab(s) to scan "
              f"({len(hidden)} hidden skipped)")
        filled = matched = 0
        for idx, ws in enumerate(candidate_tabs, start=1):
            tab_offices = ffill._match_owner(ws.title, by_owner, bridge)
            if not tab_offices:
                # No data in this upload — leave the tab alone. Whatever was
                # filled by a previous run stays put; when an upload that
                # DOES include this ICD arrives, the cells get filled then.
                # (Megan, 2026-05-20: incremental uploads must never wipe
                # previously-entered data.) Record it so the run notes who's
                # missing this week (Megan 2026-07-05, auto email-ingest era).
                not_pulled.add(ws.title)
                continue
            matched += 1
            matched_titles.add(ws.title)
            lines = ffill.fill_financial_for_tab(ws, tab_offices, weeks, dry_run)
            for line in lines:
                logfn(f"  {sheet_name}: {line}")
            if lines and lines[0].lstrip().startswith(("[OK]", "[DRY-RUN]")):
                filled += 1
            # Heartbeat every 10 ICD tabs so the user sees forward motion
            # even on a sheet where most tabs are matched + writing.
            if idx % 10 == 0:
                logfn(f"financial: {sheet_name} — {idx}/{len(candidate_tabs)} "
                      f"tabs scanned, {filled} filled so far...")
        logfn(f"financial: {sheet_name} — {filled}/{matched} matched tabs filled "
              f"(unmatched tabs left untouched)")
        total_matched += matched
        total_filled += filled
    # A tab matched in any sheet isn't "missing" — only tabs that got NO data
    # anywhere this week remain.
    not_pulled -= matched_titles
    if not_pulled:
        logfn("")
        logfn(f"===== ℹ️  {len(not_pulled)} ICD(s) had NO financials this week "
              f"(not in any email) — NOTE only, run still complete =====")
        for t in sorted(not_pulled):
            logfn(f"  – {t}")
    if problems:
        logfn("")
        logfn("===== ❌ UPLOAD PROBLEMS — Megan check these files =====")
        for name, reason in problems:
            logfn(f"  ❌ {name}: {reason}")
        logfn("(A '0 offices parsed' problem usually means the file's "
              "template is new — Claude needs to add a parser for that "
              "layout. Send the file to Claude.)")
    return {"filled": total_filled, "matched": total_matched,
            "problems": problems, "not_pulled": sorted(not_pulled)}


def main() -> int:
    import tempfile
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="Folder of uploaded FINANCIAL SUMMARY .xlsx "
                                  f"files (default: {UPLOAD_DIR}).")
    ap.add_argument("--only-sheet", help="Only this output spreadsheet (substring match).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write — just print what would change.")
    ap.add_argument("--email", action="store_true",
                    help="Auto-ingest: pull this week's FINANCIAL SUMMARY .xlsx "
                         "from the reporting inbox (all senders) into a temp "
                         "folder, instead of a manual upload dir.")
    args = ap.parse_args()

    _tmpctx = None
    if args.email:
        from automations.financial_report import email_source as _fes
        _tmpctx = tempfile.TemporaryDirectory(prefix="financial_email_")
        directory = Path(_tmpctx.name)
        print("Auto-ingest: fetching FINANCIAL SUMMARY workbooks from the "
              "reporting inbox…")
        got = _fes.fetch(directory, verbose=True)
        print(f"  fetched {len(got)} workbook(s)")
    else:
        directory = Path(args.dir).expanduser() if args.dir else UPLOAD_DIR

    # Seed a failure manifest up-front (live only). If the run crashes mid-way
    # — or bails on "no files" below — it stays ok=false so the orchestrator's
    # verify flags the run INCOMPLETE instead of "ran clean" (exit-code only);
    # mark_clean() at the end overwrites it once the fill completes cleanly.
    live = not args.dry_run
    if live:
        try:
            from automations.shared import run_manifest as _rm
            _rm.write_manifest(MANIFEST_ID, failed=["financial fill"],
                               retry_args=["--email"], kind="section",
                               note="run started but did not complete")
        except Exception:  # noqa: BLE001 — manifest is best-effort
            pass

    try:
        files = gather_files(directory)
        if not files:
            print(f"no .xlsx files found in {directory}")
            return 1
        print(f"financial report — {len(files)} file(s) from "
              f"{'email inbox' if args.email else directory}, "
              f"dry_run={args.dry_run}")
        result = run_financial_report(files, dry_run=args.dry_run,
                                      only_sheet=args.only_sheet)
        if live:
            try:
                from automations.shared import run_manifest as _rm
                problems = result.get("problems") or []
                if problems:
                    # A parse PROBLEM (usually a 0-offices file = new template)
                    # is a real INCOMPLETE — name the files + tell the user how
                    # to fix (send the file to Claude for a parser).
                    bad = [name for name, _ in problems]
                    _rm.write_manifest(
                        MANIFEST_ID, failed=bad, retry_args=["--email"],
                        kind="file",
                        note=f"{len(bad)} file(s) couldn't be parsed",
                        remediation=_rm.make_remediation(
                            reason="One or more FINANCIAL SUMMARY workbooks "
                                   "couldn't be parsed (0 offices) — usually a "
                                   "new/changed template from that sender.",
                            fix="Send the flagged file(s) to Claude to add a "
                                "parser for the new layout, then re-run.",
                            message="A financial workbook's template changed and "
                                    "the report couldn't read it. Which sender's "
                                    "format changed, and can we get a sample?"))
                else:
                    # Clean run — record WHICH workbooks were pulled in the
                    # manifest note. The orchestrator surfaces this note in the
                    # summary email so it's easy to see what came in this week.
                    # Also NOTE which ICDs got no financials (data not in any
                    # email) — run stays COMPLETE (failed=[]), it just tells Megan
                    # who to chase (Megan 2026-07-05). [[feedback_financial_incremental]]
                    names = ", ".join(sorted(p.name for p in files))
                    _note = f"pulled {len(files)} workbook(s): {names}"
                    _not = result.get("not_pulled") or []
                    if _not:
                        _note += (f" · ⚠ {len(_not)} ICD(s) got NO financials this "
                                  f"week (not in any email): " + ", ".join(_not))
                    _rm.write_manifest(
                        MANIFEST_ID, failed=[], retry_args=[], kind="section",
                        note=_note)
            except Exception:  # noqa: BLE001 — manifest is best-effort
                pass
        print("done")
        return 0
    finally:
        if _tmpctx is not None:
            _tmpctx.cleanup()


if __name__ == "__main__":
    sys.exit(main())
