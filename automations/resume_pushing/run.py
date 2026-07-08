#!/usr/bin/env python3
"""
Resume Pushing — ApplicantStream: Extract Resumes & Send to AI
Office 11580 (CARLOS HIDALGO - ALPHALETE SPECIALIZED MARKETING, INC.)

Committed, scheduled version of Carlos's uploaded Hub report. The uploaded
original was Selenium + a manual-login wait + a blocking input() at the end —
none of which can run unattended. This runs on the machine's own AppStream
session via `appstream_direct_session` (on Lucy 2 that's Carlos's account = his
own office), the collision-safe path daily_focus uses: dedicated Chrome profile,
kept warm by the session holder, chrome-guard, retry-on-"already in use".

Flow (the batch page is index.cfm?p=616 — "Process emails in batches", an
ExtJS 2.2.1 grid; the old Applicants->Process Emails menu drifts to the wrong
page, so we go straight to p=616 via the session rqst token):
  1. Attach the logged-in AppStream console (no manual login)
  2. Switch to office 11580 (fails loudly if the account can't see it)
  3. Go directly to the p=616 batch grid
  4. Auto-Extract resume info (#btnExtractResume) — fills contact info
  5. Select ALL records (grid selection model), click "Send to AI" (#saveButtton2)
  6. Read the "Batch Process Emails Save Report" popup, click OK, print a summary

--dry-run  Reports counts only — NO Auto-Extract, NO Send-To-AI clicks. Nothing
           is pushed to the call list. Run this first after any change.
--send-only  Skip Auto-Extract; go straight to select-all + send.
--extract-only  Auto-Extract only; never send.
--limit N   Send only the first N rows (small live test).
--debug    Reach the page and print a health check (grid + control presence).

NOTE: send-to-AI is IRREVERSIBLE (it pushes applicants onto the live AI call
list). The scheduled LaunchAgent runs LIVE; --dry-run is the safe probe.

WHY the send was hard (keep for future breakage): "Send to AI" (#saveButtton2)
has no ExtJS handler/listener — its click is a raw DOM listener, so it fires
ONLY on a genuine click of the inner <button> (not the table wrapper, not
synthetic/dispatched events). Select-all must use the grid's selection model
(grid.getSelectionModel().selectAll()) because the buffered view only renders
~18 rows. Ext lives in the MAIN world — reach it via add_script_tag and bridge
results back through a DOM attribute (page.evaluate is isolated-world).

The standing "terminated-ICD" / "flag unfilled cells" report rules don't apply
here — this is a single-office action bot, not a per-rep Sheet fill.
"""
from __future__ import annotations

import argparse
import re
import sys

# Reused, collision-safe infra (the same modules daily_focus runs on).
from automations.shared.tableau_patchright import appstream_direct_session
from automations.recruiting_report import fetch_office

OFFICE_ID = "11580"
OFFICE_HINT = "CARLOS HIDALGO"
BATCH_PAGE_ID = "616"          # index.cfm?p=616 = "Process emails in batches"
EXTRACT_WAIT_SECONDS = 180     # let Auto-Extract finish before sending


def _log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #
def _grid_row_count(page) -> int:
    """Rendered applicant rows in the ExtJS grid (.x-grid3-row). Note the grid is
    buffered, so this is the RENDERED count, not the full store — use the
    selection model for the true total."""
    try:
        return page.locator(".x-grid3-row").count()
    except Exception:
        return 0


def goto_batch_page(page) -> bool:
    """Go straight to the batch grid (p=616) on the live session + office, built
    from the session's own rqst token (the menu nav drifts to p=701)."""
    m = re.search(r"rqst=([A-Za-z0-9-]+)", page.url or "")
    if not m:
        _log(f"[nav] no rqst token in session URL {(page.url or '')[:80]!r}")
        return False
    target = (f"https://applicantstream.com/index.cfm?rqst={m.group(1)}"
              f"&p={BATCH_PAGE_ID}&newOfficeId={OFFICE_ID}")
    try:
        page.goto(target, wait_until="domcontentloaded")
    except Exception as e:
        _log(f"[nav] goto batch page (p={BATCH_PAGE_ID}) failed: {e}")
        return False
    for _ in range(25):                       # ExtJS grid renders after page load
        page.wait_for_timeout(1000)
        n = _grid_row_count(page)
        if n > 0:
            _log(f"[nav] batch page p={BATCH_PAGE_ID} — {n} rows rendered")
            return True
    _log(f"[nav] batch page p={BATCH_PAGE_ID} loaded but 0 grid rows (nothing waiting)")
    return True


