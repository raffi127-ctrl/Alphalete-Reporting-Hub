"""The batch push itself: extract resumes, then Send to AI. Office machine copy.

A PORT, ON PURPOSE, of the batch core in automations/resume_pushing/run.py --
same pages, same selectors, same loop rules. That module pulls in Google
Sheets, Slack and the Lucy session stack at import time, none of which may
ship to an office (test_installer_imports_ship). Only the steps that touch
the page live here, and nothing in this file imports anything at all from
the Hub.

IF APPSTREAM CHANGES, FIX BOTH. A selector that moved breaks the Lucys and
every office machine on the same day, and the Lucy copy has the --debug health
check that shows which one moved.

SEND TO AI CANNOT BE UNDONE. Everything that clicks it sits behind dry_run.
"""
from __future__ import annotations

import re
import time

TABLE = "#table-batch-resume"
EXTRACT_CAP_SECONDS = 180
MAX_EXTRACT_CYCLES = 30
MAX_SEND_PASSES = 8
STALL_CYCLES = 2

_log = print


def set_log(fn) -> None:
    global _log
    _log = fn


class ExtractionStalled(RuntimeError):
    """The extractor stopped clearing the queue. The next tick tries again."""


# --- small helpers -----------------------------------------------------------
def _click_if_present(page, labels, timeout: int = 5000) -> bool:
    for label in labels:
        loc = page.locator(
            f"xpath=//button[contains(normalize-space(.),'{label}')]"
            f" | //a[contains(normalize-space(.),'{label}')]"
            f" | //*[@role='button'][contains(normalize-space(.),'{label}')]")
        if loc.count() > 0:
            try:
                loc.first.click(timeout=timeout, no_wait_after=True)
                page.wait_for_timeout(1500)
                return True
            except Exception:  # noqa: BLE001
                continue
    return False


def _main_world(page, expr: str):
    """Evaluate in the page's MAIN world -- DataTables lives there and the
    automation world cannot see window.jQuery."""
    try:
        page.add_script_tag(content=(
            "(function(){try{document.body.setAttribute('data-mw', String("
            + expr + "));}catch(e){document.body.setAttribute('data-mw',"
            "'__ERR__:'+e);}})();"))
        page.wait_for_timeout(300)
        return page.evaluate("() => document.body.getAttribute('data-mw')")
    except Exception as e:  # noqa: BLE001
        return "__ERR__:%s" % e


# --- getting to the batch page -----------------------------------------------
def open_v2_dashboard(page):
    """'Explore Appstream AI' -> the v2 dashboard. Returns the page to use."""
    ctx = page.context
    before = len(ctx.pages)
    if not _click_if_present(page, ["Explore Appstream AI",
                                    "Explore AppStream AI"], timeout=10000):
        _log("[v2] 'Explore Appstream AI' not found -- already on v2?")
        return page
    page.wait_for_timeout(3000)
    if len(ctx.pages) > before:
        new_page = ctx.pages[-1]
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        return new_page
    return page


def goto_process_in_batches(page) -> bool:
    """Applicants -> Process Emails -> Process in Batches."""
    try:
        page.locator("xpath=//*[normalize-space(.)='Applicants']").first.hover(
            timeout=8000)
        page.wait_for_timeout(600)
        page.locator("xpath=//*[normalize-space(.)='Process Emails']").first.hover(
            timeout=8000)
        page.wait_for_timeout(600)
    except Exception as e:  # noqa: BLE001
        _log("[nav] menu hover failed: %s" % e)
    if not _click_if_present(page, ["Process in Batches", "Process In Batches"],
                             timeout=10000):
        _log("[nav] could not find 'Process in Batches'")
        return False
    page.wait_for_timeout(3000)
    for _ in range(20):
        if page.locator(TABLE).count() > 0:
            return True
        page.wait_for_timeout(1000)
    _log("[nav] Process in Batches opened but the table never appeared")
    return False


# --- counts ------------------------------------------------------------------
def render_all_rows(page) -> int:
    """Every record on one page, so select-all covers the whole list."""
    _main_world(page, "(function(){jQuery('%s').DataTable().page.len(1000)"
                      ".draw();return 'ok';})()" % TABLE)
    page.wait_for_timeout(1500)
    total = _main_world(
        page, "jQuery('%s').DataTable().page.info().recordsDisplay" % TABLE)
    try:
        return int(total)
    except (TypeError, ValueError):
        try:
            return page.locator("%s tbody tr" % TABLE).count()
        except Exception:  # noqa: BLE001
            return 0


