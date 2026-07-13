#!/usr/bin/env python3
"""
Resume Pushing — ApplicantStream v2 ("Explore Appstream AI" / Ownerville v2):
Extract Resumes & Send to AI. Office 11580 (CARLOS HIDALGO — ALPHALETE
SPECIALIZED MARKETING, INC.)

Scheduled, unattended version of Carlos's Cowork skill. It runs on the machine's
own warm AppStream session via `appstream_direct_session` (on Lucy 2 that's
Carlos's account = his own office): dedicated Chrome profile, kept warm by the
session holder, chrome-guard, retry-on-"already in use". No manual login.

WHY THIS WAS REWRITTEN (2026-07-12): the previous version went straight to the
LEGACY batch grid at index.cfm?p=616 (an ExtJS 2.2.1 page on the classic
homepage). That is the WRONG surface — the task is supposed to run on
ApplicantStream **v2**, the modern "Explore Appstream AI" dashboard (jQuery
DataTables, #table-batch-resume). The legacy page also did a SINGLE extract +
SINGLE send, so it left resumes un-extracted (extract processes ≤50 per run) and
sendable applicants behind (resolving duplicates frees up more each pass). This
version mirrors Carlos's Cowork skill exactly:

Flow:
  1. Attach the logged-in AppStream console (no manual login)
  2. Switch to office 11580 (fails loudly if the account can't see it)
  3. Click the orange "Explore Appstream AI" button → the v2 dashboard
  4. Applicants → Process Emails → Process in Batches
  5. EXTRACT LOOP: open the robot (Resume Helper) → Start, wait, reload, re-read
     "Ready For Extraction"; repeat until it hits 0 (extract does ≤50/run)
  6. SEND LOOP: render all rows (DataTable page.len(1000).draw()), select-all,
     "Send To AI", confirm "Yes"; repeat until "Sent to Call List: 0" / "no
     applicants to send" / the record count stops dropping
  7. Print a summary

--dry-run   Reports counts only — NO extract, NO send clicks. Nothing is pushed
            to the call list. Run this first after any change.
--send-only Skip extraction; go straight to the send loop.
--extract-only  Run the extract loop only; never send.
--limit N   Send only the first N rows (small live test); disables select-all.
--debug     Reach the v2 batch page, print a health check (which controls +
            counts are visible), then STOP. Use this first on a new machine or
            after any UI change to confirm the selectors still match.

NOTE: send-to-AI is IRREVERSIBLE (it pushes applicants onto the live AI call
list). The scheduled LaunchAgent runs LIVE; --dry-run is the safe probe.

SELECTORS: the control labels/ids below (Explore Appstream AI, robot / Resume
Helper / Start, #table-batch-resume, Send To AI, the "Batch Process Emails
Status" → Yes dialog, "Ready For Extraction", "Sent to Call List: N") come from
the Cowork skill. If ApplicantStream v2 changes, run `--debug` and adjust the
locators in the helpers — the health check reports exactly which ones matched.
"""
from __future__ import annotations

import argparse
import re
import sys

# Reused, collision-safe infra (the same modules daily_focus runs on).
from automations.shared.tableau_patchright import (
    appstream_direct_session, AppStreamBusy)
from automations.recruiting_report import fetch_office

OFFICE_ID = "11580"
OFFICE_HINT = "CARLOS HIDALGO"
TABLE = "#table-batch-resume"        # v2 DataTable id (from the Cowork skill)

EXTRACT_WAIT_SECONDS = 180           # let one Resume-Helper batch finish
MAX_EXTRACT_CYCLES = 30              # safety cap (≤50 resumes/cycle → ~1500)
MAX_SEND_PASSES = 8                  # safety cap for the send loop


def _log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _click_if_present(page, labels, timeout: int = 5000) -> bool:
    """Click the first visible button/element whose text contains one of `labels`."""
    for label in labels:
        loc = page.locator(f"xpath=//button[contains(normalize-space(.),'{label}')]"
                           f" | //a[contains(normalize-space(.),'{label}')]"
                           f" | //*[@role='button'][contains(normalize-space(.),'{label}')]")
        if loc.count() > 0:
            try:
                loc.first.click(timeout=timeout, no_wait_after=True)
                page.wait_for_timeout(1500)
                return True
            except Exception:
                continue
    return False