# --------------------------------------------------------------------------- #
# Extraction — "Auto Extract Information from Resume" (#btnExtractResume)
# --------------------------------------------------------------------------- #
def extract_resumes(page, dry_run: bool) -> int:
    n = _grid_row_count(page)
    if dry_run:
        _log(f"[extract] DRY-RUN — {n} rows; would click Auto-Extract, no click made")
        return 0
    btn = page.locator("#btnExtractResume")
    if btn.count() == 0:
        _log("[extract] Auto-Extract button (#btnExtractResume) not found — skipping")
        return 0
    try:
        btn.first.click(timeout=15000)
        _log(f"[extract] clicked Auto-Extract on {n} rows — processing …")
    except Exception as e:
        _log(f"[extract] click failed: {e}")
        return 0
    page.wait_for_timeout(2000)
    _click_if_present(page, ["Yes", "OK", "Continue"])   # accept any confirm
    page.wait_for_timeout(EXTRACT_WAIT_SECONDS * 1000)   # let it finish
    _click_if_present(page, ["OK", "Close"])
    _log(f"[extract] done (waited ~{EXTRACT_WAIT_SECONDS}s)")
    return n


# --------------------------------------------------------------------------- #
# Send to AI
# --------------------------------------------------------------------------- #
def _select_all(page) -> int:
    """Select EVERY record in the grid's store, not just the ~18 rows the ExtJS
    buffered view renders. A header-checker click only selects rendered rows, so
    call the grid's selection-model selectAll() in the MAIN world (add_script_tag)
    and bridge the count back via a DOM attribute. Returns the selected count."""
    try:
        page.add_script_tag(content=(
            "(function(){try{if(!window.Ext){document.body.setAttribute('data-sel','no-ext');return;}"
            "var best=null;Ext.ComponentMgr.all.each(function(c){try{"
            "if(c.getSelectionModel&&c.store&&c.store.getCount&&c.getView&&"
            "c.el&&c.el.dom&&c.el.dom.querySelector('.x-grid3-hd-checker')){"
            "if(!best||c.store.getCount()>best.store.getCount()){best=c;}}}catch(e){}return true;});"
            "if(!best){document.body.setAttribute('data-sel','no-grid');return;}"
            "var sm=best.getSelectionModel();if(sm.selectAll){sm.selectAll();}"
            "var n=sm.getCount?sm.getCount():(sm.getSelections?sm.getSelections().length:-1);"
            "document.body.setAttribute('data-sel',best.store.getCount()+'/'+n);"
            "}catch(e){document.body.setAttribute('data-sel','err:'+e);}})();"))
        page.wait_for_timeout(900)
        info = page.frames[0].evaluate("() => document.body.getAttribute('data-sel')")
        _log(f"[send] select-all (selection model): store/selected = {info}")
        if info and "/" in info:
            selected = int(info.split("/")[1])
            if selected > 0:
                return selected
    except Exception as e:
        _log(f"[send] selectAll error: {e}")
    # Fallback: header-checker real click (rendered rows only).
    try:
        page.locator(".x-grid3-hd-checker").first.click(timeout=8000)
        page.wait_for_timeout(800)
    except Exception as e:
        _log(f"[send] checker click failed: {e}")
    return page.locator(".x-grid3-row-selected").count()


def send_all_to_ai(page, dry_run: bool, limit: int = 0) -> int:
    """Select rows, click "Send to AI" (#saveButtton2), accept the "Save Report"
    popup. Reports the count AppStream says it sent (falls back to the grid drop)."""
    before = _grid_row_count(page)
    if before == 0:
        _log("[send] grid is empty — nothing to send")
        return 0
    if dry_run:
        who = f"the first {limit}" if limit else "all"
        _log(f"[send] DRY-RUN — {before} rows rendered; would select {who} + "
             "click 'Send to AI', no click made")
        return 0

    # Select rows: first `limit` (small test) or all.
    if limit and limit > 0:
        rows = page.locator(".x-grid3-row")
        for i in range(min(limit, rows.count())):
            try:
                rows.nth(i).locator(".x-grid3-td-checker").first.click(timeout=5000)
            except Exception as e:
                _log(f"[send] row {i} check failed: {e}")
        sel = page.locator(".x-grid3-row-selected").count()
        _log(f"[send] limit={limit}: {sel} rows selected")
    else:
        sel = _select_all(page)
    if sel == 0:
        _log("[send] no rows selected — aborting (nothing sent)")
        return 0

    if page.locator("#saveButtton2").count() == 0:
        _log("[send] Send-to-AI button (#saveButtton2) not found — aborting")
        return 0
    # The click is a raw DOM listener (no ExtJS handler), so it needs a genuine
    # click on the actual clickable element — the INNER <button>, not the wrapper.
    target = page.locator("#saveButtton2 button")
    if target.count() == 0:
        target = page.locator("#saveButtton2 .x-btn-text")
    if target.count() == 0:
        target = page.locator("#saveButtton2")
    try:
        target.first.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    try:
        target.first.click(timeout=8000, no_wait_after=True, force=True)
        _log("[send] clicked 'Send to AI'")
    except Exception as e:
        _log(f"[send] send click err: {e}")
    page.wait_for_timeout(2000)

    # Fallback: a true coordinate mouse-click on the button center.
    if page.locator(".x-window").count() == 0 and _grid_row_count(page) == before:
        try:
            box = page.locator("#saveButtton2").first.bounding_box()
            if box:
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                _log("[send] coordinate-clicked button")
        except Exception as e:
            _log(f"[send] coord click err: {e}")
        page.wait_for_timeout(2500)

    # Read the "Batch Process Emails Save Report" popup for the real result.
    reported = None
    try:
        win = page.locator(".x-window")
        if win.count() > 0:
            text = " ".join(win.first.inner_text().split())
            _log(f"[send] save report: {text[:200]}")
            m = re.search(r"Sent to Call List[^0-9]*([0-9,]+)", text, re.I)
            if m:
                reported = int(m.group(1).replace(",", ""))
    except Exception as e:
        _log(f"[send] report read err: {e}")

    _click_if_present(page, ["OK", "Yes", "Continue"])   # dismiss the report
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    for _ in range(15):
        page.wait_for_timeout(1000)
        if _grid_row_count(page) > 0:
            break

    sent = reported if reported is not None else max(0, before - _grid_row_count(page))
    _log(f"[send] sent {sent} to the AI call list")
    return sent


