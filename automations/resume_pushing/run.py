#!/usr/bin/env python3
"""
Resume Pushing — ApplicantStream: Extract Resumes & Send to AI
Office 11580 (CARLOS HIDALGO - ALPHALETE SPECIALIZED MARKETING, INC.)

Runs on the machine's own AppStream session via `appstream_direct_session` (on
Lucy 2 that's Carlos's account = his own office), the collision-safe path
daily_focus uses: dedicated Chrome profile, holder-warmed, chrome-guard,
retry-on-"already in use", and yield_if_busy so it steps aside for other reports.

ROUTE (Megan's walkthrough + screenshots, 2026-07-14) — this is the V2 app:
  1. Attach the logged-in AppStream console; switch to office 11580 (classic
     #searchMC switcher).
  2. Click the orange "Explore Appstream AI" button  <- enters the V2 app.
  3. Applicants -> Process Emails -> Process in Batches.
  4. Show ALL rows (the grid paginates at 10/20/50), select every applicant.
  5. Click the ROBOT icon (top right) -> Start. Extraction pulls phone + email
     out of each resume; it takes a few minutes ("Ready For Extraction" -> 0).
  6. (Then: select all + "Send To AI" — Megan is confirming the exact next
     steps, so --extract-only stops cleanly after step 5.)

WHY THE PREVIOUS BUILD FOUND NO ROBOT (keep this — it cost real time):
  * It navigated straight to index.cfm?p=616, which is the CLASSIC ExtJS grid
    (.x-grid3-row). The robot extractor ONLY exists in the V2 app. Right site,
    wrong UI — so #btnExtractResume was never going to be there.
  * The robot is also a CHROME EXTENSION. patchright's default chromium args
    include --disable-extensions, which silently switches it off even when it IS
    installed in the profile. appstream_direct_session(enable_extensions=True)
    drops that flag. Seed the extension into the profile once with:
        python -m automations.shared.tableau_patchright --appstream-extension
  * The V2 grid is a jQuery DataTable, and jQuery lives in the page's MAIN world
    while patchright's page.evaluate runs ISOLATED (site globals invisible) —
    so every DataTables call goes through add_script_tag and bridges its result
    back via a DOM attribute.

FLAGS:
  --dry-run       Report what it sees; NO robot click, NO send. Safe probe.
  --debug         Reach the batch page, dump every control it can find, STOP.
                  Run this FIRST on a new machine — it proves the robot loaded.
  --extract-only  Select all + run the robot; never send.
  --send-only     Skip extraction; go straight to select-all + send.
  --limit N       Send only the first N rows (small live test). 0 = all.

NOTE: send-to-AI is IRREVERSIBLE (it pushes applicants onto the live AI call
list). The scheduled LaunchAgent runs LIVE; --dry-run/--debug are the safe probes.

The standing "terminated-ICD" / "flag unfilled cells" report rules don't apply
here — this is a single-office action bot, not a per-rep Sheet fill.
"""
from __future__ import annotations

import argparse
import re
import sys

from automations.shared.tableau_patchright import (
    appstream_direct_session, AppStreamBusy)
from automations.recruiting_report import fetch_office

OFFICE_ID = "11580"
OFFICE_HINT = "CARLOS HIDALGO"

# The V2 grid (Carlos's original Selenium bot targeted this same table).
BATCH_TABLE = "#table-batch-resume"
# How long to let the robot chew through the resumes before giving up. Carlos:
# "takes like three, four minutes". We poll "Ready For Extraction" -> 0 and only
# fall back on this ceiling.
EXTRACT_TIMEOUT_SECONDS = 900
EXTRACT_POLL_SECONDS = 15


def _log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _main_world(page, js: str, attr: str = "data-rp"):
    """Run JS in the page's MAIN world (where jQuery/DataTables live) and bridge
    the result back. page.evaluate is isolated-world, so site globals are
    invisible there — add_script_tag is the way in."""
    page.add_script_tag(content=(
        "(function(){var o;try{o=(function(){" + js + "})();}"
        "catch(e){o='err:'+e;}"
        f"document.body.setAttribute('{attr}', String(o));}})();"))
    page.wait_for_timeout(500)
    try:
        return page.frames[0].evaluate(
            f"() => document.body.getAttribute('{attr}')")
    except Exception:
        return None


def _row_count(page) -> int:
    try:
        return page.locator(f"{BATCH_TABLE} tbody tr").count()
    except Exception:
        return 0