def _first_int(text: str):
    m = re.search(r"([0-9][0-9,]*)", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def _main_world(page, expr: str):
    """Evaluate `expr` in the page's MAIN world and return it as a string.
    patchright runs page.evaluate in an ISOLATED world that can't see window.jQuery
    (confirmed on the v2 batch page — DataTables lives in the main world), so we
    inject a <script> that stringifies the result into a DOM attribute and read
    that attribute back (the DOM is shared across worlds)."""
    try:
        page.add_script_tag(content=(
            "(function(){try{document.body.setAttribute('data-mw', String(" + expr + "));}"
            "catch(e){document.body.setAttribute('data-mw','__ERR__:'+e);}})();"))
        page.wait_for_timeout(300)
        return page.evaluate("() => document.body.getAttribute('data-mw')")
    except Exception as e:
        return f"__ERR__:{e}"


# --------------------------------------------------------------------------- #
# Navigation → the v2 batch page
# --------------------------------------------------------------------------- #
def open_v2_dashboard(page):
    """Click the orange "Explore Appstream AI" button to enter the modern (v2)
    dashboard. Returns the page to use afterwards (v2 may open in a new tab)."""
    ctx = page.context
    before = len(ctx.pages)
    clicked = _click_if_present(page, ["Explore Appstream AI", "Explore AppStream AI"],
                                timeout=10000)
    if not clicked:
        _log("[v2] 'Explore Appstream AI' button not found — already on v2? continuing")
        return page
    page.wait_for_timeout(3000)
    if len(ctx.pages) > before:               # opened in a new tab — switch to it
        new_page = ctx.pages[-1]
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass
        _log("[v2] dashboard opened in a new tab")
        return new_page
    _log("[v2] entered dashboard")
    return page


def goto_process_in_batches(page) -> bool:
    """Applicants → Process Emails → Process in Batches (v2 top nav)."""
    try:
        page.locator("xpath=//*[normalize-space(.)='Applicants']").first.hover(timeout=8000)
        page.wait_for_timeout(600)
        page.locator("xpath=//*[normalize-space(.)='Process Emails']").first.hover(timeout=8000)
        page.wait_for_timeout(600)
    except Exception as e:
        _log(f"[nav] hover Applicants/Process Emails failed: {e}")
    if _click_if_present(page, ["Process in Batches", "Process In Batches"], timeout=10000):
        page.wait_for_timeout(3000)
        # Wait for the DataTable to render.
        for _ in range(20):
            if page.locator(f"{TABLE} tbody tr").count() > 0 or page.locator(TABLE).count() > 0:
                _log("[nav] reached Process In Batches (v2 DataTable present)")
                return True
            page.wait_for_timeout(1000)
        _log("[nav] Process In Batches clicked but the DataTable never rendered")
        return True
    _log("[nav] could not find 'Process in Batches'")
    return False


# --------------------------------------------------------------------------- #
# Counts
# --------------------------------------------------------------------------- #
def ready_for_extraction(page):
    """Count rows still 'Ready For Extraction'. In v2 this is a PER-ROW status
    badge (a title attribute), not a header number, so we render all rows first
    and count the badges across the whole store. 0 = extraction complete. The
    elapsed-time counter in the Resume Helper popup is NOT reliable (it keeps
    ticking after a batch finishes), which is why we recount the DOM instead."""
    render_all_rows(page)
    res = _main_world(
        page, f"document.querySelectorAll('{TABLE} tbody [title=\"Ready For Extraction\"]').length")
    try:
        return int(res)
    except Exception:
        return None


def _rendered_row_count(page) -> int:
    try:
        return page.locator(f"{TABLE} tbody tr").count()
    except Exception:
        return 0


def render_all_rows(page) -> int:
    """Show every record on one page so select-all / status counts cover the whole
    store, not just the 10 rows the DataTable renders by default (the "Show
    entries" dropdown maxes at 50). Returns the total record count."""
    _main_world(page, f"(function(){{jQuery('{TABLE}').DataTable().page.len(1000).draw();return 'ok';}})()")
    page.wait_for_timeout(1500)
    total = _main_world(page, f"jQuery('{TABLE}').DataTable().page.info().recordsDisplay")
    if isinstance(total, str) and total.startswith("__ERR__"):
        _log(f"[rows] page.len(1000).draw() error: {total}")
    try:
        n = int(total)
    except Exception:
        n = _rendered_row_count(page)
    _log(f"[rows] rendered all rows: {n}")
    return n


# --------------------------------------------------------------------------- #
# Extract loop
# --------------------------------------------------------------------------- #
def run_extract_once(page) -> bool:
    """Open the robot (Resume Helper) popup and click Start. One Resume-Helper run
    processes ≤50 resumes."""
    # The robot icon sits top-right, just under the office name. Try a few
    # plausible hooks, then fall back to opening anything titled "Resume Helper".
    opened = False
    for sel in ["button[title*='Resume' i]", "[title*='Resume Helper' i]",
                "a[title*='Resume' i]", ".fa-robot", "i.fa-robot",
                "button:has(.fa-robot)", "[class*='robot']"]:
        loc = page.locator(sel)
        if loc.count() > 0:
            try:
                loc.first.click(timeout=8000)
                opened = True
                break
            except Exception:
                continue
    if not opened:
        _log("[extract] robot / Resume Helper icon not found — skipping this cycle")
        return False
    page.wait_for_timeout(1500)
    if not _click_if_present(page, ["Start"], timeout=8000):
        _log("[extract] 'Start' not found in the Resume Helper popup")
        return False
    _log(f"[extract] Resume Helper started — waiting ~{EXTRACT_WAIT_SECONDS}s")
    page.wait_for_timeout(EXTRACT_WAIT_SECONDS * 1000)
    _click_if_present(page, ["OK", "Close", "Done"])
    return True


def extract_loop(page, dry_run: bool) -> int:
    """Loop: Start → wait → reload → re-read "Ready For Extraction", until it hits
    0 (or the safety cap). Returns the count still ready at the end."""
    start = ready_for_extraction(page)
    _log(f"[extract] Ready For Extraction at start: {start}")
    if dry_run:
        _log("[extract] DRY-RUN — would loop Resume Helper until 0; no clicks made")
        return start or 0

    cycles = 0
    while cycles < MAX_EXTRACT_CYCLES:
        remaining = ready_for_extraction(page)
        if remaining is None:
            _log("[extract] could not read 'Ready For Extraction' — stopping loop")
            break
        if remaining <= 0:
            _log("[extract] Ready For Extraction = 0 — extraction complete")
            break
        cycles += 1
        _log(f"[extract] cycle {cycles}: {remaining} ready — running Resume Helper")
        if not run_extract_once(page):
            break
        # Reload and re-read (the elapsed timer is not a reliable done-signal).
        try:
            page.reload(wait_until="domcontentloaded")
        except Exception:
            pass
        page.wait_for_timeout(3000)
    else:
        _log(f"[extract] hit safety cap ({MAX_EXTRACT_CYCLES} cycles) — stopping")

    end = ready_for_extraction(page) or 0
    _log(f"[extract] done — {cycles} cycle(s); still 'Not Extracted'/ready: {end}")
    return end


# --------------------------------------------------------------------------- #
# Send loop
# --------------------------------------------------------------------------- #
def _select_all(page, limit: int = 0) -> int:
    """Tick the header checkbox to select every rendered row. With --limit, tick
    only the first N row checkboxes instead."""
    if limit and limit > 0:
        rows = page.locator(f"{TABLE} tbody tr")
        n = min(limit, rows.count())
        for i in range(n):
            try:
                rows.nth(i).locator("input[type='checkbox']").first.check(timeout=4000)
            except Exception as e:
                _log(f"[send] row {i} check failed: {e}")
        sel = page.locator(f"{TABLE} tbody tr input[type='checkbox']:checked").count()
        _log(f"[send] limit={limit}: {sel} rows selected")
        return sel
    # Select-all header checkbox (top-left, next to "Id").
    for sel in [f"{TABLE} thead input[type='checkbox']",
                f"{TABLE} th input[type='checkbox']",
                "thead input[type='checkbox'].select-all",
                "input#select-all"]:
        cb = page.locator(sel)
        if cb.count() > 0:
            try:
                cb.first.check(timeout=6000)
                page.wait_for_timeout(800)
                sel = page.locator(f"{TABLE} tbody tr input[type='checkbox']:checked").count()
                _log(f"[send] select-all → {sel} rows selected")
                return sel
            except Exception as e:
                _log(f"[send] select-all click failed ({sel}): {e}")
    _log("[send] no select-all checkbox found")
    return 0


def _read_status_dialog(page):
    """Read the "Batch Process Emails Status" dialog. Returns (sent, done):
    sent = 'Sent to Call List' number (or None), done = True when the dialog says
    there is nothing left to send."""
    sent, done = None, False
    dlg = page.locator(".modal:visible, .swal2-popup:visible, [role='dialog']:visible")
    try:
        if dlg.count() > 0:
            text = " ".join(dlg.first.inner_text().split())
            _log(f"[send] status: {text[:220]}")
            m = re.search(r"Sent to Call List[^0-9]*([0-9,]+)", text, re.I)
            if m:
                sent = int(m.group(1).replace(",", ""))
            if re.search(r"no applicants to send", text, re.I) or sent == 0:
                done = True
    except Exception as e:
        _log(f"[send] status read err: {e}")
    return sent, done


def send_once(page, dry_run: bool, limit: int = 0):
    """One send pass: render all → select rows → Send To AI → confirm Yes → read
    the status dialog. Returns (sent, done, rows_before)."""
    before = render_all_rows(page)
    if before == 0:
        _log("[send] table is empty — nothing to send")
        return 0, True, 0
    if dry_run:
        who = f"the first {limit}" if limit else "all"
        _log(f"[send] DRY-RUN — {before} rows; would select {who} + 'Send To AI', "
             "no click made")
        return 0, True, before

    sel = _select_all(page, limit=limit)
    if sel == 0:
        _log("[send] no rows selected — aborting this pass")
        return 0, True, before

    if not _click_if_present(page, ["Send To AI", "Send to AI"], timeout=10000):
        _log("[send] 'Send To AI' button not found — aborting")
        return 0, True, before
    page.wait_for_timeout(2000)

    sent, done = _read_status_dialog(page)         # dialog asks "Do you want to continue?"
    _click_if_present(page, ["Yes", "Continue", "OK"])   # confirm the send
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    return (sent if sent is not None else 0), done, before


def send_loop(page, dry_run: bool, limit: int = 0) -> int:
    """Repeat send passes until the status says 0 sent / no applicants, or the
    record count stops dropping, or the safety cap. Returns total sent."""
    if dry_run:
        sent, _, _ = send_once(page, dry_run=True, limit=limit)
        return 0
    if limit and limit > 0:                        # a --limit test is a single pass
        sent, _, _ = send_once(page, dry_run=False, limit=limit)
        _log(f"[send] --limit {limit}: sent {sent} (single test pass)")
        return sent

    total = 0
    prev_before = None
    for p in range(1, MAX_SEND_PASSES + 1):
        sent, done, before = send_once(page, dry_run=False, limit=0)
        total += sent
        _log(f"[send] pass {p}: sent {sent} (rows before pass: {before}; total {total})")
        if done or sent == 0:
            _log("[send] status reports nothing left to send — stopping")
            break
        if prev_before is not None and before >= prev_before:
            _log("[send] record count stopped dropping — remaining are duplicates / "
                 "data-error rows; stopping")
            break
        prev_before = before
    else:
        _log(f"[send] hit safety cap ({MAX_SEND_PASSES} passes) — stopping")
    return total


# --------------------------------------------------------------------------- #
# Health check (--debug)
# --------------------------------------------------------------------------- #
def _health_check(page) -> None:
    _log("[debug] ===== v2 health check =====")
    _log(f"[debug] url: {(page.url or '')[:100]}")
    _log(f"[debug] DataTable ({TABLE}): {'FOUND' if page.locator(TABLE).count() else 'MISSING'}")
    _log(f"[debug] rendered rows: {_rendered_row_count(page)}")
    _log(f"[debug] Ready For Extraction: {ready_for_extraction(page)}")
    probes = [
        ("Send To AI button", "xpath=//button[contains(.,'Send To AI') or contains(.,'Send to AI')]"),
        ("select-all checkbox", f"{TABLE} thead input[type='checkbox']"),
        ("robot / Resume Helper", "[title*='Resume' i], .fa-robot, [class*='robot']"),
    ]
    for name, sel in probes:
        try:
            _log(f"[debug] {name}: {'FOUND' if page.locator(sel).count() else 'MISSING'}")
        except Exception as e:
            _log(f"[debug] {name}: err {e}")
    jq = _main_world(page, "!!(window.jQuery && jQuery.fn && jQuery.fn.dataTable)")
    _log(f"[debug] jQuery + DataTables reachable (main world): {jq}")
    total = _main_world(page, f"jQuery('{TABLE}').DataTable().page.info().recordsTotal")
    _log(f"[debug] DataTable recordsTotal: {total}")
    _log("[debug] ===== end =====")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def _locate_plugin() -> int:
    """Find where the Resume Helper extension actually installed — search every
    Chrome profile on the machine + the repo's own profiles for the ext id. Tells
    us which profile to drive. Writes to the 'RP Diag' sheet tab."""
    import glob
    import os
    from automations.recruiting_report import fill as _fill
    lines = []

    def L(s):
        lines.append(str(s)[:600])
        print(s, flush=True)

    EXT = "goofbdglmeckblcbcoffnkdnmpehhhmo"
    home = os.path.expanduser("~")
    patterns = [
        home + "/Library/Application Support/Google/Chrome/*/Extensions/" + EXT,
        home + "/Library/Application Support/Google/Chrome/*/*/Extensions/" + EXT,
        home + "/recruiting-report/automations/uploaded/*/Default/Extensions/" + EXT,
        home + "/recruiting-report/automations/uploaded/*/Extensions/" + EXT,
    ]
    found = []
    for pat in patterns:
        found += glob.glob(pat)
    L("Resume Helper (" + EXT + ") found in:")
    if found:
        for f in found:
            L("  " + f)
    else:
        L("  (NOT found in any profile)")
    # list the real Chrome profiles present
    profs = glob.glob(home + "/Library/Application Support/Google/Chrome/*/Preferences")
    L("real Chrome profiles: " + str(sorted(os.path.basename(os.path.dirname(x)) for x in profs)))
    # is this machine's Chrome managed?
    mp = glob.glob("/Library/Managed Preferences/*/com.google.Chrome.plist") + \
        glob.glob("/Library/Managed Preferences/com.google.Chrome.plist")
    L("managed-Chrome policy files: " + str(mp))
    try:
        sh = _fill._client().open_by_key("1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
        try:
            t = sh.worksheet("RP Diag")
        except Exception:
            t = sh.add_worksheet(title="RP Diag", rows=200, cols=1)
        t.clear()
        t.update([[x] for x in lines], "A1")
        print(f"LOCATE: wrote {len(lines)} lines to RP Diag", flush=True)
    except Exception as e:
        print(f"LOCATE sheet err: {e}", flush=True)
    return 0


def _cdp_test() -> int:
    """Decisive Option-A test. Drive the DEDICATED extract profile
    (uploaded/.extract_profile — where the plugin was GENUINELY installed via
    'Add to Chrome', and which patchright NEVER launches, so the install isn't
    stripped) with a plain Chrome over CDP, and ask the page for chrome.runtime.
    NO --load-extension — we rely on the genuine install. If chrome.runtime is
    present here, the plain-Chrome extraction path is viable; if not, the plugin
    is refusing to run under automation. Writes to the 'RP Diag' sheet tab."""
    import subprocess
    import time as _t
    from patchright.sync_api import sync_playwright
    from automations.shared.tableau_patchright import APPSTREAM_PROFILE_DIR
    from automations.recruiting_report import fill as _fill
    lines = []

    def L(s):
        lines.append(str(s)[:600])
        print(s, flush=True)

    profile = APPSTREAM_PROFILE_DIR.parent / ".extract_profile"
    exts_dir = profile / "Default" / "Extensions"
    L(f"dedicated profile exists: {profile.is_dir()}; Extensions dir: {exts_dir.is_dir()}")
    if exts_dir.is_dir():
        L("installed extension ids: " + str([d.name for d in exts_dir.iterdir() if d.is_dir()]))
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    port = "9334"
    subprocess.run(["pkill", "-f", ".extract_profile"], capture_output=True)
    _t.sleep(3)
    # NO --load-extension / --disable-extensions-except: use the genuine install.
    launch = [chrome, f"--user-data-dir={profile}", f"--remote-debugging-port={port}",
              "--no-first-run", "--no-default-browser-check",
              "https://applicantstream.com/index.cfm"]
    proc = subprocess.Popen(launch, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    L(f"launched plain Chrome pid={proc.pid}; waiting 35s for policy/extension install…")
    _t.sleep(35)
    if exts_dir.is_dir():
        L("Extensions after 35s: " + str([d.name for d in exts_dir.iterdir() if d.is_dir()]))
    else:
        L("Extensions dir STILL absent after 35s")
    try:
        pol = subprocess.run(["defaults", "read", "com.google.Chrome",
                              "ExtensionInstallForcelist"], capture_output=True,
                             text=True, timeout=10)
        L("policy force-install list: " + ((pol.stdout or pol.stderr or "(empty)").strip())[:220])
    except Exception as e:
        L("policy read err: " + str(e)[:80])
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto("https://applicantstream.com/index.cfm", wait_until="domcontentloaded")
            except Exception as e:
                L("goto err: " + str(e)[:80])
            page.wait_for_timeout(5000)
            L("url: " + (page.url or "")[:95])
            L("searchMC (logged in?): " + str(page.locator("#searchMC").count()))
            L("service_workers: " + str([sw.url for sw in ctx.service_workers]))
            page.add_script_tag(content=(
                "(function(){try{if(typeof chrome==='undefined'||!chrome.runtime){"
                "document.body.setAttribute('data-ext','NO chrome.runtime');return;}"
                "document.body.setAttribute('data-ext','present, awaiting');"
                "chrome.runtime.sendMessage('goofbdglmeckblcbcoffnkdnmpehhhmo',{rh:'ping'},"
                "function(r){document.body.setAttribute('data-ext',chrome.runtime.lastError?"
                "('NO_EXT: '+chrome.runtime.lastError.message):('EXT_OK: '+JSON.stringify(r)));});"
                "}catch(e){document.body.setAttribute('data-ext','ERR:'+e);}})();"))
            page.wait_for_timeout(3500)
            L("*** chrome.runtime: " + str(page.evaluate("() => document.body.getAttribute('data-ext')")))
            try:
                browser.close()
            except Exception:
                pass
    except Exception as e:
        L("CDP error: " + str(e)[:220])
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        subprocess.run(["pkill", "-f", ".extract_profile"], capture_output=True)
    try:
        sh = _fill._client().open_by_key("1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
        try:
            t = sh.worksheet("RP Diag")
        except Exception:
            t = sh.add_worksheet(title="RP Diag", rows=200, cols=1)
        t.clear()
        t.update([[x] for x in lines], "A1")
        print(f"CDP-TEST: wrote {len(lines)} lines to RP Diag", flush=True)
    except Exception as e:
        print(f"CDP-TEST sheet err: {e}", flush=True)
    return 0


def _plain_probe() -> int:
    """Launch a PLAIN Google Chrome (NOT patchright) on the pusher profile, with the
    cached plugin, expose CDP, connect Playwright to it, and ask the ApplicantStream
    page whether it can reach the extension (chrome.runtime). If a plain Chrome
    activates the plugin where patchright doesn't, the plain-Chrome extraction path
    is viable. Writes full output to the 'RP Diag' sheet tab."""
    import subprocess
    import time as _t
    from patchright.sync_api import sync_playwright
    from automations.shared.tableau_patchright import APPSTREAM_PROFILE_DIR
    from automations.recruiting_report import fill as _fill
    lines = []

    def L(s):
        lines.append(str(s)[:600])
        print(s, flush=True)

    profile = APPSTREAM_PROFILE_DIR
    cache = profile.parent / ".extractor_cache"
    exts = [str(d) for d in sorted(cache.glob("ext*")) if (d / "manifest.json").exists()]
    L(f"cache extensions: {len(exts)}")
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    port = "9333"
    subprocess.run(["pkill", "-f", "appstream_profile"], capture_output=True)
    _t.sleep(3)
    launch = [chrome, f"--user-data-dir={profile}", f"--remote-debugging-port={port}",
              "--no-first-run", "--no-default-browser-check"]
    if exts:
        joined = ",".join(exts)
        launch += [f"--disable-extensions-except={joined}", f"--load-extension={joined}"]
    launch += ["https://applicantstream.com/index.cfm"]
    proc = subprocess.Popen(launch, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    L(f"launched plain Chrome pid={proc.pid}, waiting to attach…")
    _t.sleep(11)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto("https://applicantstream.com/index.cfm", wait_until="domcontentloaded")
            except Exception as e:
                L(f"goto err: {str(e)[:80]}")
            page.wait_for_timeout(5000)
            L("url: " + (page.url or "")[:95])
            L("searchMC present (logged in?): " + str(page.locator("#searchMC").count()))
            L("service_workers: " + str([sw.url for sw in ctx.service_workers]))
            page.add_script_tag(content=(
                "(function(){try{if(typeof chrome==='undefined'||!chrome.runtime){"
                "document.body.setAttribute('data-ext','NO chrome.runtime');return;}"
                "document.body.setAttribute('data-ext','present, awaiting');"
                "chrome.runtime.sendMessage('goofbdglmeckblcbcoffnkdnmpehhhmo',{rh:'ping'},"
                "function(r){document.body.setAttribute('data-ext',chrome.runtime.lastError?"
                "('NO_EXT: '+chrome.runtime.lastError.message):('EXT_OK: '+JSON.stringify(r)));});"
                "}catch(e){document.body.setAttribute('data-ext','ERR:'+e);}})();"))
            page.wait_for_timeout(3500)
            L("PLAIN chrome.runtime: " + str(page.evaluate("() => document.body.getAttribute('data-ext')")))
            try:
                browser.close()
            except Exception:
                pass
    except Exception as e:
        L("CDP connect/drive error: " + str(e)[:220])
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        subprocess.run(["pkill", "-f", "appstream_profile"], capture_output=True)
    try:
        sh = _fill._client().open_by_key("1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
        try:
            t = sh.worksheet("RP Diag")
        except Exception:
            t = sh.add_worksheet(title="RP Diag", rows=200, cols=1)
        t.clear()
        t.update([[x] for x in lines], "A1")
        print(f"PLAIN-PROBE: wrote {len(lines)} lines to RP Diag", flush=True)
    except Exception as e:
        print(f"PLAIN-PROBE sheet err: {e}", flush=True)
    return 0


def _probe() -> int:
    """Deep, honest re-check of whether the extractor plugin actually RUNS in the
    automation browser (not just whether it's on the launch line). Reports the
    extension's service-worker / background-page presence (proof it's live), the
    page buttons before/after the robot click, all frames (an injected popup would
    be a chrome-extension:// frame), and any Start controls. Writes everything to
    the 'RP Diag' Google-Sheet tab so the queue's 3-line truncation can't hide it."""
    from automations.shared.tableau_patchright import appstream_direct_session
    from automations.recruiting_report import fill as _fill
    lines = []

    def L(s):
        lines.append(str(s)[:600])
        print(s, flush=True)

    def buttons(page):
        out = []
        try:
            b = page.locator("button:visible, a.btn:visible, [role='button']:visible")
            for i in range(min(b.count(), 45)):
                try:
                    t = " ".join((b.nth(i).inner_text() or "").split())
                    if t:
                        out.append(t[:40])
                except Exception:
                    pass
        except Exception:
            pass
        return list(dict.fromkeys(out))

    with appstream_direct_session(yield_if_busy=True, load_extensions=True) as page:
        ctx = page.context
        L("service_workers@start: " + str([sw.url for sw in ctx.service_workers]))
        try:
            L("background_pages@start: " + str([bp.url for bp in ctx.background_pages]))
        except Exception as e:
            L(f"background_pages err: {e}")
        fetch_office._switch_office(page, OFFICE_ID, OFFICE_HINT)
        page.wait_for_timeout(1500)
        page = open_v2_dashboard(page)
        goto_process_in_batches(page)
        page.wait_for_timeout(3000)
        L("service_workers@batch: " + str([sw.url for sw in ctx.service_workers]))
        L("url: " + (page.url or "")[:95])

        # DEFINITIVE: can the PAGE reach the extension? This is exactly how
        # ApplicantStream itself detects the plugin — chrome.runtime.sendMessage to
        # the ext id. Runs in the page's MAIN world; result bridged to a DOM attr.
        page.add_script_tag(content=(
            "(function(){try{"
            "if(typeof chrome==='undefined'||!chrome.runtime){"
            "document.body.setAttribute('data-ext','NO chrome.runtime on page');return;}"
            "document.body.setAttribute('data-ext','runtime present, awaiting reply');"
            "chrome.runtime.sendMessage('goofbdglmeckblcbcoffnkdnmpehhhmo',{rh:'ping'},"
            "function(r){if(chrome.runtime.lastError){"
            "document.body.setAttribute('data-ext','NO_EXT: '+chrome.runtime.lastError.message);}"
            "else{document.body.setAttribute('data-ext','EXT_OK: '+JSON.stringify(r));}});"
            "}catch(e){document.body.setAttribute('data-ext','ERR:'+e);}})();"))
        page.wait_for_timeout(3000)
        try:
            extstate = page.evaluate("() => document.body.getAttribute('data-ext')")
        except Exception as e:
            extstate = f"read-err:{e}"
        L("PAGE-SEES-EXTENSION: " + str(extstate))

        L("ready_before: " + str(ready_for_extraction(page)))
        L("buttons_before: " + str(buttons(page)))

        # Per Carlos: robot -> Start opens ANOTHER window and grinds a couple
        # minutes, then returns to the main page. Catch the new page + click Start.
        ctx2 = page.context
        robot = None
        rsel = None
        for sel in ["[title*='extract resume data' i]", "[title*='Resume Helper' i]",
                    "[title*='Resume' i]", ".fa-robot", "[class*='robot']"]:
            if page.locator(sel).count():
                robot = page.locator(sel).first
                rsel = sel
                break
        L("robot selector: " + str(rsel))
        helper = None
        if robot:
            try:
                with ctx2.expect_page(timeout=9000) as _pi:
                    robot.click(timeout=8000)
                helper = _pi.value
                try:
                    helper.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                L("robot OPENED NEW WINDOW: " + (helper.url or "")[:95])
            except Exception as e:
                L("robot click: no new window (" + str(e)[:70] + ")")
        page.wait_for_timeout(4000)
        L("all open pages: " + str([(p.url or "")[:70] for p in ctx2.pages]))

        # Find + click Start across every open page/frame
        clicked_start = False
        for p in ctx2.pages:
            for f in p.frames:
                try:
                    loc = f.locator("xpath=//button[normalize-space(.)='Start'] | "
                                    "//a[normalize-space(.)='Start'] | "
                                    "//input[@type='button'][@value='Start']")
                    if loc.count():
                        L("START found on: " + (p.url or "")[:60])
                        loc.first.click(timeout=8000)
                        clicked_start = True
                        break
                except Exception:
                    pass
            if clicked_start:
                break
        L("clicked_start: " + str(clicked_start))
        if clicked_start:
            L("waiting ~160s for extraction to process…")
            page.wait_for_timeout(160000)
        L("pages after wait: " + str([(p.url or "")[:60] for p in ctx2.pages]))
        try:
            page.bring_to_front()
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        except Exception:
            pass
        L("ready_AFTER_extract: " + str(ready_for_extraction(page)))

    try:
        sh = _fill._client().open_by_key("1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
        try:
            t = sh.worksheet("RP Diag")
        except Exception:
            t = sh.add_worksheet(title="RP Diag", rows=200, cols=1)
        t.clear()
        t.update([[x] for x in lines], "A1")
        print(f"PROBE: wrote {len(lines)} lines to 'RP Diag' tab", flush=True)
    except Exception as e:
        print(f"PROBE: sheet write failed: {e}", flush=True)
    return 0


def _inspect_plugin() -> int:
    """Read the cached extractor plugin manifest(s) and report how ApplicantStream
    would detect the plugin — the fork we need to resolve the 'Download Resume
    Helper Plugin' wall. Runs via `rerun resume_pushing --inspect-plugin` (no
    browser). The DECISIVE summary is on the LAST line so it survives the command
    queue's 3-line result truncation.
      - has_key=True  → --load-extension keeps the plugin's REAL id (so a fixed-id
        site check would still recognize it → the wall is likely the account).
      - externally_connectable set → site talks to the extension BY ID (our loaded
        copy's id must match, else 'Download' no matter the account).
      - content_scripts set → the extension injects into the page (id-independent;
        our loaded copy WOULD be detected)."""
    import json as _json
    from automations.shared.tableau_patchright import APPSTREAM_PROFILE_DIR
    cache = APPSTREAM_PROFILE_DIR.parent / ".extractor_cache"
    if not cache.is_dir():
        print(f"INSPECT: no cache at {cache} — install the plugin + run once first")
        return 1
    picks = []
    for d in sorted(cache.glob("ext*")):
        mf = d / "manifest.json"
        if not mf.exists():
            continue
        try:
            m = _json.loads(mf.read_text())
        except Exception as e:
            print(f"[inspect] {d.name}: bad manifest ({e})")
            continue
        name = m.get("name", "?")
        ec = m.get("externally_connectable")
        cs = [c.get("matches") for c in m.get("content_scripts", [])]
        print(f"[inspect] {d.name} name={name!r} has_key={'key' in m} "
              f"ext_connectable={ec} content_scripts={cs}")
        picks.append((name, "key" in m, ec, cs))
    rh = next((p for p in picks if "resume" in str(p[0]).lower()), picks[0] if picks else None)
    if not rh:
        print("INSPECT: no readable extension manifest in cache")
        return 1
    print(f"INSPECT resume-helper: has_key={rh[1]} externally_connectable={rh[2]} "
          f"content_scripts={rh[3]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="ApplicantStream v2 extractor / sender")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts only; no extract, no Send-To-AI clicks.")
    ap.add_argument("--debug", action="store_true",
                    help="Reach the v2 batch page, print a health check, then STOP.")
    ap.add_argument("--send-only", action="store_true",
                    help="Skip extraction; go straight to the send loop.")
    ap.add_argument("--extract-only", action="store_true",
                    help="Run the extract loop only; never send to the AI call list.")
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="Send only the first N rows (single live test pass). 0 = all.")
    ap.add_argument("--inspect-plugin", action="store_true",
                    help="Read the cached extractor plugin's manifest and print how it "
                         "proves it's installed (fixed id vs injected script). No browser.")
    ap.add_argument("--probe", action="store_true",
                    help="Deep probe: is the extension actually RUNNING (service worker/"
                         "background), and what does the robot click do? Full output written "
                         "to the 'RP Diag' Google-Sheet tab (not truncated).")
    ap.add_argument("--plain-probe", action="store_true",
                    help="Launch a PLAIN Chrome (not patchright) on the profile with the "
                         "plugin, drive it via CDP, and check whether the page can reach the "
                         "extension. Tests the plain-Chrome extraction path. Writes to RP Diag.")
    ap.add_argument("--cdp-test", action="store_true",
                    help="Decisive test: drive the DEDICATED extract profile (where the plugin "
                         "was GENUINELY installed, never touched by patchright) via CDP and check "
                         "chrome.runtime. Genuine-install vs anti-automation. Writes to RP Diag.")
    ap.add_argument("--locate-plugin", action="store_true",
                    help="Search every Chrome profile on the machine for the Resume Helper "
                         "extension id to find where the install actually landed. Writes to RP Diag.")
    args = ap.parse_args()

    if args.inspect_plugin:
        return _inspect_plugin()
    if args.probe:
        return _probe()
    if args.plain_probe:
        return _plain_probe()
    if args.cdp_test:
        return _cdp_test()
    if args.locate_plugin:
        return _locate_plugin()

    mode = "DRY-RUN (no writes)" if args.dry_run else "LIVE (sends to AI call list)"
    _log(f"=== Resume Pushing v2 — office {OFFICE_ID} — {mode} ===")

    # Lowest-priority AppStream job on Lucy 2 (runs every 10 min): if Carlos's
    # session is busy with another report, yield_if_busy makes the attach fail
    # fast (AppStreamBusy) instead of holding the other run up; the next tick
    # retries, so nothing is lost.
    try:
        with appstream_direct_session(yield_if_busy=True,
                                      load_extensions=True) as page:
            if not fetch_office._switch_office(page, OFFICE_ID, OFFICE_HINT):
                _log(f"[office] STOP — this AppStream account cannot reach office "
                     f"{OFFICE_ID}. Confirm the machine is logged in as an account "
                     "with access to that office.")
                return 2
            page.wait_for_timeout(2000)

            page = open_v2_dashboard(page)          # enter "Explore Appstream AI"
            if not goto_process_in_batches(page):
                _log("[STOP] could not reach Process In Batches on v2.")
                return 1

            if args.debug:
                _health_check(page)
                return 0

            extracted_remaining = None
            if not args.send_only:
                extracted_remaining = extract_loop(page, args.dry_run)

            if args.extract_only:
                _log("\n===== SUMMARY (extract-only) =====")
                _log(f"Still ready/not-extracted    : {extracted_remaining}")
                _log("(--extract-only — nothing was sent to the AI call list.)")
                return 0

            sent = send_loop(page, args.dry_run, limit=args.limit)

            _log("\n===== SUMMARY =====")
            _log(f"Mode                         : {mode}")
            if extracted_remaining is not None:
                _log(f"Still ready/not-extracted    : {extracted_remaining}")
            _log(f"Applicants sent to call list : {sent}")
            if args.dry_run:
                _log("(DRY-RUN — nothing was pushed to the AI call list.)")
            elif args.limit:
                _log(f"(--limit {args.limit} — sent only the first {args.limit} as a test.)")
    except AppStreamBusy:
        _log("[yield] AppStream session is busy (another report is running) — "
             "yielding; the next 10-min run will retry.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