def _click_if_present(page, labels) -> bool:
    for label in labels:
        btn = page.locator(f"xpath=//button[contains(.,'{label}')]")
        if btn.count() > 0:
            try:
                btn.first.click(timeout=5000, no_wait_after=True)
                page.wait_for_timeout(2000)
                return True
            except Exception:
                continue
    return False


# --------------------------------------------------------------------------- #
# Health check (--debug): confirm the page + the controls the send relies on.
# --------------------------------------------------------------------------- #
def _health_check(page) -> None:
    _log("[debug] ===== health check =====")
    _log(f"[debug] url: {(page.url or '')[:90]}")
    _log(f"[debug] rendered rows (.x-grid3-row): {_grid_row_count(page)}")
    for sel, name in [("#btnExtractResume", "Auto-Extract button"),
                      ("#saveButtton2", "Send-to-AI button"),
                      ("#saveButtton", "Send-to-Call-List button"),
                      (".x-grid3-hd-checker", "select-all checker")]:
        try:
            _log(f"[debug] {name} ({sel}): {'FOUND' if page.locator(sel).count() else 'MISSING'}")
        except Exception as e:
            _log(f"[debug] {name} ({sel}): err {e}")
    try:
        page.add_script_tag(content=(
            "(function(){var o='no-ext';try{if(window.Ext){var b=null;"
            "Ext.ComponentMgr.all.each(function(c){try{if(c.getSelectionModel&&c.store&&c.store.getCount&&"
            "c.el&&c.el.dom&&c.el.dom.querySelector('.x-grid3-hd-checker')){if(!b||c.store.getCount()>b.store.getCount()){b=c;}}}catch(e){}return true;});"
            "o=b?('grid '+b.id+' store='+b.store.getCount()):'no-grid';}}catch(e){o='err:'+e;}"
            "document.body.setAttribute('data-hc',o);})();"))
        page.wait_for_timeout(600)
        _log(f"[debug] selection-model grid: {page.frames[0].evaluate('() => document.body.getAttribute(\"data-hc\")')}")
    except Exception as e:
        _log(f"[debug] ext grid probe err: {e}")
    _log("[debug] ===== end =====")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="ApplicantStream extractor / sender")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts only; no Auto-Extract, no Send-to-AI clicks.")
    ap.add_argument("--debug", action="store_true",
                    help="Reach the batch page, print a health check, then STOP.")
    ap.add_argument("--send-only", action="store_true",
                    help="Skip Auto-Extract; go straight to select-all + send.")
    ap.add_argument("--extract-only", action="store_true",
                    help="Auto-Extract only; never send to the AI call list.")
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="Send only the first N rows (small live test). 0 = all.")
    args = ap.parse_args()

    mode = "DRY-RUN (no writes)" if args.dry_run else "LIVE (sends to AI call list)"
    _log(f"=== Resume Pushing — office {OFFICE_ID} — {mode} ===")

    with appstream_direct_session() as page:
        if not fetch_office._switch_office(page, OFFICE_ID, OFFICE_HINT):
            _log(f"[office] STOP — this AppStream account cannot reach office "
                 f"{OFFICE_ID}. Confirm the machine is logged in as an account "
                 "with access to that office.")
            return 2
        page.wait_for_timeout(2000)

        if not goto_batch_page(page):
            _log("[STOP] could not reach the batch page (p=616).")
            return 1

        if args.debug:
            _health_check(page)
            return 0

        rows = _grid_row_count(page)
        if not args.send_only:
            extract_resumes(page, args.dry_run)

        if args.extract_only:
            _log("\n===== SUMMARY (extract-only) =====")
            _log(f"Rendered rows                : {rows}")
            _log(f"Auto-Extract                 : {'skipped (dry-run)' if args.dry_run else 'clicked'}")
            _log("(--extract-only — nothing was sent to the AI call list.)")
            return 0

        sent = send_all_to_ai(page, args.dry_run, limit=args.limit)

        _log("\n===== SUMMARY =====")
        _log(f"Mode                         : {mode}")
        _log(f"Applicants sent to call list : {sent}")
        if args.dry_run:
            _log("(DRY-RUN — nothing was pushed to the AI call list.)")
        elif args.limit:
            _log(f"(--limit {args.limit} — sent only the first {args.limit} as a test.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