def _ready_for_extraction(page):
    """The 'Ready For Extraction' badge. The V2 header renders the NUMBER FIRST
    ('1  Ready For Extraction'), so try that order before the label-first one."""
    try:
        body = " ".join(page.locator("body").inner_text().split())
    except Exception:
        return None
    m = re.search(r"([0-9,]+)\s*Ready\s*For\s*Extraction", body, re.I)
    if not m:
        m = re.search(r"Ready\s*For\s*Extraction\D{0,12}([0-9,]+)", body, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def _click_if_present(page, labels) -> bool:
    """Click the first matching button/link by visible text."""
    for label in labels:
        loc = page.locator(
            f"xpath=//*[self::button or self::a or self::span]"
            f"[normalize-space(.)='{label}']")
        if loc.count() == 0:
            loc = page.locator(
                f"xpath=//*[self::button or self::a][contains(.,'{label}')]")
        if loc.count() > 0:
            try:
                loc.first.click(timeout=6000, no_wait_after=True)
                page.wait_for_timeout(1500)
                _log(f"[click] '{label}'")
                return True
            except Exception:
                continue
    return False


# --------------------------------------------------------------------------- #
# Navigation — office -> Explore Appstream AI -> Process in Batches
# --------------------------------------------------------------------------- #
def enter_v2_app(page) -> bool:
    """Click the orange 'Explore Appstream AI' button on the classic console."""
    btn = page.locator(
        "xpath=//*[contains(normalize-space(.),'Explore Appstream AI')]")
    if btn.count() == 0:
        _log("[nav] 'Explore Appstream AI' button not found — maybe already in V2")
        return True
    try:
        btn.last.click(timeout=15000)
        page.wait_for_timeout(6000)
        _log(f"[nav] entered V2 app — {(page.url or '')[:70]}")
        return True
    except Exception as e:
        _log(f"[nav] could not click 'Explore Appstream AI': {e}")
        return False


def goto_batch_page(page) -> bool:
    """Applicants -> Process Emails -> Process in Batches (V2 menus)."""
    try:
        applicants = page.locator(
            "xpath=//*[self::a or self::button or self::span]"
            "[normalize-space(.)='Applicants']").first
        applicants.click(timeout=15000)
        page.wait_for_timeout(1200)
    except Exception as e:
        _log(f"[nav] 'Applicants' menu not clickable: {e}")
        return False

    # 'Process Emails' opens a submenu on hover.
    try:
        pe = page.locator(
            "xpath=//*[normalize-space(.)='Process Emails']").first
        pe.hover(timeout=8000)
        page.wait_for_timeout(1200)
    except Exception as e:
        _log(f"[nav] 'Process Emails' not hoverable: {e}")

    try:
        page.locator(
            "xpath=//*[normalize-space(.)='Process in Batches']"
        ).first.click(timeout=8000)
    except Exception as e:
        _log(f"[nav] 'Process in Batches' not clickable: {e}")
        return False

    # Wait for the DataTable to render.
    for _ in range(30):
        page.wait_for_timeout(1000)
        if _row_count(page) > 0 or page.locator(BATCH_TABLE).count() > 0:
            _log(f"[nav] on Process in Batches — {_row_count(page)} rows rendered")
            return True
    _log("[nav] reached the page but the batch table never rendered")
    return False


# --------------------------------------------------------------------------- #
# Select every applicant (the grid paginates at 10/20/50)
# --------------------------------------------------------------------------- #
def select_all(page) -> int:
    """Show ALL rows, then tick the header select-all box.

    The "Show N entries" dropdown only offers 10/20/50, so a header-checkbox
    click alone would select at most the 50 on screen. Force the DataTable's page
    length to -1 (= all) in the MAIN world first, so select-all really means all.
    """
    info = _main_world(page, (
        "if(!window.jQuery) return 'no-jquery';"
        f"var t=jQuery('{BATCH_TABLE}');"
        "if(!t.length) return 'no-table';"
        "var dt=t.DataTable();"
        "dt.page.len(-1).draw();"          # -1 = show every row on one page
        "return 'rows=' + dt.rows().count();"))
    _log(f"[select] show-all: {info}")
    page.wait_for_timeout(2500)

    rendered = _row_count(page)
    # Header select-all checkbox (thead) — now covers every row.
    cb = page.locator(f"{BATCH_TABLE} thead input[type='checkbox']")
    if cb.count() == 0:
        _log("[select] no header select-all checkbox found")
        return 0
    try:
        if not cb.first.is_checked():
            cb.first.check(timeout=8000)
        page.wait_for_timeout(1200)
    except Exception as e:
        _log(f"[select] header checkbox click failed: {e}")
        return 0

    selected = page.locator(
        f"{BATCH_TABLE} tbody input[type='checkbox']:checked").count()
    _log(f"[select] {selected} of {rendered} rows selected")
    return selected


# --------------------------------------------------------------------------- #
# The robot — extract phone + email out of each resume
# --------------------------------------------------------------------------- #
# The robot is the icon at the TOP RIGHT of the batch page (it comes from the
# Chrome extension). Green "Auto Extract Resumes" is the in-page fallback.
ROBOT_SELECTORS = [
    "[class*='robot' i]",
    ".fa-robot",
    "[title*='robot' i]",
    "[title*='resume helper' i]",
    "img[src*='robot' i]",
    "[id*='robot' i]",
]
AUTO_EXTRACT_SELECTORS = [
    "#btnExtractResume",
    "xpath=//*[self::button or self::a][contains(.,'Auto Extract Resume')]",
]


def _find_robot(page):
    for sel in ROBOT_SELECTORS + AUTO_EXTRACT_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                return loc.first, sel
        except Exception:
            continue
    return None, None


def extract_resumes(page, dry_run: bool) -> bool:
    """Select all -> click the robot -> Start -> wait for extraction to finish."""
    ready = _ready_for_extraction(page)
    _log(f"[extract] Ready For Extraction = {ready}")

    robot, sel = _find_robot(page)
    if robot is None:
        _log("[extract] ROBOT NOT FOUND. It comes from the ApplicantStream resume-"
             "extractor CHROME EXTENSION — if it's missing, the extension isn't "
             "loaded in this profile. Seed it once:\n"
             "    python -m automations.shared.tableau_patchright --appstream-extension\n"
             "(patchright also disables extensions by default; this module now "
             "passes enable_extensions=True.)")
        return False

    if dry_run:
        n = _row_count(page)
        _log(f"[extract] DRY-RUN — robot found via {sel!r}; {n} rows on the page; "
             "would select all + click the robot. No click made.")
        return True

    selected = select_all(page)
    if selected == 0:
        _log("[extract] nothing selected — skipping the robot")
        return False

    try:
        robot.click(timeout=15000)
        _log(f"[extract] clicked the robot ({sel})")
    except Exception as e:
        _log(f"[extract] robot click failed: {e}")
        return False
    page.wait_for_timeout(1500)

    # The robot opens a dialog whose confirm is "Start" (Carlos's walkthrough).
    _click_if_present(page, ["Start", "Yes", "OK", "Continue"])

    # Poll until the queue drains rather than blind-sleeping — Carlos says it
    # takes ~3-4 min, but it scales with how many resumes are waiting.
    waited = 0
    while waited < EXTRACT_TIMEOUT_SECONDS:
        page.wait_for_timeout(EXTRACT_POLL_SECONDS * 1000)
        waited += EXTRACT_POLL_SECONDS
        left = _ready_for_extraction(page)
        _log(f"[extract] …{waited}s — Ready For Extraction = {left}")
        if left == 0:
            _log(f"[extract] extraction finished after ~{waited}s")
            return True
    _log(f"[extract] still not drained after {EXTRACT_TIMEOUT_SECONDS}s — moving on")
    return True


# --------------------------------------------------------------------------- #
# Send to AI
# --------------------------------------------------------------------------- #
def send_all_to_ai(page, dry_run: bool, limit: int = 0) -> int:
    before = _row_count(page)
    if before == 0:
        _log("[send] grid is empty — nothing to send")
        return 0
    if dry_run:
        who = f"the first {limit}" if limit else "all"
        _log(f"[send] DRY-RUN — {before} rows; would select {who} + click "
             "'Send To AI'. No click made.")
        return 0

    if limit and limit > 0:
        rows = page.locator(f"{BATCH_TABLE} tbody tr")
        for i in range(min(limit, rows.count())):
            try:
                rows.nth(i).locator("input[type='checkbox']").first.check(timeout=5000)
            except Exception as e:
                _log(f"[send] row {i} check failed: {e}")
        selected = page.locator(
            f"{BATCH_TABLE} tbody input[type='checkbox']:checked").count()
        _log(f"[send] limit={limit}: {selected} rows selected")
    else:
        selected = select_all(page)
    if selected == 0:
        _log("[send] no rows selected — aborting (nothing sent)")
        return 0

    if not _click_if_present(page, ["Send To AI", "Send to AI"]):
        _log("[send] 'Send To AI' button not found — aborting")
        return 0
    page.wait_for_timeout(2500)

    reported = None
    try:
        body = " ".join(page.locator("body").inner_text().split())
        m = re.search(r"Sent to Call List\D{0,12}([0-9,]+)", body, re.I)
        if m:
            reported = int(m.group(1).replace(",", ""))
            _log(f"[send] save report says: sent {reported}")
    except Exception as e:
        _log(f"[send] report read err: {e}")

    _click_if_present(page, ["OK", "Yes", "Continue", "Close"])
    page.wait_for_timeout(3000)

    # NOTE: only trust the popup's number. Falling back to "rows before - rows
    # after" would OVER-REPORT, because AppStream also drops duplicate rows from
    # the grid without sending them (the bug Carlos reported to them).
    if reported is None:
        _log("[send] no 'Sent to Call List' number in the page — NOT inferring a "
             "count from the grid shrink (AppStream removes duplicates too, so "
             "that would over-report). Sent count unknown.")
        return -1
    return reported


# --------------------------------------------------------------------------- #
# Health check (--debug) — prove the page + the robot before trusting a run
# --------------------------------------------------------------------------- #
def _health_check(page) -> None:
    _log("[debug] ===== health check =====")
    _log(f"[debug] url            : {(page.url or '')[:100]}")
    _log(f"[debug] batch table    : {'FOUND' if page.locator(BATCH_TABLE).count() else 'MISSING'} ({BATCH_TABLE})")
    _log(f"[debug] rendered rows  : {_row_count(page)}")
    _log(f"[debug] ready-for-extr : {_ready_for_extraction(page)}")

    robot, sel = _find_robot(page)
    if robot is not None:
        _log(f"[debug] ROBOT         : FOUND via {sel!r}  <-- extension is loaded")
    else:
        _log("[debug] ROBOT         : MISSING  <-- extension NOT loaded in this "
             "profile. Seed it: python -m automations.shared.tableau_patchright "
             "--appstream-extension")

    for label in ("Send To AI", "Send To Call List", "Auto Extract Resumes"):
        n = page.locator(f"xpath=//*[self::button or self::a][contains(.,'{label}')]").count()
        _log(f"[debug] {label:<20}: {'FOUND' if n else 'MISSING'}")

    hdr = page.locator(f"{BATCH_TABLE} thead input[type='checkbox']").count()
    _log(f"[debug] select-all box : {'FOUND' if hdr else 'MISSING'}")
    _log(f"[debug] datatable      : {_main_world(page, 'return window.jQuery ? (jQuery(' + repr(BATCH_TABLE) + ').length ? jQuery(' + repr(BATCH_TABLE) + ').DataTable().rows().count() : 0) : -1;')}")
    _log("[debug] ===== end =====")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="ApplicantStream extractor / sender")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what it sees; no robot click, no send.")
    ap.add_argument("--debug", action="store_true",
                    help="Reach the batch page, dump the controls found, STOP.")
    ap.add_argument("--extract-only", action="store_true",
                    help="Select all + run the robot; never send.")
    ap.add_argument("--send-only", action="store_true",
                    help="Skip extraction; go straight to select-all + send.")
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="Send only the first N rows (small live test). 0 = all.")
    args = ap.parse_args()

    mode = "DRY-RUN (no writes)" if args.dry_run else "LIVE (sends to AI call list)"
    _log(f"=== Resume Pushing — office {OFFICE_ID} — {mode} ===")

    # LOWEST-priority AppStream job on Lucy 2 (runs every 10 min): if another
    # report holds Carlos's session, step aside and let it finish — the next tick
    # retries, so nothing is lost.
    # enable_extensions=True: the robot IS a Chrome extension, and patchright
    # disables extensions by default. Without this it can never appear.
    try:
        with appstream_direct_session(yield_if_busy=True,
                                      enable_extensions=True) as page:
            if not fetch_office._switch_office(page, OFFICE_ID, OFFICE_HINT):
                _log(f"[office] STOP — this AppStream account cannot reach office "
                     f"{OFFICE_ID}.")
                return 2
            page.wait_for_timeout(2000)

            if not enter_v2_app(page):
                _log("[STOP] could not enter the V2 Appstream AI app.")
                return 1
            if not goto_batch_page(page):
                _log("[STOP] could not reach Process in Batches.")
                return 1

            if args.debug:
                _health_check(page)
                return 0

            if not args.send_only:
                if not extract_resumes(page, args.dry_run):
                    _log("[STOP] extraction did not run.")
                    return 1

            if args.extract_only:
                _log("\n===== SUMMARY (extract-only) =====")
                _log(f"Rows on page                 : {_row_count(page)}")
                _log(f"Ready For Extraction         : {_ready_for_extraction(page)}")
                _log("(--extract-only — nothing was sent to the AI call list.)")
                return 0

            sent = send_all_to_ai(page, args.dry_run, limit=args.limit)

            _log("\n===== SUMMARY =====")
            _log(f"Mode                         : {mode}")
            if sent < 0:
                _log("Applicants sent to call list : UNKNOWN (no count in the popup)")
            else:
                _log(f"Applicants sent to call list : {sent}")
            if args.dry_run:
                _log("(DRY-RUN — nothing was pushed to the AI call list.)")
            elif args.limit:
                _log(f"(--limit {args.limit} — sent only the first {args.limit}.)")
    except AppStreamBusy:
        _log("[yield] AppStream session busy (another report is running) — "
             "yielding; the next 10-min run retries.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
