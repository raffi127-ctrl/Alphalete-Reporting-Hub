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
def read_ready_count(page):
    """Parse 'Ready For Extraction: N' from the page body."""
    body = page.locator("body").inner_text()
    m = re.search(r"Ready For Extraction[^0-9]*([0-9,]+)", body, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def extract_resumes(page, dry_run: bool) -> int:
    total_seen_start = None
    loops = 0
    while loops < MAX_EXTRACT_LOOPS:
        count = read_ready_count(page)
        if total_seen_start is None:
            total_seen_start = count or 0
        _log(f"[extract] Ready For Extraction = {count}")
        if not count or count <= 0:
            break
        if dry_run:
            _log(f"[extract] DRY-RUN — would extract {count} (skipping Start)")
            break

        try:
            page.locator(
                "[class*='robot'], [title*='Resume Helper' i], .fa-robot"
            ).first.click(timeout=15000)
            page.wait_for_timeout(1000)
            page.locator("xpath=//button[contains(.,'Start')]").first.click(timeout=15000)
            _log(f"[extract] Start clicked — waiting ~{EXTRACT_WAIT_SECONDS}s …")
        except Exception as e:
            _log(f"[extract] could not start extraction: {e}")
            break

        page.wait_for_timeout(EXTRACT_WAIT_SECONDS * 1000)
        page.reload(wait_until="domcontentloaded")  # elapsed timer isn't reliable
        page.wait_for_timeout(4000)
        loops += 1

    remaining = read_ready_count(page) or 0
    extracted = max(0, (total_seen_start or 0) - remaining)
    _log(f"[extract] done. ~{extracted} extracted this run, {remaining} still ready")
    return extracted


# --------------------------------------------------------------------------- #
# Send to AI
# --------------------------------------------------------------------------- #
def _sendable_row_count(page) -> int:
    """Best-effort count of rows currently in the batch table."""
    try:
        return page.locator(f"{BATCH_TABLE} tbody tr").count()
    except Exception:
        return 0


def _show_all_rows(page) -> None:
    """Put every record on one page. jQuery/DataTables lives in the page's MAIN
    world; patchright's page.evaluate runs ISOLATED (site globals invisible), so
    inject a <script> tag — that runs in the main world where jQuery is defined.
    Falls back silently if the table isn't a DataTable."""
    try:
        page.add_script_tag(content=(
            f"try{{jQuery('{BATCH_TABLE}').DataTable().page.len(1000).draw();}}"
            "catch(e){}"))
        page.wait_for_timeout(3000)
    except Exception:
        pass


def send_all_to_ai(page, dry_run: bool) -> int:
    total_sent = 0
    for p in range(1, MAX_SEND_PASSES + 1):
        _show_all_rows(page)

        header_cb = page.locator(f"{BATCH_TABLE} thead input[type='checkbox']")
        if header_cb.count() == 0:
            _log("[send] no select-all checkbox — table may be empty")
            break

        if dry_run:
            n = _sendable_row_count(page)
            _log(f"[send] DRY-RUN — would send ~{n} applicants to the AI call "
                 "list (skipping Send To AI)")
            return 0

        if not header_cb.first.is_checked():
            header_cb.first.check(timeout=8000)
        page.wait_for_timeout(1000)

        send_btn = page.locator("xpath=//button[contains(.,'Send To AI')]")
        if send_btn.count() == 0:
            _log("[send] 'Send To AI' button not found")
            break
        send_btn.first.click(timeout=8000)
        page.wait_for_timeout(2000)

        dialog = page.locator("body").inner_text()
        m = re.search(r"Sent to Call List[^0-9]*([0-9,]+)", dialog, re.I)
        sent = int(m.group(1).replace(",", "")) if m else 0

        if "no applicants to send" in dialog.lower() or sent == 0:
            _log(f"[send] pass {p}: Sent to Call List = 0 — stopping")
            _click_if_present(page, ["Close", "Yes"])
            break

        _click_if_present(page, ["Yes"])   # confirm "Do you want to continue?"
        total_sent += sent
        _log(f"[send] pass {p}: sent {sent} (running total {total_sent})")
        page.wait_for_timeout(4000)

    return total_sent


def _click_if_present(page, labels) -> bool:
    for label in labels:
        btn = page.locator(f"xpath=//button[contains(.,'{label}')]")
        if btn.count() > 0:
            try:
                btn.first.click(timeout=5000)
                page.wait_for_timeout(2000)
                return True
            except Exception:
                continue
    return False


# --------------------------------------------------------------------------- #
# Diagnostic — dump the batch page's actionable DOM (read-only, no clicks) so
# we can rebuild selectors against the CURRENT AppStream UI. Runs across every
# frame in case the batch table is inside an iframe.
# --------------------------------------------------------------------------- #
def _debug_dump(page) -> None:
    js = r"""() => {
      const clip = s => (s || '').replace(/\s+/g,' ').trim().slice(0,70);
      const txt = el => clip(el.innerText || el.value || el.title ||
                             el.getAttribute('aria-label') || '');
      const KEY = /extract|send|call list|to ai|start|process|resume|continue|\byes\b/i;
      const ctrls = [...document.querySelectorAll(
        "button, a, input[type=button], input[type=submit], [role=button]")]
        .map(el => ({tag: el.tagName, id: el.id, name: el.name || '',
                     cls: (el.className || '').toString().slice(0,50), t: txt(el)}))
        .filter(b => KEY.test(b.t) || KEY.test(b.id) || KEY.test(b.cls));
      const tables = [...document.querySelectorAll("table")].map(t => ({
        id: t.id, cls: (t.className || '').toString().slice(0,40),
        rows: t.querySelectorAll("tbody tr").length,
        headCb: !!t.querySelector("thead input[type=checkbox]"),
        headers: [...t.querySelectorAll("thead th")].map(th => clip(th.innerText)).slice(0,10)
      }));
      return {url: location.href.slice(0,80),
              hasReady: /Ready For Extraction/i.test(document.body.innerText),
              checkboxes: document.querySelectorAll("input[type=checkbox]").length,
              tables, ctrls};
    }"""
    _log("[debug] ===== BATCH PAGE DOM DUMP =====")
    for fr in page.frames:
        try:
            info = fr.evaluate(js)
        except Exception:
            continue
        if not info.get("tables") and not info.get("ctrls"):
            continue
        _log(f"[debug] FRAME {info['url']!r} hasReadyText={info['hasReady']} "
             f"checkboxes={info['checkboxes']}")
        for t in info["tables"]:
            _log(f"[debug]   TABLE id={t['id']!r} rows={t['rows']} "
                 f"headCb={t['headCb']} cls={t['cls']!r} headers={t['headers']}")
        for b in info["ctrls"]:
            _log(f"[debug]   CTRL <{b['tag']}> id={b['id']!r} name={b['name']!r} "
                 f"text={b['t']!r} cls={b['cls']!r}")
    _log("[debug] ===== END DUMP =====")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="ApplicantStream extractor / sender")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts only; no Start, no Send-To-AI clicks.")
    ap.add_argument("--debug", action="store_true",
                    help="Reach the batch page, dump its actionable DOM (buttons, "
                         "tables, checkboxes) to the log, then STOP. Read-only — no "
                         "extract, no send. For rebuilding selectors.")
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

        if not open_batch_page(page):
            _log("[STOP] could not reach the Process in Batches page.")
            return 1

        if args.debug:
            _debug_dump(page)
            return 0

        extracted = extract_resumes(page, args.dry_run)
        sent = send_all_to_ai(page, args.dry_run)

        _log("\n===== SUMMARY =====")
        _log(f"Mode                         : {mode}")
        _log(f"Resumes extracted this run   : ~{extracted}")
        _log(f"Applicants sent to call list : {sent}")
        if args.dry_run:
            _log("(DRY-RUN — nothing was pushed to the AI call list.)")
        else:
            _log("Remaining records are structural duplicates or data-error rows "
                 "(blank/placeholder email or phone) that this tool cannot send.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