def ready_for_extraction(page):
    """Rows still waiting on a resume read. 0 = extraction done."""
    render_all_rows(page)
    res = _main_world(page, "document.querySelectorAll('%s tbody "
                            "[title=\"Ready For Extraction\"]').length" % TABLE)
    try:
        return int(res)
    except (TypeError, ValueError):
        return None


# --- extract -----------------------------------------------------------------
def _robot_center(page):
    """The Resume Helper launcher: a small square the extension injects
    top-right."""
    r = page.evaluate(r"""() => {
      const cs=[...document.querySelectorAll('div,img,button,a')].filter(e=>{
        const b=e.getBoundingClientRect();
        return b.width>=28&&b.width<=72&&b.height>=28&&b.height<=72
               && b.left>innerWidth-130 && b.top<200 && b.top>=40;
      });
      if(!cs.length) return null;
      const b=cs[0].getBoundingClientRect();
      return [Math.round(b.left+b.width/2), Math.round(b.top+b.height/2)];
    }""")
    return tuple(r) if r else None


def _shadow_find(page, text: str):
    """An element whose text is exactly `text`, looking inside shadow roots --
    the extension draws its popup in one."""
    r = page.evaluate(
        "(want) => {"
        "  function* walk(root){"
        "    for (const e of root.querySelectorAll('*')){"
        "      yield e; if (e.shadowRoot) yield* walk(e.shadowRoot);"
        "    }"
        "  }"
        "  for (const e of walk(document)){"
        "    const t=(e.innerText||e.value||'').trim();"
        "    if (t===want){ const b=e.getBoundingClientRect();"
        "      if (b.width>0&&b.height>0)"
        "        return [Math.round(b.left+b.width/2),"
        "                Math.round(b.top+b.height/2)]; }"
        "  }"
        "  return null;"
        "}", text)
    return tuple(r) if r else None


def run_extract_once(page) -> str:
    """Robot -> Start, wait for Reset. "reset" / "cap" / "" (could not start)."""
    st = _shadow_find(page, "Start")
    if st is None:
        c = _robot_center(page)
        if c is None:
            _log("[extract] Resume Helper button not on the page "
                 "(extension not installed?)")
            return ""
        page.mouse.click(c[0], c[1])
        page.wait_for_timeout(2500)
        st = _shadow_find(page, "Start")
    if st is None:
        _log("[extract] Resume Helper opened but 'Start' is not there")
        return ""
    page.mouse.click(st[0], st[1])
    _log("[extract] Resume Helper started")
    t0 = time.time()
    page.wait_for_timeout(5000)
    while time.time() - t0 < EXTRACT_CAP_SECONDS:
        if _shadow_find(page, "Reset") is not None:
            _log("[extract] batch finished after %ds" % int(time.time() - t0))
            page.wait_for_timeout(1500)
            return "reset"
        page.wait_for_timeout(6000)
    return "cap"


