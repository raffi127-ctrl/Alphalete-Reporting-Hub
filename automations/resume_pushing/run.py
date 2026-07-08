#!/usr/bin/env python3
"""
Resume Pushing — ApplicantStream: Extract Resumes & Send to AI
Office 11580 (CARLOS HIDALGO - ALPHALETE SPECIALIZED MARKETING, INC.)

Committed, scheduled version of Carlos's uploaded Hub report. The uploaded
original was Selenium + a manual-login wait + a blocking input() at the end —
none of which can run unattended. This version runs on the machine's own
AppStream session via `appstream_direct_session` (on Lucy 2 that's Carlos's
account = his own office, so access is inherent), the same collision-safe path
daily_focus uses: dedicated Chrome profile, kept warm by the session holder,
protected by the chrome-guard, with retry-on-"already in use". Nothing here
launches a rogue Chrome or waits on a keypress.

Flow:
  1. Attach the logged-in AppStream console (no manual login)
  2. Switch to office 11580 (fails loudly if the account can't see it)
  3. Applicants -> Process Emails -> Process in Batches
  4. Extract resumes in a loop until "Ready For Extraction" == 0
  5. Send all valid applicants to the AI call list in repeated passes
  6. Print a summary

--dry-run  REPORTS what it WOULD extract/send (reads the counts) but performs
           NO Start and NO Send-To-AI clicks. Nothing is pushed to the call
           list. ALWAYS run this first on a new machine / after any change.

NOTE: send-to-AI is IRREVERSIBLE (it pushes applicants onto the live AI call
list). The scheduled LaunchAgent runs LIVE; --dry-run is the safe probe.

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

# Seconds to wait between an extraction Start and the reload/count re-check.
EXTRACT_WAIT_SECONDS = 180
MAX_EXTRACT_LOOPS = 30          # safety cap on extraction loops
MAX_SEND_PASSES = 10           # safety cap on send-to-AI passes
BATCH_TABLE = "#table-batch-resume"


def _log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# Navigation — reach the Process in Batches page
# --------------------------------------------------------------------------- #
def open_batch_page(page) -> bool:
    """Applicants -> Process Emails -> Process in Batches. Hover menus, then
    click the leaf. Returns False (caller stops) if the leaf never appears."""
    _log("[nav] opening Appstream AI dashboard / Applicants menu …")
    # Some consoles land on a splash with an 'Explore Appstream AI' button.
    explore = page.locator("xpath=//*[contains(normalize-space(),'Explore Appstream AI')]")
    if explore.count() > 0:
        try:
            explore.first.click(timeout=8000)
            page.wait_for_timeout(4000)
        except Exception:
            pass  # already on the modern dashboard

    try:
        applicants = page.locator(
            "xpath=//*[self::a or self::button][contains(.,'Applicants')]").first
        applicants.hover(timeout=15000)
        page.wait_for_timeout(1000)
        page.locator("xpath=//*[contains(.,'Process Emails')]").first.hover(timeout=8000)
        page.wait_for_timeout(1000)
        page.locator("xpath=//*[contains(.,'Process in Batches')]").first.click(timeout=8000)
        page.wait_for_timeout(4000)
        _log("[nav] on Process in Batches page")
        return True
    except Exception as e:
        _log(f"[nav] ERROR reaching batch page: {e}")
        return False


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
BATCH_PAGE_ID = "616"   # index.cfm?p=616 = "Process emails in batches" (ExtJS grid)


def _grid_row_count(page) -> int:
    """Applicant rows in the ExtJS grid (.x-grid3-row)."""
    try:
        return page.locator(".x-grid3-row").count()
    except Exception:
        return 0


def goto_batch_page(page) -> bool:
    """Go straight to the batch grid (p=616) on the live session + office. The
    old menu nav (Applicants->Process Emails->Process in Batches) drifts to
    p=701 (the recruiting view) and never reaches this grid — so build the URL
    from the session's own rqst token instead."""
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
            _log(f"[nav] batch page p={BATCH_PAGE_ID} — {n} applicant rows")
            return True
    _log(f"[nav] batch page p={BATCH_PAGE_ID} loaded but 0 grid rows (nothing waiting)")
    return True


