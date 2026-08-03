"""Financial report — fill the financial section across the focus-report
spreadsheets.

TWO SOURCES, and as of 2026-08 the run uses BOTH:
  --web    Double Entry (doubleentry.com org summary). The primary: no waiting
           on a sender, and its PROFIT/LOSS carries a real sign. Covers the 37
           offices raffi127's account manages.
  --email  the FINANCIAL SUMMARY workbooks in the reporting inbox. Still the
           only source for the ~60 owners Double Entry doesn't expose to that
           account (Carlos / Sahil / Trang / RAF-ADD-1 books, plus Coel and
           German's own formats) — see output/financial-source-gap.md.

Both emit the same (by_owner, weeks, problems) shape, so everything below the
source layer is source-agnostic; with both flags the web numbers win wherever an
office appears in both. As owners migrate to Double Entry the web share grows on
its own, and the email half can be dropped once the account sees everyone.

Bare (no source flag) still reads the manual upload dir — that's the Hub's
Manual Upload card, kept as the fallback.

Usage:
  .venv/bin/python -m automations.financial_report.run --web --email --dry-run
  .venv/bin/python -m automations.financial_report.run --web --date 2026-08-01
  .venv/bin/python -m automations.financial_report.run --dir ~/Downloads
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional

from automations.recruiting_report import fill as rfill
from . import fill as ffill
from .parse import norm_name, parse_financial_files

# Worksheet titles that aren't ICD tabs — don't touch them even if they
# happen to have a 'Total Funds Available' label (templates, summary tabs).
_NON_ICD_TAB_TITLES = {
    "1on1's", "1on1 Convos", "ATT owners list", "B2B Template",
    "Copy of Country Sales Board ", "Copy of Country Stats", "Country Metrics",
    "Country Metrics pilot", "Country Sales Board",
    "Country Sales Board (backup copy)", "Country Stats", "Focus Office - Sales",
    "Hub Activity", "Indeed/DBAs", "OLD-Daily Focus Report",
    "ORG Daily Focus Report", "Org Recruiting", "Org Recruiting AI",
    "Org Sales Board", "Owner Headcount", "Rafs", "Recruiting", "Template 1",
    "Template Fiber", "Trips", "Up and Coming",
}


def _is_non_icd_tab(title: str) -> bool:
    """A tab that is NOT an ICD/rep tab, so it never gets flagged as "missing
    financials." Covers the explicit set above PLUS patterns that catch the ones
    that kept leaking into the 'got NO financials' note (Megan 2026-07-09): any
    '<x> Template' tab, any default 'Sheet<n>' tab, and any '_'-prefixed tab."""
    t = (title or "").strip()
    return (t in _NON_ICD_TAB_TITLES
            or t.startswith("_")
            or t.lower().endswith("template")
            or bool(re.fullmatch(r"sheet\s*\d+", t, re.I)))


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


def merge_sources(primary, secondary, logfn=print):
    """Merge two (by_owner, weeks, problems) triples — `primary` wins.

    Used for the Double Entry + email hybrid. Double Entry is primary: it's
    fresher (no waiting on a sender) and its PROFIT/LOSS carries a real sign,
    where the emailed template reports magnitude only. The emailed books then
    cover the ~60 owners Double Entry doesn't expose to this account.

    Merging at the OFFICE level, not the owner level, so an owner who exists in
    both keeps a per-state office from either side. Weeks are unioned — the fill
    skips a week an office has no value for, so a wider list can't blank a cell.
    """
    p_owners, p_weeks, p_problems = primary
    s_owners, s_weeks, s_problems = secondary
    merged = {k: [dict(o) for o in v] for k, v in s_owners.items()}
    replaced = added = 0
    for key, offices in p_owners.items():
        bucket = merged.setdefault(key, [])
        for off in offices:
            st = off.get("state", "")
            at = next((i for i, x in enumerate(bucket)
                       if x.get("state", "") == st), None)
            if at is None:
                bucket.append(off)
                added += 1
            else:
                bucket[at] = off
                replaced += 1
    weeks = sorted(set(p_weeks) | set(s_weeks))
    logfn(f"financial: merged sources — {added} office(s) only in the primary, "
          f"{replaced} overridden by it, "
          f"{sum(len(v) for v in merged.values())} total; "
          f"weeks {[w.isoformat() for w in weeks]}")
    return merged, weeks, list(p_problems) + list(s_problems)


def run_financial_report(parsed, dry_run: bool = False,
                         only_sheet: Optional[str] = None, logfn=print) -> dict:
    """Fill every matching ICD tab across the focus-report spreadsheets.

    `parsed` is a (by_owner, weeks, problems) triple — whatever produced it.
    Both sources emit that same shape (parse.parse_financial_files for the
    emailed books, web_source.fetch_offices for Double Entry), so this and
    everything below it is source-agnostic. Returns a summary dict."""
    by_owner, weeks, problems = parsed
    n_offices = sum(len(v) for v in by_owner.values())
    logfn(f"financial: {n_offices} office(s) for {len(by_owner)} owner(s); "
          f"week endings {weeks}")
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
    # WENT-DARK = an ACTUAL missing cell: a tab that had a financial value LAST
    # week but is blank THIS week (its book didn't refresh). Only these are
    # flagged — never-filled template/rep tabs and long-stale owners are NOT,
    # so the note is signal, not a wall of 66 names (Megan 2026-07-09).
    # Incremental still holds: nothing is wiped, a re-run fills them once the
    # file lands. [[feedback_financial_incremental]] [[feedback_flag_unfilled_cells]]
    went_dark: set = set()
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
                          if not _is_non_icd_tab(w.title)
                          and w.title not in hidden]
        logfn(f"financial: {sheet_name} — {len(candidate_tabs)} ICD tab(s) to scan "
              f"({len(hidden)} hidden skipped)")
        filled = matched = 0
        sheet_unmatched: list = []
        for idx, ws in enumerate(candidate_tabs, start=1):
            tab_offices = ffill._match_owner(ws.title, by_owner, bridge)
            if not tab_offices:
                # No data in this upload — leave the tab alone. Whatever was
                # filled by a previous run stays put; when an upload that
                # DOES include this ICD arrives, the cells get filled then.
                # (Megan, 2026-05-20: incremental uploads must never wipe
                # previously-entered data.) Held for the went-dark check below.
                sheet_unmatched.append(ws.title)
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
        # Of this sheet's unmatched tabs, which actually LOST data this week
        # (had a value last week, blank now)? One batched read.
        went_dark |= set(ffill.find_went_dark(sh, sheet_unmatched))
        total_matched += matched
        total_filled += filled
    # A tab matched in another sheet this week isn't dark.
    went_dark -= matched_titles
    if went_dark:
        logfn("")
        logfn(f"===== ⚠ {len(went_dark)} ICD(s) WENT DARK — had financials last "
              f"week, none this week (actual missing cells) =====")
        for t in sorted(went_dark):
            logfn(f"  – {t}")
        logfn("(Their book didn't refresh this week — a re-run fills them once "
              "the file arrives; nothing was wiped.)")
    if problems:
        logfn("")
        logfn("===== ❌ UPLOAD PROBLEMS — Megan check these files =====")
        for name, reason in problems:
            logfn(f"  ❌ {name}: {reason}")
        logfn("(A '0 offices parsed' problem usually means the file's "
              "template is new — Claude needs to add a parser for that "
              "layout. Send the file to Claude.)")
    return {"filled": total_filled, "matched": total_matched,
            "problems": problems, "went_dark": sorted(went_dark)}


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
    ap.add_argument("--web", action="store_true",
                    help="Pull the financials from Double Entry "
                         "(doubleentry.com org summary). Combine with --email "
                         "to cover the owners Double Entry doesn't expose — "
                         "the web numbers win where both have an office.")
    ap.add_argument("--date", help="Week ending to pull from Double Entry "
                                   "(YYYY-MM-DD). Default: the most recent "
                                   "closed week, Central time.")
    args = ap.parse_args()

    _tmpctx = None
    _missing_books: List[str] = []
    # A file-based source runs unless --web is the ONLY source asked for. That
    # keeps the bare invocation (the Hub's Manual Upload card) reading the
    # upload dir exactly as before.
    use_files = args.email or not args.web
    # What a retry should re-run — mirrors how this run was invoked, so the
    # Hub's retry button and the orchestrator don't silently switch sources.
    _retry_args = ([a for a, on in (("--web", args.web),
                                    ("--email", args.email)) if on] or [])
    directory = None
    if args.email:
        from automations.financial_report import email_source as _fes
        _tmpctx = tempfile.TemporaryDirectory(prefix="financial_email_")
        directory = Path(_tmpctx.name)
        print("Auto-ingest: fetching FINANCIAL SUMMARY workbooks from the "
              "reporting inbox…")
        got = _fes.fetch(directory, verbose=True)
        print(f"  fetched {len(got)} workbook(s)")
        # Flag whole books that didn't email this week (a SENDER to nudge) —
        # distinct from an individual ICD with no data. Subject-based so a
        # filename change can't misreport a book as missing.
        _missing_books = _fes.missing_books()
        if _missing_books:
            print("")
            print(f"===== ⚠ {len(_missing_books)} BOOK(S) DID NOT EMAIL this "
                  f"week — nudge the sender =====")
            for b in _missing_books:
                print(f"  ✗ {b}")
            print("  (their ICDs stay blank until the file arrives — a re-run "
                  "then fills them; incremental, nothing is wiped.)")
    elif use_files:
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
                               retry_args=_retry_args, kind="section",
                               note="run started but did not complete")
        except Exception:  # noqa: BLE001 — manifest is best-effort
            pass

    try:
        files = gather_files(directory) if directory else []
        if use_files and not files and not args.web:
            print(f"no .xlsx files found in {directory}")
            return 1

        # Double Entry first — it's the primary source in the hybrid.
        web_parsed = None
        if args.web:
            from automations.financial_report import web_source as _ws
            print("Pulling the org summary from Double Entry…")
            web_parsed = _ws.fetch_offices(date=args.date)
        email_parsed = None
        if files:
            email_parsed = parse_financial_files(files)
            print(f"financial report — {len(files)} file(s) from "
                  f"{'email inbox' if args.email else directory}")

        if web_parsed and email_parsed:
            parsed = merge_sources(web_parsed, email_parsed)
        else:
            parsed = web_parsed or email_parsed
        print(f"financial report — sources: "
              f"{'+'.join(s for s, on in (('double entry', bool(web_parsed)), ('email/upload', bool(email_parsed))) if on)}, "
              f"dry_run={args.dry_run}")
        result = run_financial_report(parsed, dry_run=args.dry_run,
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
                        MANIFEST_ID, failed=bad, retry_args=_retry_args,
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
                    # Name both sources — which books arrived AND how many
                    # offices Double Entry supplied, so the summary email shows
                    # at a glance which half of the hybrid did the work.
                    bits = []
                    if web_parsed:
                        bits.append(f"Double Entry: "
                                    f"{sum(len(v) for v in web_parsed[0].values())} office(s)")
                    if files:
                        names = ", ".join(sorted(p.name for p in files))
                        bits.append(f"{len(files)} workbook(s): {names}")
                    _note = "pulled " + " · ".join(bits)
                    # Whole-book gaps first — the actionable "nudge this sender"
                    # signal, ahead of the per-ICD list.
                    if _missing_books:
                        _note += (f" · ⚠ {len(_missing_books)} BOOK(S) did NOT "
                                  f"email (nudge sender): "
                                  + ", ".join(_missing_books))
                    # Then the ACTUAL missing cells — tabs that went dark this
                    # week (had data last week, blank now). Never-filled/rep tabs
                    # are excluded, so this is signal not noise (Megan 2026-07-09).
                    _dark = result.get("went_dark") or []
                    if _dark:
                        _note += (f" · ⚠ {len(_dark)} ICD(s) went DARK (had data "
                                  f"last week, none this week): " + ", ".join(_dark))
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