def extract_loop(page, dry_run: bool) -> int:
    """Start -> wait -> reload -> recount, until nothing is waiting."""
    start = ready_for_extraction(page)
    _log("[extract] waiting for a resume read: %s" % start)
    if dry_run:
        return start or 0
    cycles, best, stall = 0, None, 0
    while cycles < MAX_EXTRACT_CYCLES:
        remaining = ready_for_extraction(page)
        if remaining is None or remaining <= 0:
            break
        # Against the LOWEST count seen, so new applicants arriving mid-run
        # cannot hide a stuck extractor.
        if best is None or remaining < best:
            best, stall = remaining, 0
        else:
            stall += 1
            if stall >= STALL_CYCLES:
                raise ExtractionStalled(
                    "%d still waiting, no drop in %d cycles" % (remaining, stall))
        cycles += 1
        res = run_extract_once(page)
        if not res:
            break
        try:
            page.reload(wait_until="domcontentloaded")
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(3000)
        if res == "cap":
            after = ready_for_extraction(page)
            if after is not None and after >= remaining:
                raise ExtractionStalled(
                    "%d still waiting after a full %d-minute pass"
                    % (after, EXTRACT_CAP_SECONDS // 60))
    return ready_for_extraction(page) or 0


# --- send --------------------------------------------------------------------
def _dismiss_modals(page, wait_s: int = 15) -> bool:
    """Clear a leftover status dialog so it cannot swallow the next click.
    Only CLOSE controls are pressed -- never Yes/OK, which could confirm."""
    dlg = page.locator(".modal:visible, .swal2-popup:visible, "
                       "[role='dialog']:visible")
    for _ in range(wait_s):
        if dlg.count() == 0:
            return True
        try:
            btn = dlg.last.locator("button.close, [data-dismiss='modal'], "
                                   "[aria-label='Close']")
            if btn.count() > 0:
                btn.first.click(timeout=2000)
            else:
                page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            try:
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
        page.wait_for_timeout(1000)
    if dlg.count() == 0:
        return True
    try:
        page.evaluate(
            "() => {"
            "  document.querySelectorAll('.modal').forEach(m => {"
            "    m.style.display = 'none'; m.classList.remove('in', 'show'); });"
            "  document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());"
            "  document.body.classList.remove('modal-open');"
            "}")
        page.wait_for_timeout(500)
    except Exception:  # noqa: BLE001
        pass
    return dlg.count() == 0


def _select_all(page) -> int:
    _dismiss_modals(page)
    for sel in ["%s thead input[type='checkbox']" % TABLE,
                "%s th input[type='checkbox']" % TABLE,
                "thead input[type='checkbox'].select-all",
                "input#select-all"]:
        cb = page.locator(sel)
        if cb.count() > 0:
            try:
                cb.first.check(timeout=6000)
                page.wait_for_timeout(800)
                return page.locator(
                    "%s tbody tr input[type='checkbox']:checked" % TABLE).count()
            except Exception as e:  # noqa: BLE001
                _log("[send] select-all failed: %s" % e)
    return 0


def _read_status_dialog(page, wait_s: int = 120):
    """(sent, done) from the 'Batch Process Emails Status' dialog. Polls: a big
    backlog is validated row by row before the dialog appears."""
    dlg = page.locator(".modal:visible, .swal2-popup:visible, "
                       "[role='dialog']:visible")
    waited = 0
    while dlg.count() == 0 and waited < wait_s:
        page.wait_for_timeout(1000)
        waited += 1
    if dlg.count() == 0:
        _log("[send] the status box never appeared -- outcome unknown")
        return None, False
    sent, done = None, False
    try:
        text = " ".join(dlg.first.inner_text().split())
        _log("[send] status: %s" % text[:220])
        m = re.search(r"Sent to Call List[^0-9]*([0-9,]+)", text, re.I)
        if m:
            sent = int(m.group(1).replace(",", ""))
        if re.search(r"no applicants to send", text, re.I) or sent == 0:
            done = True
    except Exception as e:  # noqa: BLE001
        _log("[send] could not read the status box: %s" % e)
    return sent, done


def send_once(page, dry_run: bool):
    """One pass: select all -> Send To AI -> Yes. (sent, done, rows_before)"""
    before = render_all_rows(page)
    if before == 0:
        return 0, True, 0
    if dry_run:
        _log("[send] DRY RUN -- %d rows; nothing sent" % before)
        return 0, True, before
    if _select_all(page) == 0:
        _log("[send] no rows selected")
        return 0, True, before
    if not _click_if_present(page, ["Send To AI", "Send to AI"], timeout=10000):
        _log("[send] 'Send To AI' not found")
        return 0, True, before
    sent, done = _read_status_dialog(page)
    if sent is None and not done:
        return 0, True, before          # never blind-click a confirm
    _click_if_present(page, ["Yes", "Continue", "OK"])
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(2500)
    _dismiss_modals(page)
    return (sent or 0), done, before


def send_loop(page, dry_run: bool) -> int:
    """Pass after pass until nothing more goes, or the list stops shrinking."""
    if dry_run:
        send_once(page, dry_run=True)
        return 0
    total, prev = 0, None
    for p in range(1, MAX_SEND_PASSES + 1):
        sent, done, before = send_once(page, dry_run=False)
        total += sent
        _log("[send] pass %d: sent %d (total %d)" % (p, sent, total))
        if done or sent == 0:
            break
        if prev is not None and before >= prev:
            break                       # the rest are duplicates / bad data
        prev = before
    return total


def run_batch(page, dry_run: bool) -> dict:
    """The whole batch stage from the console. {reached, waiting, left, sent}"""
    page = open_v2_dashboard(page)
    if not goto_process_in_batches(page):
        return {"reached": False, "waiting": None, "left": None, "sent": 0}
    waiting = ready_for_extraction(page)
    left = extract_loop(page, dry_run)
    sent = send_loop(page, dry_run)
    return {"reached": True, "waiting": waiting, "left": left, "sent": sent}