def extract_resumes(page, dry_run: bool) -> int:
    """Click "Auto Extract Information from Resume" (#btnExtractResume). Fills
    contact info from the attached resumes; not the irreversible step."""
    n = _grid_row_count(page)
    if dry_run:
        _log(f"[extract] DRY-RUN — {n} rows; would click Auto-Extract "
             "(#btnExtractResume), no click made")
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
def _dispatch_mouse(page, selector: str) -> None:
    """Fire a REAL mousedown->mouseup->click sequence on an element in the page's
    MAIN world. ExtJS ignores a synthetic .click() (only a click event, untrusted),
    so this mirrors the mouse-event trick Carlos's original used for the office
    dropdown. Runs via add_script_tag because patchright's evaluate is isolated."""
    page.add_script_tag(content=(
        "(function(){var el=document.querySelector(" + repr(selector) + ");"
        "if(el){['mousedown','mouseup','click'].forEach(function(t){"
        "el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window}));});}})();"))


def _select_all(page) -> int:
    """Select every grid row. Try patchright's real click on the header checker
    first; if nothing selects, fall back to dispatched mouse events. Returns the
    count of selected rows."""
    if page.locator(".x-grid3-hd-checker").count() == 0:
        _dbg("[send] select-all checker (.x-grid3-hd-checker) not found")
        return 0
    try:
        page.locator(".x-grid3-hd-checker").first.click(timeout=8000)
        page.wait_for_timeout(800)
    except Exception as e:
        _dbg(f"[send] checker click failed: {e}")
    sel = page.locator(".x-grid3-row-selected").count()
    if sel == 0:
        _dispatch_mouse(page, ".x-grid3-hd-checker")
        page.wait_for_timeout(800)
        sel = page.locator(".x-grid3-row-selected").count()
    return sel


def send_all_to_ai(page, dry_run: bool, limit: int = 0) -> int:
    """ExtJS grid: select rows, click the "Send to AI" button (#saveButtton2 —
    a stable id; the inner ext-gen* cell does NOT fire the handler), accept the
    confirm. Count is honest — how many rows actually disappear from the grid."""
    before = _grid_row_count(page)
    if before == 0:
        _dbg("[send] grid is empty — nothing to send")
        return 0
    if dry_run:
        who = f"the first {limit}" if limit else "all"
        _dbg(f"[send] DRY-RUN — {before} rows; would select {who} + click "
             "'Send to AI' (#saveButtton2), no click made")
        return 0

    try:
        open(DEBUG_FILE, "w").close()   # clean send trace per run (read via logtail)
    except Exception:
        pass

    # Select rows: first `limit` (safe test) or all.
    if limit and limit > 0:
        rows = page.locator(".x-grid3-row")
        for i in range(min(limit, rows.count())):
            try:
                rows.nth(i).locator(".x-grid3-td-checker").first.click(timeout=5000)
            except Exception as e:
                _dbg(f"[send] row {i} check failed: {e}")
        sel = page.locator(".x-grid3-row-selected").count()
        _dbg(f"[send] limit={limit}: {sel} of {before} rows selected")
    else:
        sel = _select_all(page)
        _dbg(f"[send] selected {sel} of {before} rows")
    if sel == 0:
        _dbg("[send] no rows selected — aborting (nothing sent)")
        return 0

    btn = page.locator("#saveButtton2")
    if btn.count() == 0:
        _dbg("[send] Send-to-AI button (#saveButtton2) not found — aborting")
        return 0
    # Try patchright's real click first; no_wait_after in case it reloads.
    try:
        btn.first.click(timeout=8000, no_wait_after=True)
    except Exception as e:
        _dbg(f"[send] button click err: {e}")
    _dbg("[send] clicked #saveButtton2 (patchright)")
    page.wait_for_timeout(1500)

    # If nothing happened (no dialog, grid unchanged), fire a REAL mouse sequence
    # on the button's INNER <button> element — ExtJS binds the handler there, and
    # a click on the table wrapper doesn't reach it (same reason select-all needed
    # dispatched events).
    if page.locator(".x-window").count() == 0 and _grid_row_count(page) == before:
        try:
            page.add_script_tag(content=(
                "(function(){var b=document.querySelector('#saveButtton2');if(!b)return;"
                "var t=b.querySelector('button')||b.querySelector('.x-btn-text')||b;"
                "['mousedown','mouseup','click'].forEach(function(e){"
                "t.dispatchEvent(new MouseEvent(e,{bubbles:true,cancelable:true,view:window}));});})();"))
            _dbg("[send] dispatched real events on #saveButtton2 inner button")
        except Exception as e:
            _dbg(f"[send] dispatch err: {e}")
        page.wait_for_timeout(2500)

    # Log whatever popup appeared (text + its buttons) so we know the confirm flow.
    try:
        win = page.locator(".x-window")
        if win.count() > 0:
            _dbg(f"[send] dialog: {' '.join(win.first.inner_text().split())[:170]!r}")
            wb = page.locator(".x-window button")
            labels = []
            for i in range(min(wb.count(), 6)):
                try:
                    labels.append(wb.nth(i).inner_text().strip())
                except Exception:
                    pass
            _dbg(f"[send] dialog buttons: {labels}")
    except Exception as e:
        _dbg(f"[send] dialog read err: {e}")

    _click_if_present(page, ["Yes", "OK", "Continue", "Send"])
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    for _ in range(15):
        page.wait_for_timeout(1000)
        if _grid_row_count(page) > 0:
            break
    after = _grid_row_count(page)
    sent = max(0, before - after)
    _dbg(f"[send] grid rows {before} -> {after} — actually sent ~{sent} to AI call list")
    _click_if_present(page, ["OK", "Close"])
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
# Diagnostic — dump the batch page's actionable DOM (read-only) so we can
# rebuild selectors against the CURRENT AppStream UI. Writes to a DEDICATED
# file (resume-debug.log) so the read isn't buried under the every-10-min
# scheduled runs in the shared daily log. Runs across every frame (iframe-safe).
# --------------------------------------------------------------------------- #
DEBUG_FILE = "output/logs/resume-debug.log"


def _dbg(msg: str) -> None:
    print(msg, flush=True)
    try:
        with open(DEBUG_FILE, "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _debug_dump(page, label: str) -> None:
    js = r"""() => {
      const clip = s => (s || '').replace(/\s+/g,' ').trim().slice(0,70);
      const txt = el => clip(el.innerText || el.value || el.title ||
                             el.getAttribute('aria-label') || '');
      const KEY = /extract|send|call list|to ai|start|process|resume|continue|\byes\b/i;
      const ctrls = [...document.querySelectorAll(
        "button, a, input[type=button], input[type=submit], [role=button]")]
        .map(el => ({tag: el.tagName, id: el.id, cls: (el.className||'').toString().slice(0,40), t: txt(el)}))
        .filter(b => KEY.test(b.t) || KEY.test(b.id) || KEY.test(b.cls));
      const tables = [...document.querySelectorAll("table")].map(t => ({
        id: t.id, cls: (t.className || '').toString().slice(0,40),
        rows: t.querySelectorAll("tbody tr").length,
        headCb: !!t.querySelector("thead input[type=checkbox]"),
        headers: [...t.querySelectorAll("thead th")].map(th => clip(th.innerText)).slice(0,10)
      }));
      return {url: location.href.slice(0,90),
              hasReady: /Ready For Extraction/i.test(document.body.innerText),
              checkboxes: document.querySelectorAll("input[type=checkbox]").length,
              tables, ctrls};
    }"""
    _dbg(f"[dbg:{label}] ===== DUMP @ {label} =====")
    for i, fr in enumerate(page.frames):
        try:
            info = fr.evaluate(js)
        except Exception:
            continue
        if not info.get("tables") and not info.get("ctrls"):
            continue
        _dbg(f"[dbg:{label}] FRAME{i} {info['url']} ready={info['hasReady']} cbs={info['checkboxes']}")
        for t in info["tables"]:
            _dbg(f"[dbg:{label}] TBL id={t['id']!r} rows={t['rows']} headCb={t['headCb']} hdr={t['headers']}")
        for b in info["ctrls"]:
            _dbg(f"[dbg:{label}] CTRL <{b['tag']}> id={b['id']!r} txt={b['t']!r} cls={b['cls']!r}")
    _dbg(f"[dbg:{label}] ===== END {label} =====")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="ApplicantStream extractor / sender")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts only; no Start, no Send-To-AI clicks.")
    ap.add_argument("--debug", action="store_true",
                    help="Reach the batch page, dump its actionable DOM to the log, "
                         "then STOP. Read-only — no extract, no send.")
    ap.add_argument("--extract-only", action="store_true",
                    help="Click Auto-Extract but do NOT send to the AI call list. "
                         "Safe: extraction fills resume data, it's not the "
                         "irreversible push.")
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="Send only the first N applicants (safe live test). "
                         "0 = all rows via select-all.")
    args = ap.parse_args()

    mode = "DRY-RUN (no writes)" if args.dry_run else "LIVE (sends to AI call list)"
    _log(f"=== Resume Pushing — office {OFFICE_ID} — {mode} ===")

    with appstream_direct_session() as page:
        # Office switch doubles as the access check: if the account can't see
        # 11580, _switch_office returns False and we stop loudly rather than
        # silently no-op.
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
            try:
                open(DEBUG_FILE, "w").close()   # start a clean dedicated dump file
            except Exception:
                pass
            _debug_dump(page, "p616")
            # Compact probe: locate the exact controls, by visible text (ExtJS
            # ids are dynamic). Short output so it fits one logtail cell.
            try:
                probe = page.frames[0].evaluate(r"""() => {
                  const norm = s => (s||'').replace(/\s+/g,' ').trim();
                  const all = [...document.querySelectorAll('a,button,span,div,td,input[type=button],[role=button]')];
                  const find = t => { const e = all.find(x => norm(x.innerText||x.value).toLowerCase() === t)
                                             || all.find(x => norm(x.innerText||x.value).toLowerCase().includes(t));
                    return e ? `<${e.tagName} id='${e.id}' cls='${(e.className||'').toString().slice(0,28)}'>` : 'NONE'; };
                  const rowSel = ['.x-grid3-row','.x-grid-row','.x-grid-item','tr.x-grid3-row'].map(s=>`${s}:${document.querySelectorAll(s).length}`);
                  const checker = document.querySelector('.x-grid3-hd-checker, .x-grid3-check-col, .x-column-header-checkbox, .x-grid-checkheader');
                  return {title: norm(document.title).slice(0,40),
                          rows: rowSel, cbs: document.querySelectorAll('input[type=checkbox]').length,
                          checker: checker ? `<${checker.tagName} cls='${(checker.className||'').toString().slice(0,32)}'>` : 'NONE',
                          extract: find('auto extract information from resume'),
                          sendAI: find('send to ai'), sendCL: find('send to call list')};
                }""")
                _dbg(f"[PROBE] title={probe['title']!r} cbs={probe['cbs']} rows={probe['rows']}")
                _dbg(f"[PROBE] checker={probe['checker']}")
                _dbg(f"[PROBE] extract={probe['extract']}")
                _dbg(f"[PROBE] sendAI={probe['sendAI']}")
                _dbg(f"[PROBE] sendCL={probe['sendCL']}")
            except Exception as e:
                _dbg(f"[PROBE] failed: {e}")
            return 0

        rows = _grid_row_count(page)
        extracted = extract_resumes(page, args.dry_run)

        if args.extract_only:
            _log("\n===== SUMMARY (extract-only) =====")
            _log(f"Grid rows                    : {rows}")
            _log(f"Auto-Extract                 : {'skipped (dry-run)' if args.dry_run else 'clicked'}")
            _log("(--extract-only — nothing was sent to the AI call list.)")
            return 0

        sent = send_all_to_ai(page, args.dry_run, limit=args.limit)

        _log("\n===== SUMMARY =====")
        _log(f"Mode                         : {mode}")
        _log(f"Grid rows                    : {rows}")
        _log(f"Applicants sent to call list : {sent}")
        if args.dry_run:
            _log("(DRY-RUN — nothing was pushed to the AI call list.)")
        elif args.limit:
            _log(f"(--limit {args.limit} — sent only the first {args.limit} as a test.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
